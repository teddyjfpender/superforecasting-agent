#!/usr/bin/env python3
"""
Batch Agent Runner

This module provides parallel batch processing capabilities for running the agent
across multiple prompts from a dataset. It includes:
- Dataset loading and batching
- Parallel batch processing with multiprocessing
- Checkpointing for fault tolerance and resumption
- Trajectory saving in the proper format (from/value pairs)
- Tool usage statistics aggregation across all batches

Usage:
    python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run
    
    # Resume an interrupted run
    python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run --resume
    
    # Use a specific toolset distribution
    python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run --distribution=image_gen
"""

# IMPORTANT: superforecasting_agent.bootstrap must be the very first import — UTF-8 stdio
# on Windows.  No-op on POSIX.  See superforecasting_agent.bootstrap.py for full rationale.
try:
    import superforecasting_agent.bootstrap  # noqa: F401
except ModuleNotFoundError:
    # Graceful fallback when superforecasting_agent.bootstrap isn't registered in the venv
    # yet — happens during partial ``hermes update`` where git-reset landed
    # new code but ``uv pip install -e .`` didn't finish.  Missing bootstrap
    # means UTF-8 stdio setup is skipped on Windows; POSIX is unaffected.
    pass

import json
from superforecasting_agent.trajectories.batch_run import run
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from multiprocessing import Lock

logger = logging.getLogger(__name__)
import fire

from superforecasting_agent.trajectories.batch_worker import (
    _process_batch_worker as _process_batch_worker,
    _process_single_prompt as _process_single_prompt,
)
from superforecasting_agent.trajectories.distributions import (
    list_distributions,
    sample_toolsets_from_distribution as sample_toolsets_from_distribution,
    validate_distribution
)


from superforecasting_agent.trajectories.batch_statistics import (
    ALL_POSSIBLE_TOOLS as ALL_POSSIBLE_TOOLS,
    DEFAULT_TOOL_STATS as DEFAULT_TOOL_STATS,
    _normalize_tool_stats as _normalize_tool_stats,
    _normalize_tool_error_counts as _normalize_tool_error_counts,
    _extract_tool_stats as _extract_tool_stats,
    _extract_reasoning_stats as _extract_reasoning_stats,
)






