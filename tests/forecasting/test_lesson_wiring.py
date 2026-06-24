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


# ── Lesson apply: a learning auto-compiles to an enforceable hook (lazy operator) ──
def test_recognized_lesson_auto_compiles_to_rule(tmp_path):
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(
        scope_type="domain_topic", scope_ref="politics:nyc-primaries", lesson="top-two compression",
        recommended_adjustment={"process_rule": "add_top_two_consolidation_layer", "candidate_tail_cap": "cap near 5-10%"}, status="active",
    )
    rule = (les["recommended_adjustment"] or {}).get("rule")
    assert rule and rule["check"]["signal"] == "tails.null_excess"


def test_scoreability_lesson_auto_compiles_to_born_scoreable(tmp_path):
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(
        scope_type="question_type", scope_ref="vote-share-distribution", lesson="scoreable",
        recommended_adjustment={"process_rule": "validate_vote_share_scoreability_before_commit"}, status="active",
    )
    assert (les["recommended_adjustment"]["rule"]["check"]["signal"]) == "outcome.machine_scoreable"


def test_unrecognized_lesson_stays_advisory(tmp_path):
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(
        scope_type="domain_topic", scope_ref="politics:movement-primaries", lesson="movement field",
        recommended_adjustment={"process_rule": "price_movement_field_as_turnout_composition_shock"}, status="active",
    )
    assert "rule" not in (les["recommended_adjustment"] or {})


def test_apply_lesson_compiles_prose_then_advisory_when_no_pattern(tmp_path):
    lg = _ledger(tmp_path)
    p = lg.create_calibration_lesson(scope_type="domain", scope_ref="politics", lesson="x", recommended_adjustment={"enforcement_pattern": "tail_cap"}, status="active")
    lg.update_calibration_lesson(p["id"], recommended_adjustment={"enforcement_pattern": "tail_cap"})  # strip auto rule
    assert lg.apply_lesson(p["id"])["applied"] is True
    n = lg.create_calibration_lesson(scope_type="domain", scope_ref="weather", lesson="vague prose", recommended_adjustment={"note": "no pattern here"}, status="active")
    assert lg.apply_lesson(n["id"])["applied"] is False


def test_born_scoreable_signal_flags_non_share_payload(tmp_path):
    # A choices-present (vote-share) question forecast that lacks numeric candidate
    # shares is NOT machine-scoreable; a continuous one is unaffected.
    lg = _ledger(tmp_path)
    osp = OutcomeSpace(type="distribution", choices=["A", "B", "Other"], units="pct")
    assert lg._machine_scoreable_payload({"A": 0.5, "B": 0.4, "Other": 0.1}, osp) is True
    assert lg._machine_scoreable_payload({"mean": 50, "sd": 10}, osp) is False  # not candidate shares
    # A continuous distribution (no candidate choices, as stored via from_dict) is N/A -> scoreable.
    assert lg._machine_scoreable_payload({"mean": 50}, OutcomeSpace(type="distribution", choices=[], units="usd")) is True


# ── Candidate-share PMFs are first-class: renderable -> commit LIVE -> lessons engage ──
def test_candidate_share_pmf_is_renderable(tmp_path):
    from forecasting.hooks.distribution import assess_distribution
    a = assess_distribution({"Espaillat": 44.0, "Chevalier": 43.5, "Other": 12.5}, outcome_type="distribution", units="pct")
    assert a is not None and a.is_distribution and a.renderable is True
    # probabilities (sum ~1) also recognized
    b = assess_distribution({"A": 0.44, "B": 0.435, "Other": 0.125}, outcome_type="distribution")
    assert b is not None and b.renderable is True


def test_malformed_distribution_still_not_renderable(tmp_path):
    # A single stray value (not a share PMF, not a continuous interval) stays blocked.
    from forecasting.hooks.distribution import assess_distribution
    a = assess_distribution({"foo": 1.0}, outcome_type="distribution")
    assert a is not None and a.renderable is False


def test_vote_share_forecast_commits_live_and_lessons_engage(tmp_path):
    lg = _ledger(tmp_path)
    lg.create_calibration_lesson(scope_type="question_type", scope_ref="vote-share-distribution", lesson="scoreable", recommended_adjustment={"enforcement_pattern": "born_scoreable"}, status="active")
    q = _vote_share_q(lg, ["vote share"])
    # the candidate-share dict now commits LIVE (was forced exploratory before)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution={"A": 44.0, "B": 43.5, "Other": 12.5}, rationale="share", forecast_origin="live")
    assert snap is not None
    # the scoped lesson is now recorded as engaged on this live commit
    cov = {r["lesson_id"]: r for r in lg.lesson_coverage()}
    assert any(r["in_scope_count"] >= 1 for r in cov.values())
