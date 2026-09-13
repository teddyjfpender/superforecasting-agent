"""Shared thesis and factor summaries for tools and product adapters."""

from __future__ import annotations

from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


def _validate_limit(limit: int | None) -> None:
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValidationError("summary limit must be a nonnegative integer or null")


def _top_event_sensitivities(
    event_detail: dict[str, Any] | None, k: int = 5
) -> list[dict[str, Any]] | None:
    """The k members whose ±2pp move swings P(event) most (by |Δ|), or None."""

    if not event_detail:
        return None
    rows = event_detail.get("sensitivities") or []
    return sorted(rows, key=lambda s: -abs(s.get("delta_p_event") or 0.0))[:k]


def build_thesis_summary(
    *, ledger: ForecastLedger | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """A light per-thesis summary (health/score/delta/coverage) for product consumers.

    Uncapped by default so it finds every thesis regardless of creation order;
    factors (aggregation='factor') are summarized separately by build_factor_summary.
    """

    _validate_limit(limit)
    ledger = ledger or ForecastLedger()
    out: list[dict[str, Any]] = []
    for question in ledger.list_questions(status="active", limit=limit):
        if not ledger.is_thesis(question) or ledger.is_factor(question):
            continue
        snapshots = ledger.list_snapshots(question.id)
        current = snapshots[-1] if snapshots else None
        payload = current.probability_or_distribution if current else {}
        payload = payload if isinstance(payload, dict) else {}
        previous = (
            snapshots[-2].probability_or_distribution if len(snapshots) >= 2 else None
        )
        previous_health = previous.get("health") if isinstance(previous, dict) else None
        health = payload.get("health")
        # A thesis configured as a JOINT THRESHOLD EVENT reports P(event) as its
        # headline (the question it actually asks); the mean-index health/score
        # stay as diagnostics. Fall back to health when no event is configured.
        # Only the numeric event_probability rides in the payload; the structured
        # detail (spec / count distribution / sensitivities) is in the metadata.
        event_probability = payload.get("event_probability")
        prev_event = (
            previous.get("event_probability") if isinstance(previous, dict) else None
        )
        headline = event_probability if event_probability is not None else health
        prev_headline = prev_event if event_probability is not None else previous_health
        cur_meta = current.metadata if current else {}
        cur_meta = cur_meta if isinstance(cur_meta, dict) else {}
        event_detail = (
            cur_meta.get("event") if isinstance(cur_meta.get("event"), dict) else None
        )
        out.append({
            "id": question.id,
            "title": question.title,
            "domain": question.domain,
            "health_probability": health,
            "health_display": f"{health:.0%}" if health is not None else "-",
            "thesis_score": payload.get("thesis_score"),
            "event_probability": event_probability,
            "event_band": (
                {
                    "p10": payload.get("event_p10"),
                    "p50": payload.get("event_p50"),
                    "p90": payload.get("event_p90"),
                }
                if payload.get("event_p10") is not None
                and payload.get("event_p90") is not None
                else None
            ),
            "event": event_detail.get("event") if event_detail else None,
            "count_distribution": event_detail.get("count_distribution")
            if event_detail
            else None,
            "top_sensitivities": _top_event_sensitivities(event_detail),
            "headline_probability": headline,
            "headline_display": f"{headline:.0%}" if headline is not None else "-",
            "coverage": payload.get("coverage"),
            "n_eff": payload.get("n_eff"),
            "delta": (headline - prev_headline)
            if (headline is not None and prev_headline is not None)
            else None,
            "member_count": len(ledger.list_thesis_members(question.id)),
            "as_of": current.as_of if current else None,
            "status": "withheld" if headline is None else "ok",
        })
    return out


def build_factor_summary(
    *, ledger: ForecastLedger | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """A light per-factor summary (return/vol/downside/delta) for product consumers."""

    _validate_limit(limit)
    ledger = ledger or ForecastLedger()
    out: list[dict[str, Any]] = []
    for question in ledger.list_questions(status="active", limit=limit):
        if not ledger.is_factor(question):
            continue
        snapshots = ledger.list_snapshots(question.id)
        current = snapshots[-1] if snapshots else None
        payload = current.probability_or_distribution if current else {}
        payload = payload if isinstance(payload, dict) else {}
        previous = (
            snapshots[-2].probability_or_distribution if len(snapshots) >= 2 else None
        )
        previous_mean = (
            previous.get("factor_mean") if isinstance(previous, dict) else None
        )
        mean = payload.get("factor_mean")
        out.append({
            "id": question.id,
            "title": question.title,
            "domain": question.domain,
            "units": question.outcome_space.units,
            "mean": mean,
            "sd": payload.get("factor_sd"),
            "q05": payload.get("q05"),
            "q95": payload.get("q95"),
            "downside": payload.get("downside"),
            "cvar": payload.get("cvar"),
            "coverage": payload.get("coverage"),
            "delta": (mean - previous_mean)
            if (mean is not None and previous_mean is not None)
            else None,
            "member_count": len(ledger.list_thesis_members(question.id)),
            "as_of": current.as_of if current else None,
            "status": "withheld" if mean is None else "ok",
        })
    return out
