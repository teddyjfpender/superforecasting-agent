"""Resolution use case; product adapters do not own settlement policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as InputError

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import Resolution, ScoreRecord, ValidationError


class ResolveForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question_id: str
    outcome: Any
    resolution_source: str | None = None
    resolution_source_snapshot_ref: str | None = None
    resolver_type: Literal["manual", "source_adapter", "scheduled_check"] = "manual"
    resolution_status: Literal["proposed", "confirmed", "disputed", "corrected"] = (
        "confirmed"
    )
    criteria_satisfied: bool = True
    confidence: float | None = None
    confirmed_by: str | None = None
    resolver_notes: str | None = None
    correction_ref: str | None = None
    trusted_policy_id: str | None = None
    scoreable: bool = True
    auto_score: bool = True


@dataclass(frozen=True)
class ResolutionResult:
    resolution: Resolution
    score: ScoreRecord | None
    retrospective: dict[str, Any] | None


def resolve_forecast(
    ledger: ForecastLedger, values: Mapping[str, Any]
) -> ResolutionResult:
    """Validate one request and let the ledger atomically settle/finalize it.

    Outcome semantics, source binding, censoring and retry identity remain ledger
    invariants. Optional narrative failure never rolls back durable settlement.
    """
    try:
        request = ResolveForecastRequest.model_validate(dict(values))
    except InputError as exc:
        raise ValidationError(str(exc)) from exc
    with allow_ledger_writes(reason="forecast_application.resolve"):
        resolution = ledger.resolve_question(**request.model_dump())
        finalized = (
            resolution.resolution_status == "confirmed"
            and resolution.criteria_satisfied
        )
        score = (
            ledger.get_current_score(request.question_id)
            if (finalized and request.auto_score and request.scoreable)
            else None
        )
        retrospective = None
        if finalized:
            from forecasting.writeup import write_retrospective

            try:
                retrospective = write_retrospective(
                    ledger, request.question_id, score=score
                )
            except Exception:
                # Retrying the durable finalization task is independent of prose.
                pass
    return ResolutionResult(resolution, score, retrospective)
