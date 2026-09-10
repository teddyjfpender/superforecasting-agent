"""Picklable worker functions for batch trajectory generation."""

import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from agent.agent_factory import build_agent
from superforecasting_agent.trajectories.distributions import sample_toolsets_from_distribution
from superforecasting_agent.trajectories.batch_statistics import (
    _extract_reasoning_stats, _extract_tool_stats,
    _normalize_tool_error_counts, _normalize_tool_stats,
)


def _process_single_prompt(
    prompt_index: int,
    prompt_data: Dict[str, Any],
    batch_num: int,
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process a single prompt with the agent.
    
    Args:
        prompt_index (int): Index of prompt in dataset
        prompt_data (Dict): Prompt data containing 'prompt' field and optional 'image' field
        batch_num (int): Batch number
        config (Dict): Configuration dict with agent parameters
        
    Returns:
        Dict: Result containing trajectory, stats, and metadata
    """
    prompt = prompt_data["prompt"]
    task_id = f"task_{prompt_index}"

    # Per-prompt container image override: if the dataset row has an 'image' field,
    # register it for this task's sandbox. Works with Docker, Modal, Singularity, and Daytona.
    container_image = prompt_data.get("image") or prompt_data.get("docker_image")
    if container_image:
        # Verify the image is accessible before spending tokens on the agent loop.
        # For Docker: check local cache, then try pulling.
        # For Modal: skip local check (Modal pulls server-side).
        env_type = os.getenv("TERMINAL_ENV", "local")
        if env_type == "docker":
            import subprocess as _sp
            try:
                probe = _sp.run(
                    ["docker", "image", "inspect", container_image],
                    capture_output=True, timeout=10,
                )
                if probe.returncode != 0:
                    if config.get("verbose"):
                        print(f"   Prompt {prompt_index}: Pulling docker image {container_image}...", flush=True)
                    pull = _sp.run(
                        ["docker", "pull", container_image],
                        capture_output=True, text=True, timeout=600,
                    )
                    if pull.returncode != 0:
                        return {
                            "success": False,
                            "prompt_index": prompt_index,
                            "error": f"Docker image not available: {container_image}\n{pull.stderr[:500]}",
                            "trajectory": None,
                            "tool_stats": {},
                            "toolsets_used": [],
                            "metadata": {"batch_num": batch_num, "timestamp": datetime.now().isoformat()},
                        }
            except FileNotFoundError:
                pass  # Docker CLI not installed — skip check (e.g., Modal backend)
            except Exception as img_err:
                if config.get("verbose"):
                    print(f"   Prompt {prompt_index}: Docker image check failed: {img_err}", flush=True)

        from tools.terminal_tool import register_task_env_overrides
        overrides = {
            "docker_image": container_image,
            "modal_image": container_image,
            "singularity_image": f"docker://{container_image}",
            "daytona_image": container_image,
        }
        if prompt_data.get("cwd"):
            overrides["cwd"] = prompt_data["cwd"]
        register_task_env_overrides(task_id, overrides)
        if config.get("verbose"):
            print(f"   Prompt {prompt_index}: Using container image {container_image}")

    try:
        # Sample toolsets from distribution for this prompt
        selected_toolsets = sample_toolsets_from_distribution(config["distribution"])

        if config.get("verbose"):
            print(f"   Prompt {prompt_index}: Using toolsets {selected_toolsets}")

        # Initialize agent with sampled toolsets and log prefix for identification
        log_prefix = f"[B{batch_num}:P{prompt_index}]"
        agent = build_agent(
            runtime={},
            credential_context={},
            base_url=config.get("base_url"),
            api_key=config.get("api_key"),
            model=config["model"],
            max_iterations=config["max_iterations"],
            enabled_toolsets=selected_toolsets,
            save_trajectories=False,  # We handle saving ourselves
            verbose_logging=config.get("verbose", False),
            ephemeral_system_prompt=config.get("ephemeral_system_prompt"),
            log_prefix_chars=config.get("log_prefix_chars", 100),
            log_prefix=log_prefix,
            providers_allowed=config.get("providers_allowed"),
            providers_ignored=config.get("providers_ignored"),
            providers_order=config.get("providers_order"),
            provider_sort=config.get("provider_sort"),
            openrouter_min_coding_score=config.get("openrouter_min_coding_score"),
            max_tokens=config.get("max_tokens"),
            reasoning_config=config.get("reasoning_config"),
            prefill_messages=config.get("prefill_messages"),
            skip_context_files=True,  # Don't pollute trajectories with SOUL.md/AGENTS.md
            skip_memory=True,  # Don't use persistent memory in batch runs
        )

        # Run the agent with task_id to ensure each task gets its own isolated VM
        result = agent.run_conversation(prompt, task_id=task_id)

        # Extract tool usage statistics
        tool_stats = _extract_tool_stats(result["messages"])

        # Extract reasoning coverage stats
        reasoning_stats = _extract_reasoning_stats(result["messages"])

        # Convert to trajectory format (using existing method)
        trajectory = agent._convert_to_trajectory_format(
            result["messages"],
            prompt,
            result["completed"]
        )

        return {
            "success": True,
            "prompt_index": prompt_index,
            "trajectory": trajectory,
            "tool_stats": tool_stats,
            "reasoning_stats": reasoning_stats,
            "completed": result["completed"],
            "partial": result.get("partial", False),
            "api_calls": result["api_calls"],
            "toolsets_used": selected_toolsets,
            "metadata": {
                "batch_num": batch_num,
                "timestamp": datetime.now().isoformat(),
                "model": config["model"]
            }
        }

    except Exception as e:
        print(f"❌ Error processing prompt {prompt_index}: {e}")
        if config.get("verbose"):
            traceback.print_exc()

        return {
            "success": False,
            "prompt_index": prompt_index,
            "error": str(e),
            "trajectory": None,
            "tool_stats": {},
            "toolsets_used": [],
            "metadata": {
                "batch_num": batch_num,
                "timestamp": datetime.now().isoformat()
            }
        }


def _process_batch_worker(args: Tuple) -> Dict[str, Any]:
    """
    Worker function to process a single batch of prompts.
    
    Args:
        args (Tuple): (batch_num, batch_data, output_dir, completed_prompts, config)
        
    Returns:
        Dict: Batch results with statistics
    """
    batch_num, batch_data, output_dir, completed_prompts_set, config = args

    output_dir = Path(output_dir)
    print(f"\n🔄 Batch {batch_num}: Starting ({len(batch_data)} prompts)")

    # Output file for this batch
    batch_output_file = output_dir / f"batch_{batch_num}.jsonl"

    # Filter out already completed prompts
    prompts_to_process = [
        (idx, data) for idx, data in batch_data
        if idx not in completed_prompts_set
    ]

    if not prompts_to_process:
        print(f"✅ Batch {batch_num}: Already completed (skipping)")
        return {
            "batch_num": batch_num,
            "processed": 0,
            "skipped": len(batch_data),
            "tool_stats": {},
            "completed_prompts": []
        }

    print(f"   Processing {len(prompts_to_process)} prompts (skipping {len(batch_data) - len(prompts_to_process)} already completed)")

    # Initialize aggregated stats for this batch
    batch_tool_stats = {}
    batch_reasoning_stats = {"total_assistant_turns": 0, "turns_with_reasoning": 0, "turns_without_reasoning": 0}
    completed_in_batch = []
    discarded_no_reasoning = 0

    # Process each prompt sequentially in this batch
    for prompt_index, prompt_data in prompts_to_process:
        # Process the prompt
        result = _process_single_prompt(
            prompt_index,
            prompt_data,
            batch_num,
            config
        )

        # Save trajectory if successful
        if result["success"] and result["trajectory"]:
            # Discard samples with zero reasoning across all turns
            reasoning = result.get("reasoning_stats", {})
            if not reasoning.get("has_any_reasoning", True):
                print(f"   🚫 Prompt {prompt_index} discarded (no reasoning in any turn)")
                discarded_no_reasoning += 1
                completed_in_batch.append(prompt_index)
                continue

            # Get and normalize tool stats for consistent schema across all entries
            raw_tool_stats = result.get("tool_stats", {})
            tool_stats = _normalize_tool_stats(raw_tool_stats)

            # Create normalized tool_error_counts mapping tool names to their failure counts
            raw_error_counts = {
                tool_name: stats.get("failure", 0) 
                for tool_name, stats in raw_tool_stats.items()
            }
            tool_error_counts = _normalize_tool_error_counts(raw_error_counts)

            trajectory_entry = {
                "prompt_index": prompt_index,
                "conversations": result["trajectory"],
                "metadata": result["metadata"],
                "completed": result["completed"],
                "partial": result.get("partial", False),  # True if stopped due to invalid tool calls
                "api_calls": result["api_calls"],
                "toolsets_used": result["toolsets_used"],
                "tool_stats": tool_stats,  # Full stats: {tool: {count, success, failure}} - normalized
                "tool_error_counts": tool_error_counts  # Simple: {tool: failure_count} - normalized
            }

            # Append to batch output file
            with open(batch_output_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(trajectory_entry, ensure_ascii=False) + "\n")

        # Aggregate tool statistics
        for tool_name, stats in result.get("tool_stats", {}).items():
            if tool_name not in batch_tool_stats:
                batch_tool_stats[tool_name] = {
                    "count": 0,
                    "success": 0,
                    "failure": 0
                }

            batch_tool_stats[tool_name]["count"] += stats["count"]
            batch_tool_stats[tool_name]["success"] += stats["success"]
            batch_tool_stats[tool_name]["failure"] += stats["failure"]

        # Aggregate reasoning stats
        for key in batch_reasoning_stats:
            batch_reasoning_stats[key] += result.get("reasoning_stats", {}).get(key, 0)

        # Only mark as completed if successfully saved (failed prompts can be retried on resume)
        if result["success"] and result["trajectory"]:
            completed_in_batch.append(prompt_index)
            status = "⚠️  partial" if result.get("partial") else "✅"
            print(f"   {status} Prompt {prompt_index} completed")
        else:
            print(f"   ❌ Prompt {prompt_index} failed (will retry on resume)")

    print(f"✅ Batch {batch_num}: Completed ({len(prompts_to_process)} prompts processed)")

    return {
        "batch_num": batch_num,
        "processed": len(prompts_to_process),
        "skipped": len(batch_data) - len(prompts_to_process),
        "tool_stats": batch_tool_stats,
        "reasoning_stats": batch_reasoning_stats,
        "discarded_no_reasoning": discarded_no_reasoning,
        "completed_prompts": completed_in_batch
    }
