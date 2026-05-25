"""Backtest performance helpers for the forecast desk."""

from __future__ import annotations

from typing import Any

from forecasting.benchmark_evidence import build_benchmark_evidence_profile
from forecasting.ledger import ForecastLedger
from forecasting.models import ScoreRecord


DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM = 100
DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM = 100
DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM = 2


def best_baseline(baselines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the lowest-Brier baseline from a performance report."""

    scored = [baseline for baseline in baselines if baseline.get("mean_brier") is not None]
    if not scored:
        return None
    return min(scored, key=lambda baseline: baseline["mean_brier"])


def benchmark_claim_status(row: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Describe what a benchmark run can and cannot prove."""

    summary = row.get("result_summary") or {}
    case_count = int(report.get("case_count") or summary.get("case_count") or 0)
    scored_count = int((report.get("agent") or {}).get("count") or summary.get("scored_cases") or 0)
    leakage_passed = bool(report.get("leakage_checks_passed"))
    probability_sources = list(summary.get("probability_sources") or [])
    has_agent_protocol = "agent-protocol" in probability_sources
    return {
        "evidence_type": (
            "agent_protocol_time_aware_backtest_replay"
            if has_agent_protocol
            else "time_aware_backtest_replay"
        ),
        "can_claim_live_superforecasting": False,
        "case_count": case_count,
        "scored_count": scored_count,
        "leakage_checks_passed": leakage_passed,
        "probability_sources": probability_sources,
        "verdict": "benchmark_replay_only",
        "message": (
            "Agent-protocol replay evidence only; live superiority requires repeated "
            "forecasts on held-out or live questions."
            if has_agent_protocol
            else "Benchmark replay evidence only; live superiority requires repeated "
            "agent-generated forecasts on held-out or live questions."
        ),
    }


def build_backtest_performance_summaries(
    ledger: ForecastLedger,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build report rows used by CLI, TUI, dashboard, and JSON exports."""

    summaries = []
    for row in rows:
        report = ledger.backtest_performance_report(row["id"])
        run_summary = row.get("result_summary") or {}
        benchmark_evidence = build_benchmark_evidence_profile(
            row["dataset"],
            result_summary=run_summary,
        )
        agent_brier = report["agent"]["mean_brier"]
        best = best_baseline(report["baselines"])
        best_summary = None
        edge = None
        if best is not None:
            if agent_brier is not None and best["mean_brier"] is not None:
                edge = best["mean_brier"] - agent_brier
            best_summary = {
                "baseline_type": best["baseline_type"],
                "source": best["source"],
                "mean_brier": best["mean_brier"],
                "agent_edge_mean_brier": edge,
                "paired_agent_edge_mean_brier": best.get("paired_agent_edge_mean_brier"),
                "paired_agent_edge_ci95_low": best.get("paired_agent_edge_ci95_low"),
                "paired_agent_edge_ci95_high": best.get("paired_agent_edge_ci95_high"),
                "paired_brier_count": best.get("paired_brier_count", best.get("paired_count", 0)),
                "paired_agent_wins": best.get("paired_agent_wins", 0),
                "paired_baseline_wins": best.get("paired_baseline_wins", 0),
                "paired_ties": best.get("paired_ties", 0),
            }
        summaries.append(
            {
                "id": row["id"],
                "dataset": row["dataset"],
                "case_count": report["case_count"],
                "benchmark_evidence": benchmark_evidence,
                "leakage_checks_passed": report["leakage_checks_passed"],
                "agent": report["agent"],
                "best_baseline": best_summary,
                "baselines": report["baselines"],
                "agent_by_domain": report["agent_by_domain"],
                "agent_by_horizon": report["agent_by_horizon"],
                "claim_status": benchmark_claim_status(row, report),
            }
        )
    return summaries


def build_forecasting_evidence_status(
    ledger: ForecastLedger,
    backtest_summaries: list[dict[str, Any]],
    *,
    min_live_scores: int = DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM,
    min_agent_protocol_cases: int = DEFAULT_MIN_AGENT_PROTOCOL_CASES_FOR_CLAIM,
    min_external_source_families: int = DEFAULT_MIN_EXTERNAL_SOURCE_FAMILIES_FOR_CLAIM,
) -> dict[str, Any]:
    """Summarize whether stored evidence can support live superiority claims."""

    live_scores = ledger.list_scores(forecast_origin="live", calibration_eligible=None)
    backtest_scores = ledger.list_scores(forecast_origin="backtest", calibration_eligible=None)
    imported_scores = ledger.list_scores(forecast_origin="imported_baseline", calibration_eligible=None)

    agent_protocol_scored = sum(
        int((summary.get("claim_status") or {}).get("scored_count") or 0)
        for summary in backtest_summaries
        if "agent-protocol" in ((summary.get("claim_status") or {}).get("probability_sources") or [])
    )
    leakage_free_runs = sum(1 for summary in backtest_summaries if summary.get("leakage_checks_passed"))
    positive_best_edge_runs = sum(
        1
        for summary in backtest_summaries
        if _uses_generated_probability_source(summary)
        and (summary.get("best_baseline") or {}).get("agent_edge_mean_brier") is not None
        and (summary["best_baseline"]["agent_edge_mean_brier"] > 0)
    )
    dataset_count = len({summary.get("dataset") for summary in backtest_summaries if summary.get("dataset")})
    external_dataset_count = sum(
        1
        for summary in backtest_summaries
        if (summary.get("benchmark_evidence") or {}).get("has_public_external_source")
    )
    source_families = sorted(
        {
            family
            for summary in backtest_summaries
            for family in ((summary.get("benchmark_evidence") or {}).get("source_families") or [])
        }
    )

    requirements = [
        _evidence_requirement(
            "live_scored_forecasts",
            "Repeated resolved live forecasts scored in the ledger.",
            observed=_score_count(live_scores),
            required=min_live_scores,
            recommended_action=(
                "Run prospective forecasts through the full loop: forecast resolve <id> "
                "--outcome <value> --source <url>; forecast score <id>; "
                "forecast postmortem <id>."
            ),
            command_templates=[
                "forecast pilot-cohort examples/forecasting/live-cohort.example.csv --dry-run",
                "forecast resolve <id> --outcome <value> --source <url>",
                "forecast score <id> --baselines",
                "forecast postmortem <id>",
            ],
        ),
        _evidence_requirement(
            "agent_protocol_scored_cases",
            "Held-out or historical agent-protocol replay cases scored without answer-side leakage.",
            observed=agent_protocol_scored,
            required=min_agent_protocol_cases,
            recommended_action=(
                "Capture or replay held-out agent-protocol cases: forecast backtest "
                "<cases.json> --probability-source agent-protocol --agent-output-jsonl "
                "captured-agent-protocol.jsonl."
            ),
            command_templates=[
                "forecast backtest --all-benchmarks --probability-source agent-protocol --agent-prompt-jsonl prompts.jsonl --prepare-agent-prompts",
                "forecast backtest --all-benchmarks --probability-source agent-protocol --agent-response-jsonl responses.jsonl",
                "forecast backtest <cases.json> --probability-source agent-protocol --agent-output-jsonl captured-agent-protocol.jsonl",
            ],
        ),
        _evidence_requirement(
            "leakage_free_backtest_runs",
            "Backtest runs with leakage checks passing.",
            observed=leakage_free_runs,
            required=1,
            recommended_action=(
                "Run a leakage-checked local replay: forecast backtest "
                "builtin:heldout-120-binary --probability-source forecast-engine."
            ),
            command_templates=[
                "forecast backtest builtin:heldout-120-binary --probability-source forecast-engine",
            ],
        ),
        _evidence_requirement(
            "positive_best_baseline_edge_runs",
            "Runs where the generated forecast source beats the best available baseline on mean Brier.",
            observed=positive_best_edge_runs,
            required=1,
            recommended_action=(
                "Compare a generated source against baselines: forecast backtest "
                "--all-benchmarks --probability-source forecast-engine; "
                "forecast performance --last 5."
            ),
            command_templates=[
                "forecast backtest --all-benchmarks --probability-source forecast-engine",
                "forecast performance --last 5",
            ],
        ),
        _evidence_requirement(
            "distinct_backtest_datasets",
            "Distinct benchmark datasets represented in recent performance summaries.",
            observed=dataset_count,
            required=2,
            recommended_action=(
                "Run at least two distinct benchmark datasets, for example "
                "builtin:heldout-120-binary and builtin:manifold-public-120-binary."
            ),
            command_templates=[
                "forecast backtest builtin:heldout-120-binary --probability-source forecast-engine",
                "forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine",
            ],
        ),
        _evidence_requirement(
            "external_benchmark_datasets",
            "Backtest datasets backed by public or imported external resolved-question sources.",
            observed=external_dataset_count,
            required=1,
            recommended_action=(
                "Replay at least one external resolved-question corpus, for example "
                "forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine "
                "or import resolved Manifold, Metaculus, Kalshi, or Polymarket cases."
            ),
            command_templates=[
                "forecast backtest builtin:manifold-public-120-binary --probability-source forecast-engine",
                "forecast import benchmark <resolved-cases.json>",
            ],
        ),
        _evidence_requirement(
            "external_source_families",
            "Distinct external resolved-question source families represented in benchmark evidence.",
            observed=len(source_families),
            required=min_external_source_families,
            recommended_action=(
                "Replay or import at least one more resolved-question family, for example "
                "Metaculus, Kalshi, Polymarket, or another audited dataset, so readiness "
                "is not anchored to a single platform."
            ),
            command_templates=[
                "forecast import benchmark <metaculus-or-kalshi-or-polymarket-cases.json>",
                "forecast backtest imported:<dataset-id> --probability-source forecast-engine",
                "forecast readiness --json",
            ],
        ),
    ]
    gaps = [
        requirement["id"]
        for requirement in requirements
        if not requirement["passed"]
    ]
    next_actions = [
        {
            "requirement_id": requirement["id"],
            "action": requirement["recommended_action"],
            "remaining": requirement["remaining"],
            "commands": requirement["command_templates"],
        }
        for requirement in requirements
        if not requirement["passed"]
    ]
    return {
        "verdict": "insufficient_live_evidence" if gaps else "benchmark_evidence_ready_live_claim_unproven",
        "can_claim_live_superforecasting": False,
        "message": (
            "Stored evidence is not enough for a live superforecasting claim."
            if gaps
            else "Benchmark evidence is stronger, but live superiority still requires prospective comparison."
        ),
        "requirements": requirements,
        "gaps": gaps,
        "next_actions": next_actions,
        "score_counts": {
            "live": _score_count(live_scores),
            "backtest": _score_count(backtest_scores),
            "imported_baseline": _score_count(imported_scores),
        },
        "scores": {
            "live": _score_summary(live_scores),
            "backtest": _score_summary(backtest_scores),
            "imported_baseline": _score_summary(imported_scores),
        },
        "backtests": {
            "run_count": len(backtest_summaries),
            "distinct_dataset_count": dataset_count,
            "external_dataset_count": external_dataset_count,
            "external_source_family_count": len(source_families),
            "source_families": source_families,
            "leakage_free_run_count": leakage_free_runs,
            "positive_best_baseline_edge_run_count": positive_best_edge_runs,
            "agent_protocol_scored_count": agent_protocol_scored,
        },
    }


def _evidence_requirement(
    requirement_id: str,
    description: str,
    *,
    observed: int,
    required: int,
    recommended_action: str,
    command_templates: list[str] | None = None,
) -> dict[str, Any]:
    remaining = max(required - observed, 0)
    return {
        "id": requirement_id,
        "description": description,
        "observed": observed,
        "required": required,
        "remaining": remaining,
        "passed": observed >= required,
        "recommended_action": recommended_action,
        "command_templates": list(command_templates or []),
    }


def _score_count(scores: list[ScoreRecord]) -> int:
    return sum(1 for score in scores if score.brier_score is not None)


def _score_summary(scores: list[ScoreRecord]) -> dict[str, Any]:
    brier_values = [score.brier_score for score in scores if score.brier_score is not None]
    log_values = [score.log_score for score in scores if score.log_score is not None]
    return {
        "count": len(brier_values),
        "mean_brier": sum(brier_values) / len(brier_values) if brier_values else None,
        "mean_log_score": sum(log_values) / len(log_values) if log_values else None,
    }


def _uses_generated_probability_source(summary: dict[str, Any]) -> bool:
    claim_status = summary.get("claim_status") or {}
    sources = claim_status.get("probability_sources") or []
    generated_sources = {"agent-protocol", "forecast-engine", "baseline-ensemble", "naive"}
    return any(source in generated_sources for source in sources)
