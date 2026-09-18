"""Adaptive questionnaire generation on the shared durable/cancellable job runtime."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from forecasting.jobs.context import JobContext
from forecasting.jobs.policy import ActionClass
from forecasting.jobs.types import JobType, register
from forecasting.models import utc_now_iso
from protocol.interviews import (
    InterviewFollowups,
    InterviewGenerationOptions,
    InterviewGenerationRecord,
    InterviewModel,
)


class InterviewJobSpec(InterviewModel):
    interview_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    options: InterviewGenerationOptions = Field(
        default_factory=InterviewGenerationOptions
    )
    db: str | None = None


def execute(raw: dict[str, Any], ctx: JobContext) -> dict:
    from forecasting.interviews.generation import (
        InterviewGenerationCancelled,
        apply_followups,
        build_messages,
        prompt_digest,
        run_model,
    )
    from forecasting.interviews.store import InterviewStore
    from forecasting.ledger import ForecastLedger

    spec = InterviewJobSpec.model_validate(raw)
    if ctx.should_cancel():
        return {"cancelled": True}
    ledger = ForecastLedger(spec.db)
    store = InterviewStore(ledger)
    record = store.read(spec.interview_id, spec.revision)
    latest = store.read(spec.interview_id)
    cached = ctx.record.annotations.get("generated_followups")
    # A retry after saving may already have advanced the draft by exactly this job.
    if not cached and latest["revision"] != spec.revision:
        raise ValueError(
            "interview changed; start generation from its current revision"
        )
    if cached is None:
        with ledger._connect() as conn:
            committed = conn.execute(
                "SELECT 1 FROM forecast_interview_commits WHERE interview_id = ?",
                (spec.interview_id,),
            ).fetchone()
        if committed or latest["document"]["status"] == "cancelled":
            raise ValueError("closed interviews cannot generate questions")
        ctx.authorize(
            ActionClass.LLM_SPEND,
            f"one interview call, at most {spec.options.max_tokens} output tokens",
        )
    ctx.authorize(
        ActionClass.LEDGER_WRITES,
        "append optional questions and proposed assumptions only",
    )
    try:
        if cached is None:
            messages = build_messages(ledger, record, spec.options)
            ctx.progress(phase="generating", done=0, total=1, current=spec.interview_id)
            response = run_model(messages, spec.options, ctx.should_cancel)
            output = InterviewFollowups.model_validate_json(response["content"])
            provenance = InterviewGenerationRecord(
                job_id=ctx.record.job_id,
                input_revision=spec.revision,
                input_digest=record["digest"],
                prompt_digest=prompt_digest(messages),
                response_model=response["response_model"],
                requested_provider=spec.options.provider,
                max_tokens=spec.options.max_tokens,
                output_tokens=response["output_tokens"],
                created_at=utc_now_iso(),
                summary=output.summary,
            )
            cached = {
                "output": output.model_dump(),
                "provenance": provenance.model_dump(),
            }
            # Persist validated output before its ledger write. A restart reuses it
            # instead of paying again or applying different content with the same ID.
            ctx.annotate("generated_followups", cached)
        if ctx.should_cancel():
            return {"cancelled": True, "interview_id": spec.interview_id}
        result = apply_followups(
            ledger,
            record,
            InterviewFollowups.model_validate(cached["output"]),
            InterviewGenerationRecord.model_validate(cached["provenance"]),
            spec.options.max_questions,
        )
        ctx.progress(phase="done", done=1, total=1, current=spec.interview_id)
        return {
            "interview_id": spec.interview_id,
            "revision": result["revision"],
            "questions_added": len(cached["output"]["questions"]),
        }
    except InterviewGenerationCancelled:
        return {"cancelled": True, "interview_id": spec.interview_id}


def validate_spec(raw: dict[str, Any]) -> None:
    InterviewJobSpec.model_validate(raw)


register(
    JobType(
        name="forecast_interview",
        execute=execute,
        spend_class="llm",
        validate_spec=validate_spec,
    )
)
