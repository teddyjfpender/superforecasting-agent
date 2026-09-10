#!/usr/bin/env python3
"""
Trajectory Compressor

Post-processes completed agent trajectories to compress them within a target
token budget while preserving training signal quality.

Compression Strategy:
1. Protect first turns (system, human, first gpt, first tool)
2. Protect last N turns (final actions and conclusions)
3. Compress MIDDLE turns only, starting from 2nd tool response
4. Compress only as much as needed to fit under target
5. Replace compressed region with a single human summary message
6. Keep remaining tool calls intact (model continues working after summary)

Usage:
    # Compress a directory of JSONL files
    python -m superforecasting_agent.trajectories.compression --input=data/my_run
    
    # Compress a single JSONL file
    python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl
    
    # Compress 15% sample of a file
    python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl --sample_percent=15
    
    # Compress with custom output and token target
    python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl --output=compressed.jsonl --target_max_tokens=16000
    
    # Compress 10% sample from a directory
    python -m superforecasting_agent.trajectories.compression --input=data/my_run --sample_percent=10
"""

from superforecasting_agent.trajectories.algorithm import (
    compress_trajectory,
    compress_trajectory_async,
)
from superforecasting_agent.trajectories.summarization import (
    _effective_temperature_for_model as _effective_temperature_for_model,
    _generate_summary,
    _generate_summary_async,
)
import os
import logging
from typing import List, Dict, Any, Tuple

from superforecasting_agent.urls import base_url_host_matches, base_url_hostname
from superforecasting_agent.paths import get_install_root
import fire
from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.trajectories.compression_io import process_directory, _process_directory_async
from superforecasting_agent.trajectories.reporting import _print_summary

# Load .env from HERMES_HOME first, then project root as a dev fallback.
from superforecasting_agent.runtime.env_loader import load_hermes_dotenv

_hermes_home = get_agent_home()
_project_env = get_install_root() / ".env"
load_hermes_dotenv(hermes_home=_hermes_home, project_env=_project_env)




from superforecasting_agent.trajectories.compression_types import (
    CompressionConfig, TrajectoryMetrics, AggregateMetrics,
)


