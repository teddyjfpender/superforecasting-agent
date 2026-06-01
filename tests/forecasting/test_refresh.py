"""Tests for `forecast refresh`: pull latest watched-source readings -> import
as evidence -> deterministically re-pool -> auto-commit a new live snapshot."""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting.bayes_toolkit import combine_forecasts
from forecasting.cli import register_cli
import tools.forecasting_tool as ft


# ── helpers ─────────────────────────────────────────────────────────────────


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "refresh.db"))
    ledger.initialize_schema()
    return ledger


def _market_question(ledger, *, impact=None):
    """A binary question with a market component (manifold:race) + base_rate and
    an active watched source on the market."""
    q = ledger.create_question(
        title="Will candidate R win the 2026 race?",
        resolution_criteria="Resolves yes if the Republican nominee is certified as the winner; otherwise no.",
        impact=impact,
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.55,
        rationale="baseline ensemble",
        method="log_odds_pool",
        ensemble_components={
            "components": [
                {"name": "markets", "source": "manifold:race", "probability": 0.55, "weight": 3},
                {"name": "base_rate", "probability": 0.40, "weight": 2},
            ]
        },
        require_panel=False,
    )
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="race", source_type="manifold")
    return q


def _market_fetcher(probability):
    """A stub fetcher that returns a fresh manifold reading for every spec."""

    def fetch(specs):
        return [
            {
                "source_type": spec["source_type"],
                "source": spec["source"],
                "success": True,
                "payloads": [
                    {
                        "source_or_note": f"{spec['source_type']} {spec['source']}",
                        "source_type": f"adapter:{spec['source_type']}",
                        "claim": "market reading",
                        "summary": "",
                        "metadata": {
                            "adapter": spec["source_type"],
                            "source": spec["source"],
                            "adapter_item": {"probability": probability},
                        },
                    }
                ],
                "error": None,
            }
            for spec in specs
        ]

    return fetch


def _raw_fetcher(value):
    def fetch(specs):
        return [
            {
                "source_type": spec["source_type"],
                "source": spec["source"],
                "success": True,
                "payloads": [
                    {
                        "source_or_note": f"{spec['source_type']} {spec['source']}",
                        "source_type": f"adapter:{spec['source_type']}",
                        "claim": "raw reading",
                        "summary": "",
                        "metadata": {
                            "adapter": spec["source_type"],
                            "source": spec["source"],
                            "adapter_item": {"value": value},
                        },
                    }
                ],
                "error": None,
            }
            for spec in specs
        ]

    return fetch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def _current_p(ledger, qid) -> float:
    return float(ledger.get_current_snapshot(qid).probability_or_distribution)


# ── deterministic re-pool ───────────────────────────────────────────────────


def test_refresh_dry_run_repools_without_committing(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    result = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72), dry_run=True)

    expected = combine_forecasts(
        [{"name": "markets", "probability": 0.72, "weight": 3}, {"name": "base_rate", "probability": 0.40, "weight": 2}],
        method="log_odds_pool",
    ).probability
    assert result["status"] == "re_pooled"
    assert result["committed"] is None
    assert result["proposed_probability"] == pytest.approx(expected, abs=1e-9)
    assert any("markets" in r for r in result["reasons_up"])
    # Nothing persisted.
    assert _current_p(ledger, q.id) == pytest.approx(0.55)
    assert len(ledger.list_snapshots(q.id)) == 1


def test_refresh_auto_commits_live_snapshot_satisfying_formalities(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    prior = ledger.get_current_snapshot(q.id)

    result = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72))
    assert result["status"] == "committed"

    current = ledger.get_current_snapshot(q.id)
    assert current.forecast_id == result["forecast_id"]
    assert current.forecast_origin == "live"  # scored, not exploratory
    assert current.parent_forecast_id == prior.forecast_id
    assert current.probability_or_distribution == pytest.approx(result["proposed_probability"])
    # Formalities satisfied without a human:
    assert current.metadata["panel_skipped_reason"]
    assert current.reasons_up and current.reasons_down and current.change_my_mind
    assert current.evidence_refs  # fresh import -> citations satisfied
    assert current.model_run_refs
    assert "refresh" in current.metadata


