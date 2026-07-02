"""Tests for the triage trust gate (held-out auto vs expert) + process wiring."""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.triage import build_triage_trust_gate


@pytest.fixture
def ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "trust.db"))


def _adjudicate(ledger, auto, expert):
    [row] = ledger.record_triage_labels(verdicts=[{"triage_label": auto, "title": "x"}])
    ledger.update_triage_label(
        row["id"],
        expert_label=expert,
        triage_label=expert,
        label_source="expert",
        adjudicated_at="2026-06-30T00:00:00Z",
    )


def test_trust_gate_empty_is_suggest_only(ledger):
    gate = build_triage_trust_gate(ledger)
    assert gate["mode"] == "suggest_only"
    assert gate["can_auto_filter"] is False
    assert gate["observed_accuracy"] is None
    assert gate["n"] == 0
    assert "No adjudicated" in gate["recommended_action"]


def test_trust_gate_below_sample_is_suggest_only(ledger):
    # perfect accuracy but too few labels to trust
    _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    _adjudicate(ledger, "irrelevant", "irrelevant")
    gate = build_triage_trust_gate(ledger, threshold=0.8, min_sample=5)
    assert gate["observed_accuracy"] == 1.0
    assert gate["n"] == 2
    assert gate["mode"] == "suggest_only"  # n < min_sample
    assert "adjudicated labels" in gate["recommended_action"]


def test_trust_gate_below_threshold_is_suggest_only(ledger):
    _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    _adjudicate(ledger, "relevant_interesting", "irrelevant")  # auto wrong
    _adjudicate(ledger, "irrelevant", "relevant_interesting")  # auto wrong
    _adjudicate(ledger, "irrelevant", "irrelevant")
    gate = build_triage_trust_gate(ledger, threshold=0.8, min_sample=3)
    assert gate["observed_accuracy"] == 0.5
    assert gate["mode"] == "suggest_only"
    assert gate["passed"] is False


def test_trust_gate_cleared_is_auto(ledger):
    for _ in range(4):
        _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    gate = build_triage_trust_gate(ledger, threshold=0.8, min_sample=3)
    assert gate["observed_accuracy"] == 1.0
    assert gate["n"] == 4
    assert gate["mode"] == "auto"
    assert gate["can_auto_filter"] is True
    assert gate["passed"] is True


def test_triage_trust_action(tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    db = str(tmp_path / "t.db")
    ledger = ForecastLedger(db_path=db)
    for _ in range(3):
        _adjudicate(ledger, "irrelevant", "irrelevant")
    out = forecast_ledger_tool(
        {"action": "triage_trust", "db": db, "threshold": 0.8, "min_sample": 3}
    )
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["triage_gate"]["mode"] == "auto"
    assert payload["triage_gate"]["observed_accuracy"] == 1.0


def test_research_stage_mentions_triage():
    from forecasting.protocol import _stage_task

    research = _stage_task("research")
    assert "triage_label" in research
    assert "triage_contested" in research


def _graduated_alerts(ledger):
    return [a for a in ledger.list_alerts(unresolved_only=True) if a.reason == "triage_labeler_graduated"]


def _demoted_alerts(ledger):
    return [a for a in ledger.list_alerts(unresolved_only=True) if a.reason == "triage_labeler_demoted"]


def test_gate_graduation_alerts_once_then_is_idempotent(ledger):
    for _ in range(5):
        _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    first = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)
    assert first["transition"] == "graduated"
    assert first["alert"] is not None
    # A steady-state re-sweep is silent and does not stack a second alert.
    second = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)
    assert second is None
    assert len(_graduated_alerts(ledger)) == 1


def test_gate_hysteresis_holds_auto_through_shallow_dip(ledger):
    # Graduate on a clean sample, then dip to ~0.79 accuracy (below the 0.80 bar but
    # inside the 0.05 demote band) — must NOT demote or spam a demoted alert.
    for _ in range(15):
        _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    assert ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)["transition"] == "graduated"
    for _ in range(4):
        _adjudicate(ledger, "relevant_interesting", "irrelevant")  # auto wrong
    gate = build_triage_trust_gate(ledger, threshold=0.8, min_sample=5)
    assert gate["mode"] == "suggest_only"  # the live auto-filter gate itself flipped
    assert 0.75 <= gate["observed_accuracy"] < 0.8
    held = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)
    assert held is None  # hysteresis holds "auto" for alerting; no flap
    assert _demoted_alerts(ledger) == []


def test_gate_demotes_on_real_drop(ledger):
    for _ in range(8):
        _adjudicate(ledger, "relevant_interesting", "relevant_interesting")
    assert ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)["transition"] == "graduated"
    for _ in range(5):
        _adjudicate(ledger, "relevant_interesting", "irrelevant")  # auto wrong -> 8/13 ~ 0.62
    dropped = ledger.check_triage_gate_graduation(threshold=0.8, min_sample=5)
    assert dropped["transition"] == "demoted"
    assert dropped["alert"] is not None
    assert len(_demoted_alerts(ledger)) == 1


def test_transition_desk_state_reports_change_once(ledger):
    changed, prev = ledger.transition_desk_state("k", "auto")
    assert changed is True and prev is None
    changed, prev = ledger.transition_desk_state("k", "auto")
    assert changed is False and prev == "auto"
    changed, prev = ledger.transition_desk_state("k", "suggest_only")
    assert changed is True and prev == "auto"