class TrajectoryCompressor:
    """
    Compresses agent trajectories to fit within a target token budget.
    
    Compression strategy:
    1. Keep protected head turns (system, human, first gpt+tool)
    2. Keep protected tail turns (last N turns)
    3. From the compressible middle region, compress only as much as needed
    4. Replace compressed turns with a single human summary message
    5. Keep remaining middle turns intact (model continues with tools)
    """

    def __init__(self, config: CompressionConfig):
        """Initialize the compressor."""
        self.config = config
        self.aggregate_metrics = AggregateMetrics()

        # Initialize tokenizer
        self._init_tokenizer()

        # Initialize OpenRouter client
        self._init_summarizer()

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)

    def _init_tokenizer(self):
        """Initialize HuggingFace tokenizer for token counting."""
        try:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.config.tokenizer_name,
                trust_remote_code=self.config.trust_remote_code
            )
            print(f"✅ Loaded tokenizer: {self.config.tokenizer_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to load tokenizer '{self.config.tokenizer_name}': {e}")

    def _init_summarizer(self):
        """Initialize LLM routing for summarization (sync and async).

        Uses call_llm/async_call_llm from the centralized provider router
        which handles auth, headers, and provider detection internally.
        For custom endpoints, falls back to raw client construction.
        """

        provider = self._detect_provider()
        if provider:
            # Store provider for use in _generate_summary calls
            self._llm_provider = provider
            self._use_call_llm = True
            # Verify the provider is available
            from agent.auxiliary_client import resolve_provider_client
            client, _ = resolve_provider_client(
                provider, model=self.config.summarization_model)
            if client is None:
                raise RuntimeError(
                    f"Provider '{provider}' is not configured. "
                    f"Check your API key or run: superforecasting-agent setup")
            self.client = None  # Not used directly
            self.async_client = None  # Not used directly
        else:
            # Custom endpoint — use config's raw base_url + api_key_env
            self._use_call_llm = False
            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"Missing API key. Set {self.config.api_key_env} "
                    f"environment variable.")
            from openai import OpenAI
            from agent.auxiliary_client import _to_openai_base_url
            self.client = OpenAI(
                api_key=api_key, base_url=_to_openai_base_url(self.config.base_url))
            # AsyncOpenAI is created lazily in _get_async_client() so it
            # binds to the current event loop — avoids "Event loop is closed"
            # when process_directory() is called multiple times (each call
            # creates a new loop via asyncio.run()).
            self.async_client = None
            self._async_client_api_key = api_key

        print(f"✅ Initialized summarizer client: {self.config.summarization_model}")
        print(f"   Max concurrent requests: {self.config.max_concurrent_requests}")

    def _get_async_client(self):
        """Return an AsyncOpenAI client bound to the current event loop.

        Created lazily so that each ``asyncio.run()`` call in
        ``process_directory()`` gets a client tied to its own loop,
        avoiding "Event loop is closed" errors on repeated calls.
        """
        from openai import AsyncOpenAI
        from agent.auxiliary_client import _to_openai_base_url
        # Always create a fresh client so it binds to the running loop.
        self.async_client = AsyncOpenAI(
            api_key=self._async_client_api_key,
            base_url=_to_openai_base_url(self.config.base_url),
        )
        return self.async_client

    def _detect_provider(self) -> str:
        """Detect the provider name from the configured base_url."""
        url = self.config.base_url or ""
        if base_url_host_matches(url, "openrouter.ai"):
            return "openrouter"
        if base_url_host_matches(url, "nousresearch.com"):
            return "nous"
        if (
            base_url_hostname(url) == "chatgpt.com"
            and "/backend-api/codex" in url.lower()
        ):
            return "codex"
        if base_url_host_matches(url, "z.ai"):
            return "zai"
        if (
            base_url_host_matches(url, "moonshot.ai")
            or base_url_host_matches(url, "moonshot.cn")
            or base_url_host_matches(url, "api.kimi.com")
        ):
            return "kimi-coding"
        if base_url_host_matches(url, "arcee.ai"):
            return "arcee"
        if base_url_host_matches(url, "minimaxi.com"):
            return "minimax-cn"
        if base_url_host_matches(url, "minimax.io"):
            return "minimax"
        # Unknown base_url — not a known provider
        return ""

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the configured tokenizer."""
        if not text:
            return 0
        try:
            return len(self.tokenizer.encode(text))
        except Exception:
            # Fallback to character estimate
            return len(text) // 4

    def count_trajectory_tokens(self, trajectory: List[Dict[str, str]]) -> int:
        """Count total tokens in a trajectory."""
        return sum(self.count_tokens(turn.get("value", "")) for turn in trajectory)

    def count_turn_tokens(self, trajectory: List[Dict[str, str]]) -> List[int]:
        """Count tokens for each turn in a trajectory."""
        return [self.count_tokens(turn.get("value", "")) for turn in trajectory]

    def _find_protected_indices(self, trajectory: List[Dict[str, str]]) -> Tuple[set, int, int]:
        """
        Find indices of protected turns.
        
        Returns:
            Tuple of (protected_set, compressible_start, compressible_end)
        """
        n = len(trajectory)
        protected = set()

        # Track first occurrences
        first_system = first_human = first_gpt = first_tool = None

        for i, turn in enumerate(trajectory):
            role = turn.get("from", "")
            if role == "system" and first_system is None:
                first_system = i
            elif role == "human" and first_human is None:
                first_human = i
            elif role == "gpt" and first_gpt is None:
                first_gpt = i
            elif role == "tool" and first_tool is None:
                first_tool = i

        # Protect first turns
        if self.config.protect_first_system and first_system is not None:
            protected.add(first_system)
        if self.config.protect_first_human and first_human is not None:
            protected.add(first_human)
        if self.config.protect_first_gpt and first_gpt is not None:
            protected.add(first_gpt)
        if self.config.protect_first_tool and first_tool is not None:
            protected.add(first_tool)

        # Protect last N turns
        for i in range(max(0, n - self.config.protect_last_n_turns), n):
            protected.add(i)

        # Determine compressible region
        # Start after the last protected head turn
        head_protected = [i for i in protected if i < n // 2]
        tail_protected = [i for i in protected if i >= n // 2]

        compressible_start = max(head_protected) + 1 if head_protected else 0
        compressible_end = min(tail_protected) if tail_protected else n

        return protected, compressible_start, compressible_end

    def _extract_turn_content_for_summary(self, trajectory: List[Dict[str, str]], start: int, end: int) -> str:
        """
        Extract content from turns to be summarized.
        
        Args:
            trajectory: Full trajectory
            start: Start index (inclusive)
            end: End index (exclusive)
            
        Returns:
            Formatted string of turn contents for summarization
        """
        parts = []
        for i in range(start, end):
            turn = trajectory[i]
            role = turn.get("from", "unknown")
            value = turn.get("value", "")

            # Truncate very long values for the summary prompt
            if len(value) > 3000:
                value = value[:1500] + "\n...[truncated]...\n" + value[-500:]

            parts.append(f"[Turn {i} - {role.upper()}]:\n{value}")

        return "\n\n".join(parts)

    @staticmethod
    def _coerce_summary_content(content: Any) -> str:
        """Normalize summary-model output to a safe string."""
        if not isinstance(content, str):
            content = str(content) if content else ""
        return content.strip()

    @staticmethod
    def _ensure_summary_prefix(summary: str) -> str:
        """Normalize summary text to include the expected prefix exactly once."""
        text = (summary or "").strip()
        if text.startswith("[CONTEXT SUMMARY]:"):
            return text
        return "[CONTEXT SUMMARY]:" if not text else f"[CONTEXT SUMMARY]: {text}"

    _generate_summary = _generate_summary

    _generate_summary_async = _generate_summary_async

    compress_trajectory = compress_trajectory

    compress_trajectory_async = compress_trajectory_async

    async def process_entry_async(self, entry: Dict[str, Any]) -> Tuple[Dict[str, Any], TrajectoryMetrics]:
        """
        Process a single JSONL entry (async version).
        """
        if "conversations" not in entry:
            metrics = TrajectoryMetrics()
            return entry, metrics

        trajectory = entry["conversations"]
        compressed_trajectory, metrics = await self.compress_trajectory_async(trajectory)

        # Create new entry with compressed trajectory
        result = entry.copy()
        result["conversations"] = compressed_trajectory

        # Add compression metadata if enabled
        if self.config.metrics_per_trajectory and metrics.was_compressed:
            result["compression_metrics"] = metrics.to_dict()

        return result, metrics

    def process_entry(self, entry: Dict[str, Any]) -> Tuple[Dict[str, Any], TrajectoryMetrics]:
        """
        Process a single JSONL entry.
        
        Args:
            entry: JSONL entry containing 'conversations' field
            
        Returns:
            Tuple of (processed_entry, metrics)
        """
        if "conversations" not in entry:
            metrics = TrajectoryMetrics()
            return entry, metrics

        trajectory = entry["conversations"]
        compressed_trajectory, metrics = self.compress_trajectory(trajectory)

        # Create new entry with compressed trajectory
        result = entry.copy()
        result["conversations"] = compressed_trajectory

        # Add compression metadata if enabled
        if self.config.metrics_per_trajectory and metrics.was_compressed:
            result["compression_metrics"] = metrics.to_dict()

        return result, metrics

    process_directory = process_directory

    _process_directory_async = _process_directory_async

    _print_summary = _print_summary


from superforecasting_agent.trajectories.compression_cli import main


if __name__ == "__main__":
    fire.Fire(main)
