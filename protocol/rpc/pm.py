"""Wire models for the ``pm.*`` prediction-market RPCs.

Transcribed faithfully from the SERVER's actual emission — ``forecasting/pm/
model.py`` ``to_dict`` (events, markets, books, history, distributions) and
``forecasting/pm/stream.py`` ``StreamStart.to_dict`` / ``PMStreamHub.stop`` — and
cross-checked against the TUI DTOs in ``ui-tui/src/lib/pmData.ts``. Where the two
disagreed the server won; the divergences are noted inline.

Request models mirror the handlers' actual acceptance: required fields are
required (so a missing one is rejected with the field named); leniently-coerced
numeric fields keep the handlers' "bad value -> default" behaviour via
``before`` validators so no currently-accepted payload is newly rejected.
"""

from __future__ import annotations

from typing import Any

from pydantic import field_validator

from protocol.types import (
    EventId,
    IsoInstant,
    MarketId,
    Probability,
    UnixSeconds,
    Venue,
    WireModel,
    wire_optional,
)


def _lenient_int(value: Any) -> int | None:
    """Coerce to int, else None — mirrors ``int(params.get(x) or default)``'s
    ``except (TypeError, ValueError)`` fallback so a non-numeric value defaults
    instead of raising (the handler re-reads the raw param anyway)."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── leaf DTOs (mirror forecasting/pm/model.py to_dict) ────────────────────────


class PmHistoryPoint(WireModel):
    TS_NAME = "PMHistoryPointDTO"

    ts: UnixSeconds
    p: Probability


class PmOrderLevel(WireModel):
    TS_NAME = "PMOrderLevelDTO"

    price: float
    size: float


class PmOrderBook(WireModel):
    TS_NAME = "PMOrderBookDTO"

    venue: Venue
    market_id: MarketId
    bids: list[PmOrderLevel]
    asks: list[PmOrderLevel]
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    tick_size: float | None
    timestamp: int | None


class PmMarket(WireModel):
    TS_NAME = "PMMarketDTO"

    venue: Venue
    market_id: MarketId
    event_id: EventId | None
    label: str
    question: str
    yes_bid: float | None
    yes_ask: float | None
    yes_mid: float | None
    last_price: float | None
    volume: float | None
    open_interest: float | None
    close_time: IsoInstant | None
    status: str | None
    url: str | None
    token_ids: list[str]


class PmEvent(WireModel):
    TS_NAME = "PMEventDTO"

    venue: Venue
    event_id: EventId
    title: str
    slug: str | None
    category: str | None
    close_time: IsoInstant | None
    volume: float | None
    url: str | None
    mutually_exclusive: bool
    is_binary: bool
    markets: list[PmMarket]


class PmOutcome(WireModel):
    TS_NAME = "PMOutcomeDTO"

    label: str
    prob: Probability
    raw_prob: Probability
    market_id: MarketId
    yes_bid: float | None
    yes_ask: float | None
    volume: float | None
    liquid: bool


class PmDistributionHeadline(WireModel):
    TS_NAME = "PMDistributionHeadline"

    top_label: str | None
    top_prob: float | None
    n: int
    # SERVER WINS: total_volume is `_round(self.total_volume, 2)` over a float
    # field that defaults to 0.0 — it is never None. pmData.ts declared it
    # `null | number`; the server always emits a number.
    total_volume: float
    close_time: IsoInstant | None


class PmDistribution(WireModel):
    TS_NAME = "PMDistributionDTO"

    venue: Venue
    event_id: EventId
    title: str
    binary: bool
    overround: float
    total_volume: float
    close_time: IsoInstant | None
    url: str | None
    headline: PmDistributionHeadline
    outcomes: list[PmOutcome]
    notes: list[str]
    normalized: bool


class PmListItem(WireModel):
    TS_NAME = "PMListItem"

    event: PmEvent
    distribution: PmDistribution


# ── pm.list ───────────────────────────────────────────────────────────────────


class PmListRequest(WireModel):
    TS_NAME = "PmListRequest"

    venue: Venue | None = None
    query: str | None = None
    tag: str | None = None
    limit: int | None = None

    @field_validator("limit", mode="before")
    @classmethod
    def _coerce_limit(cls, value: Any) -> int | None:
        return _lenient_int(value)


class PmListResponse(WireModel):
    TS_NAME = "PmListResponse"

    events: list[PmListItem]
    count: int


# ── pm.detail ─────────────────────────────────────────────────────────────────


class PmDetailRequest(WireModel):
    TS_NAME = "PmDetailRequest"

    venue: Venue
    event_id: EventId


class PmDetailResponse(WireModel):
    TS_NAME = "PmDetailResponse"

    event: PmEvent
    distribution: PmDistribution


# ── pm.book ───────────────────────────────────────────────────────────────────


class PmBookRequest(WireModel):
    TS_NAME = "PmBookRequest"

    venue: Venue
    market_id: MarketId


class PmBookResponse(WireModel):
    TS_NAME = "PmBookResponse"

    book: PmOrderBook


# ── pm.history ────────────────────────────────────────────────────────────────


class PmHistoryRequest(WireModel):
    TS_NAME = "PmHistoryRequest"

    venue: Venue
    market_id: MarketId
    # SERVER WINS: `range` is passed straight through as an arbitrary string
    # (the handler accepts "1m" et al and the gateway suite tests it); pmData.ts
    # narrowed it to a '1d'|'1w'|'all' union, which the server does not enforce.
    range: str | None = None
    interval: str | None = None
    series_ticker: str | None = None
    period_interval: int | None = None
    max_points: int | None = None

    @field_validator("period_interval", "max_points", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int | None:
        return _lenient_int(value)


class PmHistoryResponse(WireModel):
    TS_NAME = "PmHistoryResponse"

    points: list[PmHistoryPoint]
    count: int


# ── pm.stream.start / pm.stream.stop ──────────────────────────────────────────


class PmStreamStartRequest(WireModel):
    TS_NAME = "PmStreamStartRequest"

    venue: Venue
    market_ids: list[str] | None = None


class PmStreamStartResponse(WireModel):
    TS_NAME = "PMStreamStart"

    streaming: bool
    # StreamStart.to_dict emits these ONLY when truthy/non-empty (conditional).
    reason: str | None = wire_optional()
    subscribed: list[str] | None = wire_optional()


class PmStreamStopRequest(WireModel):
    TS_NAME = "PmStreamStopRequest"

    venue: Venue
    market_ids: list[str] | None = None


class PmStreamStopResponse(WireModel):
    TS_NAME = "PmStreamStopResponse"

    stopped: bool
    venue: Venue
    # PMStreamHub.stop emits exactly one of `closed` / `remaining` (or neither).
    closed: bool | None = wire_optional()
    remaining: list[str] | None = wire_optional()


__all__ = [
    "PmHistoryPoint",
    "PmOrderLevel",
    "PmOrderBook",
    "PmMarket",
    "PmEvent",
    "PmOutcome",
    "PmDistributionHeadline",
    "PmDistribution",
    "PmListItem",
    "PmListRequest",
    "PmListResponse",
    "PmDetailRequest",
    "PmDetailResponse",
    "PmBookRequest",
    "PmBookResponse",
    "PmHistoryRequest",
    "PmHistoryResponse",
    "PmStreamStartRequest",
    "PmStreamStartResponse",
    "PmStreamStopRequest",
    "PmStreamStopResponse",
]
