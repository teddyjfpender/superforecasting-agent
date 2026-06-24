"""Lesson enforcement — Slice 1: the previously-dead lessons_applied gate now
fires honestly. A numeric calibration lesson is "applied" only when the committed
forecast net-MOVED from the recorded pre-lesson raw payload, not when a lesson ref
was stapled on. This is what makes a calibration learning actually bite on the
next in-scope forecast instead of being silently ignored."""

from __future__ import annotations

from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the official source reports the value exceeds the threshold at the close date."


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
