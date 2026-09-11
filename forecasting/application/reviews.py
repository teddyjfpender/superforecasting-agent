"""Review selection and learned-error merging shared by CLI and TUI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as InputError

from forecasting.learning import (
    is_learned_error_review_reason,
    learned_error_profile_id,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastingError, ValidationError


class ReviewForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stale: bool = False
    last_days: int = 7
    domain: str | None = None
    topic: str | None = None
    horizon: str | None = None
    confidence_below: float | None = None
    confidence_above: float | None = None
    large_delta_threshold: float | None = None
    now: str | None = None


def review_forecasts(ledger: ForecastLedger, **values: Any) -> list[dict[str, Any]]:
    """Select review work without presentation or command dispatch side effects."""
    try:
        request = ReviewForecastRequest.model_validate(values)
    except InputError as exc:
        raise ValidationError(str(exc)) from exc
    rows = ledger.review_questions(**request.model_dump())
    _merge_learned_error_reviews(
        rows,
        ledger=ledger,
        domain=request.domain,
        topic=request.topic,
        horizon=request.horizon,
        confidence_below=request.confidence_below,
        confidence_above=request.confidence_above,
    )
    return rows


def _active_learned_error_review_rows(
    ledger: ForecastLedger,
    *,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for alert in ledger.list_alerts(unresolved_only=True):
        if alert.scope_type != "question" or not is_learned_error_review_reason(
            alert.reason
        ):
            continue
        key = (alert.scope_ref, alert.reason)
        if key in seen:
            continue
        seen.add(key)
        try:
            question = ledger.get_question(alert.scope_ref)
        except ForecastingError:
            continue
        if question.status != "active":
            continue
        snapshot = ledger.get_current_snapshot(question.id)
        if not _review_alert_matches_filters(
            ledger,
            question=question,
            snapshot=snapshot,
            domain=domain,
            topic=topic,
            horizon=horizon,
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        ):
            continue
        rows.append({
            "alert": alert,
            "question": question,
            "current_snapshot": snapshot,
            "profile_id": learned_error_profile_id(alert.reason),
        })
        if limit is not None and len(rows) >= limit:
            break
    return rows


def _review_alert_matches_filters(
    ledger: ForecastLedger,
    *,
    question: Any,
    snapshot: Any,
    domain: str | None,
    topic: str | None,
    horizon: str | None,
    confidence_below: float | None,
    confidence_above: float | None,
) -> bool:
    if domain and question.domain != domain:
        return False
    if topic and topic not in question.topics:
        return False
    if horizon and (
        snapshot is None
        or not ledger._horizon_matches(snapshot.forecast_horizon_days, horizon)
    ):
        return False
    if confidence_below is not None or confidence_above is not None:
        if snapshot is None or snapshot.confidence is None:
            return False
        if confidence_below is not None and snapshot.confidence >= confidence_below:
            return False
        if confidence_above is not None and snapshot.confidence <= confidence_above:
            return False
    return True


def _merge_learned_error_reviews(
    rows: list[dict[str, Any]],
    *,
    ledger: ForecastLedger,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
) -> None:
    rows_by_id = {row["question"].id: row for row in rows}
    for learned_row in _active_learned_error_review_rows(
        ledger,
        domain=domain,
        topic=topic,
        horizon=horizon,
        confidence_below=confidence_below,
        confidence_above=confidence_above,
    ):
        question = learned_row["question"]
        alert = learned_row["alert"]
        existing = rows_by_id.get(question.id)
        if existing is not None:
            reasons = existing.setdefault("reasons", [])
            if alert.reason not in reasons:
                reasons.append(alert.reason)
            existing["priority"] = min(int(existing.get("priority") or 9), 4)
            continue
        row = {
            "question": question,
            "current_snapshot": learned_row["current_snapshot"],
            "reasons": [alert.reason],
            "priority": 4,
        }
        rows.append(row)
        rows_by_id[question.id] = row
    _sort_review_rows(rows)


def _sort_review_rows(rows: list[dict[str, Any]]) -> None:
    rows.sort(
        key=lambda row: (
            int(row.get("priority") or 9),
            row["question"].close_time
            or row["question"].resolution_time
            or "9999-12-31T00:00:00Z",
            row["question"].title.lower(),
        )
    )
