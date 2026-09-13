"""`forecast readiness --run-safe-benchmarks` advances readiness OFFLINE: it runs the
builtin benchmark suite (no network / no paid LLM) via a deterministic generated
source, then re-evaluates. It closes the offline-closeable gaps (datasets / external
families / leakage / positive-edge) but leaves the genuinely-live ones."""

from __future__ import annotations

import argparse

import pytest

from forecasting.application import benchmarks as benchmark_service
from forecasting.backtesting import build_backtest_performance_summaries, build_forecasting_evidence_status
from forecasting.cli import _cmd_readiness, _run_safe_benchmarks
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "r.db"))
    lg.initialize_schema()
    return lg


@pytest.mark.timeout(180)
def test_run_safe_benchmarks_runs_offline_suite(tmp_path):
    lg = _ledger(tmp_path)
    ran = _run_safe_benchmarks(lg, "forecast-engine")
    assert ran["runs"] == 5  # the 5 builtin datasets
    assert ran["scored"] > 400  # all builtin cases are resolved/scoreable
    assert all(r["leakage_checks_passed"] for r in ran["results"])
    # both external families are present (manifold + kalshi)
    families = {r["dataset"] for r in ran["results"]}
    assert "builtin:manifold-public-120-binary" in families
    assert "builtin:kalshi-public-120-binary" in families


def _tiny_external_cases(source: str, family: str) -> list[dict[str, object]]:
    return [
        {
            "id": f"{family}-yes",
            "title": f"Will the {family} fixture resolve yes?",
            "resolution_criteria": "Resolved yes for the fixture.",
            "as_of": "2026-01-10T00:00:00Z",
            "close_time": "2026-01-20T00:00:00Z",
            "outcome": "yes",
            "baselines": [{"baseline_type": "market", "source": source, "probability": 0.6}],
            "evidence": [{"available_at": "2026-01-09T00:00:00Z", "stance": "increases"}],
        },
        {
            "id": f"{family}-no",
            "title": f"Will the {family} fixture resolve yes?",
            "resolution_criteria": "Resolved no for the fixture.",
            "as_of": "2026-01-10T00:00:00Z",
            "close_time": "2026-01-20T00:00:00Z",
            "outcome": "no",
            "baselines": [{"baseline_type": "market", "source": source, "probability": 0.4}],
            "evidence": [{"available_at": "2026-01-09T00:00:00Z", "stance": "decreases"}],
        },
    ]


def test_safe_benchmarks_close_offline_gaps_only(tmp_path, monkeypatch):
    cases_by_dataset = {
        "builtin:manifold-public-120-binary": _tiny_external_cases("manifold", "manifold"),
        "builtin:kalshi-public-120-binary": _tiny_external_cases("kalshi", "kalshi"),
    }
    monkeypatch.setattr(
        benchmark_service,
        "list_builtin_benchmarks",
        lambda: [
            {"name": "manifold-public-120-binary", "case_count": 2, "description": "fixture"},
            {"name": "kalshi-public-120-binary", "case_count": 2, "description": "fixture"},
        ],
    )
    monkeypatch.setattr(
        benchmark_service,
        "load_builtin_benchmark",
        lambda dataset, **_: list(cases_by_dataset[dataset]),
    )

    lg = _ledger(tmp_path)
    _run_safe_benchmarks(lg, "forecast-engine")
    rows = lg.list_backtest_runs()
    status = build_forecasting_evidence_status(
        lg, build_backtest_performance_summaries(lg, rows),
        min_live_scores=100, min_agent_protocol_cases=100, min_external_source_families=2,
    )
    gaps = set(status.get("gaps") or [])
    # offline benchmarks close these
    for closed in ("leakage_free_backtest_runs", "distinct_backtest_datasets", "external_source_families", "external_benchmark_datasets"):
        assert closed not in gaps, f"{closed} should be closed by the offline suite"
    # but these genuinely require prospective live / LLM work and must remain
    assert "live_scored_forecasts" in gaps
    assert "agent_protocol_scored_cases" in gaps


def test_agent_protocol_source_is_rejected_as_unsafe(tmp_path):
    lg = _ledger(tmp_path)
    args = argparse.Namespace(
        db=str(tmp_path / "r.db"), last=20, dataset=None, min_live_scores=100,
        min_agent_protocol_cases=100, min_external_source_families=2, require_evidence=False,
        json=False, run_safe_benchmarks=True, probability_source="agent-protocol", dry_run=False,
    )
    with pytest.raises(SystemExit):
        _cmd_readiness(args)
