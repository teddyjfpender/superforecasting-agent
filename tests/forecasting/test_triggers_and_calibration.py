"""Tests for executable update_triggers and the observed-frequency calibration
curve (Expected/Max Calibration Error)."""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting.cli import register_cli
from forecasting.models import (
    ValidationError,
    evaluate_update_triggers,
    normalize_update_triggers,
)
from tools.forecasting_tool import forecast_ledger_tool


# ── helpers ─────────────────────────────────────────────────────────────────


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "f.db"))
    ledger.initialize_schema()
    return ledger


def _trigger_question(ledger):
    return ledger.create_question(
        title="Will CPI YoY exceed 3% at the July 2026 release?",
        resolution_criteria="Resolves yes if BLS CPI-U YoY for the July 2026 release exceeds 3.0%; otherwise no.",
        update_triggers=[
            {
                "mechanism": "CPI breaches 3%",
                "source_ref": "fred:CPIAUCSL",
                "operator": ">=",
                "threshold": 3.0,
            }
        ],
    )


def _binary_score(ledger, probability, outcome, *, title):
    q = ledger.create_question(
        title=title,
        resolution_criteria="Resolves yes if the official index closes above target; otherwise no.",
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=probability,
        rationale="committed forecast",
        require_panel=False,
    )
    ledger.resolve_question(question_id=q.id, outcome=outcome)  # auto-scores
    return q.id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


# ── normalize_update_triggers ───────────────────────────────────────────────


def test_normalize_executable_trigger_coerces_threshold_to_float():
    out = normalize_update_triggers(
        [{"mechanism": "m", "source_ref": "fred:X", "operator": ">=", "threshold": "3"}]
    )
    assert out[0]["operator"] == ">="
    assert out[0]["threshold"] == 3.0
    assert isinstance(out[0]["threshold"], float)


def test_normalize_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        normalize_update_triggers(
            [{"mechanism": "m", "source_ref": "fred:X", "operator": "=~", "threshold": 3}]
        )


def test_normalize_rejects_operator_without_threshold():
    with pytest.raises(ValidationError):
        normalize_update_triggers([{"mechanism": "m", "source_ref": "fred:X", "operator": ">"}])


def test_normalize_keeps_free_form_trigger_unexecutable():
    out = normalize_update_triggers([{"mechanism": "watch the Fed", "threshold": "monthly"}])
    assert "operator" not in out[0]
    assert out[0]["threshold"] == "monthly"


# ── evaluate_update_triggers (pure) ─────────────────────────────────────────


def test_evaluate_fires_when_comparison_true():
    triggers = normalize_update_triggers(
        [{"mechanism": "m", "source_ref": "fred:X", "operator": ">=", "threshold": 3.0}]
    )
    fired = evaluate_update_triggers(triggers, {"fred:X": 3.4})
    assert len(fired) == 1
    assert fired[0]["observed"] == 3.4
    assert fired[0]["operator"] == ">="


def test_evaluate_does_not_fire_when_false_or_missing():
    triggers = normalize_update_triggers(
        [{"mechanism": "m", "source_ref": "fred:X", "operator": ">=", "threshold": 3.0}]
    )
    assert evaluate_update_triggers(triggers, {"fred:X": 2.9}) == []
    assert evaluate_update_triggers(triggers, {"other:Y": 9.0}) == []  # no observation for source


def test_evaluate_ignores_free_form_triggers():
    triggers = normalize_update_triggers([{"mechanism": "free", "source_ref": "fred:X"}])
    assert evaluate_update_triggers(triggers, {"fred:X": 9.0}) == []


# ── ledger.check_update_triggers ────────────────────────────────────────────


def test_check_update_triggers_fires_and_is_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    q = _trigger_question(ledger)

    assert ledger.check_update_triggers(question_id=q.id, observations={"fred:CPIAUCSL": 2.8}) == []
    fired = ledger.check_update_triggers(question_id=q.id, observations={"fred:CPIAUCSL": 3.2})
    assert len(fired) == 1
    assert fired[0].reason == "trigger_fired:fred:CPIAUCSL"
    # One open alert per source until acknowledged.
    assert ledger.check_update_triggers(question_id=q.id, observations={"fred:CPIAUCSL": 3.2}) == []


