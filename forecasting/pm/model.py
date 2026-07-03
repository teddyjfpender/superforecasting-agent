"""Frozen data model for prediction-market events, markets, books, and history.

Pure data + ``to_dict`` only — no I/O, no aggregation logic. Both venues
(Polymarket, Kalshi) normalise into these shapes so downstream consumers (the
aggregate/service layers, the gateway RPCs, the agent tool) never branch on
venue-specific field names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _round(value: float | None, ndigits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


@dataclass(frozen=True)
class PMHistoryPoint:
    """A single price observation on a [0, 1] probability scale."""

    ts: int  # unix seconds
    p: float

    def to_dict(self) -> dict[str, Any]:
        return {"ts": int(self.ts), "p": _round(self.p)}


@dataclass(frozen=True)
class PMOrderLevel:
    price: float
    size: float

    def to_dict(self) -> dict[str, Any]:
        return {"price": _round(self.price), "size": _round(self.size, 2)}


@dataclass(frozen=True)
class PMOrderBook:
    """A YES-oriented order book: ``bids`` sorted high→low, ``asks`` low→high."""

    venue: str
    market_id: str
    bids: tuple[PMOrderLevel, ...] = ()
    asks: tuple[PMOrderLevel, ...] = ()
    tick_size: float | None = None
    timestamp: int | None = None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market_id": self.market_id,
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
            "best_bid": _round(self.best_bid),
            "best_ask": _round(self.best_ask),
            "mid": _round(self.mid),
            "tick_size": self.tick_size,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PMMarket:
    """One outcome-market. On Polymarket a categorical event's child market; on
    Kalshi one bucket of an event. ``label`` is the human outcome name."""

    venue: str
    market_id: str
    label: str
    question: str
    event_id: str | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    last_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    close_time: str | None = None
    status: str | None = None
    url: str | None = None
    token_ids: tuple[str, ...] = ()

    @property
    def yes_mid(self) -> float | None:
        """Best-available YES probability estimate: quote mid, else last trade."""
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2.0
        if self.yes_bid is not None:
            return self.yes_bid
        if self.yes_ask is not None:
            return self.yes_ask
        return self.last_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market_id": self.market_id,
            "event_id": self.event_id,
            "label": self.label,
            "question": self.question,
            "yes_bid": _round(self.yes_bid),
            "yes_ask": _round(self.yes_ask),
            "yes_mid": _round(self.yes_mid),
            "last_price": _round(self.last_price),
            "volume": _round(self.volume, 2),
            "open_interest": _round(self.open_interest, 2),
            "close_time": self.close_time,
            "status": self.status,
            "url": self.url,
            "token_ids": list(self.token_ids),
        }


@dataclass(frozen=True)
class PMEvent:
    """A venue event: on Polymarket a Gamma event (negRisk/categorical or
    binary); on Kalshi an event with nested outcome markets."""

    venue: str
    event_id: str
    title: str
    markets: tuple[PMMarket, ...] = ()
    slug: str | None = None
    category: str | None = None
    close_time: str | None = None
    volume: float | None = None
    url: str | None = None
    mutually_exclusive: bool = True

    @property
    def is_binary(self) -> bool:
        return len(self.markets) <= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "event_id": self.event_id,
            "title": self.title,
            "slug": self.slug,
            "category": self.category,
            "close_time": self.close_time,
            "volume": _round(self.volume, 2),
            "url": self.url,
            "mutually_exclusive": self.mutually_exclusive,
            "is_binary": self.is_binary,
            "markets": [m.to_dict() for m in self.markets],
        }


@dataclass(frozen=True)
class PMOutcome:
    """One row of a discretised distribution: a de-vigged outcome probability
    alongside the raw quote it came from (honest raw-vs-devig labelling)."""

    label: str
    prob: float  # de-vigged, sums to ~1 across a mutually-exclusive event
    raw_prob: float  # pre-devig YES mid
    market_id: str
    yes_bid: float | None = None
    yes_ask: float | None = None
    volume: float | None = None
    liquid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "prob": _round(self.prob),
            "raw_prob": _round(self.raw_prob),
            "market_id": self.market_id,
            "yes_bid": _round(self.yes_bid),
            "yes_ask": _round(self.yes_ask),
            "volume": _round(self.volume, 2),
            "liquid": self.liquid,
        }


@dataclass(frozen=True)
class PMDistribution:
    """The headline+sub-rows contract: an event collapsed into an ordered set
    of de-vigged outcomes plus a synthesised headline."""

    venue: str
    event_id: str
    title: str
    outcomes: tuple[PMOutcome, ...] = ()
    binary: bool = False
    overround: float = 0.0
    total_volume: float = 0.0
    close_time: str | None = None
    url: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    # True iff the outcome probs were de-vig normalised. Normalisation must be
    # EARNED: only a guaranteed mutually-exclusive partition whose book sums to
    # a sane total gets normalised — an open-ended or truncated outcome list
    # rendered to sum-to-1 would overstate every listed outcome.
    normalized: bool = True

    @property
    def headline(self) -> dict[str, Any]:
        top = self.outcomes[0] if self.outcomes else None
        return {
            "top_label": top.label if top else None,
            "top_prob": _round(top.prob) if top else None,
            "n": len(self.outcomes),
            "total_volume": _round(self.total_volume, 2),
            "close_time": self.close_time,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "event_id": self.event_id,
            "title": self.title,
            "binary": self.binary,
            "overround": _round(self.overround, 4),
            "total_volume": _round(self.total_volume, 2),
            "close_time": self.close_time,
            "url": self.url,
            "headline": self.headline,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "notes": list(self.notes),
            "normalized": self.normalized,
        }


__all__ = [
    "PMHistoryPoint",
    "PMOrderLevel",
    "PMOrderBook",
    "PMMarket",
    "PMEvent",
    "PMOutcome",
    "PMDistribution",
]