def test_refresh_no_op_when_reading_and_probability_unchanged(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72))  # commit #2
    count_after_first = len(ledger.list_snapshots(q.id))

    result = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.72))  # same reading
    assert result["status"] == "no_change"
    assert result["committed"] is None
    assert len(ledger.list_snapshots(q.id)) == count_after_first


def test_refresh_tracks_source_across_successive_moves(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.40))
    assert _current_p(ledger, q.id) == pytest.approx(0.40, abs=1e-6)
    ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.90))
    # Re-matched the market component on the SECOND refresh (source preserved).
    assert _current_p(ledger, q.id) > 0.6


# ── carry-forward / raw-data / guards ───────────────────────────────────────


def test_refresh_raw_data_carries_forward_and_flags_agent(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    # Replace the watched market with a raw FRED-style series (no probability).
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="CPIAUCSL", source_type="fred")

    result = ledger.refresh_forecast(q.id, fetcher=_raw_fetcher(3.5))
    # Raw reading imported, but a raw value cannot deterministically re-estimate.
    assert result["needs_agent"] is True
    assert result["status"] == "committed"  # evidence changed -> still commits
    assert _current_p(ledger, q.id) == pytest.approx(0.55)  # probability carried forward
    assert result["new_evidence_ids"]


def test_refresh_carry_forward_mode_skips_repool(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    result = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.90), re_estimate="carry_forward")
    assert result["needs_agent"] is True
    assert _current_p(ledger, q.id) == pytest.approx(0.55)


def test_refresh_no_watched_sources(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Will it rain?",
        resolution_criteria="Resolves yes if measurable precipitation is recorded; otherwise no.",
    )
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="base", require_panel=False)
    result = ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.9))
    assert result["status"] == "no_watched_sources"
    assert result["committed"] is None


def test_refresh_requires_baseline_snapshot(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Will it snow?",
        resolution_criteria="Resolves yes if measurable snowfall is recorded; otherwise no.",
    )
    with pytest.raises(Exception):
        ledger.refresh_forecast(q.id, fetcher=_market_fetcher(0.9))


def test_refresh_reports_fetch_failures_without_aborting(tmp_path):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)

    def failing_fetch(specs):
        return [
            {"source_type": s["source_type"], "source": s["source"], "success": False, "payloads": [], "error": "boom"}
            for s in specs
        ]

    result = ledger.refresh_forecast(q.id, fetcher=failing_fetch)
    assert result["status"] == "no_change"
    assert result["fetch_failures"] and result["fetch_failures"][0]["error"] == "boom"


# ── _refresh_pool_method ────────────────────────────────────────────────────


def test_refresh_pool_method_aliases():
    assert ForecastLedger._refresh_pool_method("log_odds_pool") == "log_odds_pool"
    assert ForecastLedger._refresh_pool_method("logit") == "log_odds_pool"
    assert ForecastLedger._refresh_pool_method("linear") == "linear_pool"
    assert ForecastLedger._refresh_pool_method("log_linear") == "log_pool"
    assert ForecastLedger._refresh_pool_method(None) == "log_odds_pool"
    assert ForecastLedger._refresh_pool_method("autopilot") == "log_odds_pool"  # fallback


# ── fetcher (tool layer) ────────────────────────────────────────────────────


