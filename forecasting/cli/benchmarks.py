"""``forecast bench`` / ``backtest`` — ForecastBench scoreboard + historical replay.

A carved CLI subcommand domain (the CLI-assembler pattern; see
:mod:`forecasting.cli.thesis`). ``bench`` (the read-only scoreboard) and
``backtest`` (time-aware replay) occupy two different registration positions, so
the domain exposes :func:`register_bench` and :func:`register`, each invoked at
its pre-carve position — ``forecast --help`` stays byte-identical. The
agent-protocol JSONL writers/readers travelled with ``_cmd_backtest``.

THE MONKEYPATCH CLUSTER (the coda's explicit ``_core.``-hop flag): the case
LOADERS — ``_load_backtest_cases`` (which dispatches to the ``load_*`` source
adapters), ``_apply_backtest_probability_source``, and ``list_builtin_benchmarks``
— STAY in ``core`` (they are used by ``_run_safe_benchmarks`` /
``_cmd_import_adapter`` too, and the ``load_*`` adapters are patched at
``forecasting.cli.load_*`` which forwards to ``core``). They are reached here
through call-time ``_core.`` hop wrappers so a test that patches
``forecasting.cli._load_backtest_cases`` / ``cli.list_builtin_benchmarks`` /
``cli.load_fred_observations`` reaches these carved handlers' call sites exactly
as the pre-carve single module did.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from forecasting.cli import core as _core
from forecasting.cli.core import (
    ForecastLedger,
    PRODUCT_NAME,
    _format_ci95,
    _format_delta,
    _format_metric,
    _format_pvalue,
    _format_win_rate,
    build_agent_protocol_prompt_packet,
    build_benchmark_evidence_profile,
)


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    """Hop to ``core._ledger`` at CALL time (monkeypatch discipline)."""
    return _core._ledger(args)


def _load_backtest_cases(*args, **kwargs):
    """Hop to ``core._load_backtest_cases`` at CALL time — the loader (and the
    ``load_*`` adapters it dispatches to) stay patchable at the façade."""
    return _core._load_backtest_cases(*args, **kwargs)


def _apply_backtest_probability_source(*args, **kwargs):
    """Hop to ``core._apply_backtest_probability_source`` at CALL time."""
    return _core._apply_backtest_probability_source(*args, **kwargs)


def list_builtin_benchmarks(*args, **kwargs):
    """Hop to ``core.list_builtin_benchmarks`` at CALL time (test-patched)."""
    return _core.list_builtin_benchmarks(*args, **kwargs)


def register_bench(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``bench`` scoreboard command (its registration position)."""

    bench_parser = forecast_sub.add_parser(
        "bench",
        help="Show the read-only ForecastBench backtest scoreboard (agent vs market Brier)",
    )
    bench_parser.add_argument("--limit", type=int, default=None, help="Cap the number of rows shown")
    bench_parser.add_argument("--json", action="store_true", help="Emit the machine-readable scoreboard JSON")
    bench_parser.set_defaults(_forecast_handler=_cmd_bench)


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``backtest`` command group (its registration position)."""

    backtest_parser = forecast_sub.add_parser("backtest", help="Run or inspect time-aware historical replay datasets")
    backtest_parser.add_argument("dataset", nargs="?")
    backtest_parser.add_argument("--as-of")
    backtest_parser.add_argument("--evidence-cutoff-policy", default="available_at_lte_cutoff")
    backtest_parser.add_argument(
        "--probability-source",
        choices=["dataset", "baseline-ensemble", "forecast-engine", "agent-protocol", "naive"],
        default="dataset",
        help=(
            "Choose how replay probabilities are produced: dataset uses stored "
            "case probabilities, baseline-ensemble combines explicit baselines, "
            "forecast-engine generates a local desk-ensemble probability, "
            "agent-protocol runs the forecasting protocol through AIAgent or "
            "captured JSONL agent outputs, and naive uses 0.5 for binary cases."
        ),
    )
    backtest_parser.add_argument(
        "--agent-response-jsonl",
        help=(
            "JSONL file of captured agent protocol responses keyed by case_id/id/index; "
            "used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--agent-output-jsonl",
        help=(
            "Write agent protocol responses as JSONL for later deterministic replay; "
            "used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--agent-prompt-jsonl",
        help=(
            "Write sanitized agent protocol prompt packets as JSONL for offline model runs; "
            "used with --prepare-agent-prompts and --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--prepare-agent-prompts",
        action="store_true",
        help="Only write --agent-prompt-jsonl packets for the selected dataset and do not run the backtest",
    )
    backtest_parser.add_argument("--agent-model", help="Model used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-provider", help="Provider used for agent-protocol backtests")
    backtest_parser.add_argument("--agent-max-iterations", type=int, default=12)
    backtest_parser.add_argument(
        "--closed-book",
        action="store_true",
        help=(
            "Closed-book agent-protocol replay: disable the live web/search "
            "toolset so the agent forecasts from the question text and reasoning "
            "only. Use for historical questions whose outcome is googleable. "
            "Used only with --probability-source agent-protocol."
        ),
    )
    backtest_parser.add_argument(
        "--market-hidden",
        action="store_true",
        help=(
            "MARKET-HIDDEN ARM (agent-protocol only): withhold the freeze market "
            "baseline from the agent's PROMPT so no market price is shown to it, "
            "while the market baseline is STILL scored for the head-to-head + "
            "complementarity. Pair with --closed-book for a true intrinsic-only "
            "forecast (no tooling to look the price up). ForecastBench datasets only."
        ),
    )
    backtest_parser.add_argument("--allow-calibration-memory", action="store_true")
    backtest_parser.add_argument("--benchmarks", action="store_true", help="List built-in benchmark datasets")
    backtest_parser.add_argument(
        "--all-benchmarks",
        action="store_true",
        help="Run every built-in benchmark dataset with the selected probability source",
    )
    backtest_parser.add_argument("--list", action="store_true")
    backtest_parser.add_argument("--show")
    backtest_parser.set_defaults(_forecast_handler=_cmd_backtest)



def _cmd_bench(args: argparse.Namespace) -> None:
    """Print the read-only ForecastBench backtest scoreboard (agent vs market Brier)."""

    from forecasting.dashboard import build_bench_scoreboard

    ledger = _ledger(args)
    payload = build_bench_scoreboard(ledger=ledger, limit=args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    rows = payload["rows"]
    aggregate = payload["aggregate"]
    print(PRODUCT_NAME)
    print(
        f"bench: questions={payload['count']}  resolved={payload['resolved_count']}  "
        f"scored_pairs={aggregate['n']}"
    )
    if not rows:
        print("no ForecastBench questions found (ingest a forecastbench dataset first)")
        return

    header = (
        f"{'QUESTION':<40} {'SRC':<10} {'AGENT':>7} {'MARKET':>7} "
        f"{'OUT':>4} {'A.BRIER':>8} {'M.BRIER':>8} {'EDGE':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        title = (row.get("title") or row.get("id") or "")[:39]
        source = (row.get("source") or "-")[:10]
        outcome = row.get("outcome")
        out_text = "-" if outcome is None else ("1" if outcome >= 0.5 else "0")
        print(
            f"{title:<40} {source:<10} "
            f"{row.get('agent_probability_display') or '-':>7} "
            f"{row.get('market_probability_display') or '-':>7} "
            f"{out_text:>4} "
            f"{_format_metric(row.get('agent_brier')):>8} "
            f"{_format_metric(row.get('market_brier')):>8} "
            f"{_format_delta(row.get('brier_edge')):>7}"
        )
    print("-" * len(header))
    print(
        f"aggregate: n={aggregate['n']}  "
        f"mean_agent_brier={_format_metric(aggregate['mean_agent_brier'])}  "
        f"mean_market_brier={_format_metric(aggregate['mean_market_brier'])}  "
        f"edge={_format_delta(aggregate['mean_brier_edge'])} "
        f"(positive = agent beat the market freeze)"
    )


def _cmd_backtest(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    if args.agent_response_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-response-jsonl requires --probability-source agent-protocol")
    if args.agent_output_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-output-jsonl requires --probability-source agent-protocol")
    if args.agent_prompt_jsonl and args.probability_source != "agent-protocol":
        raise SystemExit("--agent-prompt-jsonl requires --probability-source agent-protocol")
    if getattr(args, "closed_book", False) and args.probability_source != "agent-protocol":
        raise SystemExit("--closed-book requires --probability-source agent-protocol")
    if getattr(args, "market_hidden", False) and args.probability_source != "agent-protocol":
        raise SystemExit("--market-hidden requires --probability-source agent-protocol")
    if args.agent_prompt_jsonl and not args.prepare_agent_prompts:
        raise SystemExit("--agent-prompt-jsonl requires --prepare-agent-prompts")
    if args.prepare_agent_prompts and args.probability_source != "agent-protocol":
        raise SystemExit("--prepare-agent-prompts requires --probability-source agent-protocol")
    if args.prepare_agent_prompts and not args.agent_prompt_jsonl:
        raise SystemExit("--prepare-agent-prompts requires --agent-prompt-jsonl")
    if args.prepare_agent_prompts and (args.agent_response_jsonl or args.agent_output_jsonl):
        raise SystemExit("--prepare-agent-prompts cannot be combined with agent response or output JSONL")
    if args.prepare_agent_prompts and (args.benchmarks or args.list or args.show):
        raise SystemExit("--prepare-agent-prompts requires a dataset or --all-benchmarks")
    if args.prepare_agent_prompts and args.dataset and args.all_benchmarks:
        raise SystemExit("--prepare-agent-prompts cannot combine a dataset with --all-benchmarks")
    if args.prepare_agent_prompts and not (args.dataset or args.all_benchmarks):
        raise SystemExit("--prepare-agent-prompts requires a dataset or --all-benchmarks")
    if args.benchmarks:
        rows = list_builtin_benchmarks()
        imported = ledger.list_benchmark_datasets()
        if not rows and not imported:
            print("No benchmarks found.")
            return
        print("Name                              Cases  Provenance        Source Families  Description")
        for row in rows:
            evidence = row.get("benchmark_evidence") or {}
            families = ",".join(evidence.get("source_families") or []) or "-"
            provenance = str(evidence.get("provenance") or "-")
            print(
                f"builtin:{row['name']:<25} "
                f"{row['case_count']:<6} "
                f"{provenance:<16} "
                f"{families:<16} "
                f"{row['description']}"
            )
        for row in imported:
            description = row.get("description") or f"Imported from {row['source']}"
            evidence = build_benchmark_evidence_profile(f"imported:{row['id']}", row.get("cases") or [])
            families = ",".join(evidence.get("source_families") or []) or "-"
            provenance = str(evidence.get("provenance") or "-")
            print(
                f"imported:{row['id']:<24} "
                f"{row['case_count']:<6} "
                f"{provenance:<16} "
                f"{families:<16} "
                f"{description}"
            )
        return
    if args.all_benchmarks:
        if args.dataset:
            raise SystemExit("forecast backtest --all-benchmarks cannot be combined with a dataset")
        rows = list_builtin_benchmarks()
        if not rows:
            print("No built-in benchmarks found.")
            return
        if args.prepare_agent_prompts:
            datasets: list[tuple[str, list[dict[str, Any]]]] = []
            for row in rows:
                dataset = f"builtin:{row['name']}"
                datasets.append((dataset, _load_backtest_cases(dataset, ledger=ledger)))
            path, total_cases = _write_agent_protocol_prompt_jsonl_for_datasets(
                args.agent_prompt_jsonl,
                datasets,
            )
            print(f"agent_protocol_prompts: {path}")
            print(f"benchmark_suite: builtin ({len(rows)} datasets)")
            print(f"cases: {total_cases}")
            for dataset, cases in datasets:
                print(f"  {dataset}: {len(cases)}")
            print("next: run the prompt packets through an agent, then replay responses with:")
            print(
                "  forecast backtest --all-benchmarks --probability-source agent-protocol "
                "--agent-response-jsonl <responses.jsonl>"
            )
            return
        agent_runner = (
            _backtest_agent_protocol_runner(args)
            if args.probability_source == "agent-protocol"
            else None
        )
        recorded_agent_model = _resolved_recorded_agent_model(args, agent_runner)
        print(f"benchmark_suite: builtin ({len(rows)} datasets)")
        print(f"probability_source: {args.probability_source}")
        suite_runs = 0
        suite_cases = 0
        suite_scored = 0
        for row in rows:
            dataset = f"builtin:{row['name']}"
            cases = _apply_backtest_probability_source(
                _load_backtest_cases(dataset, ledger=ledger),
                args.probability_source,
                agent_runner=agent_runner,
                agent_model=recorded_agent_model,
                agent_provider=args.agent_provider,
            )
            run = ledger.run_backtest_dataset(
                dataset=dataset,
                cases=cases,
                default_forecast_time_cutoff=args.as_of,
                evidence_cutoff_policy=args.evidence_cutoff_policy,
                allow_calibration_memory=args.allow_calibration_memory,
            )
            summary = run["result_summary"]
            suite_runs += 1
            suite_cases += int(summary.get("case_count", 0) or 0)
            suite_scored += int(summary.get("scored_cases", 0) or 0)
            print(
                f"{dataset} backtest_run={run['id']} "
                f"cases={summary.get('case_count', 0)} "
                f"scored={summary.get('scored_cases', 0)} "
                f"agent_mean_brier={_format_metric(summary.get('agent_mean_brier'))} "
                f"leakage={run['leakage_checks_passed']}"
            )
        print(f"suite_summary: runs={suite_runs} cases={suite_cases} scored={suite_scored}")
        return
    if args.list:
        rows = ledger.list_backtest_runs()
        if not rows:
            print("No backtest runs found.")
            return
        print("ID             Dataset              Cases  Scored  Leakage  Sources")
        for row in rows:
            summary = row["result_summary"]
            sources = ",".join(summary.get("probability_sources") or ["dataset"])
            print(
                f"{row['id']:<14} {row['dataset']:<20} "
                f"{summary.get('case_count', 0):<6} {summary.get('scored_cases', 0):<7} "
                f"{row['leakage_checks_passed']!s:<8} {sources}"
            )
        return
    if args.show:
        run = ledger.get_backtest_run(args.show)
        cases = ledger.list_backtest_cases(args.show)
        report = ledger.backtest_performance_report(args.show)
        print(f"backtest_run: {run['id']}")
        print(f"dataset: {run['dataset']}")
        print(f"leakage_checks_passed: {run['leakage_checks_passed']}")
        print(
            "probability_sources: "
            f"{', '.join(run['result_summary'].get('probability_sources') or ['dataset'])}"
        )
        print(f"cases: {len(cases)}")
        agent = report["agent"]
        print(
            "agent_mean_brier: "
            f"{_format_metric(agent['mean_brier'])} n={agent['count']}"
        )
        if report["baselines"]:
            print("baselines:")
            for baseline in report["baselines"]:
                name = f"{baseline['baseline_type']}:{baseline['source']}"
                print(
                    f"  {name} mean_brier={_format_metric(baseline['mean_brier'])} "
                    f"n={baseline['count']} paired={baseline['paired_count']} "
                    f"brier_improvement={_format_metric(baseline['mean_brier_improvement_vs_baseline'])}"
                )
                print(
                    "    paired_brier "
                    f"agent={_format_metric(baseline.get('paired_agent_mean_brier'))} "
                    f"baseline={_format_metric(baseline.get('paired_baseline_mean_brier'))} "
                    f"edge={_format_delta(baseline.get('paired_agent_edge_mean_brier'))} "
                    f"ci95={_format_ci95(baseline.get('paired_agent_edge_ci95_low'), baseline.get('paired_agent_edge_ci95_high'))} "
                    f"p={_format_pvalue(baseline.get('paired_p_value'))} "
                    f"floor={_format_metric(baseline.get('paired_brier_coin_flip_floor'))} "
                    f"wins={baseline.get('paired_agent_wins', 0)}/"
                    f"{baseline.get('paired_baseline_wins', 0)}/"
                    f"{baseline.get('paired_ties', 0)}"
                )
            win_rate = report.get("win_rate_vs_best") or {}
            if win_rate.get("win_rate_vs_best") is not None:
                print(
                    "  win_rate_vs_best="
                    f"{_format_win_rate(win_rate.get('win_rate_vs_best'), win_rate.get('win_rate_vs_best_n'))}"
                )
        else:
            print("baselines: none")
        if report["agent_by_domain"]:
            print("agent_by_domain:")
            for domain, summary in report["agent_by_domain"].items():
                print(f"  {domain} mean_brier={_format_metric(summary['mean_brier'])} n={summary['count']}")
        if report["agent_by_horizon"]:
            print("agent_by_horizon:")
            for horizon, summary in report["agent_by_horizon"].items():
                print(f"  {horizon} mean_brier={_format_metric(summary['mean_brier'])} n={summary['count']}")
        for case in cases:
            snapshot_details = _backtest_case_snapshot_details(ledger, case)
            print(
                f"  {case['id']} question={case['question_id']} "
                f"score={case['score_record_id'] or '-'} leakage={case['leakage_check_status']}"
                f"{snapshot_details}"
            )
        return
    if args.prepare_agent_prompts:
        if not args.dataset:
            raise SystemExit("forecast backtest --prepare-agent-prompts requires a dataset")
        cases = _load_backtest_cases(
            args.dataset,
            ledger=ledger,
            hide_market_baseline=getattr(args, "market_hidden", False),
        )
        path = _write_agent_protocol_prompt_jsonl(args.agent_prompt_jsonl, cases, dataset=args.dataset)
        print(f"agent_protocol_prompts: {path}")
        print(f"cases: {len(cases)}")
        print("next: run the prompt packets through an agent, then replay responses with:")
        print(
            "  forecast backtest "
            f"{args.dataset} --probability-source agent-protocol "
            "--agent-response-jsonl <responses.jsonl>"
        )
        return
    if not args.dataset:
        raise SystemExit("forecast backtest requires a dataset, --list, or --show")
    agent_runner = (
        _backtest_agent_protocol_runner(args)
        if args.probability_source == "agent-protocol"
        else None
    )
    cases = _apply_backtest_probability_source(
        _load_backtest_cases(
            args.dataset,
            ledger=ledger,
            hide_market_baseline=getattr(args, "market_hidden", False),
        ),
        args.probability_source,
        agent_runner=agent_runner,
        agent_model=_resolved_recorded_agent_model(args, agent_runner),
        agent_provider=args.agent_provider,
    )
    market_hidden = bool(getattr(args, "market_hidden", False))
    run = ledger.run_backtest_dataset(
        dataset=args.dataset,
        cases=cases,
        default_forecast_time_cutoff=args.as_of,
        evidence_cutoff_policy=args.evidence_cutoff_policy,
        allow_calibration_memory=args.allow_calibration_memory,
        arm="market_hidden" if market_hidden else None,
    )
    print(f"backtest_run: {run['id']}")
    print(f"cases: {run['result_summary'].get('case_count', 0)}")
    print(f"scored_cases: {run['result_summary'].get('scored_cases', 0)}")
    print(f"leakage_checks_passed: {run['leakage_checks_passed']}")
    if market_hidden:
        _print_market_hidden_report(ledger, run["id"])


def _print_market_hidden_report(ledger: ForecastLedger, run_id: str) -> None:
    """Market-hidden arm scoring report: agent vs the WITHHELD market baseline.

    Reuses the run's :meth:`ForecastLedger.backtest_performance_report` for the
    agent Brier + market baseline Brier + P0.2 paired-bootstrap edge CI / p-value /
    win-rate (same cases), and :func:`market_ensemble.market_hidden_pool_report` for
    the equal-weight log-odds POOL Brier + the P1.3 fitted-simplex complementarity
    (does a market+agent blend beat both?). Read-only."""
    from forecasting.market_ensemble import market_hidden_pool_report

    perf = ledger.backtest_performance_report(run_id)
    pool = market_hidden_pool_report(ledger, run_id)
    agent_brier = (perf.get("agent") or {}).get("mean_brier")
    market_row = next(
        (b for b in perf.get("baselines") or [] if b.get("baseline_type") == "market"),
        None,
    )

    print("market-hidden arm (market price scored as baseline, WITHHELD from the agent):")
    print(f"  paired cases: {pool['n']}" + (f" (skipped {pool['skipped']})" if pool["skipped"] else ""))
    print(f"  agent Brier   = {_format_metric(agent_brier)}")
    if market_row is not None:
        print(f"  market Brier  = {_format_metric(market_row.get('mean_brier'))}")
        print(
            "  agent edge vs market (market_brier - agent_brier) = "
            f"{_format_delta(market_row.get('paired_agent_edge_mean_brier'))} "
            f"ci95={_format_ci95(market_row.get('paired_agent_edge_ci95_low'), market_row.get('paired_agent_edge_ci95_high'))} "
            f"p={_format_pvalue(market_row.get('paired_p_value'))}"
        )
        print(
            "  win-rate vs market = "
            f"{_format_win_rate(pool.get('win_rate_vs_market'), pool['n'])} "
            f"(wins/losses/ties {market_row.get('paired_agent_wins', 0)}/"
            f"{market_row.get('paired_baseline_wins', 0)}/{market_row.get('paired_ties', 0)})"
        )
    else:
        print("  market Brier  = - (no scored market baseline on this run)")
    print(
        "  pooled (agent+market log-odds) Brier = "
        f"{_format_metric(pool.get('pooled_brier'))}  "
        f"beats_both={bool(pool.get('pool_beats_both'))}"
    )
    fitted = pool.get("fitted") or {}
    weights = fitted.get("weights")
    if weights:
        wtxt = ", ".join(f"{name}={weights[name]:.3f}" for name in sorted(weights))
        print(f"  fitted simplex complementarity: weights[{wtxt}]")
    print(
        "    loo_ensemble_brier (honest) = "
        f"{_format_metric(fitted.get('loo_ensemble_brier'))}  "
        f"blend beats BOTH (LOO) = {bool(fitted.get('beats_both'))}"
    )
    for note in pool.get("notes") or []:
        print(f"  note: {note}")


def _backtest_case_snapshot_details(ledger: ForecastLedger, case: dict[str, Any]) -> str:
    forecast_id = case.get("generated_forecast_id")
    if not forecast_id:
        return " source=- method=- model=-"
    snapshot = ledger.get_snapshot(forecast_id)
    source = snapshot.metadata.get("probability_source") or snapshot.method or "dataset"
    method = snapshot.method or "-"
    model = snapshot.agent_model or "-"
    return f" source={source} method={method} model={model}"


def _resolved_recorded_agent_model(args: argparse.Namespace, agent_runner) -> str | None:
    """Model recorded on agent-protocol cases (drives the P2.4 cutoff gate).

    Prefer the explicit ``--agent-model``; otherwise fall back to the live
    agent's RESOLVED default model (exposed by ``_backtest_agent_protocol_runner``
    as ``resolved_agent_model``) so the model-cutoff gate still fires when
    ``--agent-model`` is omitted instead of recording an empty string.
    """

    explicit = getattr(args, "agent_model", None)
    if explicit:
        return explicit
    return getattr(agent_runner, "resolved_agent_model", None)


def _backtest_agent_protocol_runner(args: argparse.Namespace):
    output_path = _prepare_agent_protocol_output_jsonl(args.agent_output_jsonl)
    if args.agent_response_jsonl:
        responses = _load_agent_protocol_response_jsonl(args.agent_response_jsonl)

        def captured_runner(messages: list[dict[str, str]], case: dict[str, Any], index: int) -> Any:
            del messages
            keys = []
            if case.get("id") is not None:
                keys.append(str(case["id"]))
            keys.extend([f"index:{index}", str(index)])
            for key in keys:
                if key in responses:
                    response = responses[key]
                    _write_agent_protocol_response_jsonl(output_path, case, index, response)
                    return response
            raise SystemExit(
                "agent protocol response missing for "
                f"{case.get('id') or f'index:{index}'}"
            )

        # Replaying captured responses: no live agent, so the recorded model is
        # whatever the operator passed (the responses themselves carry agent_model).
        captured_runner.resolved_agent_model = args.agent_model or None
        return captured_runner

    from run_agent import AIAgent

    # Closed-book replay: the agent must have NO tool that can reach the now-known
    # outcome, so a historical question cannot be answered by fetching/reading it.
    # Dropping "web" is NOT enough, and neither is keeping "file": (a) the
    # "forecasting" toolset's forecast_ledger.import_source_evidence fetches the LIVE
    # current state of manifold/metaculus/polymarket/url sources (the answer), and
    # (b) the "file" toolset's read_file/search_files can read the on-disk
    # ForecastBench resolution-set cache (which holds resolved_to for every id). The
    # agent-protocol replay scores the agent's parsed JSON OUTPUT and needs NO tools
    # to emit a forecast, so closed-book runs with an EMPTY toolset — reason only.
    closed_book = bool(getattr(args, "closed_book", False))
    enabled_toolsets = [] if closed_book else ["forecasting", "file", "web"]

    agent = AIAgent(
        model=args.agent_model or "",
        provider=args.agent_provider,
        max_iterations=args.agent_max_iterations,
        enabled_toolsets=enabled_toolsets,
        platform="cli",
    )

    def live_runner(messages: list[dict[str, str]], case: dict[str, Any], index: int) -> Any:
        result = agent.run_conversation(
            messages[1]["content"],
            system_message=messages[0]["content"],
        )
        if isinstance(result, dict):
            response = result.get("final_response") or result
        else:
            response = result
        _write_agent_protocol_response_jsonl(output_path, case, index, response)
        return response

    # P2.4 model-cutoff gate fires on the recorded agent_model; default it to the
    # agent's RESOLVED/default model so the gate works even when --agent-model is
    # omitted (agent.model is the resolved default, not the empty placeholder).
    live_runner.resolved_agent_model = (
        getattr(agent, "model", None) or args.agent_model or None
    )
    return live_runner


def _prepare_agent_protocol_output_jsonl(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _write_agent_protocol_prompt_jsonl(path_value: str, cases: list[dict[str, Any]], *, dataset: str) -> Path:
    path, _ = _write_agent_protocol_prompt_jsonl_for_datasets(path_value, [(dataset, cases)])
    return path


def _write_agent_protocol_prompt_jsonl_for_datasets(
    path_value: str,
    datasets: list[tuple[str, list[dict[str, Any]]]],
) -> tuple[Path, int]:
    path = Path(path_value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    total_cases = 0
    with path.open("w", encoding="utf-8") as handle:
        for dataset, cases in datasets:
            for index, case in enumerate(cases):
                packet = build_agent_protocol_prompt_packet(case, case_index=index, dataset=dataset)
                handle.write(json.dumps(packet, sort_keys=True) + "\n")
                total_cases += 1
    return path, total_cases


def _write_agent_protocol_response_jsonl(
    path: Path | None,
    case: dict[str, Any],
    index: int,
    response: Any,
) -> None:
    if path is None:
        return
    row = {
        "case_id": case.get("id"),
        "index": index,
        "response": response,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _load_agent_protocol_response_jsonl(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise SystemExit(f"agent response JSONL file not found: {path}")
    responses: dict[str, Any] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"agent response JSONL line {line_number} is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"agent response JSONL line {line_number} must be an object")
        key = payload.get("case_id", payload.get("id", payload.get("index")))
        if key is None:
            raise SystemExit(
                f"agent response JSONL line {line_number} needs case_id, id, or index"
            )
        responses[str(key)] = payload.get("response", payload)
    return responses
