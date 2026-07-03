"""Websocket wire format for the two venues — pure, no I/O.

The connection-management half lives in :mod:`forecasting.pm.stream`; this half
is just message parsing and the per-venue subscribe/URL spec, so both stay well
under the non-monolithic size budget and the parsing is unit-testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from forecasting.pm.model import honest_yes_mid

POLYMARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
KALSHI_WS = "wss://api.elections.kalshi.com/trade-api/ws/v2"


@dataclass(frozen=True)
class Tick:
    market_id: str
    kind: str  # "price" | "book"
    payload: dict
    # The HONEST probability estimate for this tick, computed server-side via
    # the canonical honest_yes_mid rule — None when the message carries no
    # estimate-grade information (degenerate/one-sided books, level deltas).
    # Consumers (the TUI overlay) must fold ONLY this field and never re-derive
    # prices from the raw payload: the operator caught a streamed empty book
    # overwriting Putin's honest 12% with a fabricated 50% client-side.
    estimate: float | None = None


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
        estimate: float | None = None
        if kind == "book":
            bids = [b for b in (msg.get("bids") or []) if isinstance(b, dict)]
            asks = [a for a in (msg.get("asks") or []) if isinstance(a, dict)]
            bb = max((_f(b.get("price")) for b in bids), default=None)
            ba = min((_f(a.get("price")) for a in asks), default=None)
            estimate = honest_yes_mid(bb, ba, None)
        elif event == "last_trade_price":
            estimate = _f(msg.get("price"))
        # price_change carries LEVEL deltas (not a trade, not a full book):
        # no estimate can honestly be derived from it.
        ticks.append(Tick(market_id=str(asset), kind=kind, payload=msg, estimate=estimate))
    return ticks


def _f(value: object) -> float | None:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v


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
        estimate: float | None = None
        if chan == "ticker":
            bid = _cents(body.get("yes_bid"))
            ask = _cents(body.get("yes_ask"))
            last = _cents(body.get("last_price") or body.get("price"))
            if last is not None and last <= 0.0:
                last = None  # 0 = no trade yet, never a 0% probability
            estimate = honest_yes_mid(bid, ask, last)
        elif chan == "trade":
            price = _cents(body.get("yes_price") or body.get("price"))
            estimate = price if price and price > 0.0 else None
        ticks.append(Tick(market_id=str(ticker), kind=kind, payload=msg, estimate=estimate))
    return ticks


def _cents(value: object) -> float | None:
    v = _f(value)
    return None if v is None else (v / 100.0 if v > 1.0 else v)


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
