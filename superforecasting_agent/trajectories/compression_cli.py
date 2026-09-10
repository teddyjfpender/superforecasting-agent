"""Command-line handling for offline trajectory compression."""

import json
from pathlib import Path

from superforecasting_agent.trajectories.compression_types import CompressionConfig


def main(
    input: str,
    output: str = None,
    config: str = "configs/trajectory_compression.yaml",
    target_max_tokens: int = None,
    tokenizer: str = None,
    sample_percent: float = None,
    seed: int = 42,
    dry_run: bool = False,
):
    """
    Compress agent trajectories to fit within a target token budget.
    
    Supports both single JSONL files and directories containing multiple JSONL files.
    Optionally sample a percentage of trajectories before compression.
    
    Args:
        input: Path to JSONL file or directory containing JSONL files
        output: Output path (file for file input, directory for dir input)
                Default: adds "_compressed" suffix to input name
        config: Path to YAML configuration file
        target_max_tokens: Override target token count from config
        tokenizer: Override tokenizer name from config
        sample_percent: Sample this percentage of trajectories (1-100) before compression
        seed: Random seed for sampling reproducibility (default: 42)
        dry_run: Analyze without compressing (just show what would happen)
    
    Examples:
        # Compress a directory (original behavior)
        python -m superforecasting_agent.trajectories.compression --input=data/my_run
        
        # Compress a single file
        python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl
        
        # Compress 15% sample of a file
        python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl --sample_percent=15
        
        # Compress 10% sample with custom output
        python -m superforecasting_agent.trajectories.compression --input=data/trajectories.jsonl --sample_percent=10 --output=data/sampled_compressed.jsonl
    """
    from superforecasting_agent.trajectories.compression import TrajectoryCompressor
    import random
    import tempfile
    import shutil

    print("🗜️  Trajectory Compressor")
    print("=" * 60)

    # Load configuration
    config_path = Path(config)
    if config_path.exists():
        print(f"📋 Loading config from {config}")
        compression_config = CompressionConfig.from_yaml(config)
    else:
        print(f"⚠️  Config not found at {config}, using defaults")
        compression_config = CompressionConfig()

    # Apply CLI overrides
    if target_max_tokens:
        compression_config.target_max_tokens = target_max_tokens
    if tokenizer:
        compression_config.tokenizer_name = tokenizer

    # Validate sample_percent
    if sample_percent is not None:
        if sample_percent <= 0 or sample_percent > 100:
            print(f"❌ sample_percent must be between 1 and 100, got {sample_percent}")
            return
        print(f"🎲 Will sample {sample_percent}% of trajectories (seed={seed})")

    # Setup paths and determine input type
    input_path = Path(input)
    if not input_path.exists():
        print(f"❌ Input not found: {input}")
        return

    is_file_input = input_path.is_file()

    if is_file_input:
        print(f"📄 Input mode: Single JSONL file")

        # For file input, default output is file with _compressed suffix
        if output:
            output_path = Path(output)
        else:
            output_path = input_path.parent / (input_path.stem + compression_config.output_suffix + ".jsonl")

        # Load entries from the single file
        entries = []
        with open(input_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"⚠️  Skipping invalid JSON at line {line_num}: {e}")

        total_entries = len(entries)
        print(f"   Loaded {total_entries:,} trajectories from {input_path.name}")

        # Sample if requested
        if sample_percent is not None:
            random.seed(seed)
            sample_size = max(1, int(total_entries * sample_percent / 100))
            entries = random.sample(entries, sample_size)
            print(f"   Sampled {len(entries):,} trajectories ({sample_percent}% of {total_entries:,})")

        if dry_run:
            print(f"\n🔍 DRY RUN MODE - analyzing without writing")
            print(f"📄 Would process: {len(entries):,} trajectories")
            print(f"📄 Would output to: {output_path}")
            return

        # Create a temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_input_dir = Path(temp_dir) / "input"
            temp_output_dir = Path(temp_dir) / "output"
            temp_input_dir.mkdir()

            # Write entries to temp file
            temp_input_file = temp_input_dir / "trajectories.jsonl"
            with open(temp_input_file, 'w', encoding='utf-8') as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')

            # Initialize compressor and process
            compressor = TrajectoryCompressor(compression_config)
            compressor.process_directory(temp_input_dir, temp_output_dir)

            # Copy result to output path (merge all files in temp_output_dir)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as out_f:
                for jsonl_file in sorted(temp_output_dir.glob("*.jsonl")):
                    with open(jsonl_file, 'r', encoding='utf-8') as in_f:
                        for line in in_f:
                            out_f.write(line)

            # Copy metrics file if it exists
            metrics_file = temp_output_dir / compression_config.metrics_output_file
            if metrics_file.exists():
                metrics_output = output_path.parent / (output_path.stem + "_metrics.json")
                shutil.copy(metrics_file, metrics_output)
                print(f"💾 Metrics saved to {metrics_output}")

        print(f"\n✅ Compression complete!")
        print(f"📄 Output: {output_path}")

    else:
        # Directory input - original behavior
        print(f"📁 Input mode: Directory of JSONL files")

        if output:
            output_path = Path(output)
        else:
            output_path = input_path.parent / (input_path.name + compression_config.output_suffix)

        # If sampling is requested for directory mode, we need to handle it differently
        if sample_percent is not None:
            print(f"\n⚠️  Sampling from directory: will sample {sample_percent}% from each file")

            # Create a temp directory with sampled files
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_input_dir = Path(temp_dir) / "input"
                temp_input_dir.mkdir()

                random.seed(seed)
                total_original = 0
                total_sampled = 0

                # Sample from each JSONL file
                for jsonl_file in sorted(input_path.glob("*.jsonl")):
                    entries = []
                    with open(jsonl_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entries.append(json.loads(line))
                                except json.JSONDecodeError:
                                    pass

                    total_original += len(entries)
                    sample_size = max(1, int(len(entries) * sample_percent / 100))
                    sampled_entries = random.sample(entries, min(sample_size, len(entries)))
                    total_sampled += len(sampled_entries)

                    # Write sampled entries
                    temp_file = temp_input_dir / jsonl_file.name
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        for entry in sampled_entries:
                            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

                print(f"   Sampled {total_sampled:,} from {total_original:,} total trajectories")

                if dry_run:
                    print(f"\n🔍 DRY RUN MODE - analyzing without writing")
                    print(f"📁 Would process: {temp_input_dir}")
                    print(f"📁 Would output to: {output_path}")
                    return

                # Initialize compressor and process the sampled data
                compressor = TrajectoryCompressor(compression_config)
                compressor.process_directory(temp_input_dir, output_path)
        else:
            if dry_run:
                print(f"\n🔍 DRY RUN MODE - analyzing without writing")
                print(f"📁 Would process: {input_path}")
                print(f"📁 Would output to: {output_path}")
                return

            # Initialize compressor and process directly
            compressor = TrajectoryCompressor(compression_config)
            compressor.process_directory(input_path, output_path)

        print("\n✅ Compression complete!")
