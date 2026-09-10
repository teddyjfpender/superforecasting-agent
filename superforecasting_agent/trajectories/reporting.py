"""Human-readable reports for completed trajectory compression runs."""

def _print_summary(self):
    """Print comprehensive compression summary statistics."""
    m = self.aggregate_metrics.to_dict()

    # Calculate some additional stats
    total = m['summary']['total_trajectories']
    compressed = m['summary']['trajectories_compressed']
    skipped = m['summary']['trajectories_skipped_under_target']
    over_limit = m['summary']['trajectories_still_over_limit']
    failed = m['summary']['trajectories_failed']

    # Token stats
    tokens_before = m['tokens']['total_before']
    tokens_after = m['tokens']['total_after']
    tokens_saved = m['tokens']['total_saved']

    # Calculate percentages
    compressed_pct = (compressed / max(total, 1)) * 100
    skipped_pct = (skipped / max(total, 1)) * 100
    over_limit_pct = (over_limit / max(total, 1)) * 100

    print(f"\n")
    print(f"╔{'═'*70}╗")
    print(f"║{'TRAJECTORY COMPRESSION REPORT':^70}║")
    print(f"╠{'═'*70}╣")

    # Trajectories section
    print(f"║{'':2}📁 TRAJECTORIES{' '*54}║")
    print(f"║{'─'*70}║")
    print(f"║{'':4}Total Processed:        {total:>10,}{' '*32}║")
    print(f"║{'':4}├─ Compressed:          {compressed:>10,}  ({compressed_pct:>5.1f}%){' '*18}║")
    print(f"║{'':4}├─ Skipped (under limit):{skipped:>9,}  ({skipped_pct:>5.1f}%){' '*18}║")
    print(f"║{'':4}├─ Still over limit:    {over_limit:>10,}  ({over_limit_pct:>5.1f}%){' '*18}║")
    print(f"║{'':4}└─ Failed:              {failed:>10,}{' '*32}║")

    print(f"╠{'═'*70}╣")

    # Tokens section
    print(f"║{'':2}🔢 TOKENS{' '*60}║")
    print(f"║{'─'*70}║")
    print(f"║{'':4}Before Compression:     {tokens_before:>15,} tokens{' '*21}║")
    print(f"║{'':4}After Compression:      {tokens_after:>15,} tokens{' '*21}║")
    print(f"║{'':4}Total Saved:            {tokens_saved:>15,} tokens{' '*21}║")
    print(f"║{'':4}Overall Compression:    {m['tokens']['overall_compression_ratio']:>14.1%}{' '*28}║")

    if tokens_before > 0:
        savings_pct = (tokens_saved / tokens_before) * 100
        print(f"║{'':4}Space Savings:          {savings_pct:>14.1f}%{' '*28}║")

    print(f"╠{'═'*70}╣")

    # Turns section
    print(f"║{'':2}💬 CONVERSATION TURNS{' '*48}║")
    print(f"║{'─'*70}║")
    print(f"║{'':4}Before Compression:     {m['turns']['total_before']:>15,} turns{' '*22}║")
    print(f"║{'':4}After Compression:      {m['turns']['total_after']:>15,} turns{' '*22}║")
    print(f"║{'':4}Total Removed:          {m['turns']['total_removed']:>15,} turns{' '*22}║")

    print(f"╠{'═'*70}╣")

    # Averages section (for compressed trajectories only)
    print(f"║{'':2}📈 AVERAGES (Compressed Trajectories Only){' '*27}║")
    print(f"║{'─'*70}║")
    if compressed > 0:
        print(f"║{'':4}Avg Compression Ratio:  {m['averages']['avg_compression_ratio']:>14.1%}{' '*28}║")
        print(f"║{'':4}Avg Tokens Saved:       {m['averages']['avg_tokens_saved_per_compressed']:>14,.0f}{' '*28}║")
        print(f"║{'':4}Avg Turns Removed:      {m['averages']['avg_turns_removed_per_compressed']:>14.1f}{' '*28}║")
    else:
        print(f"║{'':4}No trajectories were compressed{' '*38}║")

    print(f"╠{'═'*70}╣")

    # Summarization API section
    print(f"║{'':2}🤖 SUMMARIZATION API{' '*49}║")
    print(f"║{'─'*70}║")
    print(f"║{'':4}API Calls Made:         {m['summarization']['total_api_calls']:>15,}{' '*27}║")
    print(f"║{'':4}Errors:                 {m['summarization']['total_errors']:>15,}{' '*27}║")
    print(f"║{'':4}Success Rate:           {m['summarization']['success_rate']:>14.1%}{' '*28}║")

    print(f"╠{'═'*70}╣")

    # Processing time section
    duration = m['processing']['duration_seconds']
    if duration > 60:
        time_str = f"{duration/60:.1f} minutes"
    else:
        time_str = f"{duration:.1f} seconds"

    throughput = total / max(duration, 0.001)

    print(f"║{'':2}⏱️  PROCESSING TIME{' '*51}║")
    print(f"║{'─'*70}║")
    print(f"║{'':4}Duration:               {time_str:>20}{' '*22}║")
    print(f"║{'':4}Throughput:             {throughput:>15.1f} traj/sec{' '*18}║")
    print(f"║{'':4}Started:                {m['processing']['start_time'][:19]:>20}{' '*22}║")
    print(f"║{'':4}Finished:               {m['processing']['end_time'][:19]:>20}{' '*22}║")

    print(f"╚{'═'*70}╝")

    # Distribution summary if we have data
    if self.aggregate_metrics.compression_ratios:
        ratios = self.aggregate_metrics.compression_ratios
        tokens_saved_list = self.aggregate_metrics.tokens_saved_list

        print(f"\n📊 Distribution Summary:")
        print(f"   Compression ratios: min={min(ratios):.2%}, max={max(ratios):.2%}, median={sorted(ratios)[len(ratios)//2]:.2%}")
        print(f"   Tokens saved:       min={min(tokens_saved_list):,}, max={max(tokens_saved_list):,}, median={sorted(tokens_saved_list)[len(tokens_saved_list)//2]:,}")
