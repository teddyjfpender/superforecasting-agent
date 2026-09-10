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


def test_prose_lesson_can_be_upgraded_to_an_enforced_rule(tmp_path):
    # The exact path used to make the live NY-12 lesson bite: update an existing
    # prose lesson to carry a validated rule, after which it enforces.
    lg = _ledger(tmp_path)
    les = lg.create_calibration_lesson(scope_type="domain", scope_ref="politics", lesson="build vote-share first", recommended_adjustment={"note": "prose"}, status="active")
    lg.update_calibration_lesson(les["id"], recommended_adjustment={"note": "prose", "rule": _ANCHOR_RULE})
    q = lg.create_question(title="Will the candidate win by close?", resolution_criteria=CRIT, domain="politics")
    with pytest.raises(Exception):  # the upgraded lesson now blocks an unanchored politics commit
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="no anchor", forecast_origin="live")
    with pytest.raises(ValidationError, match="rule is invalid"):  # update also validates
        lg.update_calibration_lesson(les["id"], recommended_adjustment={"rule": {"check": {"signal": "nope", "op": ">=", "value": 1}}})


def test_warning_failure_is_not_recorded_as_applied(tmp_path):
    lg = _ledger(tmp_path)
    rule = dict(_ANCHOR_RULE, severity='warn')
    lesson = lg.create_calibration_lesson(scope_type='domain', scope_ref='politics', lesson='Use a reference class.', status='active', recommended_adjustment={'rule': rule})
    q = lg.create_question(title='Will the candidate win the primary?', resolution_criteria=CRIT, domain='politics')
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=.5, rationale='No reference class yet.')
    decision = next(d for d in snap.metadata['lesson_decisions'] if d['lesson_id'] == lesson['id'])
    assert decision['reason'] == 'rule_failed'
    assert decision['applied'] is False
    coverage = lg.lesson_coverage()[0]
    assert coverage['applied_count'] == 0
    assert coverage['verified_count'] == 1
    lg.add_reference_class(question_id=q.id, name='Comparable primaries', inclusion_criteria='Same race type.')
    lg.create_snapshot(question_id=q.id, probability_or_distribution=.5, rationale='Now anchored.')
    assert lg.lesson_coverage()[0]['applied_count'] == 1


def test_supersession_is_shared_by_context_and_rule_selection(tmp_path):
    from forecasting.learning import active_lessons_for_question
    lg = _ledger(tmp_path)
    q = lg.create_question(title='Will the candidate win?', resolution_criteria=CRIT, domain='politics')
    old = lg.create_calibration_lesson(scope_type='global', scope_ref=None, lesson='Old guidance.', status='active')
    new = lg.create_calibration_lesson(scope_type='domain', scope_ref='politics', lesson='Replacement guidance.', status='active')
    lg.update_calibration_lesson(new['id'], supersedes_lesson_id=old['id'])
    assert [r['id'] for r in active_lessons_for_question(lg, q)] == [new['id']]
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=.5, rationale='Replacement applies.')
    old_decision = next(d for d in snap.metadata['lesson_decisions'] if d['lesson_id'] == old['id'])
    assert old_decision['reason'] == f"superseded_by:{new['id']}"
    lg.update_calibration_lesson(new['id'], status='rejected')
    assert [r['id'] for r in active_lessons_for_question(lg, q)] == [old['id']]


def test_legacy_coverage_and_supersession_cycles_are_not_trusted(tmp_path):
    lg = _ledger(tmp_path)
    q, lesson = _politics_q_with_numeric_lesson(lg)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=.6, rationale='Historical application.')
    with lg._connect() as conn:
        conn.execute("UPDATE forecast_snapshots SET metadata='{}' WHERE forecast_id=?", (snap.forecast_id,))
        conn.execute('UPDATE lesson_applications SET applied=1 WHERE snapshot_id=?', (snap.forecast_id,))
    row = lg.lesson_coverage()[0]
    assert row['unverified_count'] == 1
    assert row['applied_count'] == 0
    with pytest.raises(Exception, match='supersession.*cycle'):
        lg.update_calibration_lesson(lesson['id'], supersedes_lesson_id=lesson['id'])


def test_caller_metadata_cannot_forge_a_lesson_verdict(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    lesson = _politics_lesson_rule(lg)
    q = lg.create_question(title='Will the candidate win?', resolution_criteria=CRIT, domain='politics')
    monkeypatch.setattr('forecasting.learning.compile_lesson_rules', lambda *a: [])
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=.5, rationale='Compiler unavailable.',
        metadata={'lesson_rule_report': {'verdicts': [{'rule_id': f"lesson:{lesson['id']}", 'passed': True}]}})
    decision, = snap.metadata['lesson_decisions']
    assert decision['reason'] == 'rule_not_evaluated'
    assert decision['applied'] is False
