"""Tests for the per-forecast settings surface: ledger.update_question_config +
resolve_question_config (cadence re-arm, decision card, hook gate overrides, and
per-question minimum-requirement thresholds with the looser-than-standard flag)."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.models import ValidationError


def _make_ledger(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "config.db"))
    ledger.initialize_schema()
    return ledger


def _make_question(ledger, **overrides):
    defaults: dict = dict(
        title="Will CPI YoY exceed 3.0% in July 2026?",
        resolution_criteria="BLS CPI-U YoY for the July 2026 release exceeds 3.0%.",
    )
    defaults.update(overrides)
    return ledger.create_question(**defaults)


def test_resolve_question_config_defaults(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    cfg = ledger.resolve_question_config(q.id)

    assert cfg["question_id"] == q.id
    assert cfg["profile"] == "standard"
    # every built-in gate is listed with a profile-sourced severity
    assert cfg["gates"], "expected the gate list to be populated"
    assert all(g["source"] == "profile" for g in cfg["gates"])
    # the threshold registry is surfaced at its defaults, none flagged looser
    keys = {t["key"] for t in cfg["thresholds"]}
    assert {"min_perspectives", "max_width_ratio", "min_sharpness", "null_excess_tolerance"} <= keys
    assert all(t["source"] == "default" and not t["looser"] for t in cfg["thresholds"])


def test_update_question_config_roundtrip_cadence_decision_hooks(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        review_cadence="weekly",
        next_review_at="2026-07-01T00:00:00Z",
    )

    ledger.update_question_config(
        q.id,
        review_cadence="every 2 weeks",
        decision={"decision_owner": "desk lead", "action_threshold": "act if P > 0.7"},
        hooks={
            "profile": "strict",
            "overrides": {"require_citations": "error", "quorum_participation": "off"},
            "thresholds": {"min_perspectives": 2, "max_width_ratio": 3.0},
        },
    )

    # cadence persisted on the question column + the live schedule re-armed
    refreshed = ledger.get_question(q.id)
    assert refreshed.review_cadence == "every 2 weeks"
    live = ledger.next_review_by_question().get(q.id)
    assert live is not None and live["cadence"] == "every 2 weeks"

    cfg = ledger.resolve_question_config(q.id)
    assert cfg["profile"] == "strict"
    assert cfg["cadence"] == "every 2 weeks"
    assert cfg["next_run_at"] == live["next_run_at"]
    assert cfg["decision"]["decision_owner"] == "desk lead"
    assert cfg["decision"]["action_threshold"] == "act if P > 0.7"

    gates = {g["id"]: g for g in cfg["gates"]}
    assert gates["require_citations"]["severity"] == "error"
    assert gates["require_citations"]["source"] == "override"
    # quorum_participation OFF is LOOSER than the standard WARN → flagged, never silent
    assert gates["quorum_participation"]["severity"] == "off"
    assert gates["quorum_participation"]["looser"] is True

    thr = {t["key"]: t for t in cfg["thresholds"]}
    assert thr["min_perspectives"]["value"] == 2
    assert thr["min_perspectives"]["looser"] is True  # below the default of 3
    assert thr["max_width_ratio"]["value"] == 3.0
    assert thr["max_width_ratio"]["looser"] is True  # above the default of 1.0


def test_update_question_config_clear_cadence_disables_schedule(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger, review_cadence="daily", next_review_at="2026-07-01T00:00:00Z")
    assert ledger.next_review_by_question().get(q.id) is not None

    ledger.update_question_config(q.id, review_cadence="")
    assert ledger.get_question(q.id).review_cadence is None
    # the enabled per-question schedule is disabled → no longer in the live map
    assert ledger.next_review_by_question().get(q.id) is None


def test_update_question_config_rejects_bad_inputs(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)

    with pytest.raises(ValidationError):
        ledger.update_question_config(q.id, review_cadence="whenever the mood strikes")

    with pytest.raises(ValidationError):
        ledger.update_question_config(q.id, hooks={"profile": "nonexistent"})

    with pytest.raises(ValidationError):
        ledger.update_question_config(q.id, hooks={"overrides": {"not_a_real_gate": "error"}})

    with pytest.raises(ValidationError):
        ledger.update_question_config(q.id, hooks={"overrides": {"require_citations": "maybe"}})

    # lesson:* rules are non-demotable at the config layer (the engine guardrail)
    with pytest.raises(ValidationError):
        ledger.update_question_config(q.id, hooks={"overrides": {"lesson:ny12": "off"}})


def test_threshold_values_are_clamped_to_registry_range(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    # min_perspectives max is 12, max_width_ratio max is 10 — values past the
    # bound are clamped, not rejected (the modal slider can overshoot).
    ledger.update_question_config(
        q.id, hooks={"thresholds": {"min_perspectives": 99, "max_width_ratio": 999}}
    )
    thr = {t["key"]: t for t in ledger.resolve_question_config(q.id)["thresholds"]}
    assert thr["min_perspectives"]["value"] == 12
    assert thr["max_width_ratio"]["value"] == 10.0
