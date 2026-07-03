"""Websocket wire format for the two venues — pure, no I/O.

The connection-management half lives in :mod:`forecasting.pm.stream`; this half
is just message parsing and the per-venue subscribe/URL spec, so both stay well
under the non-monolithic size budget and the parsing is unit-testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

POLYMARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
KALSHI_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"


@dataclass(frozen=True)
class Tick:
    market_id: str
    kind: str  # "price" | "book"
    payload: dict


def _as_messages(raw: object) -> list[dict]:
    """A frame may be a single object or a batch list; normalise to a list."""
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return [raw] if isinstance(raw, dict) else []


def parse_polymarket(raw: object) -> list[Tick]:
    """Polymarket market channel: ``book`` / ``price_change`` / ``tick_size_change``."""
    ticks: list[Tick] = []
    for msg in _as_messages(raw):
        event = str(msg.get("event_type") or msg.get("type") or "").lower()
        asset = msg.get("asset_id") or msg.get("market")
        if not asset:
            continue
        kind = "book" if event == "book" else "price"
        ticks.append(Tick(market_id=str(asset), kind=kind, payload=msg))
    return ticks


def parse_kalshi(raw: object) -> list[Tick]:
    """Kalshi public channels: ``ticker`` / ``trade`` / orderbook deltas."""
    ticks: list[Tick] = []
    for msg in _as_messages(raw):
        chan = str(msg.get("type") or "").lower()
        body = msg.get("msg") if isinstance(msg.get("msg"), dict) else msg
        ticker = body.get("market_ticker") or body.get("ticker") or msg.get("market_ticker")
        if not ticker:
            continue
        kind = "book" if chan in ("orderbook_delta", "orderbook_snapshot") else "price"
        ticks.append(Tick(market_id=str(ticker), kind=kind, payload=msg))
    return ticks


@dataclass(frozen=True)
class VenueSpec:
    venue: str
    url: str
    parse: Callable[[object], list[Tick]]
    subscribe: Callable[[Iterable[str]], dict]
    channels: tuple[str, ...] = ()


def _poly_subscribe(market_ids: Iterable[str]) -> dict:
    return {"type": "market", "assets_ids": list(market_ids)}


def _kalshi_subscribe(market_ids: Iterable[str]) -> dict:
    return {
        "id": 1,
        "cmd": "subscribe",
        "params": {"channels": ["ticker", "trade"], "market_tickers": list(market_ids)},
    }


POLYMARKET_SPEC = VenueSpec(
    venue="polymarket",
    url=POLYMARKET_WS,
    parse=parse_polymarket,
    subscribe=_poly_subscribe,
)
KALSHI_SPEC = VenueSpec(
    venue="kalshi",
    url=KALSHI_WS,
    parse=parse_kalshi,
    subscribe=_kalshi_subscribe,
    channels=("ticker", "trade"),
)


def spec_for(venue: str) -> VenueSpec:
    v = venue.lower()
    if v in ("polymarket", "poly", "pm"):
        return POLYMARKET_SPEC
    if v == "kalshi":
        return KALSHI_SPEC
    raise ValueError(f"unknown venue {venue!r}")


__all__ = [
    "Tick",
    "VenueSpec",
    "POLYMARKET_SPEC",
    "KALSHI_SPEC",
    "POLYMARKET_WS",
    "KALSHI_WS",
    "parse_polymarket",
    "parse_kalshi",
    "spec_for",
]
