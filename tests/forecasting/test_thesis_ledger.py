"""Integration tests for the thesis layer: ledger membership + aggregation +
dashboard surfacing. The pure aggregation math is covered separately in
test_thesis_aggregate.py."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.dashboard import (
    build_dashboard_summary,
    build_thesis_summary,
    build_workspace_payload,
)
from forecasting.models import OutcomeSpace

CRITERIA = "Resolves to the official value reported by the named source on the close date."
THESIS_CRITERIA = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _seed(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    capex = ledger.create_question(title="Hyperscaler AI capex > $400B in 2026?", resolution_criteria=CRITERIA, domain="macro", topics=["ai"])
    ledger.create_snapshot(question_id=capex.id, probability_or_distribution=0.62, rationale="guidance trend")
    dist = ledger.create_question(
        title="Aggregate 2026 AI capex (USD billions)?",
        resolution_criteria=CRITERIA,
        domain="macro",
        outcome_space=OutcomeSpace(type="distribution", units="usd_billions"),
    )
    ledger.create_snapshot(
        question_id=dist.id,
        probability_or_distribution={"mean": 390, "q05": 285, "q50": 380, "q95": 560, "sd": 85},
        rationale="consensus + upside",
    )
    overbuild = ledger.create_question(title="AI infra overbuild signs by 2027-06-30?", resolution_criteria=CRITERIA, domain="macro")
    ledger.create_snapshot(question_id=overbuild.id, probability_or_distribution=0.30, rationale="early, low")
    thesis = ledger.create_question(
        title="AI infrastructure scarcity thesis",
        resolution_criteria=THESIS_CRITERIA,
        domain="macro",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    return ledger, capex, dist, overbuild, thesis


def test_thesis_is_first_class_question(tmp_path):
    ledger, *_, thesis = _seed(tmp_path)
    assert thesis.outcome_space.type == "thesis"
    assert ledger.is_thesis(thesis) is True
    assert ledger.is_thesis(thesis.id) is True


def test_add_member_idempotent_and_signed(tmp_path):
    ledger, capex, _dist, _ob, thesis = _seed(tmp_path)
    ledger.add_thesis_member(thesis.id, capex.id, direction="support", weight=3.0, role="capex")
    # re-tag updates rather than duplicating
    ledger.add_thesis_member(thesis.id, capex.id, direction="inverted", weight=1.0)
    members = ledger.list_thesis_members(thesis.id)
    assert len(members) == 1
    assert members[0]["direction"] == "inverted"
    assert members[0]["weight"] == 1.0
    assert ledger.list_theses_for_member(capex.id)[0]["thesis_id"] == thesis.id


def test_member_must_not_be_thesis_itself(tmp_path):
    ledger, *_, thesis = _seed(tmp_path)
    with pytest.raises(Exception):
        ledger.add_thesis_member(thesis.id, thesis.id)


def test_aggregate_writes_snapshot_note_and_components(tmp_path):
    ledger, capex, dist, overbuild, thesis = _seed(tmp_path)
    ledger.add_thesis_member(thesis.id, capex.id, direction="support", weight=3.0)
    ledger.add_thesis_member(thesis.id, dist.id, direction="support", weight=2.0, target=400.0)
    ledger.add_thesis_member(thesis.id, overbuild.id, direction="inverted", weight=1.5)

    result = ledger.aggregate_thesis(thesis.id)
    assert result["snapshot_id"]
    payload = result["payload"]
    assert 0.0 <= payload["health"] <= 1.0
    assert 0.0 <= payload["thesis_score"] <= 100.0

    snap = ledger.get_current_snapshot(thesis.id)
    assert snap.probability_or_distribution["health"] == payload["health"]
    assert snap.method == "thesis_aggregate"
    assert snap.calibration_eligible is False
    assert len(snap.ensemble_components["components"]) == 3

    note = ledger.latest_analyst_note(thesis.id, kind="brief")
    assert note is not None and "health" in note["headline"].lower()


def test_inverted_member_drags_health_down(tmp_path):
    ledger, capex, _dist, overbuild, thesis = _seed(tmp_path)
    # capex alone (support, p=0.62)
    ledger.add_thesis_member(thesis.id, capex.id, direction="support", weight=1.0)
    health_support_only = ledger.aggregate_thesis(thesis.id, commit=False)["payload"]["health"]
    # add a HIGH overbuild risk inverted (p=0.30 -> only mild drag); now make it high
    ledger.create_snapshot(question_id=overbuild.id, probability_or_distribution=0.85, rationale="rising")
    ledger.add_thesis_member(thesis.id, overbuild.id, direction="inverted", weight=2.0)
    health_with_risk = ledger.aggregate_thesis(thesis.id, commit=False)["payload"]["health"]
    # a heavy, likely overbuild risk (inverted) must pull health below capex-only
    assert health_with_risk < health_support_only


def test_all_missing_members_withholds_no_fabrication(tmp_path):
    ledger, *_rest, thesis = _seed(tmp_path)
    # a member with NO snapshot
    empty = ledger.create_question(title="Member with no forecast yet?", resolution_criteria=CRITERIA, domain="macro")
    ledger.add_thesis_member(thesis.id, empty.id, direction="support", weight=1.0)
    result = ledger.aggregate_thesis(thesis.id)
    assert result["payload"].get("health") is None  # nothing to aggregate
    assert result["snapshot_id"] is None  # NO fabricated snapshot
    assert ledger.get_current_snapshot(thesis.id) is None


def test_workspace_payload_partitions_theses(tmp_path):
    ledger, capex, dist, overbuild, thesis = _seed(tmp_path)
    ledger.add_thesis_member(thesis.id, capex.id, direction="support", weight=3.0)
    ledger.add_thesis_member(thesis.id, dist.id, direction="support", weight=2.0, target=400.0)
    ledger.aggregate_thesis(thesis.id)

    payload = build_workspace_payload(ledger=ledger)
    # thesis is NOT in the forecast book
    assert all(f["outcome_type"] != "thesis" for f in payload["forecasts"])
    assert payload["thesis_count"] == 1
    th = payload["theses"][0]
    assert th["id"] == thesis.id
    assert th["health_display"].endswith("%")
    assert len(th["components"]) == 2
    # members carry the thesis badge
    capex_item = next(f for f in payload["forecasts"] if f["id"] == capex.id)
    assert capex_item["thesis_ids"][0]["thesis_id"] == thesis.id


def test_dashboard_summary_excludes_thesis_from_questions(tmp_path):
    ledger, capex, _dist, _ob, thesis = _seed(tmp_path)
    ledger.add_thesis_member(thesis.id, capex.id, direction="support", weight=1.0)
    ledger.aggregate_thesis(thesis.id)
    summary = build_dashboard_summary(ledger=ledger)
    assert all(q["id"] != thesis.id for q in summary["questions"])
    assert len(summary["theses"]) == 1
    assert summary["theses"][0]["member_count"] == 1
    # standalone helper agrees
    assert build_thesis_summary(ledger=ledger)[0]["id"] == thesis.id
