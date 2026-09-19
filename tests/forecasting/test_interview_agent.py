"""Scheduled agents share durable elicitation but never acquire user authorship."""

import json

import pytest

from forecasting.interviews.agent import REVIEW_QUESTIONS, review_for_update
from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import ValidationError
from tools.forecasting_tool import FORECAST_LEDGER_SCHEMA, forecast_ledger_tool


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Will the event occur?",
            resolution_criteria="Official confirmation by December 2030.",
        )
    return ledger, question


def call(ledger, **request):
    return json.loads(
        forecast_ledger_tool(
            {
                "db": str(ledger.db_path),
                "action": "interview",
                "interview_request": request,
            },
            main_runtime={"forecast_commit_policy": "proposal_only"},
        )
    )


def test_agent_review_uses_same_store_and_cannot_impersonate_user(desk):
    ledger, question = desk
    result = call(
        ledger, operation="begin", interview_id="scheduled", question_id=question.id
    )
    assert result["success"]
    bad = call(
        ledger,
        operation="answer",
        interview_id="scheduled",
        revision=1,
        request_id="spoof",
        answer={
            "question_id": "drivers",
            "status": "answered",
            "value": "Driver",
            "actor": "user",
        },
    )
    assert not bad["success"]
    for key in REVIEW_QUESTIONS:
        result = call(
            ledger,
            operation="answer",
            interview_id="scheduled",
            revision=result["interview"]["revision"],
            request_id=key,
            answer={"question_id": key, "status": "unknown", "note": "Needs research"},
        )
        assert result["success"], result
    stamp = review_for_update(ledger, question.id, "scheduled", [])
    assert stamp["unresolved_questions"] == list(REVIEW_QUESTIONS)
    draft = InterviewService(ledger).store.read("scheduled")["document"]
    assert all(item["actor"] == "agent" for item in draft["answers"])
    assert ledger.list_snapshots(question.id) == []


def test_unattended_update_refuses_missing_review_before_spend_or_write(desk):
    ledger, question = desk
    result = json.loads(
        forecast_ledger_tool(
            {
                "db": str(ledger.db_path),
                "action": "update_forecast",
                "question_id": question.id,
                "probability": 0.6,
                "rationale": "Proposal",
            },
            main_runtime={"forecast_commit_policy": "proposal_only"},
        )
    )
    assert not result["success"]
    assert "structured interview" in result["error"]
    assert ledger.list_snapshots(question.id) == []


def test_adaptive_agent_proposals_are_optional_and_agent_attributed(desk):
    ledger, question = desk
    call(ledger, operation="begin", interview_id="scheduled", question_id=question.id)
    request = dict(
        operation="propose",
        interview_id="scheduled",
        revision=1,
        request_id="followup",
        followups={
            "summary": "Probe measurement",
            "questions": [
                {
                    "id": "publication",
                    "section": "uncertainty",
                    "prompt": "Which reporting change matters?",
                    "rationale": "Check measurement stability",
                    "kind": "text",
                    "required": True,
                }
            ],
            "assumptions": [
                {
                    "id": "stable",
                    "statement": "Reporting remains comparable",
                    "actor": "user",
                }
            ],
        },
    )
    result = call(ledger, **request)
    assert result["success"], result
    assert result == call(ledger, **request)
    draft = result["interview"]["document"]
    assert draft["questions"][-1]["required"] is False
    assert draft["assumptions"][-1]["actor"] == "agent"
    assert draft["generations"] == []
    failed = call(
        ledger,
        operation="answer",
        interview_id="scheduled",
        revision=2,
        request_id="invent",
        answer={
            "question_id": "publication",
            "status": "answered",
            "value": "Unsupported",
            "evidence_refs": ["invented"],
        },
    )
    assert not failed["success"]
    assert "frozen interview" in failed["error"]


def test_user_beliefs_survive_agent_tool_calls(desk):
    ledger, question = desk
    service = InterviewService(ledger)
    service.begin("user", question_id=question.id)
    record = service.answer(
        "user",
        expected_revision=1,
        request_id="belief",
        question_id="belief",
        status="answered",
        value=0.3,
    )
    denied = call(
        ledger,
        operation="answer",
        interview_id="user",
        revision=record["revision"],
        request_id="replace",
        answer={"question_id": "belief", "status": "answered", "value": 0.8},
    )
    assert not denied["success"]
    assert service.store.read("user") == record
    with pytest.raises(ValidationError, match="complete the agent review"):
        review_for_update(ledger, question.id, "user", [])


def test_tool_contract_advertises_only_agent_operations():
    schema = FORECAST_LEDGER_SCHEMA["parameters"]
    assert "interview" in schema["properties"]["action"]["enum"]
    assert schema["properties"]["interview_request"]["properties"]["operation"][
        "enum"
    ] == ["begin", "read", "answer", "propose", "scenario"]
    assert "actor" not in schema["$defs"]["InterviewAgentAnswer"]["properties"]


@pytest.mark.parametrize("field,value", [("title", "A different event"), ("source", "A different authority"), ("criteria", "A different settlement condition")])
def test_contract_edits_are_rejected_consistently_before_agent_or_model_work(desk, field, value):
    from forecasting.interviews.evaluation import prepare
    from protocol.scenarios import ScenarioEvaluationOptions

    ledger, question = desk
    service = InterviewService(ledger)
    service.begin("changed-contract", question_id=question.id)
    record = service.answer("changed-contract", expected_revision=1, request_id="edit", question_id=field, status="answered", value=value)
    preview = service.preview("changed-contract", record["revision"])
    assert not preview["committable"]
    assert any(f"({field})" in issue for issue in preview["unanswered"])
    with pytest.raises(ValidationError, match="changed resolution contract"):
        review_for_update(ledger, question.id, "changed-contract", [])
    with pytest.raises(ValidationError, match="changed resolution contract"):
        prepare(ledger, "changed-contract", record["revision"], ScenarioEvaluationOptions(scenario_ids=["unused"]))
