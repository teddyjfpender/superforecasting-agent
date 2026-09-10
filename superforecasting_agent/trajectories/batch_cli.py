"""Command-line options for dataset batch runs."""

import json
import traceback


def main(
    dataset_file: str = None,
    batch_size: int = None,
    run_name: str = None,
    distribution: str = "default",
    model: str = "anthropic/claude-sonnet-4.6",
    api_key: str = None,
    base_url: str = "https://openrouter.ai/api/v1",
    max_turns: int = 10,
    num_workers: int = 4,
    resume: bool = False,
    verbose: bool = False,
    list_distributions: bool = False,
    ephemeral_system_prompt: str = None,
    log_prefix_chars: int = 100,
    providers_allowed: str = None,
    providers_ignored: str = None,
    providers_order: str = None,
    provider_sort: str = None,
    max_tokens: int = None,
    reasoning_effort: str = None,
    reasoning_disabled: bool = False,
    prefill_messages_file: str = None,
    max_samples: int = None,
):
    """
    Run batch processing of agent prompts from a dataset.

    Args:
        dataset_file (str): Path to JSONL file with 'prompt' field in each entry
        batch_size (int): Number of prompts per batch
        run_name (str): Name for this run (used for output and checkpointing)
        distribution (str): Toolset distribution to use (default: "default")
        model (str): Model name to use (default: "claude-opus-4-20250514")
        api_key (str): API key for model authentication
        base_url (str): Base URL for model API
        max_turns (int): Maximum number of tool calling iterations per prompt (default: 10)
        num_workers (int): Number of parallel worker processes (default: 4)
        resume (bool): Resume from checkpoint if run was interrupted (default: False)
        verbose (bool): Enable verbose logging (default: False)
        list_distributions (bool): List available toolset distributions and exit
        ephemeral_system_prompt (str): System prompt used during agent execution but NOT saved to trajectories (optional)
        log_prefix_chars (int): Number of characters to show in log previews for tool calls/responses (default: 20)
        providers_allowed (str): Comma-separated list of OpenRouter providers to allow (e.g. "anthropic,openai")
        providers_ignored (str): Comma-separated list of OpenRouter providers to ignore (e.g. "together,deepinfra")
        providers_order (str): Comma-separated list of OpenRouter providers to try in order (e.g. "anthropic,openai,google")
        provider_sort (str): Sort providers by "price", "throughput", or "latency" (OpenRouter only)
        max_tokens (int): Maximum tokens for model responses (optional, uses model default if not set)
        reasoning_effort (str): OpenRouter reasoning effort level: "none", "minimal", "low", "medium", "high", "xhigh" (default: "medium")
        reasoning_disabled (bool): Completely disable reasoning/thinking tokens (default: False)
        prefill_messages_file (str): Path to JSON file containing prefill messages (list of {role, content} dicts)
        max_samples (int): Only process the first N samples from the dataset (optional, processes all if not set)
        
    Examples:
        # Basic usage
        python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run
        
        # Resume interrupted run
        python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run --resume
        
        # Use specific distribution
        python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=image_test --distribution=image_gen
        
        # With disabled reasoning and max tokens
        python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run \\
                               --reasoning_disabled --max_tokens=128000
        
        # With prefill messages from file
        python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 --run_name=my_run \\
                               --prefill_messages_file=configs/prefill_opus.json
        
        # List available distributions
        python -m superforecasting_agent.trajectories.batch --list_distributions
    """
    from superforecasting_agent.trajectories.batch import BatchRunner
    # Handle list distributions
    if list_distributions:
        from superforecasting_agent.trajectories.distributions import (
            list_distributions as available_distributions, print_distribution_info,
        )

        print("📊 Available Toolset Distributions")
        print("=" * 70)

        all_dists = available_distributions()
        for dist_name in sorted(all_dists.keys()):
            print_distribution_info(dist_name)

        print("\n💡 Usage:")
        print("  python -m superforecasting_agent.trajectories.batch --dataset_file=data.jsonl --batch_size=10 \\")
        print("                         --run_name=my_run --distribution=<name>")
        return

    # Validate required arguments
    if not dataset_file:
        print("❌ Error: --dataset_file is required")
        raise SystemExit(2)

    if not batch_size or batch_size < 1:
        print("❌ Error: --batch_size must be a positive integer")
        raise SystemExit(2)

    if not run_name:
        print("❌ Error: --run_name is required")
        raise SystemExit(2)

    # Parse provider preferences (comma-separated strings to lists)
    providers_allowed_list = [p.strip() for p in providers_allowed.split(",")] if providers_allowed else None
    providers_ignored_list = [p.strip() for p in providers_ignored.split(",")] if providers_ignored else None
    providers_order_list = [p.strip() for p in providers_order.split(",")] if providers_order else None

    # Build reasoning_config from CLI flags
    # --reasoning_disabled takes priority, then --reasoning_effort, then default (medium)
    reasoning_config = None
    if reasoning_disabled:
        # Completely disable reasoning/thinking tokens
        reasoning_config = {"effort": "none"}
        print("🧠 Reasoning: DISABLED (effort=none)")
    elif reasoning_effort:
        # Use specified effort level
        valid_efforts = ["none", "minimal", "low", "medium", "high", "xhigh"]
        if reasoning_effort not in valid_efforts:
            print(f"❌ Error: --reasoning_effort must be one of: {', '.join(valid_efforts)}")
            raise SystemExit(2)
        reasoning_config = {"enabled": True, "effort": reasoning_effort}
        print(f"🧠 Reasoning effort: {reasoning_effort}")

    # Load prefill messages from JSON file if provided
    prefill_messages = None
    if prefill_messages_file:
        try:
            with open(prefill_messages_file, 'r', encoding='utf-8') as f:
                prefill_messages = json.load(f)
            if not isinstance(prefill_messages, list):
                print("❌ Error: prefill_messages_file must contain a JSON array of messages")
                raise SystemExit(2)
            print(f"💬 Loaded {len(prefill_messages)} prefill messages from {prefill_messages_file}")
        except Exception as e:
            print(f"❌ Error loading prefill messages: {e}")
            raise SystemExit(2)

    # Initialize and run batch runner
    try:
        runner = BatchRunner(
            dataset_file=dataset_file,
            batch_size=batch_size,
            run_name=run_name,
            distribution=distribution,
            max_iterations=max_turns,
            base_url=base_url,
            api_key=api_key,
            model=model,
            num_workers=num_workers,
            verbose=verbose,
            ephemeral_system_prompt=ephemeral_system_prompt,
            log_prefix_chars=log_prefix_chars,
            providers_allowed=providers_allowed_list,
            providers_ignored=providers_ignored_list,
            providers_order=providers_order_list,
            provider_sort=provider_sort,
            max_tokens=max_tokens,
            reasoning_config=reasoning_config,
            prefill_messages=prefill_messages,
            max_samples=max_samples,
        )

        runner.run(resume=resume)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        if verbose:
            traceback.print_exc()
        raise SystemExit(1)
