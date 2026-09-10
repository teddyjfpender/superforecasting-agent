"""Parallel orchestration, resumption, and output aggregation for batch runs."""

import json
import logging
import time
from datetime import datetime
from multiprocessing import Lock, Pool

from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TextColumn, TimeRemainingColumn,
)

from superforecasting_agent.trajectories.batch_statistics import ALL_POSSIBLE_TOOLS
from superforecasting_agent.trajectories.batch_worker import _process_batch_worker

logger = logging.getLogger("superforecasting_agent.trajectories.batch")


def run(self, resume: bool = False):
    """
        Run the batch processing pipeline.
        
        Args:
            resume (bool): Whether to resume from checkpoint
        """
    print("\n" + "=" * 70)
    print("🚀 Starting Batch Processing")
    print("=" * 70)

    # Smart resume: scan batch files by content to find completed prompts
    completed_prompt_texts = set()
    if resume:
        completed_prompt_texts = self._scan_completed_prompts_by_content()
        if completed_prompt_texts:
            print(f"   Found {len(completed_prompt_texts)} already-completed prompts by content matching")

    # Filter dataset to only include unprocessed prompts
    if resume and completed_prompt_texts:
        filtered_entries, skipped_indices = self._filter_dataset_by_completed(completed_prompt_texts)

        if not filtered_entries:
            print("\n✅ All prompts have already been processed!")
            return

        # Recreate batches from filtered entries (keeping original indices for tracking)
        batches_to_process = []
        for i in range(0, len(filtered_entries), self.batch_size):
            batch = filtered_entries[i:i + self.batch_size]
            batches_to_process.append(batch)

        self.batches = batches_to_process

        # Print prominent resume summary
        print("\n" + "=" * 70)
        print("📊 RESUME SUMMARY")
        print("=" * 70)
        print(f"   Original dataset size:     {len(self.dataset):,} prompts")
        print(f"   Already completed:         {len(skipped_indices):,} prompts")
        print("   ─────────────────────────────────────────")
        print(f"   🎯 RESUMING WITH:          {len(filtered_entries):,} prompts")
        print(f"   New batches created:       {len(batches_to_process)}")
        print("=" * 70 + "\n")

    # Load existing checkpoint (so resume doesn't clobber prior progress)
    checkpoint_data = self._load_checkpoint()
    if checkpoint_data.get("run_name") != self.run_name:
        checkpoint_data = {
            "run_name": self.run_name,
            "completed_prompts": [],
            "batch_stats": {},
            "last_updated": None
        }

    # Prepare configuration for workers.
    #
    # ``self.api_key`` may be a zero-arg callable (Azure Foundry Entra ID
    # bearer provider returned by ``agent.azure_identity_adapter``). Such
    # closures are not safely picklable across the multiprocessing.Pool
    # boundary. Drop the callable here and let each worker rebuild its
    # own provider via ``resolve_runtime_provider()``, which reads
    # ``model.auth_mode`` from ``config.yaml`` and constructs a fresh
    # token provider in the worker process (azure-identity caches
    # in-process so each worker gets its own short-lived cache).
    if callable(self.api_key) and not isinstance(self.api_key, str):
        worker_api_key = None
        print(
            "ℹ️  Detected Entra ID bearer provider — workers will rebuild "
            "credentials from config.yaml in each process.",
            flush=True,
        )
    else:
        worker_api_key = self.api_key

    config = {
        "distribution": self.distribution,
        "model": self.model,
        "max_iterations": self.max_iterations,
        "base_url": self.base_url,
        "api_key": worker_api_key,
        "verbose": self.verbose,
        "ephemeral_system_prompt": self.ephemeral_system_prompt,
        "log_prefix_chars": self.log_prefix_chars,
        "providers_allowed": self.providers_allowed,
        "providers_ignored": self.providers_ignored,
        "providers_order": self.providers_order,
        "provider_sort": self.provider_sort,
        "openrouter_min_coding_score": self.openrouter_min_coding_score,
        "max_tokens": self.max_tokens,
        "reasoning_config": self.reasoning_config,
        "prefill_messages": self.prefill_messages,
    }

    # For backward compatibility, still track by index (but this is secondary to content matching)
    completed_prompts_set = set(checkpoint_data.get("completed_prompts", []))

    # Aggregate statistics across all batches
    total_tool_stats = {}

    start_time = time.time()

    print(f"\n🔧 Initializing {self.num_workers} worker processes...")

    # Checkpoint writes happen in the parent process; keep a lock for safety.
    checkpoint_lock = Lock()

    # Process batches in parallel
    with Pool(processes=self.num_workers) as pool:
        # Create tasks for each batch
        tasks = [
            (
                batch_num,
                batch_data,
                str(self.output_dir),  # Convert Path to string for pickling
                completed_prompts_set,
                config
            )
            for batch_num, batch_data in enumerate(self.batches)
        ]

        print(f"✅ Created {len(tasks)} batch tasks")
        print("🚀 Starting parallel batch processing...\n")

        # Use rich Progress for better visual tracking with persistent bottom bar
        # redirect_stdout/stderr lets rich manage all output so progress bar stays clean
        results = []
        console = Console(force_terminal=True)
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]📦 Batches"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
            refresh_per_second=2,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as progress:
            task = progress.add_task("Processing", total=len(tasks))

            # Temporarily suppress DEBUG logging to avoid bar interference
            root_logger = logging.getLogger()
            original_level = root_logger.level
            root_logger.setLevel(logging.WARNING)

            try:
                for result in pool.imap_unordered(_process_batch_worker, tasks):
                    results.append(result)
                    progress.update(task, advance=1)

                    # Incremental checkpoint update (so resume works after crash)
                    try:
                        batch_num = result.get('batch_num')
                        completed = result.get('completed_prompts', []) or []
                        completed_prompts_set.update(completed)

                        if isinstance(batch_num, int):
                            checkpoint_data.setdefault('batch_stats', {})[str(batch_num)] = {
                                'processed': result.get('processed', 0),
                                'skipped': result.get('skipped', 0),
                                'discarded_no_reasoning': result.get('discarded_no_reasoning', 0),
                            }

                        checkpoint_data['completed_prompts'] = sorted(completed_prompts_set)
                        self._save_checkpoint(checkpoint_data, lock=checkpoint_lock)
                    except Exception as ckpt_err:
                        # Don't fail the run if checkpoint write fails
                        print(f"⚠️  Warning: Failed to save incremental checkpoint: {ckpt_err}")
            except Exception as e:
                logger.error("Batch worker failed: %s", e, exc_info=True)
                raise
            finally:
                root_logger.setLevel(original_level)

    # Aggregate all batch statistics and update checkpoint
    total_reasoning_stats = {"total_assistant_turns": 0, "turns_with_reasoning": 0, "turns_without_reasoning": 0}

    for batch_result in results:
        # Aggregate tool stats
        for tool_name, stats in batch_result.get("tool_stats", {}).items():
            if tool_name not in total_tool_stats:
                total_tool_stats[tool_name] = {
                    "count": 0,
                    "success": 0,
                    "failure": 0
                }

            total_tool_stats[tool_name]["count"] += stats["count"]
            total_tool_stats[tool_name]["success"] += stats["success"]
            total_tool_stats[tool_name]["failure"] += stats["failure"]

        # Aggregate reasoning stats
        for key in total_reasoning_stats:
            total_reasoning_stats[key] += batch_result.get("reasoning_stats", {}).get(key, 0)

    # Save final checkpoint (best-effort; incremental writes already happened)
    try:
        checkpoint_data["completed_prompts"] = sorted(completed_prompts_set)
        self._save_checkpoint(checkpoint_data, lock=checkpoint_lock)
    except Exception as ckpt_err:
        print(f"âš ï¸  Warning: Failed to save final checkpoint: {ckpt_err}")

    # Calculate success rates
    for tool_name in total_tool_stats:
        stats = total_tool_stats[tool_name]
        total_calls = stats["success"] + stats["failure"]
        if total_calls > 0:
            stats["success_rate"] = round(stats["success"] / total_calls * 100, 2)
            stats["failure_rate"] = round(stats["failure"] / total_calls * 100, 2)
        else:
            stats["success_rate"] = 0.0
            stats["failure_rate"] = 0.0

    # Combine ALL batch files in directory into a single trajectories.jsonl file
    # This includes both old batches (from previous runs) and new batches (from resume)
    # Also filter out corrupted entries (where model generated invalid tool names)
    combined_file = self.output_dir / "trajectories.jsonl"
    print(f"\n📦 Combining ALL batch files into {combined_file.name}...")

    # Valid tools auto-derived from superforecasting_agent/tooling/runtime.py — no manual updates needed
    VALID_TOOLS = ALL_POSSIBLE_TOOLS

    total_entries = 0
    filtered_entries = 0
    batch_files_found = 0

    # Find ALL batch files in the output directory (handles resume merging old + new)
    all_batch_files = sorted(self.output_dir.glob("batch_*.jsonl"))

    with open(combined_file, 'w', encoding='utf-8') as outfile:
        for batch_file in all_batch_files:
            batch_files_found += 1
            batch_num = batch_file.stem.split("_")[1]  # Extract batch number for logging

            with open(batch_file, 'r', encoding='utf-8') as infile:
                for line in infile:
                    total_entries += 1
                    try:
                        data = json.loads(line)
                        tool_stats = data.get('tool_stats', {})

                        # Check for invalid tool names (model hallucinations)
                        invalid_tools = [k for k in tool_stats if k not in VALID_TOOLS]

                        if invalid_tools:
                            filtered_entries += 1
                            invalid_preview = invalid_tools[0][:50] + "..." if len(invalid_tools[0]) > 50 else invalid_tools[0]
                            print(f"   ⚠️  Filtering corrupted entry (batch {batch_num}): invalid tool '{invalid_preview}'")
                            continue

                        outfile.write(line)
                    except json.JSONDecodeError:
                        filtered_entries += 1
                        print(f"   ⚠️  Filtering invalid JSON entry (batch {batch_num})")

    if filtered_entries > 0:
        print(f"⚠️  Filtered {filtered_entries} corrupted entries out of {total_entries} total")
    print(f"✅ Combined {batch_files_found} batch files into trajectories.jsonl ({total_entries - filtered_entries} entries)")

    # Save final statistics
    final_stats = {
        "run_name": self.run_name,
        "distribution": self.distribution,
        "total_prompts": len(self.dataset),
        "total_batches": len(self.batches),
        "batch_size": self.batch_size,
        "model": self.model,
        "completed_at": datetime.now().isoformat(),
        "duration_seconds": round(time.time() - start_time, 2),
        "tool_statistics": total_tool_stats,
        "reasoning_statistics": total_reasoning_stats,
    }

    with open(self.stats_file, 'w', encoding='utf-8') as f:
        json.dump(final_stats, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 70)
    print("📊 BATCH PROCESSING COMPLETE")
    print("=" * 70)
    print(f"✅ Prompts processed this run: {sum(r.get('processed', 0) for r in results)}")
    print(f"✅ Total trajectories in merged file: {total_entries - filtered_entries}")
    print(f"✅ Total batch files merged: {batch_files_found}")
    print(f"⏱️  Total duration: {round(time.time() - start_time, 2)}s")
    print("\n📈 Tool Usage Statistics:")
    print("-" * 70)

    if total_tool_stats:
        # Sort by count descending
        sorted_tools = sorted(
            total_tool_stats.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )

        print(f"{'Tool Name':<25} {'Count':<10} {'Success':<10} {'Failure':<10} {'Success Rate':<12}")
        print("-" * 70)
        for tool_name, stats in sorted_tools:
            print(
                f"{tool_name:<25} "
                f"{stats['count']:<10} "
                f"{stats['success']:<10} "
                f"{stats['failure']:<10} "
                f"{stats['success_rate']:.1f}%"
            )
    else:
        print("No tool calls were made during this run.")

    # Print reasoning coverage stats
    total_discarded = sum(r.get("discarded_no_reasoning", 0) for r in results)

    print("\n🧠 Reasoning Coverage:")
    print("-" * 70)
    total_turns = total_reasoning_stats["total_assistant_turns"]
    with_reasoning = total_reasoning_stats["turns_with_reasoning"]
    without_reasoning = total_reasoning_stats["turns_without_reasoning"]
    if total_turns > 0:
        pct_with = round(with_reasoning / total_turns * 100, 1)
        pct_without = round(without_reasoning / total_turns * 100, 1)
        print(f"   Total assistant turns:    {total_turns:,}")
        print(f"   With reasoning:           {with_reasoning:,} ({pct_with}%)")
        print(f"   Without reasoning:        {without_reasoning:,} ({pct_without}%)")
    else:
        print("   No assistant turns recorded.")
    if total_discarded > 0:
        print(f"   🚫 Samples discarded (zero reasoning): {total_discarded:,}")

    print(f"\n💾 Results saved to: {self.output_dir}")
    print("   - Trajectories: trajectories.jsonl (combined)")
    print("   - Individual batches: batch_*.jsonl (for debugging)")
    print(f"   - Statistics: {self.stats_file.name}")
    print(f"   - Checkpoint: {self.checkpoint_file.name}")
