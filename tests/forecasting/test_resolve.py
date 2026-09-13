"""Tests for name-based question resolution (no UUIDs) and the trigger
observation-date recency fix."""

from __future__ import annotations

import argparse

import pytest

from forecasting import ForecastLedger
from forecasting.cli import register_cli
from forecasting.search import resolve_question_ref
import tools.forecasting_tool as ft


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "resolve.db"))
    ledger.initialize_schema()
    return ledger


def _two_questions(ledger):
    cpi = ledger.create_question(
        title="What will the May 2026 US CPI-U all-items 12-month percent change be?",
        resolution_criteria="Resolves to the first-published BLS CPI-U YoY for May 2026.",
    )
    tx = ledger.create_question(
        title="Texas Senate Election Winner",
        resolution_criteria="Resolves to the party certified as the winner of the Texas U.S. Senate race.",
    )
    return cpi, tx


# ── resolve_question_ref ────────────────────────────────────────────────────


def test_resolve_by_exact_id(tmp_path):
    ledger = _ledger(tmp_path)
    cpi, _ = _two_questions(ledger)
    res = resolve_question_ref(ledger, cpi.id)
    assert res.reason == "id"
    assert res.question.id == cpi.id


def test_resolve_unknown_id_is_not_found(tmp_path):
    ledger = _ledger(tmp_path)
    _two_questions(ledger)
    res = resolve_question_ref(ledger, "fq_deadbeef0000")
    assert res.reason == "not_found"
    assert res.question is None


def test_resolve_by_name_unique(tmp_path):
    ledger = _ledger(tmp_path)
    _, tx = _two_questions(ledger)
    res = resolve_question_ref(ledger, "Texas Senate")
    assert res.question is not None and res.question.id == tx.id
    assert res.reason in {"unique_match", "best_match"}


def test_resolve_by_name_best_match(tmp_path):
    ledger = _ledger(tmp_path)
    cpi, _ = _two_questions(ledger)
    res = resolve_question_ref(ledger, "May CPI")
    assert res.question is not None and res.question.id == cpi.id


def test_resolve_no_match_is_not_found(tmp_path):
    ledger = _ledger(tmp_path)
    _two_questions(ledger)
    res = resolve_question_ref(ledger, "zebra quantum widget")
    assert res.reason == "not_found"
    assert res.question is None


def test_resolve_ambiguous_returns_candidates(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.create_question(
        title="Texas Senate Election Winner",
        resolution_criteria="Resolves to the certified Texas U.S. Senate winner.",
    )
    ledger.create_question(
        title="Florida Senate Election Winner",
        resolution_criteria="Resolves to the certified Florida U.S. Senate winner.",
    )
    res = resolve_question_ref(ledger, "Senate Election Winner")
    assert res.reason == "ambiguous"
    assert res.question is None
    assert len(res.candidates) >= 2


def test_resolve_falls_back_to_all_statuses(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Will the bridge bond measure pass?",
        resolution_criteria="Resolves yes if the bond measure is certified as passed; otherwise no.",
    )
    # Resolve it so it is no longer 'active'; name resolution must still find it.
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="base", require_panel=False)
    ledger.resolve_question(question_id=q.id, outcome="yes")
    res = resolve_question_ref(ledger, "bridge bond measure")
    assert res.question is not None and res.question.id == q.id


# ── CLI name-based refresh ──────────────────────────────────────────────────


def _parser():
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def test_cli_refresh_resolves_name(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "resolve.db")
    ledger = ForecastLedger(db_path=db)
    ledger.initialize_schema()
    q = ledger.create_question(
        title="Texas Senate Election Winner",
        resolution_criteria="Resolves to the certified Texas U.S. Senate winner.",
    )
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.55, rationale="base", method="log_odds_pool",
        ensemble_components={"components": [
            {"name": "markets", "source": "manifold:tx", "probability": 0.55, "weight": 3},
            {"name": "base_rate", "probability": 0.4, "weight": 2}]},
        require_panel=False,
    )
    # binary so the deterministic re-pool runs
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="tx", source_type="manifold")

    def fake_fetch(specs, **k):
        return [{"source_type": s["source_type"], "source": s["source"], "success": True,
                 "payloads": [{"source_or_note": "m", "source_type": "adapter:manifold", "claim": "c", "summary": "",
                               "metadata": {"adapter": "manifold", "source": s["source"], "adapter_item": {"probability": 0.7}}}],
                 "error": None} for s in specs]

    monkeypatch.setattr("forecasting.sources.watched.fetch_watched_source_payloads", fake_fetch)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", db, "refresh", "Texas Senate"])  # NAME, not id
    args.func(args)
    out = capsys.readouterr().out
    assert "status: committed" in out


def test_cli_refresh_ambiguous_name_exits_with_shortlist(tmp_path, capsys):
    db = str(tmp_path / "resolve.db")
    ledger = ForecastLedger(db_path=db)
    ledger.initialize_schema()
    for state in ("Texas", "Florida"):
        ledger.create_question(
            title=f"{state} Senate Election Winner",
            resolution_criteria=f"Resolves to the certified {state} U.S. Senate winner.",
        )
    parser = _parser()
    with pytest.raises(SystemExit) as exc:
        args = parser.parse_args(["forecast", "--db", db, "refresh", "Senate Election Winner"])
        args.func(args)
    assert exc.value.code == 2
    assert "matched several forecasts" in capsys.readouterr().err


# ── trigger observation-date recency (#derivation fix) ──────────────────────


def test_derive_trigger_observations_uses_observation_date_not_import_time(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Will oil pass-through lift CPI?",
        resolution_criteria="Resolves yes if CPI YoY exceeds 3.0%; otherwise no.",
    )
    # Three WTI observations imported in ONE batch (identical available_at),
    # out of observation-date order. The stale mid-month peak must NOT win.
    for obs_date, value in [("2026-05-18", 112.25), ("2026-05-26", 97.63), ("2026-05-14", 104.66)]:
        ledger.add_evidence(
            question_id=q.id, source_or_note="wti", source_type="adapter:fred",
            available_at="2026-05-28T13:10:00Z",
            metadata={"adapter": "fred", "source": "DCOILWTICO", "entry_id": f"DCOILWTICO:{obs_date}",
                      "adapter_item": {"value": value, "observation_date": obs_date}},
        )
    obs = ledger._derive_trigger_observations(q.id)
    # Latest observation_date (05-26 -> 97.63), not the 05-18 peak (112.25).
    assert obs["fred:DCOILWTICO"] == pytest.approx(97.63)