class BatchRunner:
    """
    Manages batch processing of agent prompts with checkpointing and statistics.
    """

    def __init__(
        self,
        dataset_file: str,
        batch_size: int,
        run_name: str,
        distribution: str = "default",
        max_iterations: int = 10,
        base_url: str = None,
        api_key: str = None,
        model: str = "claude-opus-4-20250514",
        num_workers: int = 4,
        verbose: bool = False,
        ephemeral_system_prompt: str = None,
        log_prefix_chars: int = 100,
        providers_allowed: List[str] = None,
        providers_ignored: List[str] = None,
        providers_order: List[str] = None,
        provider_sort: str = None,
        openrouter_min_coding_score: Optional[float] = None,
        max_tokens: int = None,
        reasoning_config: Dict[str, Any] = None,
        prefill_messages: List[Dict[str, Any]] = None,
        max_samples: int = None,
    ):
        """
        Initialize the batch runner.

        Args:
            dataset_file (str): Path to the dataset JSONL file with 'prompt' field
            batch_size (int): Number of prompts per batch
            run_name (str): Name for this run (used for checkpointing and output)
            distribution (str): Toolset distribution to use (default: "default")
            max_iterations (int): Max iterations per agent run
            base_url (str): Base URL for model API
            api_key (str): API key for model
            model (str): Model name to use
            num_workers (int): Number of parallel workers
            verbose (bool): Enable verbose logging
            ephemeral_system_prompt (str): System prompt used during agent execution but NOT saved to trajectories (optional)
            log_prefix_chars (int): Number of characters to show in log previews for tool calls/responses (default: 20)
            providers_allowed (List[str]): OpenRouter providers to allow (optional)
            providers_ignored (List[str]): OpenRouter providers to ignore (optional)
            providers_order (List[str]): OpenRouter providers to try in order (optional)
            provider_sort (str): Sort providers by price/throughput/latency (optional)
            max_tokens (int): Maximum tokens for model responses (optional, uses model default if not set)
            reasoning_config (Dict): OpenRouter reasoning config override (e.g. {"effort": "none"} to disable thinking)
            prefill_messages (List[Dict]): Messages to prepend as prefilled conversation context (few-shot priming).
                NOTE: Anthropic Sonnet 4.6+ and Opus 4.6+ reject a trailing assistant-role prefill
                (400 error).  For those models use output_config.format or structured-output
                schemas instead.  Safe here for user-role priming and for older Claude / non-Claude models.
            max_samples (int): Only process the first N samples from the dataset (optional, processes all if not set)
        """
        self.dataset_file = Path(dataset_file)
        self.batch_size = batch_size
        self.run_name = run_name
        self.distribution = distribution
        self.max_iterations = max_iterations
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.num_workers = num_workers
        self.verbose = verbose
        self.ephemeral_system_prompt = ephemeral_system_prompt
        self.log_prefix_chars = log_prefix_chars
        self.providers_allowed = providers_allowed
        self.providers_ignored = providers_ignored
        self.providers_order = providers_order
        self.provider_sort = provider_sort
        self.openrouter_min_coding_score = openrouter_min_coding_score
        self.max_tokens = max_tokens
        self.reasoning_config = reasoning_config
        self.prefill_messages = prefill_messages
        self.max_samples = max_samples

        # Validate distribution
        if not validate_distribution(distribution):
            raise ValueError(f"Unknown distribution: {distribution}. Available: {list(list_distributions().keys())}")

        # Setup output directory
        self.output_dir = Path("data") / run_name
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Checkpoint file
        self.checkpoint_file = self.output_dir / "checkpoint.json"

        # Statistics file
        self.stats_file = self.output_dir / "statistics.json"

        # Load dataset (and optionally truncate to max_samples)
        self.dataset = self._load_dataset()
        if self.max_samples and self.max_samples < len(self.dataset):
            full_count = len(self.dataset)
            self.dataset = self.dataset[:self.max_samples]
            print(f"✂️  Truncated dataset from {full_count} to {self.max_samples} samples (--max_samples)")

        # Create batches
        self.batches = self._create_batches()

        print("📊 Batch Runner Initialized")
        print(f"   Dataset: {self.dataset_file} ({len(self.dataset)} prompts)")
        print(f"   Batch size: {self.batch_size}")
        print(f"   Total batches: {len(self.batches)}")
        print(f"   Run name: {self.run_name}")
        print(f"   Distribution: {self.distribution}")
        print(f"   Output directory: {self.output_dir}")
        print(f"   Workers: {self.num_workers}")
        if self.ephemeral_system_prompt:
            prompt_preview = self.ephemeral_system_prompt[:60] + "..." if len(self.ephemeral_system_prompt) > 60 else self.ephemeral_system_prompt
            print(f"   🔒 Ephemeral system prompt: '{prompt_preview}'")

    def _load_dataset(self) -> List[Dict[str, Any]]:
        """
        Load dataset from JSONL file.
        
        Returns:
            List[Dict]: List of dataset entries
        """
        if not self.dataset_file.exists():
            raise FileNotFoundError(f"Dataset file not found: {self.dataset_file}")

        dataset = []
        with open(self.dataset_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                    if 'prompt' not in entry:
                        print(f"⚠️  Warning: Line {line_num} missing 'prompt' field, skipping")
                        continue
                    dataset.append(entry)
                except json.JSONDecodeError as e:
                    print(f"⚠️  Warning: Invalid JSON on line {line_num}: {e}")
                    continue

        if not dataset:
            raise ValueError(f"No valid entries found in dataset file: {self.dataset_file}")

        return dataset

    def _create_batches(self) -> List[List[Tuple[int, Dict[str, Any]]]]:
        """
        Split dataset into batches with indices.
        
        Returns:
            List of batches, where each batch is a list of (index, entry) tuples
        """
        batches = []
        for i in range(0, len(self.dataset), self.batch_size):
            batch = [(idx, entry) for idx, entry in enumerate(self.dataset[i:i + self.batch_size], start=i)]
            batches.append(batch)

        return batches

    def _load_checkpoint(self) -> Dict[str, Any]:
        """
        Load checkpoint data if it exists.
        
        Returns:
            Dict: Checkpoint data with completed prompt indices
        """
        if not self.checkpoint_file.exists():
            return {
                "run_name": self.run_name,
                "completed_prompts": [],
                "batch_stats": {},
                "last_updated": None
            }

        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Warning: Failed to load checkpoint: {e}")
            return {
                "run_name": self.run_name,
                "completed_prompts": [],
                "batch_stats": {},
                "last_updated": None
            }

    def _save_checkpoint(self, checkpoint_data: Dict[str, Any], lock: Optional[Lock] = None):
        """
        Save checkpoint data.
        
        Args:
            checkpoint_data (Dict): Checkpoint data to save
            lock (Lock): Optional lock for thread-safe access
        """
        checkpoint_data["last_updated"] = datetime.now().isoformat()

        from superforecasting_agent.storage.files import atomic_json_write
        if lock:
            with lock:
                atomic_json_write(self.checkpoint_file, checkpoint_data)
        else:
            atomic_json_write(self.checkpoint_file, checkpoint_data)

    def _scan_completed_prompts_by_content(self) -> set:
        """
        Scan all batch files and extract completed prompts by their actual content.
        
        This provides a more robust resume mechanism that matches on prompt text
        rather than indices, allowing recovery even if indices don't match.
        
        Returns:
            set: Set of prompt texts that have been successfully processed
        """
        completed_prompts = set()
        batch_files = sorted(self.output_dir.glob("batch_*.jsonl"))

        if not batch_files:
            return completed_prompts

        print(f"📂 Scanning {len(batch_files)} batch files for completed prompts...")

        for batch_file in batch_files:
            try:
                with open(batch_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())

                            # Skip failed entries - we want to retry these
                            if entry.get("failed", False):
                                continue

                            # Extract the human/user prompt from conversations
                            conversations = entry.get("conversations", [])
                            for msg in conversations:
                                if msg.get("from") == "human":
                                    prompt_text = msg.get("value", "").strip()
                                    if prompt_text:
                                        completed_prompts.add(prompt_text)
                                    break  # Only need the first human message
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                print(f"  ⚠️  Warning: Error reading {batch_file.name}: {e}")

        return completed_prompts

    def _filter_dataset_by_completed(self, completed_prompts: set) -> Tuple[List[Dict], List[int]]:
        """
        Filter the dataset to exclude prompts that have already been completed.
        
        Args:
            completed_prompts: Set of prompt texts that have been completed
            
        Returns:
            Tuple of (filtered_dataset, skipped_indices)
        """
        filtered_dataset = []
        skipped_indices = []

        for idx, entry in enumerate(self.dataset):
            # Extract prompt from the dataset entry
            prompt_text = entry.get("prompt", "").strip()

            # Also check conversations format
            if not prompt_text:
                conversations = entry.get("conversations", [])
                for msg in conversations:
                    role = msg.get("role") or msg.get("from")
                    if role in {"user", "human"}:
                        prompt_text = (msg.get("content") or msg.get("value", "")).strip()
                        break

            if prompt_text in completed_prompts:
                skipped_indices.append(idx)
            else:
                # Keep original index for tracking
                filtered_dataset.append((idx, entry))

        return filtered_dataset, skipped_indices

    run = run


from superforecasting_agent.trajectories.batch_cli import main


if __name__ == "__main__":
    fire.Fire(main)
