"""Directory processing for offline trajectory compression."""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

from rich.console import Console
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn,
    TimeElapsedColumn, TimeRemainingColumn,
)

from superforecasting_agent.trajectories.compression_types import TrajectoryMetrics


def process_directory(self, input_dir: Path, output_dir: Path):
    """
        Process all JSONL files in a directory using async parallel processing.
        
        Args:
            input_dir: Input directory containing JSONL files
            output_dir: Output directory for compressed files
        """
    # Run the async version
    asyncio.run(self._process_directory_async(input_dir, output_dir))


async def _process_directory_async(self, input_dir: Path, output_dir: Path):
    """
        Async implementation of directory processing with parallel API calls.
        """
    console = Console()

    # Record start time
    self.aggregate_metrics.processing_start_time = datetime.now().isoformat()
    start_time = time.time()

    # Find all JSONL files
    jsonl_files = sorted(input_dir.glob("*.jsonl"))

    if not jsonl_files:
        self.logger.warning(f"No JSONL files found in {input_dir}")
        return

    # Load ALL entries from all files
    console.print("\n[dim]Loading all entries...[/dim]")
    all_entries = []  # List of (file_path, entry_idx, entry)

    for file_path in jsonl_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        all_entries.append((file_path, line_num, entry))
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Skipping invalid JSON at {file_path}:{line_num}: {e}")

    total_entries = len(all_entries)

    console.print(f"\n{'='*60}")
    console.print(f"📂 Input: {input_dir}")
    console.print(f"📂 Output: {output_dir}")
    console.print(f"📄 Files to process: {len(jsonl_files)}")
    console.print(f"📊 Total trajectories: {total_entries:,}")
    console.print(f"🎯 Target max tokens: {self.config.target_max_tokens:,}")
    console.print(f"📝 Summary target tokens: {self.config.summary_target_tokens}")
    console.print(f"⚡ Max concurrent API calls: {self.config.max_concurrent_requests}")
    console.print(f"{'='*60}\n")

    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)

    # Tracking for progress display (thread-safe with lock)
    progress_lock = asyncio.Lock()
    compressed_count = 0
    skipped_count = 0
    api_calls = 0
    in_flight = 0

    # Results storage: {file_path: {entry_idx: (processed_entry, metrics)}}
    results = {f: {} for f in jsonl_files}

    # Track timeouts separately
    timeout_count = 0

    async def process_single(file_path: Path, entry_idx: int, entry: Dict,
                              progress, main_task, status_task):
        """Process a single entry with semaphore rate limiting and timeout."""
        nonlocal compressed_count, skipped_count, api_calls, in_flight, timeout_count

        async with semaphore:
            # Track in-flight
            async with progress_lock:
                in_flight += 1

            try:
                # Apply per-trajectory timeout
                processed_entry, metrics = await asyncio.wait_for(
                    self.process_entry_async(entry),
                    timeout=self.config.per_trajectory_timeout
                )
                results[file_path][entry_idx] = (processed_entry, metrics)

                # Update aggregate metrics (with lock for thread safety)
                async with progress_lock:
                    self.aggregate_metrics.add_trajectory_metrics(metrics)

                    # Update counters
                    if metrics.was_compressed:
                        compressed_count += 1
                        api_calls += metrics.summarization_api_calls
                    if metrics.skipped_under_target:
                        skipped_count += 1

                    in_flight -= 1

                    # Update progress
                    progress.advance(main_task)
                    progress.update(
                        status_task,
                        description=f"[dim]✅ {compressed_count} compressed | ⏭️ {skipped_count} skipped | ⏱️ {timeout_count} timeout | 🔄 {api_calls} API calls | ⚡ {in_flight} in-flight[/dim]"
                    )

            except asyncio.TimeoutError:
                self.logger.warning(f"Timeout processing entry from {file_path}:{entry_idx} (>{self.config.per_trajectory_timeout}s)")

                async with progress_lock:
                    self.aggregate_metrics.trajectories_failed += 1
                    timeout_count += 1
                    in_flight -= 1
                    progress.advance(main_task)
                    progress.update(
                        status_task,
                        description=f"[dim]✅ {compressed_count} compressed | ⏭️ {skipped_count} skipped | ⏱️ {timeout_count} timeout | 🔄 {api_calls} API calls | ⚡ {in_flight} in-flight[/dim]"
                    )

                # Skip this entry entirely (don't include in output)
                results[file_path][entry_idx] = None

            except Exception as e:
                self.logger.error(f"Error processing entry from {file_path}:{entry_idx}: {e}")

                async with progress_lock:
                    self.aggregate_metrics.trajectories_failed += 1
                    in_flight -= 1
                    progress.advance(main_task)

                # Keep original entry on error
                results[file_path][entry_idx] = (entry, TrajectoryMetrics())

    # Create progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        refresh_per_second=10  # Higher refresh for async
    ) as progress:
        # Main task for overall progress
        main_task = progress.add_task(
            f"[cyan]Compressing {total_entries:,} trajectories",
            total=total_entries
        )

        # Status line task
        status_task = progress.add_task(
            "[dim]Starting...[/dim]",
            total=None
        )

        # Create all tasks
        tasks = [
            process_single(file_path, entry_idx, entry, progress, main_task, status_task)
            for file_path, entry_idx, entry in all_entries
        ]

        # Run all tasks concurrently (semaphore limits actual concurrency)
        await asyncio.gather(*tasks)

        # Remove status task
        progress.remove_task(status_task)

    # Write results to output files (preserving original order)
    console.print("\n[dim]Writing output files...[/dim]")
    output_dir.mkdir(parents=True, exist_ok=True)

    for file_path in jsonl_files:
        output_path = output_dir / file_path.name
        file_results = results[file_path]

        # Sort by original entry index to preserve order, skip None (timed out) entries
        sorted_entries = [
            file_results[idx][0]
            for idx in sorted(file_results.keys())
            if file_results[idx] is not None
        ]

        with open(output_path, 'w', encoding='utf-8') as f:
            for entry in sorted_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    # Record end time
    self.aggregate_metrics.processing_end_time = datetime.now().isoformat()
    self.aggregate_metrics.processing_duration_seconds = time.time() - start_time

    # Print summary
    self._print_summary()

    # Save metrics
    if self.config.metrics_enabled:
        metrics_path = output_dir / self.config.metrics_output_file
        with open(metrics_path, 'w', encoding="utf-8") as f:
            json.dump(self.aggregate_metrics.to_dict(), f, indent=2)
        console.print(f"\n💾 Metrics saved to {metrics_path}")