def test_fetch_watched_source_payloads_isolates_failures(monkeypatch):
    from types import SimpleNamespace

    def fake_load(adapter, source, args):
        if source == "bad":
            raise RuntimeError("adapter down")
        return [SimpleNamespace(probability=0.6)]

    monkeypatch.setattr(ft, "_load_source_adapter_items", fake_load)
    out = ft.fetch_watched_source_payloads(
        [{"source_type": "manifold", "source": "good"}, {"source_type": "manifold", "source": "bad"}]
    )
    by_source = {r["source"]: r for r in out}
    assert by_source["good"]["success"] is True
    assert by_source["good"]["payloads"][0]["metadata"]["adapter_item"]["probability"] == 0.6
    assert by_source["bad"]["success"] is False
    assert "adapter down" in by_source["bad"]["error"]


# ── CLI + tool surfaces ─────────────────────────────────────────────────────


def test_cli_refresh_commits(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ft, "fetch_watched_source_payloads", lambda specs, **k: _market_fetcher(0.72)(specs))
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "refresh.db"), "refresh", q.id])
    args.func(args)
    out = capsys.readouterr().out
    assert "status: committed" in out
    assert "committed snapshot fs_" in out
    assert _current_p(ledger, q.id) != pytest.approx(0.55)


def test_cli_refresh_dry_run_json_does_not_commit(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ft, "fetch_watched_source_payloads", lambda specs, **k: _market_fetcher(0.72)(specs))
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "refresh.db"), "refresh", q.id, "--dry-run", "--json"])
    args.func(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "re_pooled"
    assert data["committed"] is None
    assert _current_p(ledger, q.id) == pytest.approx(0.55)


def test_cli_refresh_agent_routes_to_update_stage(tmp_path, capsys):
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    parser = _parser()
    # --agent --dry-run renders the update-stage protocol prompt (no model call,
    # no deterministic refresh) — proving it routes to the agent path.
    args = parser.parse_args(
        ["forecast", "--db", str(tmp_path / "refresh.db"), "refresh", q.id, "--agent", "--dry-run"]
    )
    args.func(args)
    out = capsys.readouterr().out
    assert "## system" in out and "Stage Task" in out
    assert _current_p(ledger, q.id) == pytest.approx(0.55)  # nothing committed


def test_cli_pipeline_refresh_runs_then_renders_status(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ft, "fetch_watched_source_payloads", lambda specs, **k: _market_fetcher(0.72)(specs))
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "refresh.db"), "pipeline", q.id, "--refresh"])
    args.func(args)
    out = capsys.readouterr().out
    assert out.startswith("refresh:")
    assert "stages:" in out
    assert ledger.get_current_snapshot(q.id).forecast_id  # committed snapshot is current


def test_tool_refresh_forecast_action(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "fetch_watched_source_payloads", lambda specs, **k: _market_fetcher(0.72)(specs))
    db = str(tmp_path / "refresh.db")
    ledger = _ledger(tmp_path)
    q = _market_question(ledger)

    preview = json.loads(ft.forecast_ledger_tool({"db": db, "action": "refresh_forecast", "question_id": q.id, "dry_run": True}))
    assert preview["success"] is True
    assert preview["status"] == "re_pooled"
    assert preview["committed"] is None

    committed = json.loads(ft.forecast_ledger_tool({"db": db, "action": "refresh_forecast", "question_id": q.id}))
    assert committed["success"] is True
    assert committed["status"] == "committed"
    assert committed["forecast_id"]


def test_tool_refresh_forecast_in_action_enum():
    actions = ft.FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"]
    assert "refresh_forecast" in actions


# ── evidence dedup (#4) ─────────────────────────────────────────────────────


def _fred_loader(value):
    from types import SimpleNamespace

    def load(adapter, source, args):
        return [SimpleNamespace(value=value, observation_date="2026-05-13", entry_id=f"{source}:2026-05")]

    return load


