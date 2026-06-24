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


# ── Slice 4: vote-share forecasts are machine-scoreable (vector MAE/RMSE) ──
def test_vote_share_dict_outcome_scored_as_vector_mae(tmp_path):
    lg = _ledger(tmp_path)
    osp = OutcomeSpace(type="distribution", choices=["Lasher", "Bores", "Other"], units="pct")
    res = lg._score_forecast_payload({"Lasher": 0.42, "Bores": 0.33, "Other": 0.25}, {"Lasher": 39.2, "Bores": 35.0, "Other": 25.8}, osp)
    assert res["score_rule"] == "vector_mae_percentage_points"
    assert 0.0 <= res["proper_score"] <= 100.0 and res["proper_score"] > 90  # ~1.9pp MAE


def test_vote_share_scored_end_to_end(tmp_path):
    lg = _ledger(tmp_path)
    osp = OutcomeSpace(type="distribution", choices=["A", "B", "Other"], units="pct")
    q = lg.create_question(title="What certified vote percentages will the candidates receive?", resolution_criteria=VS_CRIT, domain="politics", topics=["vote share"], outcome_space=osp)
    # exploratory commit bypasses the unrelated renderable-distribution gate.
    lg.create_snapshot(question_id=q.id, probability_or_distribution={"A": 0.5, "B": 0.4, "Other": 0.1}, rationale="share forecast", forecast_origin="exploratory")
    lg.resolve_question(question_id=q.id, outcome={"A": 52.0, "B": 38.0, "Other": 10.0}, resolution_status="confirmed", criteria_satisfied=True, auto_score=True)
    sc = lg.score_question(q.id)
    assert sc.score_rule == "vector_mae_percentage_points"


def test_normal_distribution_still_routes_to_normal_score(tmp_path):
    # Regression: a mean/sd distribution must NOT hit the vote-share branch.
    lg = _ledger(tmp_path)
    osp = OutcomeSpace(type="distribution", units="usd_billions")
    res = lg._score_forecast_payload({"mean": 390.0, "sd": 85.0}, 400.0, osp)
    assert res["score_rule"] != "vector_mae_percentage_points"


# ── Slice 3: scope-matched lessons reach the agent context + the TUI workspace ──
def test_context_packet_surfaces_scope_matched_lesson(tmp_path):
    from forecasting.protocol import build_context_packet
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(scope_type="domain_topic", scope_ref="politics:nyc-primaries", lesson="cap lower-tier candidate share near 5-10pp", status="active")
    q = _vote_share_q(lg, ["nyc-primaries", "vote share"])
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 50, "sd": 10, "q05": 35, "q50": 50, "q95": 65}, rationale="x", forecast_origin="exploratory")
    packet = build_context_packet(lg, lg.get_question(q.id), snap)
    assert "cap lower-tier candidate share" in packet  # the domain_topic lesson now surfaces (was global/domain-only before)
    assert les["id"] in packet or "lower-tier" in packet


def test_workspace_payload_exposes_relevant_lessons(tmp_path):
    from forecasting.dashboard import build_workspace_payload
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(scope_type="domain_topic", scope_ref="politics:nyc-primaries", lesson="top-two compression", status="active")
    q = _vote_share_q(lg, ["nyc-primaries", "vote share"])
    lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 50, "sd": 10, "q05": 35, "q50": 50, "q95": 65}, rationale="x", forecast_origin="exploratory")
    item = next(f for f in build_workspace_payload(ledger=lg)["forecasts"] if f["id"] == q.id)
    assert item["lessons_count"] >= 1
    assert any(l["id"] == les["id"] for l in item["relevant_lessons"])
