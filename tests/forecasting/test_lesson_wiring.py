"""Lesson WIRING — make scoped lessons reach the right next forecast.

The NY-primary lessons were authored at domain_topic + a vote-share-distribution
question_type, neither of which the retrieval walked — so they were dormant. These
tests pin the retrieval that connects them to matching questions."""

from __future__ import annotations

import pytest

from forecasting.learning import active_lessons_for_question
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError

VS_CRIT = "Resolves to the certified vote percentage the board reports for each candidate on the close date."
NUM_CRIT = "Resolves to the official reported numeric value at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "lw.db"))
    lg.initialize_schema()
    return lg


def _vote_share_q(lg, topics):
    return lg.create_question(
        title="What certified vote percentages will the candidates receive in the primary?",
        resolution_criteria=VS_CRIT, domain="politics", topics=topics,
        outcome_space=OutcomeSpace(type="distribution", choices=["A", "B", "Other"], units="pct"),
    )


def test_domain_topic_lesson_reaches_matching_question(tmp_path):
    lg = _ledger(tmp_path)
    dt = lg.create_calibration_lesson(scope_type="domain_topic", scope_ref="politics:nyc-primaries", lesson="top-two compression", status="active")
    q = _vote_share_q(lg, ["nyc-primaries", "vote share"])
    assert dt["id"] in {l["id"] for l in active_lessons_for_question(lg, q)}


def test_vote_share_distribution_question_type_matches_via_canonical(tmp_path):
    lg = _ledger(tmp_path)
    vs = lg.create_calibration_lesson(scope_type="question_type", scope_ref="vote-share-distribution", lesson="born scoreable", status="active")
    q = _vote_share_q(lg, ["vote share"])
    assert vs["id"] in {l["id"] for l in active_lessons_for_question(lg, q)}


def test_continuous_distribution_does_not_match_vote_share_lessons(tmp_path):
    lg = _ledger(tmp_path)
    dt = lg.create_calibration_lesson(scope_type="domain_topic", scope_ref="politics:nyc-primaries", lesson="x", status="active")
    vs = lg.create_calibration_lesson(scope_type="question_type", scope_ref="vote-share-distribution", lesson="y", status="active")
    q = lg.create_question(title="What will the metric value be at the close date?", resolution_criteria=NUM_CRIT, domain="econ", outcome_space=OutcomeSpace(type="distribution", choices=[], units="usd"))
    ids = {l["id"] for l in active_lessons_for_question(lg, q)}
    assert dt["id"] not in ids and vs["id"] not in ids  # wrong domain/topic + no choices


def test_existing_scopes_still_retrieved(tmp_path):
    # Additive: domain + question_type(raw) lessons must still match.
    lg = _ledger(tmp_path)
    dom = lg.create_calibration_lesson(scope_type="domain", scope_ref="politics", lesson="dom", status="active")
    raw = lg.create_calibration_lesson(scope_type="question_type", scope_ref="distribution", lesson="rawtype", status="active")
    q = _vote_share_q(lg, ["vote share"])
    ids = {l["id"] for l in active_lessons_for_question(lg, q)}
    assert dom["id"] in ids and raw["id"] in ids


def test_domain_topic_authoring_requires_colon_scope_ref(tmp_path):
    lg = _ledger(tmp_path)
    with pytest.raises(ValidationError, match="domain:topic"):
        lg.create_calibration_lesson(scope_type="domain_topic", scope_ref="politics", lesson="bad", status="active")
