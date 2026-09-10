"""Learning must retain its scored sources and count independent questions."""

from forecasting import ForecastLedger
from forecasting.protocol import build_context_packet


def _resolved(ledger, index, *, snapshots=1, domain="release-rehearsal"):
    question = ledger.create_question(
        title=f"Will recorded observation {index} exceed the threshold?",
        domain=domain,
        resolution_criteria="Resolves yes if the official recorded value exceeds 10.",
    )
    forecasts = [ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Independent fixture forecast before resolution.",
    ) for _ in range(snapshots)]
    ledger.resolve_question(question_id=question.id, outcome="no" if index % 10 == 0 else "yes")
    for forecast in forecasts:
        ledger.score_snapshot(forecast.forecast_id)
    return question


def test_bias_lesson_keeps_sources_and_is_invalidated_by_correction(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    ledger._live_score_count = lambda domain: 0
    for index in range(40):
        _resolved(ledger, index)
    result = ledger.synthesize_bias_lessons(scope="release-rehearsal")[0]
    lesson = ledger.get_calibration_lesson(result["action"]["lesson_id"])
    source_ids = {score.id for score in ledger.list_scores()}
    assert set(lesson["source_score_record_refs"]) == source_ids
    assert lesson["status"] == "active"
    assert lesson["recommended_adjustment"] == {}
    next_question = ledger.create_question(
        title="Will the next observation exceed the threshold?",
        domain="release-rehearsal",
        resolution_criteria="Resolves yes if the official recorded value exceeds 10.",
    )
    next_snapshot = ledger.create_snapshot(
        question_id=next_question.id, probability_or_distribution=0.7, rationale="Next forecast.",
    )
    packet = build_context_packet(ledger, next_question, next_snapshot)
    assert "under-confident" in packet
    assert "scored_sources=40" in packet
    assert "effective_sample=40.0" in packet
    assert sorted(source_ids)[0] in packet
    assert next_snapshot.probability_or_distribution == 0.7
    correction = ledger.create_correction(
        target_type="score_record", target_id=sorted(source_ids)[0],
        reason="The source outcome was corrected.", status="applied",
    )
    assert lesson["id"] in correction["affected_calibration_lesson_refs"]
    assert ledger.get_calibration_lesson(lesson["id"])["status"] == "superseded"
    assert "under-confident" not in build_context_packet(ledger, next_question, next_snapshot)


def test_many_snapshots_of_one_outcome_do_not_clear_sample_floor(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    ledger._live_score_count = lambda domain: 0
    _resolved(ledger, 0, snapshots=25)
    _resolved(ledger, 1, snapshots=25)
    report = ledger.calibration_bias(domain="release-rehearsal")
    assert report["n"] == 2
    assert report["ess"] == 2
    assert report["status"] == "insufficient_evidence"
    assert ledger.synthesize_bias_lessons(scope="release-rehearsal")[0]["action"]["written"] is False


def test_global_and_domain_bias_do_not_multiply_the_same_correction(tmp_path):
    from forecasting.learning import apply_active_lesson_adjustments

    ledger = ForecastLedger(tmp_path / "ledger.db")
    ledger._live_score_count = lambda domain: 0
    for index in range(80):
        _resolved(ledger, index)
    ledger.synthesize_bias_lessons(scope="all", enable_mechanical=True)
    lessons = ledger.list_calibration_lessons(active_only=True)
    assert {item["scope_type"] for item in lessons} == {"global", "domain"}
    question = ledger.create_question(
        title="Will the follow-up observation exceed the threshold?",
        domain="release-rehearsal",
        resolution_criteria="Resolves yes if the official recorded value exceeds 10.",
    )
    adjusted, refs, audit = apply_active_lesson_adjustments(
        ledger=ledger, question=question, payload=0.7,
        calibration_lesson_refs=[], calibration_adjustment={},
    )
    domain_lesson = next(item for item in lessons if item["scope_type"] == "domain")
    assert audit["applied_logit_scale"] == domain_lesson["recommended_adjustment"]["logit_scale"]
    assert audit["applied_logit_scale"] <= 1.2
    assert set(refs) == {item["id"] for item in lessons}
    assert 0.7 < adjusted < 0.8


def test_domain_lesson_tracks_global_prior_sources_too(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    ledger._live_score_count = lambda domain: 0
    for index in range(40):
        _resolved(ledger, index)
    other = _resolved(ledger, 1, domain="another-domain")
    lesson_result = ledger.synthesize_bias_lessons(scope="release-rehearsal")[0]
    lesson = ledger.get_calibration_lesson(lesson_result["action"]["lesson_id"])
    metadata = lesson["metadata"]
    assert len(metadata["measurement_score_record_refs"]) == 40
    assert len(metadata["shrink_prior_score_record_refs"]) == 41
    other_score = ledger.score_question(other.id)
    assert other_score.id in lesson["source_score_record_refs"]
    correction = ledger.create_correction(
        target_type="score_record", target_id=other_score.id,
        reason="A global prior source was corrected.", status="applied",
    )
    assert lesson["id"] in correction["affected_calibration_lesson_refs"]


def test_report_provenance_excludes_neutral_and_lesson_exposed_rows():
    from forecasting.calibration_bias import Observation, assess_bias

    report = assess_bias([
        Observation(0.7, 1.0, score_record_id="included"),
        Observation(0.5, 1.0, score_record_id="neutral"),
        Observation(0.7, 1.0, lesson_active=True, score_record_id="lesson-exposed"),
        Observation(0.7, 1.0, weight=0.0, score_record_id="zero-weight"),
    ])
    assert report.source_score_record_refs == ["included"]
    assert report.n == 1
    assert report.status == "insufficient_evidence"
