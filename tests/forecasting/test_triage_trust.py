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
