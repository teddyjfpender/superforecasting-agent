"""Evidence crux map: track the decisive variables a forecast hinges on + whether
the desk actually watches a source that could satisfy each, so 'lots of evidence
but the crux is missing' is surfaced instead of buried (feedback item #3)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError

CRIT = "Resolves yes if the reported segment revenue beats consensus next quarter."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "crux.db"))
    lg.initialize_schema()
    return lg


def test_crux_add_list_and_idempotency(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the segment beat consensus?", resolution_criteria=CRIT)
    lg.add_crux(question_id=q.id, crux_variable="segment consensus within 7d", preferred_roles=["consensus"], materiality="high")
    lg.add_crux(question_id=q.id, crux_variable="hyperscaler capex trend", preferred_roles=["leading_indicator"], materiality="medium", status="current")
    assert len(lg.list_cruxes(q.id)) == 2
    # Re-adding the same crux variable updates it rather than duplicating.
    updated = lg.add_crux(question_id=q.id, crux_variable="segment consensus within 7d", materiality="high", status="stale")
    assert len(lg.list_cruxes(q.id)) == 2
    assert updated["status"] == "stale"


def test_invalid_materiality_role_and_status_rejected(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will it beat?", resolution_criteria=CRIT)
    with pytest.raises(ValidationError):
        lg.add_crux(question_id=q.id, crux_variable="x", materiality="enormous")
    with pytest.raises(ValidationError):
        lg.add_crux(question_id=q.id, crux_variable="x", preferred_roles=["bogus"])
    with pytest.raises(ValidationError):
        lg.add_crux(question_id=q.id, crux_variable="x", status="vibes")


def test_evidence_map_flags_high_materiality_gaps_and_source_match(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the segment beat consensus?", resolution_criteria=CRIT)
    crux = lg.add_crux(
        question_id=q.id, crux_variable="segment consensus within 7d",
        preferred_roles=["consensus", "resolver"], materiality="high", status="missing",
    )
    em = lg.evidence_map(q.id)
    assert em["gap_count"] == 1  # high-materiality + missing
    top = em["cruxes"][0]
    assert top["materiality"] == "high"
    assert top["has_matching_source"] is False  # no consensus/resolver source watched yet

    # Watch a consensus-role source + capture the crux -> the gap closes.
    lg.add_watched_source(scope_type="question", scope_ref=q.id, source="https://x/consensus", source_type="rss", role="consensus")
    lg.set_crux_status(crux["id"], "current")
    em2 = lg.evidence_map(q.id)
    assert em2["gap_count"] == 0
    assert em2["cruxes"][0]["has_matching_source"] is True
