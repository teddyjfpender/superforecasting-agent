"""Score a forecast and optionally its imported baselines through one use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as InputError

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import ScoreRecord, ValidationError


class ScoreForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question_id: str
    force: bool = False
    baselines: bool = False


@dataclass(frozen=True)
class ScoringResult:
    score: ScoreRecord
    baselines: list[dict[str, Any]] | None


def score_forecast(ledger: ForecastLedger, values: Mapping[str, Any]) -> ScoringResult:
    try:
        request = ScoreForecastRequest.model_validate(dict(values))
    except InputError as exc:
        raise ValidationError(str(exc)) from exc
    # Settlement semantics and score lineage remain authoritative in the ledger.
    with allow_ledger_writes(reason="forecast_application.score"):
        score = ledger.score_question(request.question_id, force=request.force)
        baselines = (
            ledger.score_baseline_comparisons(request.question_id, force=request.force)
            if request.baselines
            else None
        )
    return ScoringResult(score, baselines)
