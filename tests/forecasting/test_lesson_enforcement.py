"""Lesson enforcement — Slice 1: the previously-dead lessons_applied gate now
fires honestly. A numeric calibration lesson is "applied" only when the committed
forecast net-MOVED from the recorded pre-lesson raw payload, not when a lesson ref
was stapled on. This is what makes a calibration learning actually bite on the
next in-scope forecast instead of being silently ignored."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError

CRIT = "Resolves yes if the official source reports the value exceeds the threshold at the close date."

# A structural lesson rule: politics forecasts must carry an outside-view anchor.
_ANCHOR_RULE = {
    "category": "reasoning", "severity": "error",
    "check": {"signal": "reference_classes.count", "op": ">=", "value": 1},
    "message": "politics forecasts need an outside-view anchor (lesson)",
}


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "le.db"))
    lg.initialize_schema()
    return lg


def _verdict(snapshot, rule_id: str):
    sat = (snapshot.metadata or {}).get("saturation") or {}
    for v in sat.get("verdicts", []):
        if v.get("rule_id") == rule_id:
            return v.get("passed")
    return None


def _politics_q_with_numeric_lesson(lg):
    q = lg.create_question(title="Will the candidate win the contested primary?", resolution_criteria=CRIT, domain="politics")
    lesson = lg.create_calibration_lesson(
        scope_type="domain", scope_ref="politics",
        lesson="Correct chronic under-confidence on politics forecasts.",
        recommended_adjustment={"logit_shift": 0.3}, status="active",
    )
    return q, lesson


def test_ignored_numeric_lesson_fires_the_gate(tmp_path):
    lg = _ledger(tmp_path)
    q, _lesson = _politics_q_with_numeric_lesson(lg)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="baseline ignoring the lesson", forecast_origin="live")
    assert _verdict(snap, "lessons_applied") is False  # the gate is alive now (was always-pass before)


def test_genuine_application_passes(tmp_path):
    lg = _ledger(tmp_path)
    q, lesson = _politics_q_with_numeric_lesson(lg)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.57, rationale="applied the calibration lesson",
        forecast_origin="live", calibration_lesson_refs=[lesson["id"]],
        calibration_adjustment={"applied_active_lessons": [{"id": lesson["id"]}], "raw_probability": 0.5, "applied_logit_shift": 0.3},
    )
    assert _verdict(snap, "lessons_applied") is True


def test_citation_staple_does_not_satisfy_the_gate(tmp_path):
    # Attaching the ref WITHOUT moving the number must NOT count as applied.
    lg = _ledger(tmp_path)
    q, lesson = _politics_q_with_numeric_lesson(lg)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="stapled the ref but did not move",
        forecast_origin="live", calibration_lesson_refs=[lesson["id"]], calibration_adjustment={},
    )
    assert _verdict(snap, "lessons_applied") is False


def test_no_active_lessons_is_clean(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric clear the bar by close?", resolution_criteria=CRIT, domain="econ")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="no lessons in scope", forecast_origin="live")
    assert _verdict(snap, "lessons_applied") is True


def test_prose_only_lesson_is_not_counted_in_slice1(tmp_path):
    # A prose lesson (no numeric key) is NOT a numeric obligation; Slice 1 must not
    # count it (it becomes a compiled rule in Slice 2). Otherwise it would be
    # un-satisfiable (no numeric application possible).
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the candidate win the other primary?", resolution_criteria=CRIT, domain="politics")
    lg.create_calibration_lesson(
        scope_type="domain", scope_ref="politics",
        lesson="Build vote-share first, then translate to winner odds.",
        recommended_adjustment={"recommended_adjustment": "prose only, no numeric key"}, status="active",
    )
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="prose lesson present", forecast_origin="live")
    assert _verdict(snap, "lessons_applied") is True


# ── Slice 2: structural lessons compile to lesson:* rules that bite at commit ──
def _politics_lesson_rule(lg):
    return lg.create_calibration_lesson(
        scope_type="domain", scope_ref="politics", lesson="Anchor politics forecasts to a reference class.",
        recommended_adjustment={"rule": _ANCHOR_RULE}, status="active",
    )


def test_structural_lesson_blocks_when_violated(tmp_path):
    lg = _ledger(tmp_path)
    _politics_lesson_rule(lg)
    q = lg.create_question(title="Will the candidate win the primary by close?", resolution_criteria=CRIT, domain="politics")
    with pytest.raises(Exception):  # SaturationBlocked — the lesson rule (error) fires (no reference class)
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="no anchor", forecast_origin="live")


def test_structural_lesson_passes_when_satisfied(tmp_path):
    lg = _ledger(tmp_path)
    _politics_lesson_rule(lg)
    q = lg.create_question(title="Will the other candidate win by close?", resolution_criteria=CRIT, domain="politics")
    lg.add_reference_class(question_id=q.id, name="recent comparable primaries", inclusion_criteria="same-type contested primaries")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="anchored to a reference class", forecast_origin="live")
    assert snap is not None  # the anchor satisfies the lesson rule -> commits


def test_lesson_rule_scope_is_force_stamped(tmp_path):
    # The same lesson is scoped domain:politics; an econ forecast must be unaffected.
    lg = _ledger(tmp_path)
    _politics_lesson_rule(lg)
    q = lg.create_question(title="Will the econ metric clear the bar by close?", resolution_criteria=CRIT, domain="econ")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="out of scope for the politics lesson", forecast_origin="live")
    assert snap is not None


def test_lesson_rule_override_cannot_demote(tmp_path):
    lg = _ledger(tmp_path)
    lesson = _politics_lesson_rule(lg)
    q = lg.create_question(
        title="Will the third candidate win by close?", resolution_criteria=CRIT, domain="politics",
        metadata={"forecast_hooks": {"overrides": {f"lesson:{lesson['id']}": "off"}}},
    )
    with pytest.raises(Exception):  # the override must NOT demote a lesson:* rule
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="tried to override the lesson off", forecast_origin="live")


def test_invalid_lesson_rule_refused_at_authoring(tmp_path):
    lg = _ledger(tmp_path)
    with pytest.raises(ValidationError, match="rule is invalid"):
        lg.create_calibration_lesson(
            scope_type="domain", scope_ref="politics", lesson="broken",
            recommended_adjustment={"rule": {"check": {"signal": "nonsense.signal", "op": ">=", "value": 1}}}, status="active",
        )


# ── Slice 3: NY-12 structural rule via committed_winner_prob + derived_child_present ──
_NY12_RULE = {
    "category": "calibration", "severity": "error",
    "message": "a >65% politics winner call needs a linked vote-share child (lesson)",
    "check": {"any": [
        {"signal": "confidence.winner_prob", "op": "<=", "value": 0.65},
        {"signal": "links.derived_child_present", "op": "is_true"},
    ]},
}


def _ny12_lesson(lg):
    return lg.create_calibration_lesson(
        scope_type="domain", scope_ref="politics",
        lesson="Build vote-share first for confident primary winner calls.",
        recommended_adjustment={"rule": _NY12_RULE}, status="active",
    )


def test_confident_winner_without_vote_share_child_is_blocked(tmp_path):
    lg = _ledger(tmp_path)
    _ny12_lesson(lg)
    q = lg.create_question(title="Will candidate A win the primary?", resolution_criteria=CRIT, domain="politics")
    with pytest.raises(Exception):
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.70, rationale="confident, no vote-share model", forecast_origin="live")


def test_capped_winner_is_allowed(tmp_path):
    lg = _ledger(tmp_path)
    _ny12_lesson(lg)
    q = lg.create_question(title="Will candidate B win the primary?", resolution_criteria=CRIT, domain="politics")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.60, rationale="capped below 65 without a model", forecast_origin="live")
    assert snap is not None  # <=0.65 satisfies the rule


def test_confident_winner_with_vote_share_child_is_allowed(tmp_path):
    from forecasting.models import OutcomeSpace
    lg = _ledger(tmp_path)
    _ny12_lesson(lg)
    q = lg.create_question(title="Will candidate C win the primary?", resolution_criteria=CRIT, domain="politics")
    child = lg.create_question(
        title="Certified vote share for candidate C?",
        resolution_criteria="Resolves to the certified vote percentage the board reports for candidate C on the close date.",
        domain="politics", outcome_space=OutcomeSpace(type="distribution", units="pct"),
    )
    lg.create_snapshot(question_id=child.id, probability_or_distribution={"mean": 52, "sd": 6, "q05": 42, "q50": 52, "q95": 62}, rationale="vote-share model")
    lg.add_forecast_link(from_question_id=child.id, to_question_id=q.id, link_type="component_of")
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.70, rationale="confident, backed by the vote-share model", forecast_origin="live")
    assert snap is not None  # the linked vote-share child satisfies the rule


def test_distribution_payload_is_not_treated_as_a_winner_probability(tmp_path):
    # A vote-share distribution's quantiles must NOT be read as a 0.62 "winner prob"
    # (that bug would block every distribution commit under the NY-12 rule).
    from forecasting.models import OutcomeSpace
    lg = _ledger(tmp_path)
    _ny12_lesson(lg)
    q = lg.create_question(
        title="Certified vote share for the leading candidate?",
        resolution_criteria="Resolves to the certified vote percentage the board reports on the close date.",
        domain="politics", outcome_space=OutcomeSpace(type="distribution", units="pct"),
    )
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 52, "sd": 6, "q05": 42, "q50": 52, "q95": 62}, rationale="a vote-share model itself", forecast_origin="live")
    assert snap is not None  # winner_prob is None for a distribution -> rule not triggered


# ── Slice 3 (coverage audit): "is each learning actually being used?" ──
def test_coverage_records_in_scope_and_applied(tmp_path):
    lg = _ledger(tmp_path)
    num = lg.create_calibration_lesson(scope_type="domain", scope_ref="politics", lesson="numeric bias", recommended_adjustment={"logit_shift": 0.3}, status="active")
    q = lg.create_question(title="Will the candidate win the primary by close?", resolution_criteria=CRIT, domain="politics")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="ignored the lesson", forecast_origin="live")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.57, rationale="applied the lesson", forecast_origin="live", calibration_adjustment={"applied_active_lessons": [{"id": num["id"]}], "raw_probability": 0.5})
    cov = {r["lesson_id"]: r for r in lg.lesson_coverage()}
    assert cov[num["id"]]["in_scope_count"] == 2
    assert cov[num["id"]]["applied_count"] == 1  # one ignored, one applied


def test_coverage_flags_dormant_lesson(tmp_path):
    lg = _ledger(tmp_path)
    # a lesson scoped to a domain we never commit in
    dormant = lg.create_calibration_lesson(scope_type="domain", scope_ref="space", lesson="never encountered", recommended_adjustment={"logit_shift": 0.1}, status="active")
    q = lg.create_question(title="Will the politics metric clear the bar by close?", resolution_criteria=CRIT, domain="politics")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="out of the dormant lesson's scope", forecast_origin="live")
    cov = {r["lesson_id"]: r for r in lg.lesson_coverage()}
    assert cov[dormant["id"]]["dormant"] is True and cov[dormant["id"]]["in_scope_count"] == 0


def test_coverage_marks_prose_lesson_unenforceable(tmp_path):
    lg = _ledger(tmp_path)
    prose = lg.create_calibration_lesson(scope_type="domain", scope_ref="politics", lesson="build vote-share first", recommended_adjustment={"note": "prose only"}, status="active")
    cov = {r["lesson_id"]: r for r in lg.lesson_coverage()}
    assert cov[prose["id"]]["enforceable"] is False and cov[prose["id"]]["kind"] == "advisory"
