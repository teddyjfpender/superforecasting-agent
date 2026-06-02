"""Export/import round-trip for thesis memberships + entities (+ factor constituents)."""

from __future__ import annotations

import json

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace

CRITERIA = "Resolves to the official value reported by the named source on the close date."
THESIS_CRITERIA = "Aggregate health of the tagged member forecasts; reviewed as members update."


def test_membership_and_entities_round_trip(tmp_path):
    src = ForecastLedger(tmp_path / "src.db")
    power = src.create_question(title="Power binding constraint?", resolution_criteria=CRITERIA, domain="macro")
    src.create_snapshot(question_id=power.id, probability_or_distribution=0.6, rationale="x")
    thesis = src.create_question(title="AI infra scarcity thesis", resolution_criteria=THESIS_CRITERIA, domain="macro", outcome_space=OutcomeSpace(type="thesis"))
    src.add_thesis_member(thesis.id, power.id, direction="support", weight=2.0, role="power", hi_is_good=True)
    src.add_thesis_entity(thesis.id, "BE", kind="equity", weights=[{"member_id": power.id, "weight": 0.6, "direction": "support"}])

    pkt_power = json.loads(src.export_question(power.id, fmt="json"))
    pkt_thesis = json.loads(src.export_question(thesis.id, fmt="json"))
    assert len(pkt_thesis["thesis_members"]) == 1
    assert len(pkt_thesis["thesis_entities"]) == 1

    dst = ForecastLedger(tmp_path / "dst.db")
    dst.import_packet(pkt_power, conflict="skip")
    summary = dst.import_packet(pkt_thesis, conflict="skip")
    assert summary["imported"]["thesis_members"] == 1
    assert summary["imported"]["thesis_entities"] == 1

    members = dst.list_thesis_members(thesis.id)
    assert members[0]["member_question_id"] == power.id
    assert members[0]["weight"] == 2.0
    assert members[0]["hi_is_good"] is True
    assert members[0]["role"] == "power"
    entities = dst.list_thesis_entities(thesis.id)
    assert entities[0]["name"] == "BE"
    assert entities[0]["weights"][0]["member_id"] == power.id
    # and it still aggregates after restore
    assert dst.aggregate_thesis(thesis.id)["payload"]["health"] is not None


def test_dangling_membership_is_skipped_not_aborted(tmp_path):
    """A thesis packet imported WITHOUT its member questions skips the edges."""
    src = ForecastLedger(tmp_path / "src.db")
    power = src.create_question(title="Power binding constraint?", resolution_criteria=CRITERIA, domain="macro")
    src.create_snapshot(question_id=power.id, probability_or_distribution=0.6, rationale="x")
    thesis = src.create_question(title="Thesis?", resolution_criteria=THESIS_CRITERIA, domain="macro", outcome_space=OutcomeSpace(type="thesis"))
    src.add_thesis_member(thesis.id, power.id, direction="support", weight=1.0)

    pkt_thesis = json.loads(src.export_question(thesis.id, fmt="json"))
    dst = ForecastLedger(tmp_path / "dst.db")
    # import ONLY the thesis (member question absent) -> membership skipped, no crash
    summary = dst.import_packet(pkt_thesis, conflict="skip")
    assert summary["imported"].get("thesis_members", 0) == 0
    assert dst.list_thesis_members(thesis.id) == []
