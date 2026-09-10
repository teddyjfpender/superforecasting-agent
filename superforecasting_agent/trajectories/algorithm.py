"""Protected-turn selection and compression for completed trajectories."""

from typing import Dict, List, Tuple

from superforecasting_agent.trajectories.compression_types import TrajectoryMetrics


def compress_trajectory(
    self,
    trajectory: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], TrajectoryMetrics]:
    """
        Compress a single trajectory to fit within target token budget.
        
        Algorithm:
        1. Count total tokens
        2. If under target, skip
        3. Find compressible region (between protected head and tail)
        4. Calculate how many tokens need to be saved
        5. Accumulate turns from start of compressible region until savings met
        6. Replace accumulated turns with single human summary
        7. Keep remaining turns intact
        
        Args:
            trajectory: List of conversation turns
            
        Returns:
            Tuple of (compressed_trajectory, metrics)
        """
    metrics = TrajectoryMetrics()
    metrics.original_turns = len(trajectory)

    # Count tokens per turn
    turn_tokens = self.count_turn_tokens(trajectory)
    total_tokens = sum(turn_tokens)
    metrics.original_tokens = total_tokens

    # Check if compression needed
    if total_tokens <= self.config.target_max_tokens:
        metrics.skipped_under_target = True
        metrics.compressed_tokens = total_tokens
        metrics.compressed_turns = len(trajectory)
        metrics.compression_ratio = 1.0
        return trajectory, metrics

    # Find protected regions
    protected, compress_start, compress_end = self._find_protected_indices(trajectory)

    # Check if there's anything to compress
    if compress_start >= compress_end:
        # Nothing to compress, return as-is
        metrics.compressed_tokens = total_tokens
        metrics.compressed_turns = len(trajectory)
        metrics.still_over_limit = total_tokens > self.config.target_max_tokens
        return trajectory, metrics

    # Calculate how much we need to save
    tokens_to_save = total_tokens - self.config.target_max_tokens

    # We'll replace N turns with 1 summary turn
    # Net savings = (sum of N turns' tokens) - summary_target_tokens
    # We need: net_savings >= tokens_to_save
    # So: sum of turns >= tokens_to_save + summary_target_tokens
    target_tokens_to_compress = tokens_to_save + self.config.summary_target_tokens

    # Accumulate turns from compress_start until we have enough savings
    accumulated_tokens = 0
    compress_until = compress_start

    for i in range(compress_start, compress_end):
        accumulated_tokens += turn_tokens[i]
        compress_until = i + 1  # Exclusive end

        # Check if we have enough savings
        if accumulated_tokens >= target_tokens_to_compress:
            break

    # If we still don't have enough savings, compress the entire compressible region
    if accumulated_tokens < target_tokens_to_compress and compress_until < compress_end:
        compress_until = compress_end
        accumulated_tokens = sum(turn_tokens[compress_start:compress_end])

    # Record compression region
    metrics.turns_compressed_start_idx = compress_start
    metrics.turns_compressed_end_idx = compress_until
    metrics.turns_in_compressed_region = compress_until - compress_start

    # Extract content for summary
    content_to_summarize = self._extract_turn_content_for_summary(
        trajectory, compress_start, compress_until
    )

    # Generate summary
    summary = self._generate_summary(content_to_summarize, metrics)

    # Build compressed trajectory
    compressed = []

    # Add head (turns before compression region)
    for i in range(compress_start):
        turn = trajectory[i].copy()
        # Add notice to system message
        if turn.get("from") == "system" and self.config.add_summary_notice:
            turn["value"] = turn["value"] + self.config.summary_notice_text
        compressed.append(turn)

    # Add summary as human message
    compressed.append({
        "from": "human",
        "value": summary
    })

    # Add tail (turns after compression region)
    for i in range(compress_until, len(trajectory)):
        compressed.append(trajectory[i].copy())

    # Calculate final metrics
    metrics.compressed_turns = len(compressed)
    metrics.compressed_tokens = self.count_trajectory_tokens(compressed)
    metrics.turns_removed = metrics.original_turns - metrics.compressed_turns
    metrics.tokens_saved = metrics.original_tokens - metrics.compressed_tokens
    metrics.compression_ratio = metrics.compressed_tokens / max(metrics.original_tokens, 1)
    metrics.was_compressed = True
    metrics.still_over_limit = metrics.compressed_tokens > self.config.target_max_tokens

    return compressed, metrics


