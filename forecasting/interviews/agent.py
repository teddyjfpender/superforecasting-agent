"""Agent adapter and unattended-update review gate shared with interactive interviews."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from forecasting.interviews.context import read_context
from forecasting.interviews.generation import apply_followups
from forecasting.interviews.review import belief_errors, review_findings
from forecasting.interviews.service import InterviewService
from forecasting.models import ValidationError
from protocol.interview_agent import InterviewAgentRequest
from protocol.interviews import InterviewDraft

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger

REVIEW_QUESTIONS = (
    "new_evidence",
    "reference_class",
    "base_rate",
    "drivers",
    "dependence",
    "epistemic",
    "aleatoric",
    "measurement",
    "counterevidence",
    "crux",
    "triggers",
)


def operate(ledger: ForecastLedger, request: InterviewAgentRequest) -> dict:
    service = InterviewService(ledger)
    if request.operation == "begin":
        if not request.question_id:
            raise ValidationError("agent reviews require an existing question_id")
        result = service.begin(request.interview_id, question_id=request.question_id)
    elif request.operation == "read":
        result = service.store.read(request.interview_id, request.revision)
    else:
        if request.revision is None or request.request_id is None:
            raise ValidationError(
                "interview writes require revision and stable request_id"
            )
        record = service.store.read(request.interview_id, request.revision)
        if request.operation == "answer":
            if request.answer is None:
                raise ValidationError("answer is required")
            if not set(request.answer.evidence_refs) <= set(
                record["document"]["evidence_refs"]
            ):
                raise ValidationError(
                    "answer cites evidence outside the frozen interview"
                )
            result = service.answer(
                request.interview_id,
                expected_revision=request.revision,
                request_id=request.request_id,
                actor="agent",
                **request.answer.model_dump(),
            )
        elif request.operation == "propose":
            if request.followups is None:
                raise ValidationError("followups are required")
            # This is the calling agent's proposal, not a second LLM call. No
            # synthetic provider receipt or user answer is manufactured.
            result = apply_followups(
                ledger,
                record,
                request.followups,
                None,
                16,
                request_id=request.request_id,
            )
        else:
            if request.scenario is None:
                raise ValidationError("scenario is required")
            result = service.save_scenario(
                request.interview_id,
                expected_revision=request.revision,
                request_id=request.request_id,
                scenario=request.scenario,
                actor="agent",
            )
    return {
        "interview": result,
        "review_questions": list(REVIEW_QUESTIONS),
        "elicitation_gaps": review_findings(
            InterviewDraft.model_validate(result["document"])
        ),
        "guidance": "Answer as the agent using frozen evidence; record Unknown when unsupported. Prior user beliefs are historical. Do not impersonate the user or silently change probabilities.",
    }


def review_for_update(
    ledger: ForecastLedger,
    question_id: str,
    interview_id: str | None,
    evidence_refs: list[str],
) -> dict:
    if not interview_id:
        raise ValidationError(
            "unattended updates require a structured interview: call forecast_ledger action=interview with operation=begin after collecting evidence, answer the returned review_questions as the agent, then pass interview_id to update_forecast"
        )
    service = InterviewService(ledger)
    record = service.store.read(interview_id)
    draft = InterviewDraft.model_validate(record["document"])
    errors = belief_errors(draft)
    if errors:
        raise ValidationError(" ".join(errors))
    question = ledger.get_question(question_id)
    if (
        draft.question_id != question_id
        or draft.baseline_forecast_id != question.current_forecast_id
        or draft.status == "cancelled"
        or not draft.context_digest
    ):
        raise ValidationError(
            "review does not match the current question/baseline; start a new interview"
        )
    context = read_context(ledger, interview_id, draft.context_digest)
    current = asdict(question)
    if any(
        context["question"].get(key) != current.get(key)
        for key in (
            "resolution_criteria",
            "resolution_source",
            "close_time",
            "resolution_time",
            "outcome_space",
            "status",
        )
    ):
        raise ValidationError("question contract changed; start a new review")
    if not set(evidence_refs) <= set(draft.evidence_refs):
        raise ValidationError(
            "new evidence was collected after the review; start a fresh interview"
        )
    answers = {item.question_id: item for item in draft.answers}
    missing = [
        key
        for key in REVIEW_QUESTIONS
        if key not in answers
        or answers[key].actor != "agent"
        or answers[key].status == "skipped"
    ]
    if missing:
        raise ValidationError(
            "complete the agent review (answer or explicitly mark Unknown): "
            + ", ".join(missing)
        )
    return {
        "interview_id": interview_id,
        "revision": record["revision"],
        "digest": record["digest"],
        "elicitation_gaps": review_findings(draft),
        "review_complete_is_not_evidence_of_quality": True,
        "unresolved_questions": [
            key for key in REVIEW_QUESTIONS if answers[key].status == "unknown"
        ],
        "unanswered_optional_questions": [
            item.id
            for item in draft.questions
            if item.id not in REVIEW_QUESTIONS
            and (item.id not in answers or answers[item.id].status != "answered")
        ],
        "assumptions": [item.model_dump() for item in draft.assumptions],
        "scenarios": [item.model_dump() for item in draft.scenarios],
    }