def test_check_update_triggers_derives_value_from_imported_evidence(tmp_path):
    ledger = _ledger(tmp_path)
    q = _trigger_question(ledger)
    ledger.add_evidence(
        question_id=q.id,
        source_or_note="FRED CPI",
        available_at="2026-02-01T00:00:00Z",
        metadata={"adapter": "fred", "source": "CPIAUCSL", "adapter_item": {"value": 3.5}},
    )
    fired = ledger.check_update_triggers(question_id=q.id)
    assert len(fired) == 1
    assert "observed 3.5" in fired[0].recommended_action


def test_self_check_fires_executable_triggers(tmp_path):
    ledger = _ledger(tmp_path)
    q = _trigger_question(ledger)
    ledger.add_evidence(
        question_id=q.id,
        source_or_note="FRED CPI",
        available_at="2026-02-01T00:00:00Z",
        metadata={"adapter": "fred", "source": "CPIAUCSL", "adapter_item": {"value": 3.6}},
    )
    alerts = ledger.self_check(question_id=q.id)
    assert any(alert.reason == "trigger_fired:fred:CPIAUCSL" for alert in alerts)


# ── CLI + tool surfaces ─────────────────────────────────────────────────────


def test_cli_triggers_command_fires(tmp_path, capsys):
    ledger = _ledger(tmp_path)
    q = _trigger_question(ledger)
    parser = _parser()
    args = parser.parse_args(
        [
            "forecast",
            "--db",
            str(tmp_path / "f.db"),
            "triggers",
            q.id,
            "--observation",
            "fred:CPIAUCSL=3.4",
        ]
    )
    args.func(args)
    out = capsys.readouterr().out
    assert "fired 1 trigger(s)" in out
    assert "trigger_fired:fred:CPIAUCSL" in out


def test_tool_check_update_triggers(tmp_path):
    db = str(tmp_path / "f.db")
    ledger = _ledger(tmp_path)
    q = _trigger_question(ledger)
    out = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "check_update_triggers",
                "question_id": q.id,
                "observations": {"fred:CPIAUCSL": 3.9},
            }
        )
    )
    assert out["success"] is True
    assert len(out["alerts"]) == 1
    assert out["alerts"][0]["reason"] == "trigger_fired:fred:CPIAUCSL"


# ── observed-frequency calibration curve ────────────────────────────────────


def test_calibration_curve_reports_observed_frequency_and_ece(tmp_path):
    ledger = _ledger(tmp_path)
    # Two forecasts at 0.8 (one yes, one no), two at 0.2 (both no).
    _binary_score(ledger, 0.8, "yes", title="A?")
    _binary_score(ledger, 0.8, "no", title="B?")
    _binary_score(ledger, 0.2, "no", title="C?")
    _binary_score(ledger, 0.2, "no", title="D?")

    summary = ledger.calibration_summary(calibration_eligible=None)
    assert summary["calibration_curve_sample_count"] == 4
    # ECE = (2*|0.5-0.8| + 2*|0.0-0.2|) / 4 = (0.6 + 0.4) / 4 = 0.25
    assert summary["expected_calibration_error"] == pytest.approx(0.25)
    assert summary["max_calibration_error"] == pytest.approx(0.3)
    assert summary["mean_predicted"] == pytest.approx(0.5)
    assert summary["observed_frequency"] == pytest.approx(0.25)

    by_bucket = {row["bucket"]: row for row in summary["calibration_curve"]}
    assert by_bucket["0.8-0.9"]["count"] == 2
    assert by_bucket["0.8-0.9"]["mean_predicted"] == pytest.approx(0.8)
    assert by_bucket["0.8-0.9"]["observed_frequency"] == pytest.approx(0.5)
    assert by_bucket["0.2-0.3"]["observed_frequency"] == pytest.approx(0.0)


def test_calibration_curve_empty_when_no_binary_scores(tmp_path):
    ledger = _ledger(tmp_path)
    summary = ledger.calibration_summary(calibration_eligible=None)
    assert summary["expected_calibration_error"] is None
    assert summary["max_calibration_error"] is None
    assert summary["calibration_curve_sample_count"] == 0
    # The curve scaffold still has 10 (empty) deciles for a stable shape.
    assert len(summary["calibration_curve"]) == 10
    assert all(row["count"] == 0 for row in summary["calibration_curve"])