async def compress_trajectory_async(
    self,
    trajectory: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], TrajectoryMetrics]:
    """
        Compress a single trajectory to fit within target token budget (async version).
        
        Same algorithm as compress_trajectory but uses async API calls for summarization.
        """
    metrics = TrajectoryMetrics()
    metrics.original_turns = len(trajectory)

    # Count tokens per turn
    turn_tokens = self.count_turn_tokens(trajectory)
    total_tokens = sum(turn_tokens)
    metrics.original_tokens = total_tokens

    # Check if compression needed
    if total_tokens <= self.config.target_max_tokens:
        metrics.skipped_under_target = True
        metrics.compressed_tokens = total_tokens
        metrics.compressed_turns = len(trajectory)
        metrics.compression_ratio = 1.0
        return trajectory, metrics

    # Find protected regions
    protected, compress_start, compress_end = self._find_protected_indices(trajectory)

    # Check if there's anything to compress
    if compress_start >= compress_end:
        metrics.compressed_tokens = total_tokens
        metrics.compressed_turns = len(trajectory)
        metrics.still_over_limit = total_tokens > self.config.target_max_tokens
        return trajectory, metrics

    # Calculate how much we need to save
    tokens_to_save = total_tokens - self.config.target_max_tokens
    target_tokens_to_compress = tokens_to_save + self.config.summary_target_tokens

    # Accumulate turns from compress_start until we have enough savings
    accumulated_tokens = 0
    compress_until = compress_start

    for i in range(compress_start, compress_end):
        accumulated_tokens += turn_tokens[i]
        compress_until = i + 1
        if accumulated_tokens >= target_tokens_to_compress:
            break

    # If we still don't have enough savings, compress the entire compressible region
    if accumulated_tokens < target_tokens_to_compress and compress_until < compress_end:
        compress_until = compress_end
        accumulated_tokens = sum(turn_tokens[compress_start:compress_end])

    # Record compression region
    metrics.turns_compressed_start_idx = compress_start
    metrics.turns_compressed_end_idx = compress_until
    metrics.turns_in_compressed_region = compress_until - compress_start

    # Extract content for summary
    content_to_summarize = self._extract_turn_content_for_summary(
        trajectory, compress_start, compress_until
    )

    # Generate summary (ASYNC)
    summary = await self._generate_summary_async(content_to_summarize, metrics)

    # Build compressed trajectory
    compressed = []

    # Add head (turns before compression region)
    for i in range(compress_start):
        turn = trajectory[i].copy()
        if turn.get("from") == "system" and self.config.add_summary_notice:
            turn["value"] = turn["value"] + self.config.summary_notice_text
        compressed.append(turn)

    # Add summary as human message
    compressed.append({
        "from": "human",
        "value": summary
    })

    # Add tail (turns after compression region)
    for i in range(compress_until, len(trajectory)):
        compressed.append(trajectory[i].copy())

    # Calculate final metrics
    metrics.compressed_turns = len(compressed)
    metrics.compressed_tokens = self.count_trajectory_tokens(compressed)
    metrics.turns_removed = metrics.original_turns - metrics.compressed_turns
    metrics.tokens_saved = metrics.original_tokens - metrics.compressed_tokens
    metrics.compression_ratio = metrics.compressed_tokens / max(metrics.original_tokens, 1)
    metrics.was_compressed = True
    metrics.still_over_limit = metrics.compressed_tokens > self.config.target_max_tokens

    return compressed, metrics
