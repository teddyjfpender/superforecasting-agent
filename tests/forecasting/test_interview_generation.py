"""Adaptive interviews preserve user authority across failure and recovery."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from forecasting.interviews import generation
from forecasting.interviews.service import InterviewService
from forecasting.jobs.model import JobRecord
from forecasting.jobs.runtime import run
from forecasting.jobs.store import JobStore
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from protocol.interviews import (
    InterviewAssumption,
    InterviewDraft,
    InterviewGenerationOptions,
)


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ledger = ForecastLedger(tmp_path / "ledger.db")
    service = InterviewService(ledger)
    service.begin("interview")
    jobs = JobStore(tmp_path)
    record = JobRecord(
        job_id=jobs.new_id(),
        type="forecast_interview",
        spec={
            "interview_id": "interview",
            "revision": 1,
            "db": str(tmp_path / "ledger.db"),
        },
    )
    jobs.write(record)
    return service, jobs, record


def response():
    return {
        "content": json.dumps({
            "questions": [
                {
                    "id": "disconfirm",
                    "section": "challenge",
                    "prompt": "Which observation would disconfirm your leading explanation?",
                    "rationale": "Identify a falsifiable crux",
                    "kind": "text",
                    "required": True,
                }
            ],
            "assumptions": [
                {
                    "id": "measurement",
                    "statement": "The measurement method stays comparable",
                    "uncertainty": "epistemic",
                    "actor": "user",
                }
            ],
            "summary": "Check measurement stability and counterevidence.",
        }),
        "response_model": "controlled-provider",
        "output_tokens": 90,
    }


def test_job_appends_optional_proposals_with_frozen_provenance(work, monkeypatch):
    service, jobs, record = work
    call = Mock(return_value=response())
    monkeypatch.setattr(generation, "run_model", call)
    result = run(record.job_id, store=jobs)
    assert result.status == "done", result.error
    document = service.store.read("interview")["document"]
    assert document["questions"][-1]["required"] is False
    assert document["assumptions"][-1]["actor"] == "agent"
    assert document["answers"] == []
    provenance = document["generations"][0]
    assert provenance["input_revision"] == 1
    assert provenance["input_digest"] == service.store.read("interview", 1)["digest"]
    assert provenance["response_model"] == "controlled-provider"
    assert len(provenance["prompt_digest"]) == 64
    assert service.ledger.list_questions() == []
    # Even a crash after ledger save but before job completion reuses the response.
    recovered = jobs.read(record.job_id)
    recovered.status = "running"
    jobs.write(recovered)
    assert run(record.job_id, store=jobs).status == "done"
    assert service.store.read("interview")["revision"] == 2
    assert call.call_count == 1


def test_user_edit_during_call_is_preserved_and_proposal_is_retained(work, monkeypatch):
    service, jobs, record = work

    def concurrent_edit(*args):
        service.answer(
            "interview",
            expected_revision=1,
            request_id="edit",
            question_id="belief",
            status="answered",
            value=0.6,
        )
        return response()

    monkeypatch.setattr(generation, "run_model", concurrent_edit)
    result = run(record.job_id, store=jobs)
    assert result.status == "error"
    assert "reload" in result.error
    assert "generated_followups" in jobs.read(record.job_id).annotations
    document = service.store.read("interview")["document"]
    assert document["answers"][0]["value"] == 0.6
    assert document["generations"] == []


@pytest.mark.parametrize(
    "bad", ["not JSON", '{"questions": [], "summary": "x", "answers": []}']
)
def test_invalid_model_output_never_changes_interview(work, monkeypatch, bad):
    service, jobs, record = work
    monkeypatch.setattr(
        generation, "run_model", lambda *args: {**response(), "content": bad}
    )
    assert run(record.job_id, store=jobs).status == "error"
    assert service.store.read("interview")["revision"] == 1


def test_cancel_after_call_keeps_proposal_without_applying_it(work, monkeypatch):
    service, jobs, record = work

    def cancel(*args):
        jobs.request_cancel(record.job_id)
        return response()

    monkeypatch.setattr(generation, "run_model", cancel)
    assert run(record.job_id, store=jobs).status == "cancelled"
    assert service.store.read("interview")["revision"] == 1
    assert "generated_followups" in jobs.read(record.job_id).annotations


def test_agent_cannot_rewrite_or_remove_user_assumptions(work):
    service, jobs, record = work
    draft = InterviewDraft.model_validate(service.store.read("interview")["document"])
    draft.assumptions = response_assumptions = [
        InterviewAssumption(
            id="health", statement="Candidate remains healthy", uncertainty="mixed"
        )
    ]
    service.store.save(
        "interview",
        draft,
        expected_revision=1,
        request_id="user-assumption",
        actor="user",
    )
    for changed in (
        [],
        [response_assumptions[0].model_copy(update={"actor": "agent"})],
    ):
        draft.assumptions = changed
        with pytest.raises(ValidationError, match="assumptions"):
            service.store.save(
                "interview",
                draft,
                expected_revision=2,
                request_id="agent-edit",
                actor="agent",
            )


@pytest.mark.parametrize("failure", ["cancel", "deadline"])
def test_owned_worker_is_terminated_and_reaped_on_interrupt(monkeypatch, failure):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("worker", 2), 0]
    spawn = Mock(return_value=process)
    monkeypatch.setattr(generation.subprocess, "Popen", spawn)
    if failure == "cancel":
        cancel = Mock(side_effect=[False, True])
        expected = generation.InterviewGenerationCancelled
    else:
        cancel = lambda: False
        monkeypatch.setattr(generation.time, "monotonic", Mock(side_effect=[0, 10]))
        expected = TimeoutError
    with pytest.raises(expected):
        generation.run_model(
            [], InterviewGenerationOptions(timeout_seconds=5.0), cancel
        )
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert spawn.call_args.kwargs["stdin"] == subprocess.DEVNULL


def test_cancelled_before_spawn_does_not_allocate_process(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(generation.subprocess, "Popen", spawn)
    with pytest.raises(generation.InterviewGenerationCancelled):
        generation.run_model([], InterviewGenerationOptions(), lambda: True)
    spawn.assert_not_called()


def test_enqueue_retry_has_one_durable_identity_even_after_interview_advances(work):
    service, jobs, _ = work
    options = InterviewGenerationOptions()
    first = generation.enqueue_generation(
        service.ledger, "interview", 1, "start", options
    )
    assert jobs.read(first).spec["revision"] == 1
    service.answer(
        "interview",
        expected_revision=1,
        request_id="edit",
        question_id="belief",
        status="unknown",
    )
    assert (
        generation.enqueue_generation(service.ledger, "interview", 1, "start", options)
        == first
    )
    with pytest.raises(ValidationError, match="different settings"):
        generation.enqueue_generation(
            service.ledger,
            "interview",
            1,
            "start",
            InterviewGenerationOptions(max_questions=4),
        )
    with pytest.raises(ValidationError, match="reload"):
        generation.enqueue_generation(
            service.ledger, "interview", 1, "another", options
        )


@pytest.mark.parametrize("mutation", ["repeat", "invent_evidence", "budget"])
def test_unusable_proposals_fail_without_partial_writes(work, monkeypatch, mutation):
    service, jobs, record = work
    reply = response()
    content = json.loads(reply["content"])
    if mutation == "repeat":
        content["questions"][0]["id"] = service.store.read("interview")["document"][
            "questions"
        ][0]["id"]
    elif mutation == "invent_evidence":
        content["assumptions"][0]["evidence_refs"] = ["imaginary-source"]
    else:
        content["questions"] *= 9
    reply["content"] = json.dumps(content)
    monkeypatch.setattr(generation, "run_model", lambda *args: reply)
    assert run(record.job_id, store=jobs).status == "error"
    assert service.store.read("interview")["revision"] == 1


def test_real_worker_cancellation_reaps_child(monkeypatch):
    import sys

    real_spawn = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        process = real_spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(process)
        return process

    monkeypatch.setattr(generation.subprocess, "Popen", spawn)
    try:
        with pytest.raises(generation.InterviewGenerationCancelled):
            generation.run_model(
                [], InterviewGenerationOptions(), lambda: bool(children)
            )
        assert len(children) == 1
        assert children[0].poll() is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_child_profile_aliases_are_consistent_without_mutating_parent(
    tmp_path, monkeypatch
):
    from superforecasting_agent.constants import subprocess_home_env
    import os

    monkeypatch.setenv("HERMES_HOME", "/old-profile")
    monkeypatch.setenv("FORECAST_HOME", "/other-profile")
    before = dict(os.environ)
    env = subprocess_home_env(tmp_path)
    assert (
        env["SUPERFORECASTING_AGENT_HOME"]
        == env["FORECAST_HOME"]
        == env["HERMES_HOME"]
        == str(tmp_path)
    )
    assert dict(os.environ) == before


def test_generation_status_is_scoped_and_preserves_terminal_states(work, monkeypatch):
    service, jobs, _ = work
    service.begin("other")
    assert generation.generation_status(service.ledger, "interview") == {"found": False, "job": None, "request_id": None}
    job_id = generation.enqueue_generation(service.ledger, "interview", 1, "start", InterviewGenerationOptions())
    monkeypatch.setattr(generation, "run_model", lambda *args: response())
    assert run(job_id, store=jobs).status == "done"
    assert generation.generation_status(service.ledger, "interview")["job"]["status"] == "done"
    assert generation.generation_status(service.ledger, "other")["found"] is False
    service.answer("interview", expected_revision=2, request_id="confirm-outcome", question_id="outcome",
                   status="answered", value="binary")
    assert service.store.read("interview")["document"]["questions"][-1]["id"] == "disconfirm"
    jobs.path(job_id).unlink()
    with pytest.raises(ValidationError, match="missing"):
        generation.generation_status(service.ledger, "interview")


def test_rolled_back_generation_enqueue_cannot_spend(work, monkeypatch):
    service, jobs, _ = work
    with service.ledger._connect() as conn:
        conn.execute("CREATE TRIGGER fail_generation_receipt BEFORE INSERT ON forecast_interview_generation_requests BEGIN SELECT RAISE(ABORT, 'injected interruption'); END")
    written = []
    original = JobStore.write

    def capture(self, record):
        written.append(record.job_id)
        return original(self, record)

    monkeypatch.setattr(JobStore, "write", capture)
    with pytest.raises(Exception, match="injected interruption"):
        generation.enqueue_generation(service.ledger, "interview", 1, "lost", InterviewGenerationOptions())
    orphan = written[0]
    call = Mock()
    monkeypatch.setattr(generation, "run_model", call)
    result = run(orphan, store=jobs)
    assert result.status == "error"
    assert "receipt was not committed" in result.error
    call.assert_not_called()
    assert service.store.read("interview")["revision"] == 1
