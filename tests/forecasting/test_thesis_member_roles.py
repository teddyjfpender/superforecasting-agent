"""Thesis member roles are a validated SEMANTIC taxonomy (leading_indicator,
confirming_signal, bottleneck_signal, market_validation, disconfirming_signal) so a
thesis reads as decision intelligence — which signal leads, which is the
bottleneck — not an undifferentiated weighted pool (feedback item #6A)."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, THESIS_MEMBER_ROLES
from forecasting.models import OutcomeSpace, ValidationError

CRIT = "Resolves to the official value reported by the named source on the close date."
THCRIT = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _thesis_with_member(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "tm.db"))
    lg.initialize_schema()
    m = lg.create_question(title="Will power capacity tighten by year end?", resolution_criteria=CRIT, domain="energy")
    lg.create_snapshot(question_id=m.id, probability_or_distribution=0.5, rationale="baseline")
    th = lg.create_question(
        title="AI infra scarcity thesis", resolution_criteria=THCRIT, domain="tech",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    return lg, th, m


def test_semantic_member_role_accepted(tmp_path):
    lg, th, m = _thesis_with_member(tmp_path)
    lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0, role="bottleneck_signal")
    members = lg.list_thesis_members(th.id)
    assert members[0]["role"] == "bottleneck_signal"


def test_role_is_optional(tmp_path):
    lg, th, m = _thesis_with_member(tmp_path)
    lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0)
    assert lg.list_thesis_members(th.id)[0]["role"] is None


def test_unknown_member_role_rejected(tmp_path):
    lg, th, m = _thesis_with_member(tmp_path)
    with pytest.raises(ValidationError, match="role must be one of"):
        lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0, role="capex")


def test_taxonomy_matches_the_feedback_roles():
    assert THESIS_MEMBER_ROLES == {
        "leading_indicator", "confirming_signal", "bottleneck_signal",
        "market_validation", "disconfirming_signal",
    }
