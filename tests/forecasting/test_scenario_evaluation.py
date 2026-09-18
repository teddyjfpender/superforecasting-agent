"""Matched scenario execution preserves inputs, recovery and forecast authority."""

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
            "fingerprint": fingerprint,
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
