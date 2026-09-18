"""Durable scenario evaluation; never changes the interview or active forecast."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from forecasting.jobs.context import JobContext
from forecasting.jobs.types import JobType, register
from protocol.interviews import InterviewModel
from protocol.scenarios import ScenarioEvaluationOptions


class ScenarioJobSpec(InterviewModel):
    interview_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    options: ScenarioEvaluationOptions
    db: str | None = None
    request_id: str | None = None


def execute(raw: dict[str, Any], ctx: JobContext) -> dict:
    from forecasting.interviews.evaluation import execute_plan, prepare
    from forecasting.interviews.store import InterviewStore
    from forecasting.ledger import ForecastLedger

    spec = ScenarioJobSpec.model_validate(raw)
    if ctx.should_cancel():
        return {"cancelled": True}
    ledger = ForecastLedger(spec.db)
    if spec.request_id:
        with ledger._connect() as conn:
            receipt = conn.execute(
                "SELECT job_id FROM forecast_interview_evaluation_requests WHERE interview_id = ? AND request_id = ?",
                (spec.interview_id, spec.request_id),
            ).fetchone()
        if receipt is None or receipt["job_id"] != ctx.record.job_id:
            raise ValueError(
                "scenario start receipt was not committed; no model calls made"
            )
    plan = ctx.record.annotations.get("scenario_plan")
    if plan is None:
        if InterviewStore(ledger).read(spec.interview_id)["revision"] != spec.revision:
            raise ValueError("interview changed; reload before evaluating")
        plan = prepare(ledger, spec.interview_id, spec.revision, spec.options)
        # Freeze before approval or spending. Recovery must never reconstruct
        # context from a newer draft or repeat a completed response.
        ctx.annotate("scenario_plan", plan)
    if (plan["interview_id"], plan["revision"], plan["options"]) != (
        spec.interview_id,
        spec.revision,
        spec.options.model_dump(),
    ):
        raise ValueError("saved scenario plan does not match the job request")
    return execute_plan(plan, ctx)


def validate_spec(raw: dict[str, Any]) -> None:
    ScenarioJobSpec.model_validate(raw)


register(
    JobType(
        name="forecast_scenarios",
        execute=execute,
        spend_class="llm",
        validate_spec=validate_spec,
    )
)
