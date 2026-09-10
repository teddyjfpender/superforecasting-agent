"""Configuration and metrics for offline trajectory compression."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from superforecasting_agent.constants import OPENROUTER_BASE_URL


@dataclass
class CompressionConfig:
    """Configuration for trajectory compression."""
    # Tokenizer
    tokenizer_name: str = "moonshotai/Kimi-K2-Thinking"
    trust_remote_code: bool = True

    # Compression targets
    target_max_tokens: int = 15250
    summary_target_tokens: int = 750

    # Protected turns
    protect_first_system: bool = True
    protect_first_human: bool = True
    protect_first_gpt: bool = True
    protect_first_tool: bool = True
    protect_last_n_turns: int = 4

    # Summarization (OpenRouter)
    summarization_model: str = "google/gemini-3-flash-preview"
    base_url: str = OPENROUTER_BASE_URL
    api_key_env: str = "OPENROUTER_API_KEY"
    temperature: float = 0.3
    max_retries: int = 3
    retry_delay: int = 2

    # Output
    add_summary_notice: bool = True
    summary_notice_text: str = "\n\nSome of your previous tool responses may be summarized to preserve context."
    output_suffix: str = "_compressed"

    # Processing
    num_workers: int = 4
    max_concurrent_requests: int = 50  # Max concurrent API calls for summarization
    skip_under_target: bool = True
    save_over_limit: bool = True
    per_trajectory_timeout: int = 300  # Timeout per trajectory in seconds (default: 5 min)

    # Metrics
    metrics_enabled: bool = True
    metrics_per_trajectory: bool = True
    metrics_output_file: str = "compression_metrics.json"

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "CompressionConfig":
        """Load configuration from YAML file."""
        with open(yaml_path, 'r', encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        config = cls()

        # Tokenizer
        if 'tokenizer' in data:
            config.tokenizer_name = data['tokenizer'].get('name', config.tokenizer_name)
            config.trust_remote_code = data['tokenizer'].get('trust_remote_code', config.trust_remote_code)

        # Compression
        if 'compression' in data:
            config.target_max_tokens = data['compression'].get('target_max_tokens', config.target_max_tokens)
            config.summary_target_tokens = data['compression'].get('summary_target_tokens', config.summary_target_tokens)

        # Protected turns
        if 'protected_turns' in data:
            config.protect_first_system = data['protected_turns'].get('first_system', config.protect_first_system)
            config.protect_first_human = data['protected_turns'].get('first_human', config.protect_first_human)
            config.protect_first_gpt = data['protected_turns'].get('first_gpt', config.protect_first_gpt)
            config.protect_first_tool = data['protected_turns'].get('first_tool', config.protect_first_tool)
            config.protect_last_n_turns = data['protected_turns'].get('last_n_turns', config.protect_last_n_turns)

        # Summarization
        if 'summarization' in data:
            config.summarization_model = data['summarization'].get('model', config.summarization_model)
            config.base_url = data['summarization'].get('base_url') or config.base_url
            config.api_key_env = data['summarization'].get('api_key_env', config.api_key_env)
            config.temperature = data['summarization'].get('temperature', config.temperature)
            config.max_retries = data['summarization'].get('max_retries', config.max_retries)
            config.retry_delay = data['summarization'].get('retry_delay', config.retry_delay)

        # Output
        if 'output' in data:
            config.add_summary_notice = data['output'].get('add_summary_notice', config.add_summary_notice)
            config.summary_notice_text = data['output'].get('summary_notice_text', config.summary_notice_text)
            config.output_suffix = data['output'].get('output_suffix', config.output_suffix)

        # Processing
        if 'processing' in data:
            config.num_workers = data['processing'].get('num_workers', config.num_workers)
            config.max_concurrent_requests = data['processing'].get('max_concurrent_requests', config.max_concurrent_requests)
            config.skip_under_target = data['processing'].get('skip_under_target', config.skip_under_target)
            config.save_over_limit = data['processing'].get('save_over_limit', config.save_over_limit)

        # Metrics
        if 'metrics' in data:
            config.metrics_enabled = data['metrics'].get('enabled', config.metrics_enabled)
            config.metrics_per_trajectory = data['metrics'].get('per_trajectory', config.metrics_per_trajectory)
            config.metrics_output_file = data['metrics'].get('output_file', config.metrics_output_file)

        return config



@dataclass
class TrajectoryMetrics:
    """Metrics for a single trajectory compression."""
    original_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 1.0

    original_turns: int = 0
    compressed_turns: int = 0
    turns_removed: int = 0

    turns_compressed_start_idx: int = -1
    turns_compressed_end_idx: int = -1
    turns_in_compressed_region: int = 0

    was_compressed: bool = False
    still_over_limit: bool = False
    skipped_under_target: bool = False

    summarization_api_calls: int = 0
    summarization_errors: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": round(self.compression_ratio, 4),
            "original_turns": self.original_turns,
            "compressed_turns": self.compressed_turns,
            "turns_removed": self.turns_removed,
            "compression_region": {
                "start_idx": self.turns_compressed_start_idx,
                "end_idx": self.turns_compressed_end_idx,
                "turns_count": self.turns_in_compressed_region,
            },
            "was_compressed": self.was_compressed,
            "still_over_limit": self.still_over_limit,
            "skipped_under_target": self.skipped_under_target,
            "summarization_api_calls": self.summarization_api_calls,
            "summarization_errors": self.summarization_errors,
        }



@dataclass
class AggregateMetrics:
    """Aggregate metrics across all trajectories."""
    total_trajectories: int = 0
    trajectories_compressed: int = 0
    trajectories_skipped_under_target: int = 0
    trajectories_still_over_limit: int = 0
    trajectories_failed: int = 0

    total_tokens_before: int = 0
    total_tokens_after: int = 0
    total_tokens_saved: int = 0

    total_turns_before: int = 0
    total_turns_after: int = 0
    total_turns_removed: int = 0

    total_summarization_calls: int = 0
    total_summarization_errors: int = 0

    # Distribution stats
    compression_ratios: List[float] = field(default_factory=list)
    tokens_saved_list: List[int] = field(default_factory=list)
    turns_removed_list: List[int] = field(default_factory=list)

    processing_start_time: str = ""
    processing_end_time: str = ""
    processing_duration_seconds: float = 0.0

    def add_trajectory_metrics(self, metrics: TrajectoryMetrics):
        """Add a trajectory's metrics to the aggregate."""
        self.total_trajectories += 1
        self.total_tokens_before += metrics.original_tokens
        self.total_tokens_after += metrics.compressed_tokens
        self.total_tokens_saved += metrics.tokens_saved
        self.total_turns_before += metrics.original_turns
        self.total_turns_after += metrics.compressed_turns
        self.total_turns_removed += metrics.turns_removed
        self.total_summarization_calls += metrics.summarization_api_calls
        self.total_summarization_errors += metrics.summarization_errors

        if metrics.was_compressed:
            self.trajectories_compressed += 1
            self.compression_ratios.append(metrics.compression_ratio)
            self.tokens_saved_list.append(metrics.tokens_saved)
            self.turns_removed_list.append(metrics.turns_removed)

        if metrics.skipped_under_target:
            self.trajectories_skipped_under_target += 1

        if metrics.still_over_limit:
            self.trajectories_still_over_limit += 1

    def to_dict(self) -> Dict[str, Any]:
        avg_compression_ratio = (
            sum(self.compression_ratios) / len(self.compression_ratios)
            if self.compression_ratios else 1.0
        )
        avg_tokens_saved = (
            sum(self.tokens_saved_list) / len(self.tokens_saved_list)
            if self.tokens_saved_list else 0
        )
        avg_turns_removed = (
            sum(self.turns_removed_list) / len(self.turns_removed_list)
            if self.turns_removed_list else 0
        )

        return {
            "summary": {
                "total_trajectories": self.total_trajectories,
                "trajectories_compressed": self.trajectories_compressed,
                "trajectories_skipped_under_target": self.trajectories_skipped_under_target,
                "trajectories_still_over_limit": self.trajectories_still_over_limit,
                "trajectories_failed": self.trajectories_failed,
                "compression_rate": round(self.trajectories_compressed / max(self.total_trajectories, 1), 4),
            },
            "tokens": {
                "total_before": self.total_tokens_before,
                "total_after": self.total_tokens_after,
                "total_saved": self.total_tokens_saved,
                "overall_compression_ratio": round(self.total_tokens_after / max(self.total_tokens_before, 1), 4),
            },
            "turns": {
                "total_before": self.total_turns_before,
                "total_after": self.total_turns_after,
                "total_removed": self.total_turns_removed,
            },
            "averages": {
                "avg_compression_ratio": round(avg_compression_ratio, 4),
                "avg_tokens_saved_per_compressed": round(avg_tokens_saved, 1),
                "avg_turns_removed_per_compressed": round(avg_turns_removed, 2),
            },
            "summarization": {
                "total_api_calls": self.total_summarization_calls,
                "total_errors": self.total_summarization_errors,
                "success_rate": round(1 - (self.total_summarization_errors / max(self.total_summarization_calls, 1)), 4),
            },
            "processing": {
                "start_time": self.processing_start_time,
                "end_time": self.processing_end_time,
                "duration_seconds": round(self.processing_duration_seconds, 2),
            },
        }
