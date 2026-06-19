"""Tests for the question decision card and structured reasoning fields."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.models import (
    FAILURE_CLASSES,
    OutcomeSpace,
    ValidationError,
    normalize_update_triggers,
    question_decision_readiness_issues,
)
from forecasting.protocol import build_context_packet


def _make_ledger(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "decision.db"))
    ledger.initialize_schema()
    return ledger


def _make_question(ledger, **overrides):
    defaults: dict = dict(
        title="Will CPI YoY exceed 3.0% in July 2026?",
        resolution_criteria="BLS CPI-U YoY for July 2026 release exceeds 3.0%.",
    )
    defaults.update(overrides)
    return ledger.create_question(**defaults)


# ---------- normalize_update_triggers ----------


def test_normalize_update_triggers_accepts_strings_and_objects():
    triggers = normalize_update_triggers(
        [
            "PCE release in 24h",
            {"mechanism": "fred:CPIAUCSL", "threshold": "MoM > 0.3%", "action": "review"},
        ]
    )
    assert triggers == [
        {"mechanism": "PCE release in 24h"},
        {"mechanism": "fred:CPIAUCSL", "threshold": "MoM > 0.3%", "action": "review"},
    ]


def test_normalize_update_triggers_strips_blank_optional_fields():
    triggers = normalize_update_triggers([{"mechanism": "x", "threshold": "  ", "notes": ""}])
    assert triggers == [{"mechanism": "x"}]


def test_normalize_update_triggers_requires_mechanism():
    with pytest.raises(ValidationError):
        normalize_update_triggers([{"threshold": "MoM > 0.3%"}])


def test_normalize_update_triggers_accepts_none_and_single_dict():
    assert normalize_update_triggers(None) == []
    assert normalize_update_triggers({"mechanism": "x"}) == [{"mechanism": "x"}]


def test_normalize_update_triggers_rejects_non_list():
    with pytest.raises(ValidationError):
        normalize_update_triggers("not a list or dict")


# ---------- create_question persistence ----------


def test_create_question_persists_decision_card(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        decision_owner="Trading desk lead",
        decision_deadline="2026-08-15T00:00:00Z",
        action_threshold="If P(YES) > 0.6, reduce duration exposure by 10%.",
        update_triggers=[
            "PCE release within 24h",
            {"mechanism": "fred:CPIAUCSL", "threshold": "MoM > 0.3%"},
        ],
    )
    assert q.decision_owner == "Trading desk lead"
    assert q.decision_deadline == "2026-08-15T00:00:00Z"
    assert q.action_threshold == "If P(YES) > 0.6, reduce duration exposure by 10%."
    assert q.update_triggers == [
        {"mechanism": "PCE release within 24h"},
        {"mechanism": "fred:CPIAUCSL", "threshold": "MoM > 0.3%"},
    ]
    # Round-trip through the database
    q2 = ledger.get_question(q.id)
    assert q2.decision_owner == q.decision_owner
    assert q2.update_triggers == q.update_triggers


def test_create_question_strips_empty_decision_strings(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger, decision_owner="   ", action_threshold="")
    assert q.decision_owner is None
    assert q.action_threshold is None


def test_create_question_defaults_to_empty_update_triggers(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    assert q.update_triggers == []


def test_create_question_invalid_decision_deadline(tmp_path):
    ledger = _make_ledger(tmp_path)
    with pytest.raises(ValidationError):
        _make_question(ledger, decision_deadline="not-a-timestamp")


# ---------- decision_readiness_issues ----------


def test_decision_readiness_issues_lists_missing_fields(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    issues = ledger.decision_readiness_issues(q)
    assert set(issues) == {"missing decision_owner", "missing action_threshold", "missing update_triggers"}


def test_decision_readiness_issues_clear_when_complete(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        decision_owner="Owner",
        action_threshold="P > 0.5 -> act",
        update_triggers=["trigger A"],
    )
    assert ledger.decision_readiness_issues(q) == []


def test_decision_readiness_issues_accepts_id_or_object(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    assert ledger.decision_readiness_issues(q) == ledger.decision_readiness_issues(q.id)


def test_question_decision_readiness_issues_pure_function(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    assert question_decision_readiness_issues(q) == ledger.decision_readiness_issues(q)


# ---------- update_question_decision ----------


def test_update_question_decision_patches_fields_in_place(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    patched = ledger.update_question_decision(
        q.id,
        decision_owner="Ops lead",
        action_threshold="P > 0.6 -> alert",
        update_triggers=["PCE release in 24h"],
    )
    assert patched.decision_owner == "Ops lead"
    assert patched.action_threshold == "P > 0.6 -> alert"
    assert patched.update_triggers == [{"mechanism": "PCE release in 24h"}]


def test_update_question_decision_leaves_unspecified_fields_untouched(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger, decision_owner="Owner", action_threshold="threshold")
    patched = ledger.update_question_decision(q.id, decision_deadline="2026-09-01T00:00:00Z")
    assert patched.decision_owner == "Owner"
    assert patched.action_threshold == "threshold"
    assert patched.decision_deadline == "2026-09-01T00:00:00Z"


def test_update_question_decision_can_clear_triggers(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger, update_triggers=["t1", "t2"])
    patched = ledger.update_question_decision(q.id, update_triggers=[])
    assert patched.update_triggers == []


# ---------- snapshot reasons fields ----------


def test_create_snapshot_persists_reasons(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.42,
        rationale="Prior + base rate",
        reasons_up=["sticky services", "rents reaccelerating"],
        reasons_down=["energy disinflation"],
        change_my_mind=["core CPI > 0.4% MoM for three months"],
    )
    assert snap.reasons_up == ["sticky services", "rents reaccelerating"]
    assert snap.reasons_down == ["energy disinflation"]
    assert snap.change_my_mind == ["core CPI > 0.4% MoM for three months"]
    snap2 = ledger.get_snapshot(snap.forecast_id)
    assert snap2.reasons_up == snap.reasons_up


def test_create_snapshot_treats_string_reasons_as_lines(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        reasons_up="alpha\nbeta\n",
    )
    assert snap.reasons_up == ["alpha", "beta"]


def test_create_snapshot_drops_blank_reason_entries(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        reasons_up=["   ", "useful"],
    )
    assert snap.reasons_up == ["useful"]


def test_create_snapshot_rejects_non_string_reason_entries(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    with pytest.raises(ValidationError):
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="r",
            reasons_up=[123],
        )


# ---------- require_structured_reasoning gate ----------


def test_require_structured_reasoning_blocks_missing_fields(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    with pytest.raises(ValidationError) as exc:
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="r",
            require_structured_reasoning=True,
        )
    msg = str(exc.value)
    assert "reasons_up" in msg
    assert "reasons_down" in msg
    assert "change_my_mind" in msg


def test_require_structured_reasoning_allows_complete_snapshot(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        reasons_up=["a"],
        reasons_down=["b"],
        change_my_mind=["c"],
        require_structured_reasoning=True,
    )
    assert snap.reasons_up == ["a"]


def test_require_structured_reasoning_does_not_block_backtests(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        require_structured_reasoning=True,
        forecast_origin="backtest",
    )
    assert snap.forecast_origin == "backtest"


# ---------- require_decision_readiness gate ----------


def test_require_decision_readiness_blocks_missing_card(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    with pytest.raises(ValidationError) as exc:
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="r",
            require_decision_readiness=True,
        )
    msg = str(exc.value)
    assert "decision_owner" in msg
    assert "action_threshold" in msg


def test_require_decision_readiness_passes_when_card_complete(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        decision_owner="Owner",
        action_threshold="P > 0.5 -> act",
        update_triggers=["t"],
    )
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        require_decision_readiness=True,
    )
    assert snap.probability_or_distribution == 0.5


def test_require_decision_readiness_does_not_block_backtests(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="r",
        require_decision_readiness=True,
        forecast_origin="backtest",
    )
    assert snap.forecast_origin == "backtest"


# ---------- protocol context packet shows decision card ----------


def test_context_packet_shows_decision_card_and_readiness(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        decision_owner="Ops lead",
        action_threshold="P > 0.05 -> evacuate",
        update_triggers=[{"mechanism": "official warning", "threshold": "level 3+"}],
    )
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.02,
        rationale="base rate",
        reasons_up=["escalation last week"],
        reasons_down=["no new troop movements"],
        change_my_mind=["nuclear use elsewhere"],
    )
    packet = build_context_packet(ledger, q, snap)
    assert "Decision Card" in packet
    assert "Ops lead" in packet
    assert "P > 0.05 -> evacuate" in packet
    assert "official warning [level 3+]" in packet
    assert "decision_readiness_issues: none" in packet
    assert "reasons_up: escalation last week" in packet
    assert "reasons_down: no new troop movements" in packet
    assert "change_my_mind: nuclear use elsewhere" in packet


def test_context_packet_flags_missing_decision_card(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    packet = build_context_packet(ledger, q, None)
    assert "decision_readiness_issues: missing decision_owner" in packet


def test_context_packet_rerun_banner_when_snapshot_exists(tmp_path):
    # A committed snapshot => re-run: the packet must mandate refreshing evidence
    # before re-estimating, and push toward concentration as the horizon shortens.
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    snap = ledger.create_snapshot(question_id=q.id, probability_or_distribution=0.4, rationale="prior")

    rerun = build_context_packet(ledger, q, snap)
    assert "Re-run — refresh evidence before you re-estimate" in rerun
    assert "forecast refresh" in rerun
    assert "CONCENTRATE" in rerun

    # A fresh forecast (no snapshot) must NOT show the re-run banner.
    fresh = build_context_packet(ledger, q, None)
    assert "Re-run — refresh evidence" not in fresh


# ---------- postmortem failure_class ----------


def _resolve_and_score(ledger, question, outcome):
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="r",
    )
    ledger.resolve_question(question_id=question.id, outcome=outcome)
    ledger.score_question(question.id)


def test_postmortem_persists_failure_class(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    _resolve_and_score(ledger, q, "yes")
    pm = ledger.create_postmortem(
        question_id=q.id,
        summary="missed inflection",
        lesson="add monthly CPI trend check",
        failure_class="base_rate",
    )
    assert pm["failure_class"] == "base_rate"
    fetched = ledger.get_postmortem(pm["id"])
    assert fetched["failure_class"] == "base_rate"
    listed = ledger.list_postmortems(question_id=q.id)
    assert listed[0]["failure_class"] == "base_rate"


def test_postmortem_rejects_unknown_failure_class(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    _resolve_and_score(ledger, q, "yes")
    with pytest.raises(ValidationError):
        ledger.create_postmortem(
            question_id=q.id,
            summary="x",
            failure_class="not-a-real-class",
        )


def test_postmortem_failure_class_optional(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(ledger)
    _resolve_and_score(ledger, q, "yes")
    pm = ledger.create_postmortem(question_id=q.id, summary="x")
    assert pm["failure_class"] is None


def test_failure_classes_export_is_stable():
    expected = {
        "base_rate",
        "inside_view",
        "definition",
        "timing",
        "aggregation",
        "motivated_reasoning",
        "tail",
        "noise",
        "other",
    }
    assert FAILURE_CLASSES == expected


# ---------- import/export round trip preserves new fields ----------


def test_export_round_trip_preserves_decision_card_and_reasons(tmp_path):
    ledger = _make_ledger(tmp_path)
    q = _make_question(
        ledger,
        decision_owner="Owner",
        action_threshold="P > 0.5 -> act",
        update_triggers=[{"mechanism": "fred:X", "threshold": "above 100"}],
    )
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.4,
        rationale="r",
        reasons_up=["a"],
        reasons_down=["b"],
        change_my_mind=["c"],
    )
    import json
    packet = json.loads(ledger.export_all(fmt="json"))
    other = ForecastLedger(db_path=str(tmp_path / "round-trip.db"))
    other.initialize_schema()
    other.import_packet(packet, conflict="error")
    q2 = other.get_question(q.id)
    assert q2.decision_owner == "Owner"
    assert q2.action_threshold == "P > 0.5 -> act"
    assert q2.update_triggers == [{"mechanism": "fred:X", "threshold": "above 100"}]
    s2 = other.get_snapshot(snap.forecast_id)
    assert s2.reasons_up == ["a"]
    assert s2.reasons_down == ["b"]
    assert s2.change_my_mind == ["c"]
