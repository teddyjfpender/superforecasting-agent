"""Entity-suitability layer: per-name suitability + §10 trade triggers, the
generic translation of thesis signals into entity recommendations."""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.dashboard import build_workspace_payload
from forecasting.models import OutcomeSpace

CRITERIA = "Resolves to the official value reported by the named source on the close date."
THESIS_CRITERIA = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _thesis_with_signals(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    power = ledger.create_question(title="Power is the binding AI constraint by 2026-12-31?", resolution_criteria=CRITERIA, domain="macro")
    ledger.create_snapshot(question_id=power.id, probability_or_distribution=0.55, rationale="x")
    compute = ledger.create_question(title="AI compute shortage persists through 2026?", resolution_criteria=CRITERIA, domain="macro")
    ledger.create_snapshot(question_id=compute.id, probability_or_distribution=0.62, rationale="x")
    overbuild = ledger.create_question(title="AI overbuild signs by 2027-06-30?", resolution_criteria=CRITERIA, domain="macro")
    ledger.create_snapshot(question_id=overbuild.id, probability_or_distribution=0.30, rationale="x")
    thesis = ledger.create_question(title="AI infrastructure scarcity thesis", resolution_criteria=THESIS_CRITERIA, domain="macro", outcome_space=OutcomeSpace(type="thesis"))
    for member, weight, direction in [(power, 2.0, "support"), (compute, 2.0, "support"), (overbuild, 1.5, "inverted")]:
        ledger.add_thesis_member(thesis.id, member.id, direction=direction, weight=weight)
    return ledger, thesis, power, compute, overbuild


def test_entity_crud_and_weight(tmp_path):
    ledger, thesis, power, _compute, overbuild = _thesis_with_signals(tmp_path)
    ledger.add_thesis_entity(thesis.id, "BE", kind="equity", label="Bloom Energy")
    ledger.set_entity_weight(thesis.id, "BE", power.id, weight=0.6, direction="support")
    ledger.set_entity_weight(thesis.id, "BE", overbuild.id, weight=0.3, direction="inverted")
    entities = ledger.list_thesis_entities(thesis.id)
    assert len(entities) == 1
    be = entities[0]
    assert be["name"] == "BE" and be["kind"] == "equity"
    assert len(be["weights"]) == 2
    # idempotent re-weight replaces, not duplicates
    ledger.set_entity_weight(thesis.id, "BE", power.id, weight=0.7, direction="support")
    be = ledger.list_thesis_entities(thesis.id)[0]
    assert len(be["weights"]) == 2
    assert ledger.remove_thesis_entity(thesis.id, "BE") == 1
    assert ledger.list_thesis_entities(thesis.id) == []


def test_aggregate_produces_entity_suitability(tmp_path):
    ledger, thesis, power, compute, overbuild = _thesis_with_signals(tmp_path)
    ledger.add_thesis_entity(thesis.id, "BE", kind="equity", weights=[
        {"member_id": power.id, "weight": 0.6, "direction": "support"},
        {"member_id": overbuild.id, "weight": 0.3, "direction": "inverted"},
    ])
    ledger.add_thesis_entity(thesis.id, "NBIS", kind="equity", weights=[
        {"member_id": compute.id, "weight": 0.7, "direction": "support"},
        {"member_id": power.id, "weight": 0.3, "direction": "support"},
    ])
    result = ledger.aggregate_thesis(thesis.id)
    entities = {e["name"]: e for e in result["entities"]}
    assert set(entities) == {"BE", "NBIS"}
    assert 0.0 <= entities["BE"]["suitability"] <= 1.0
    assert entities["BE"]["stance"] in {"OVERWEIGHT", "ADD", "NEUTRAL", "TRIM", "UNDERWEIGHT"}
    assert entities["BE"]["top_driver"]  # the dominant signal
    # first run -> no triggers (no prior snapshot to diff)
    assert result["triggers"] == []


def test_inverted_weight_lowers_suitability(tmp_path):
    ledger, thesis, power, _compute, overbuild = _thesis_with_signals(tmp_path)
    # make overbuild risk HIGH
    ledger.create_snapshot(question_id=overbuild.id, probability_or_distribution=0.85, rationale="rising")
    ledger.add_thesis_entity(thesis.id, "PURE", weights=[{"member_id": power.id, "weight": 1.0, "direction": "support"}])
    ledger.add_thesis_entity(thesis.id, "RISKY", weights=[
        {"member_id": power.id, "weight": 1.0, "direction": "support"},
        {"member_id": overbuild.id, "weight": 1.0, "direction": "inverted"},
    ])
    entities = {e["name"]: e for e in ledger.aggregate_thesis(thesis.id, commit=False)["entities"]}
    # the entity carrying the high inverted overbuild risk is less suited
    assert entities["RISKY"]["suitability"] < entities["PURE"]["suitability"]


def test_signal_move_fires_trade_trigger(tmp_path):
    ledger, thesis, power, compute, _overbuild = _thesis_with_signals(tmp_path)
    ledger.add_thesis_entity(thesis.id, "BE", weights=[{"member_id": power.id, "weight": 0.8, "direction": "support"}])
    ledger.add_thesis_entity(thesis.id, "IREN", weights=[{"member_id": power.id, "weight": 0.6, "direction": "support"}])
    ledger.aggregate_thesis(thesis.id)  # baseline
    # Committing a moved member now AUTO-re-aggregates the parent thesis (the
    # member-commit cascade), so the trade trigger fires at this commit — read it
    # off the thesis's freshly-cascaded snapshot, not a manual re-aggregate (which
    # would see no further move and produce nothing).
    ledger.create_snapshot(question_id=power.id, probability_or_distribution=0.85, rationale="power tightening")
    meta = ledger.get_current_snapshot(thesis.id).metadata or {}
    triggers = meta.get("triggers") or []
    assert triggers, "a large signal move should produce a trigger"
    trig = triggers[0]
    assert trig["direction"] == "up"
    assert set(trig["better"]) >= {"BE", "IREN"}
    assert "better suited" in trig["note"]
    # the entities' suitability rose
    entities = {e["name"]: e for e in (meta.get("entities") or [])}
    assert entities["BE"]["delta"] > 0


def test_generic_kinds_work_for_non_stocks(tmp_path):
    """The layer is generic: an election thesis with candidate entities."""
    ledger = ForecastLedger(tmp_path / "f.db")
    swing = ledger.create_question(title="Does the swing-state economy improve by Nov?", resolution_criteria=CRITERIA, domain="politics")
    ledger.create_snapshot(question_id=swing.id, probability_or_distribution=0.6, rationale="x")
    thesis = ledger.create_question(title="Incumbent-party retention thesis", resolution_criteria=THESIS_CRITERIA, domain="politics", outcome_space=OutcomeSpace(type="thesis"))
    ledger.add_thesis_member(thesis.id, swing.id, direction="support", weight=1.0)
    ledger.add_thesis_entity(thesis.id, "Candidate A", kind="candidate", weights=[{"member_id": swing.id, "weight": 1.0, "direction": "support"}])
    ledger.add_thesis_entity(thesis.id, "Candidate B", kind="candidate", weights=[{"member_id": swing.id, "weight": 1.0, "direction": "inverted"}])
    entities = {e["name"]: e for e in ledger.aggregate_thesis(thesis.id, commit=False)["entities"]}
    assert entities["Candidate A"]["kind"] == "candidate"
    # a good economy supports A and opposes B
    assert entities["Candidate A"]["suitability"] > entities["Candidate B"]["suitability"]


def test_entities_surface_in_workspace_payload(tmp_path):
    ledger, thesis, power, compute, _overbuild = _thesis_with_signals(tmp_path)
    ledger.add_thesis_entity(thesis.id, "BE", kind="equity", weights=[{"member_id": power.id, "weight": 1.0, "direction": "support"}])
    ledger.aggregate_thesis(thesis.id)
    payload = build_workspace_payload(ledger=ledger)
    th = payload["theses"][0]
    assert len(th["entities"]) == 1
    assert th["entities"][0]["name"] == "BE"
    assert th["entities"][0]["suitability_display"].endswith("%")
    assert "triggers" in th  # present (empty on first run)
