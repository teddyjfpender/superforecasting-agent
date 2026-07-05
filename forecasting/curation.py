"""Question curation — fuel for the calibration loop.

The binding constraint on every downstream capability is the supply of resolved,
calibration-eligible CONTESTED binaries (the audit's finding 2: the measurement
loop learns from ~20 lifetime points, 15 of them trivial weather). This module
turns the prediction-market data plane into a standing pool of candidate
questions: it filters live markets down to SHORT-HORIZON, CONTESTED, LIQUID
BINARIES — exactly the decision-relevant stratum the shrinkage activation gate
and the learning loop are starved of — and pre-drafts a scoreable resolution
criterion from the market.

Deliberately PURE + write-free: it proposes, it never creates. The caller (the
``forecast curate`` CLI verb / the ``curate_questions`` tool action) surfaces the
proposals for the operator to confirm PER QUESTION; nothing here touches the
ledger or the network. The market fetch happens in the caller and is passed in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forecasting.models import timestamp_to_datetime, utc_now_iso

# The contested band: a market the crowd is genuinely unsure about (|p−0.5|
# small) is where a fresh-information edge can actually show up. Near-certain
# markets (weather-like) teach the loop nothing.
DEFAULT_PRICE_MIN = 0.15
DEFAULT_PRICE_MAX = 0.85
# Short horizon → the resolution flows back into the loop fast (the whole point).
DEFAULT_MAX_HORIZON_DAYS = 45
# Liquidity floor: a price nobody is trading is not a real crowd estimate. Volume
# units differ by venue, so this is an ADVISORY floor; the hard gate is that the
# outcome carries a live quote (``liquid``).
DEFAULT_MIN_VOLUME = 1000.0


@dataclass(frozen=True)
class CurationFilters:
    price_min: float = DEFAULT_PRICE_MIN
    price_max: float = DEFAULT_PRICE_MAX
    max_horizon_days: float = DEFAULT_MAX_HORIZON_DAYS
    min_volume: float = DEFAULT_MIN_VOLUME
    # Live markets group binary sub-questions under multi-outcome EVENTS ("which
    # candidate wins?"), so a native single-market binary is rare. Each de-vigged
    # outcome of a mutually-exclusive event is itself a contested yes/no ("will
    # outcome X occur?") — mine those too, or the pool comes back empty.
    include_event_outcomes: bool = True


@dataclass(frozen=True)
class CuratedCandidate:
    """A proposed calibration question drafted from a live market. NOT created —
    the operator confirms per question."""

    title: str
    resolution_criteria: str
    market_probability: float
    close_time: str | None
    horizon_days: float | None
    venue: str
    event_id: str
    market_id: str | None
    url: str | None
    volume: float | None
    domain: str = "prediction_markets"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "resolution_criteria": self.resolution_criteria,
            "market_probability": round(self.market_probability, 4),
            "close_time": self.close_time,
            "horizon_days": round(self.horizon_days, 2) if self.horizon_days is not None else None,
            "venue": self.venue,
            "event_id": self.event_id,
            "market_id": self.market_id,
            "url": self.url,
            "volume": round(self.volume, 2) if self.volume is not None else None,
            "domain": self.domain,
        }


@dataclass
class CurationReport:
    candidates: list[CuratedCandidate] = field(default_factory=list)
    screened: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": len(self.candidates),
            "screened": self.screened,
            "rejected": self.rejected,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _horizon_days(close_time: str | None, now: str) -> float | None:
    """Days from ``now`` to ``close_time`` (None when unparseable)."""
    if not close_time:
        return None
    close_dt = timestamp_to_datetime(close_time)
    now_dt = timestamp_to_datetime(now)
    if close_dt is None or now_dt is None:
        return None
    return (close_dt - now_dt).total_seconds() / 86400.0


def _market_rows(event: Any, distribution: Any, *, include_event_outcomes: bool) -> list[dict[str, Any]]:
    """The candidate binary yes/no rows a market pair offers.

    A native binary distribution yields ONE row (the event question). A
    multi-outcome event yields one row per outcome ("will outcome X occur?"),
    each a legitimate de-vigged binary sub-question — but only when
    ``include_event_outcomes`` is set (else non-binary events are skipped)."""
    outcomes = list(getattr(distribution, "outcomes", ()) or ())
    title = str(getattr(distribution, "title", None) or getattr(event, "title", "") or "").strip()
    if getattr(distribution, "binary", False):
        if len(outcomes) != 1:
            return []
        outcome = outcomes[0]
        return [
            {
                "title": title,
                "label": getattr(outcome, "label", None),
                "prob": float(getattr(outcome, "prob", 0.0) or 0.0),
                "market_id": getattr(outcome, "market_id", None),
                "liquid": bool(getattr(outcome, "liquid", False)),
                "volume": getattr(outcome, "volume", None),
                "from_event_outcome": False,
            }
        ]
    if not include_event_outcomes:
        return []
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        label = str(getattr(outcome, "label", "") or "").strip()
        question = f"In {title.rstrip('?')}, will the outcome be {label}?" if title and label else title
        rows.append(
            {
                "title": question,
                "label": label or None,
                "prob": float(getattr(outcome, "prob", 0.0) or 0.0),
                "market_id": getattr(outcome, "market_id", None),
                "liquid": bool(getattr(outcome, "liquid", False)),
                "volume": getattr(outcome, "volume", None),
                "from_event_outcome": True,
            }
        )
    return rows


def draft_resolution_criteria(
    *, title: str, venue: str, url: str | None, close_time: str | None, probability: float
) -> str:
    """A scoreable YES/NO criterion drafted from the market: what settles it,
    where, and when, plus the market-implied prior at curation time. Kept to a
    single sentence, ≥5 words, no em-dashes (desk style)."""
    where = f"the {venue} market" + (f" ({url})" if url else "")
    when = f" at its close on {close_time}" if close_time else " at market settlement"
    prior = f" Market-implied probability at curation: {probability * 100:.0f} percent."
    return (
        f"Resolves YES if {title.rstrip('?')}, as settled by {where}{when}; "
        f"otherwise NO.{prior}"
    ).strip()


def curate_market_candidates(
    pairs: Any,
    *,
    filters: CurationFilters | None = None,
    now: str | None = None,
) -> CurationReport:
    """Screen ``(event, distribution)`` pairs down to short-horizon contested
    liquid binaries and draft a candidate question for each survivor.

    PURE: no network, no ledger. ``pairs`` is whatever the caller fetched (e.g.
    ``PMService.list_events`` output). Returns a :class:`CurationReport` with the
    survivors + a per-reason rejection tally so the operator can see WHY the pool
    is the size it is."""
    filters = filters or CurationFilters()
    now = now or utc_now_iso()
    report = CurationReport()
    rejected: dict[str, int] = {
        "not_binary": 0,
        "no_live_quote": 0,
        "not_contested": 0,
        "no_close_time": 0,
        "horizon_too_long": 0,
        "already_closed": 0,
        "illiquid": 0,
    }
    for pair in pairs:
        report.screened += 1
        event, distribution = (pair[0], pair[1]) if isinstance(pair, (tuple, list)) else (pair, pair)
        rows = _market_rows(event, distribution, include_event_outcomes=filters.include_event_outcomes)
        if not rows:
            rejected["not_binary"] += 1
            continue
        close_time = getattr(distribution, "close_time", None) or getattr(event, "close_time", None)
        horizon = _horizon_days(close_time, now)
        url = getattr(distribution, "url", None) or getattr(event, "url", None)
        venue = str(getattr(distribution, "venue", None) or getattr(event, "venue", "") or "")
        event_id = str(getattr(event, "event_id", None) or getattr(distribution, "event_id", "") or "")
        for row in rows:
            if not row["liquid"]:
                rejected["no_live_quote"] += 1
                continue
            probability = row["prob"]
            if not (filters.price_min <= probability <= filters.price_max):
                rejected["not_contested"] += 1
                continue
            if close_time is None or horizon is None:
                rejected["no_close_time"] += 1
                continue
            if horizon <= 0:
                rejected["already_closed"] += 1
                continue
            if horizon > filters.max_horizon_days:
                rejected["horizon_too_long"] += 1
                continue
            volume = row["volume"]
            if volume is None and row["from_event_outcome"] is False:
                volume = getattr(distribution, "total_volume", None)
            if volume is not None and float(volume) < filters.min_volume:
                rejected["illiquid"] += 1
                continue
            title = str(row["title"] or "").strip()
            report.candidates.append(
                CuratedCandidate(
                    title=title,
                    resolution_criteria=draft_resolution_criteria(
                        title=title, venue=venue, url=url, close_time=close_time, probability=probability
                    ),
                    market_probability=probability,
                    close_time=close_time,
                    horizon_days=horizon,
                    venue=venue,
                    event_id=event_id,
                    market_id=row["market_id"],
                    url=url,
                    volume=float(volume) if volume is not None else None,
                )
            )
    report.rejected = {reason: count for reason, count in rejected.items() if count}
    # Most-contested first (closest to 50/50), then soonest to resolve.
    report.candidates.sort(key=lambda c: (abs(c.market_probability - 0.5), c.horizon_days or 1e9))
    return report
