"""Matched scenario execution preserves inputs, recovery and forecast authority."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError as ModelError

from forecasting.interviews import evaluation
from forecasting.interviews.service import InterviewService
from forecasting.jobs.model import JobRecord
from forecasting.jobs.runtime import run
from forecasting.jobs.store import JobStore
from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import ValidationError
from protocol.interviews import InterviewScenario
from protocol.scenarios import ScenarioEstimate, ScenarioEvaluationOptions


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = ForecastLedger(tmp_path / "ledger.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Will the event occur by 2030?",
            resolution_criteria="Official confirmation before December 2030.",
        )
    service = InterviewService(ledger)
    service.begin("review", question_id=question.id)
    draft = service.answer(
        "review",
        expected_revision=1,
        request_id="drivers",
        question_id="drivers",
        status="answered",
        value="Candidate stays healthy",
    )
    factor = draft["document"]["assumptions"][0]["id"]
    for scenario in [
        InterviewScenario(
            id="healthy", name="Healthy", kind="conditional", conditions={factor: True}
        ),
        InterviewScenario(
            id="omit",
            name="Omit health",
            kind="ablation",
            excluded_assumption_ids=[factor],
        ),
    ]:
        draft = service.save_scenario(
            "review",
            expected_revision=draft["revision"],
            request_id=scenario.id,
            scenario=scenario,
        )
    jobs = JobStore(tmp_path)
    record = JobRecord(
        job_id=jobs.new_id(),
        type="forecast_scenarios",
        spec={
            "interview_id": "review",
            "revision": draft["revision"],
            "options": {"scenario_ids": ["healthy", "omit"]},
            "db": str(ledger.db_path),
        },
    )
    jobs.write(record)
    return service, question, jobs, record


def response(probability=0.4, fingerprint="same"):
    return {
        "content": json.dumps({
            "outcome_type": "binary",
            "probability": probability,
            "rationale": "Controlled reasoning",
        }),
        "response_model": "controlled-model",
        "output_tokens": 40,
        "request_receipt": {
            "fingerprint": hashlib.sha256(fingerprint.encode()).hexdigest(),
            "provider": "fake",
            "model": "controlled-model",
        },
    }


def test_variants_are_matched_and_never_promoted(work, monkeypatch):
    service, question, jobs, record = work
    call = Mock(side_effect=[response(0.4), response(0.7), response(0.5)])
    monkeypatch.setattr(evaluation, "run_model", call)
    outcome = run(record.job_id, store=jobs)
    assert outcome.status == "done", outcome.error
    saved = jobs.read(record.job_id)
    results = saved.annotations["scenario_results"]
    assert [item["kind"] for item in results] == ["baseline", "conditional", "ablation"]
    packets = [json.loads(args.args[0][1]["content"]) for args in call.call_args_list]
    assert [packet.pop("variant")["kind"] for packet in packets] == [
        "baseline",
        "conditional",
        "ablation",
    ]
    assert packets[0] == packets[1] == packets[2]
    summaries = evaluation.summarize(results)
    assert summaries[1]["dimensions"]["probability"]["paired_delta"] == pytest.approx(
        0.3
    )
    assert summaries[1]["dimensions"]["probability"]["model_dispersion"] is None
    assert service.ledger.list_snapshots(question.id) == []
    assert service.store.read("review")["revision"] == record.spec["revision"]


def test_interrupted_run_reuses_completed_calls(work, monkeypatch):
    _, _, jobs, record = work
    call = Mock(side_effect=[response(), RuntimeError("interrupted")])
    monkeypatch.setattr(evaluation, "run_model", call)
    assert run(record.job_id, store=jobs).status == "error"
    saved = jobs.read(record.job_id)
    assert len(saved.annotations["scenario_results"]) == 1
    saved.status = "running"
    jobs.write(saved)
    call = Mock(side_effect=[response(0.7), response(0.5)])
    monkeypatch.setattr(evaluation, "run_model", call)
    assert run(record.job_id, store=jobs).status == "done"
    assert call.call_count == 2


def test_changed_route_is_retained_but_never_compared(work, monkeypatch):
    _, _, jobs, record = work
    call = Mock(side_effect=[response(), response(fingerprint="changed")])
    monkeypatch.setattr(evaluation, "run_model", call)
    result = run(record.job_id, store=jobs)
    assert result.status == "error"
    assert "comparison is invalid" in result.error
    saved = jobs.read(record.job_id)
    assert len(saved.annotations["scenario_results"]) == 2
    saved.status = "running"
    jobs.write(saved)
    assert run(record.job_id, store=jobs).status == "error"
    assert call.call_count == 2


def test_cancel_during_call_preserves_result_without_more_spend(work, monkeypatch):
    _, _, jobs, record = work

    def cancel(*args):
        jobs.request_cancel(record.job_id)
        return response()

    call = Mock(side_effect=cancel)
    monkeypatch.setattr(evaluation, "run_model", call)
    result = run(record.job_id, store=jobs)
    assert result.status == "cancelled"
    assert call.call_count == 1
    assert len(jobs.read(record.job_id).annotations["scenario_results"]) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"outcome_type": "binary", "probability": "0.4"},
        {"outcome_type": "binary", "probability": 1.2},
        {"outcome_type": "binary", "probability": 0.4, "q50": 2.0},
        {"outcome_type": "categorical", "categories": {"a": 0.4, "b": 0.4}},
        {
            "outcome_type": "numeric",
            "q10": 10.0,
            "q50": 2.0,
            "q90": 12.0,
            "units": "percent",
        },
        {
            "outcome_type": "numeric",
            "q10": 1.0,
            "q50": 2.0,
            "q90": float("nan"),
            "units": "percent",
        },
    ],
)
def test_invalid_measurements_fail_closed(fields):
    with pytest.raises(ModelError):
        ScenarioEstimate.model_validate({**fields, "rationale": "test"})


def test_exact_units_categories_and_evidence_are_required():
    estimate = ScenarioEstimate(
        outcome_type="numeric",
        q10=1.0,
        q50=2.0,
        q90=3.0,
        units="percent",
        rationale="test",
    )
    plan = {
        "contract": {"outcome_space": {"type": "numeric", "units": "USD"}},
        "evidence_refs": [],
    }
    with pytest.raises(ValidationError, match="units"):
        evaluation.validate_estimate(estimate, plan)
    estimate = ScenarioEstimate(
        outcome_type="categorical", categories={"wrong": 1.0}, rationale="test"
    )
    plan["contract"]["outcome_space"] = {"type": "categorical", "choices": ["correct"]}
    with pytest.raises(ValidationError, match="identities"):
        evaluation.validate_estimate(estimate, plan)
    estimate = ScenarioEstimate(
        outcome_type="binary",
        probability=0.5,
        evidence_refs=["invented"],
        rationale="test",
    )
    plan["contract"]["outcome_space"] = {"type": "binary"}
    with pytest.raises(ValidationError, match="invented"):
        evaluation.validate_estimate(estimate, plan)


def test_repetition_budget_and_dispersion(work, monkeypatch):
    service, _, jobs, record = work
    options = ScenarioEvaluationOptions(scenario_ids=["healthy"], repetitions=2)
    plan = evaluation.prepare(
        service.ledger, "review", record.spec["revision"], options
    )
    assert len(plan["calls"]) == 4
    record.spec["options"] = options.model_dump()
    jobs.write(record)
    monkeypatch.setattr(
        evaluation,
        "run_model",
        Mock(side_effect=[response(0.4), response(0.6), response(0.5), response(0.8)]),
    )
    assert run(record.job_id, store=jobs).status == "done"
    summary = evaluation.summarize(
        jobs.read(record.job_id).annotations["scenario_results"]
    )[1]
    assert summary["dimensions"]["probability"]["paired_delta"] == pytest.approx(0.25)
    assert summary["dimensions"]["probability"]["model_dispersion"] == pytest.approx(
        0.1
    )


def test_saved_plan_survives_interview_changes(work, monkeypatch):
    service, _, jobs, record = work
    call = Mock(side_effect=[response(), RuntimeError("interrupted")])
    monkeypatch.setattr(evaluation, "run_model", call)
    assert run(record.job_id, store=jobs).status == "error"
    service.answer(
        "review",
        expected_revision=record.spec["revision"],
        request_id="new-belief",
        question_id="belief",
        status="answered",
        value=0.9,
    )
    saved = jobs.read(record.job_id)
    old_plan = saved.annotations["scenario_plan"]
    saved.status = "running"
    jobs.write(saved)
    monkeypatch.setattr(
        evaluation, "run_model", Mock(side_effect=[response(0.7), response(0.5)])
    )
    assert run(record.job_id, store=jobs).status == "done"
    assert jobs.read(record.job_id).annotations["scenario_plan"] == old_plan
    assert service.store.read("review")["document"]["answers"][-1]["value"] == 0.9


def test_update_cannot_silently_compare_a_changed_contract(work):
    service, _, _, record = work
    updated = service.answer(
        "review",
        expected_revision=record.spec["revision"],
        request_id="change-criteria",
        question_id="criteria",
        status="answered",
        value="A different event before 2040",
    )
    with pytest.raises(ValidationError, match="new question"):
        evaluation.prepare(
            service.ledger,
            "review",
            updated["revision"],
            ScenarioEvaluationOptions(scenario_ids=["healthy"]),
        )


def test_idempotent_start_and_typed_status(work, monkeypatch):
    from forecasting.interviews.evaluation_jobs import (
        enqueue_evaluation,
        evaluation_status,
    )
    from protocol.rpc.interviews import InterviewEvaluationStatusResponse

    service, _, jobs, record = work
    options = ScenarioEvaluationOptions(scenario_ids=["healthy"])
    job_id = enqueue_evaluation(
        service.ledger, "review", record.spec["revision"], "start", options
    )
    assert (
        enqueue_evaluation(
            service.ledger, "review", record.spec["revision"], "start", options
        )
        == job_id
    )
    with pytest.raises(ValidationError, match="different settings"):
        enqueue_evaluation(
            service.ledger,
            "review",
            record.spec["revision"],
            "start",
            ScenarioEvaluationOptions(scenario_ids=["omit"]),
        )
    monkeypatch.setattr(
        evaluation, "run_model", Mock(side_effect=[response(), response(0.6)])
    )
    assert run(job_id, store=jobs).status == "done"
    status = InterviewEvaluationStatusResponse.model_validate(
        evaluation_status(service.ledger, "review")
    )
    assert status.report.matched
    assert status.report.scenarios[0].id == "healthy"
    assert status.stale is False
    service.answer(
        "review",
        expected_revision=record.spec["revision"],
        request_id="later",
        question_id="belief",
        status="answered",
        value=0.9,
    )
    assert evaluation_status(service.ledger, "review")["stale"] is True


def test_uncommitted_enqueue_cannot_spend(work, monkeypatch):
    _, _, jobs, record = work
    record.spec["request_id"] = "missing-receipt"
    jobs.write(record)
    call = Mock()
    monkeypatch.setattr(evaluation, "run_model", call)
    result = run(record.job_id, store=jobs)
    assert result.status == "error"
    assert "receipt was not committed" in result.error
    call.assert_not_called()


def test_interview_allows_only_one_active_comparison(work):
    from forecasting.interviews.evaluation_jobs import enqueue_evaluation

    service, _, _, record = work
    options = ScenarioEvaluationOptions(scenario_ids=["healthy"])
    enqueue_evaluation(
        service.ledger, "review", record.spec["revision"], "first", options
    )
    with pytest.raises(ValidationError, match="already active"):
        enqueue_evaluation(
            service.ledger, "review", record.spec["revision"], "second", options
        )


def promotion_job(work, monkeypatch, *, outside_view=True):
    service, question, jobs, original = work
    evidence = service.ledger.add_evidence(
        question_id=question.id,
        source_or_note="Official report",
        claim="Recorded observation",
        summary="Relevant evidence for the estimate",
        archive_url_snapshot=False,
    )
    if outside_view:
        service.ledger.add_reference_class(
            question_id=question.id, name="Comparable elections",
            inclusion_criteria="Prior elections under the same rules", base_rate=0.4,
        )
    draft = service.begin("promotion", question_id=question.id)
    record = JobRecord(
        job_id=jobs.new_id(),
        type="forecast_scenarios",
        spec={
            **original.spec,
            "interview_id": "promotion",
            "revision": draft["revision"],
        },
    )
    jobs.write(record)
    result = response()
    content = json.loads(result["content"])
    content["evidence_refs"] = [evidence.id]
    content["reference_class_refs"] = [item["id"] for item in service.ledger.list_reference_classes(question.id)]
    result["content"] = json.dumps(content)
    monkeypatch.setattr(evaluation, "run_model", Mock(return_value=result))
    outcome = run(record.job_id, store=jobs)
    assert outcome.status == "done", outcome.error
    return record.job_id


def test_explicit_promotion_is_atomic_and_idempotent(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion, promote

    service, question, jobs, _ = work
    job_id = promotion_job(work, monkeypatch)
    preview = preview_promotion(service.ledger, job_id)
    assert preview["would_commit"], preview
    assert service.ledger.list_snapshots(question.id) == []
    result = promote(service.ledger, job_id, 0, preview["preview_digest"])
    assert promote(service.ledger, job_id, 0, preview["preview_digest"]) == result
    assert len(service.ledger.list_snapshots(question.id)) == 1
    snapshot = service.ledger.get_current_snapshot(question.id)
    assert snapshot.forecast_id == result["forecast_id"]
    assert (
        snapshot.metadata["interview_evaluation"]["selected_result"]["kind"]
        == "baseline"
    )
    assert snapshot.probability_or_distribution == 0.4
    with pytest.raises(ValidationError, match="different reviewed candidate"):
        promote(service.ledger, job_id, 1, preview["preview_digest"])


def test_stale_baseline_and_bad_preview_cannot_promote(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion, promote

    service, question, _, _ = work
    job_id = promotion_job(work, monkeypatch)
    preview = preview_promotion(service.ledger, job_id)
    with pytest.raises(ValidationError, match="preview changed"):
        promote(service.ledger, job_id, 0, "0" * 64)
    with allow_ledger_writes(reason="fixture"):
        service.ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.8,
            rationale="New baseline",
            forecast_origin="exploratory",
        )
    with pytest.raises(ValidationError, match="active forecast changed"):
        promote(service.ledger, job_id, 0, preview["preview_digest"])
    assert len(service.ledger.list_snapshots(question.id)) == 1


def test_ledger_blockers_are_preserved_by_promotion(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion, promote

    service, question, jobs, record = work
    monkeypatch.setattr(evaluation, "run_model", Mock(return_value=response()))
    assert run(record.job_id, store=jobs).status == "done"
    preview = preview_promotion(service.ledger, record.job_id)
    assert not preview["would_commit"]
    assert preview["blockers"]
    with pytest.raises(ValidationError, match="promotion blocked"):
        promote(service.ledger, record.job_id, 0, preview["preview_digest"])
    assert service.ledger.list_snapshots(question.id) == []


def test_promotion_receipt_failure_rolls_back_snapshot(work, monkeypatch):
    import sqlite3

    from forecasting.interviews.promotion import preview_promotion, promote

    service, question, _, _ = work
    job_id = promotion_job(work, monkeypatch)
    preview = preview_promotion(service.ledger, job_id)
    with service.ledger.transaction(immediate=True) as conn:
        conn.execute(
            "CREATE TRIGGER fail_promotion BEFORE INSERT ON forecast_interview_promotions BEGIN SELECT RAISE(ABORT, 'injected interruption'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected interruption"):
        promote(service.ledger, job_id, 0, preview["preview_digest"])
    assert service.ledger.list_snapshots(question.id) == []
    assert service.ledger.get_question(question.id).current_forecast_id is None
    with service.ledger.transaction(immediate=True) as conn:
        conn.execute("DROP TRIGGER fail_promotion")
    saved = promote(service.ledger, job_id, 0, preview["preview_digest"])
    restored = preview_promotion(service.ledger, job_id)
    assert restored["promoted_forecast_id"] == saved["forecast_id"]


def test_promotion_rejects_altered_result_records(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion

    service, question, jobs, _ = work
    job_id = promotion_job(work, monkeypatch)
    stored = jobs.read(job_id)
    stored.result["results"][0]["estimate"]["probability"] = 0.99
    jobs.write(stored)
    with pytest.raises(ValidationError, match="durable call records"):
        preview_promotion(service.ledger, job_id)
    assert service.ledger.list_snapshots(question.id) == []


def test_censored_promotion_never_invents_tail_probability(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion
    from forecasting.models import OutcomeSpace

    service, _, jobs, original = work
    with allow_ledger_writes(reason="fixture"):
        question = service.ledger.create_question(
            title="How many days until official confirmation?",
            resolution_criteria="Days from January 1 until the official report, observed through January 7.",
            outcome_space=OutcomeSpace(
                type="numeric",
                choices=[],
                units="days",
                censoring={
                    "threshold": 6,
                    "inclusive": True,
                    "probability_key": "p_gte_6",
                },
            ),
        )
    record = service.begin("censored", question_id=question.id)
    record = service.answer(
        "censored",
        expected_revision=record["revision"],
        request_id="drivers",
        question_id="drivers",
        status="answered",
        value="Official publication is delayed",
    )
    factor = record["document"]["assumptions"][0]["id"]
    record = service.save_scenario(
        "censored",
        expected_revision=record["revision"],
        request_id="scenario",
        scenario=InterviewScenario(
            id="delayed", name="Delayed", kind="conditional", conditions={factor: True}
        ),
    )
    job = JobRecord(
        job_id=jobs.new_id(),
        type="forecast_scenarios",
        spec={
            **original.spec,
            "interview_id": "censored",
            "revision": record["revision"],
            "options": {"scenario_ids": ["delayed"]},
        },
    )
    jobs.write(job)
    result = response()
    result["content"] = json.dumps({
        "outcome_type": "numeric",
        "q10": 1.0,
        "q50": 4.0,
        "q90": 8.0,
        "units": "days",
        "rationale": "Direct elicited quantiles",
    })
    monkeypatch.setattr(evaluation, "run_model", Mock(return_value=result))
    completed = run(job.job_id, store=jobs)
    assert completed.status == "done", completed.error
    preview = preview_promotion(service.ledger, job.job_id)
    assert preview["would_commit"] is False
    assert any(
        "Gaussian fallback is forbidden" in blocker for blocker in preview["blockers"]
    )
    assert "sd" not in preview["candidate"]
    assert "p_gte_6" not in preview["candidate"]
    assert service.ledger.list_snapshots(question.id) == []


def test_promotion_enforces_outside_view_quality_gate(work, monkeypatch):
    from forecasting.interviews.promotion import preview_promotion, promote

    service, question, _, _ = work
    job_id = promotion_job(work, monkeypatch, outside_view=False)
    preview = preview_promotion(service.ledger, job_id)
    assert not preview["would_commit"]
    assert any("outside-view" in item for item in preview["blockers"])
    with pytest.raises(ValidationError, match="outside-view"):
        promote(service.ledger, job_id, 0, preview["preview_digest"])
    assert service.ledger.list_snapshots(question.id) == []


def test_scenario_cannot_cite_reference_class_outside_frozen_context(work, monkeypatch):
    service, question, jobs, record = work
    reference = service.ledger.add_reference_class(
        question_id=question.id, name="Added after capture", inclusion_criteria="Comparable cases", base_rate=0.4,
    )
    result = response()
    content = json.loads(result["content"])
    content["reference_class_refs"] = [reference["id"]]
    result["content"] = json.dumps(content)
    monkeypatch.setattr(evaluation, "run_model", Mock(return_value=result))
    outcome = run(record.job_id, store=jobs)
    assert outcome.status == "error"
    assert "invented a reference-class reference" in outcome.error
    assert service.ledger.list_snapshots(question.id) == []


@pytest.mark.parametrize("kind", ["numeric", "distribution", "categorical"])
def test_existing_outcome_contracts_have_typed_elicitation_and_reject_incoherence(tmp_path, kind):
    from forecasting.models import OutcomeSpace

    ledger = ForecastLedger(tmp_path / "typed.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Measured outcome", resolution_criteria="Official confirmation before December 2030.",
            outcome_space=OutcomeSpace(type=kind, units="USD" if kind != "categorical" else None,
                                       choices=["A", "B"] if kind == "categorical" else []),
        )
    service = InterviewService(ledger)
    record = service.begin("typed", question_id=question.id)
    qs = record["document"]["questions"]
    if kind == "categorical":
        assert next(a["value"] for a in record["document"]["answers"] if a["question_id"] == "categories") == "A\nB"
        values = [(q["id"], 0.7) for q in qs if q["id"].startswith("category_prob_")]
        assert len(values) == 2
    else:
        assert "quantile_10" in {q["id"] for q in qs}
        assert "categories" not in {q["id"] for q in qs}
        values = [("quantile_10", 10.0), ("quantile_90", 2.0)]
    for key, value in values:
        record = service.answer("typed", expected_revision=record["revision"], request_id=key,
                                question_id=key, status="answered", value=value)
    with pytest.raises(ValidationError, match="Quantiles|sum to 1"):
        evaluation.prepare(ledger, "typed", record["revision"], ScenarioEvaluationOptions(scenario_ids=["unused"]))


def test_comparison_rejects_changed_categorical_contract(tmp_path):
    from forecasting.models import OutcomeSpace

    ledger = ForecastLedger(tmp_path / "categories.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(title="Which result?", resolution_criteria="Official confirmation before December 2030.",
                                          outcome_space=OutcomeSpace(type="categorical", choices=["A", "B"]))
    service = InterviewService(ledger)
    service.begin("categories", question_id=question.id)
    record = service.answer("categories", expected_revision=1, request_id="change", question_id="categories",
                            status="answered", value="A\nC")
    with pytest.raises(ValidationError, match="category identities"):
        evaluation.prepare(ledger, "categories", record["revision"], ScenarioEvaluationOptions(scenario_ids=["unused"]))