def test_import_source_evidence_dedupes_repeat_readings(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "_load_source_adapter_items", _fred_loader(3.5))
    db = str(tmp_path / "f.db")
    ledger = ForecastLedger(db_path=db)
    ledger.initialize_schema()
    q = ledger.create_question(
        title="Will CPI be high?",
        resolution_criteria="Resolves yes if CPI YoY exceeds 3.0%; otherwise no.",
    )
    base = {
        "db": db, "action": "import_source_evidence", "question_id": q.id,
        "source_type": "fred", "source": "CPIAUCSL", "available_at": "2026-05-13T00:00:00Z",
    }
    a1 = json.loads(ft.forecast_ledger_tool(dict(base)))
    a2 = json.loads(ft.forecast_ledger_tool(dict(base)))  # identical reading
    a3 = json.loads(ft.forecast_ledger_tool({**base, "dedupe": False}))  # forced
    assert a1["imported_count"] == 1 and a1["skipped_duplicates"] == 0
    assert a2["imported_count"] == 0 and a2["skipped_duplicates"] == 1
    assert a3["imported_count"] == 1 and a3["skipped_duplicates"] == 0
    assert len(ledger.list_evidence(q.id)) == 2  # not 3


def test_existing_evidence_keys_skips_entryless_notes(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "f.db"))
    ledger.initialize_schema()
    q = ledger.create_question(
        title="Will it?",
        resolution_criteria="Resolves yes if the official source confirms; otherwise no.",
    )
    ledger.add_evidence(question_id=q.id, source_or_note="free-form note, no entry_id")
    ledger.add_evidence(
        question_id=q.id, source_or_note="fred", source_type="adapter:fred",
        metadata={"entry_id": "CPIAUCSL:2026-05"},
    )
    keys = ledger.existing_evidence_keys(q.id)
    assert keys == {("adapter:fred", "CPIAUCSL:2026-05")}  # note without entry_id excluded


# ── tool-API friction (#6) ──────────────────────────────────────────────────


def test_combine_forecasts_accepts_method_aliases():
    from forecasting.bayes_toolkit import combine_forecasts, ensure_industry_backends

    ensure_industry_backends()
    comps = [{"name": "a", "probability": 0.6, "weight": 2}, {"name": "b", "probability": 0.4, "weight": 1}]
    canonical = combine_forecasts(comps, method="log_odds_pool").probability
    for alias in ("log_odds_weighted", "weighted_log_odds", "geo_mean_odds", "log_odds"):
        assert combine_forecasts(comps, method=alias).probability == pytest.approx(canonical)


def test_combine_forecasts_accepts_correlation_auto():
    from forecasting.bayes_toolkit import combine_forecasts, ensure_industry_backends

    ensure_industry_backends()
    comps = [{"name": "a", "probability": 0.6}, {"name": "b", "probability": 0.4}]
    result = combine_forecasts(comps, method="log_odds_pool", correlation_matrix="auto")
    assert result.correlation_applied is True


def test_import_url_source_type_points_to_ingest(tmp_path):
    db = str(tmp_path / "f.db")
    ledger = ForecastLedger(db_path=db)
    ledger.initialize_schema()
    q = ledger.create_question(
        title="Will it?",
        resolution_criteria="Resolves yes if the official source confirms; otherwise no.",
    )
    out = json.loads(
        ft.forecast_ledger_tool(
            {"db": db, "action": "import_source_evidence", "question_id": q.id, "source_type": "url", "source": "https://example.com"}
        )
    )
    assert out["success"] is False
    assert "ingest" in out["error"]


# ── guidance (#1, #2) ───────────────────────────────────────────────────────


def test_update_stage_guidance_requires_structured_components():
    from forecasting.protocol import _stage_task

    update_task = _stage_task("update")
    assert "ensemble_components" in update_task
    assert "forecast refresh" in update_task


def test_parse_stage_guidance_requires_executable_triggers():
    from forecasting.protocol import _stage_task

    parse_task = _stage_task("parse")
    assert "operator" in parse_task and "source_ref" in parse_task
    assert "never fires" in parse_task.lower() or "cannot be refreshed" in parse_task.lower() or "prose" in parse_task.lower()
