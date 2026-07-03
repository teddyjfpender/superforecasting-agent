"""Polymarket read-only client: Gamma discovery + CLOB pricing.

Public market data only — no auth, no trading endpoints. Parsing is split from
fetching so tests exercise the parsers against recorded fixtures and never touch
the network.

Gamma  https://gamma-api.polymarket.com   /events (nested markets[]), /events/{id}
CLOB   https://clob.polymarket.com         /book, /midpoint, /prices-history
"""

from __future__ import annotations

import ast
import json
from typing import Any, Callable, Sequence
from urllib.parse import urlencode

from forecasting.pm._http import http_get_json
from forecasting.pm.model import (
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
VENUE = "polymarket"

FetchJson = Callable[[str], object]


# ── parsing (pure) ───────────────────────────────────────────────────────────


def _json_list(value: object) -> list[Any]:
    """Polymarket serialises arrays as JSON *strings* (e.g. ``'["Yes","No"]'``)."""
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, list):
                return list(parsed)
    return []


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_public_url(market: dict, event_slug: str | None) -> str | None:
    slug = market.get("slug") or event_slug
    if slug:
        return f"https://polymarket.com/event/{event_slug or slug}"
    return None


def parse_market(raw: dict, *, event_id: str | None = None, event_slug: str | None = None) -> PMMarket:
    token_ids = tuple(str(t) for t in _json_list(raw.get("clobTokenIds")))
    prices = _json_list(raw.get("outcomePrices"))
    outcomes = [str(o).lower() for o in _json_list(raw.get("outcomes"))]
    label = str(raw.get("groupItemTitle") or raw.get("question") or "").strip() or "Yes"
    volume = _to_float(raw.get("volumeNum"))
    if volume is None:
        volume = _to_float(raw.get("volume"))
    # The YES-oriented outcome price: outcomePrices is per-outcome BY
    # CONSTRUCTION (no direction ambiguity), gated on real volume because dead
    # placeholders carry ~[0.49, 0.51] defaults.
    yes_outcome_price: float | None = None
    if prices and (volume or 0.0) > 0.0:
        if "yes" in outcomes:
            yes_outcome_price = _to_float(prices[outcomes.index("yes")])
        elif prices:
            yes_outcome_price = _to_float(prices[0])
    closed = bool(raw.get("closed"))
    if closed:
        # A CLOSED child market is RESOLVED: outcomePrices holds the terminal
        # truth (YES 0 or 1). lastTradePrice can be the NO-side redemption
        # print (the operator's catch: Peru winning the World Cup rendered
        # 100% off lastTradePrice=1 while outcomePrices said YES=0), and any
        # leftover one-sided asks are junk — void the book entirely.
        yes_bid = yes_ask = None
        last_price = yes_outcome_price
    else:
        yes_bid = _to_float(raw.get("bestBid"))
        yes_ask = _to_float(raw.get("bestAsk"))
        # Prefer the YES-oriented outcome price over the direction-ambiguous
        # lastTradePrice; keep lastTradePrice only as the final fallback.
        last_price = yes_outcome_price
        if last_price is None:
            last_price = _to_float(raw.get("lastTradePrice"))
    return PMMarket(
        venue=VENUE,
        market_id=str(raw.get("conditionId") or raw.get("id") or (token_ids[0] if token_ids else "")),
        label=label,
        question=str(raw.get("question") or label).strip(),
        event_id=event_id,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        last_price=last_price,
        volume=volume,
        close_time=(str(raw.get("endDate")) if raw.get("endDate") else None),
        status=("closed" if raw.get("closed") else "open"),
        url=_market_public_url(raw, event_slug),
        token_ids=token_ids,
    )


def parse_event(raw: dict) -> PMEvent:
    slug = raw.get("slug")
    event_id = str(raw.get("id") or slug or "")
    markets = tuple(
        parse_market(m, event_id=event_id, event_slug=slug)
        for m in (raw.get("markets") or [])
        if isinstance(m, dict)
    )
    volume = _to_float(raw.get("volume")) or _to_float(raw.get("volume24hr"))
    return PMEvent(
        venue=VENUE,
        event_id=event_id,
        title=str(raw.get("title") or raw.get("question") or "").strip(),
        markets=markets,
        slug=(str(slug) if slug else None),
        category=(str(raw["tags"][0].get("label")) if isinstance(raw.get("tags"), list) and raw["tags"] and isinstance(raw["tags"][0], dict) else None),
        close_time=(str(raw.get("endDate")) if raw.get("endDate") else None),
        volume=volume,
        url=(f"https://polymarket.com/event/{slug}" if slug else None),
        mutually_exclusive=bool(raw.get("negRisk") or raw.get("enableNegRisk")),
    )


def parse_events(raw: object) -> list[PMEvent]:
    rows = raw if isinstance(raw, list) else (raw.get("data") if isinstance(raw, dict) else None)
    if not isinstance(rows, list):
        return []
    return [parse_event(r) for r in rows if isinstance(r, dict)]


def _levels(rows: object, *, reverse: bool) -> tuple[PMOrderLevel, ...]:
    out: list[PMOrderLevel] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("price"))
        size = _to_float(row.get("size"))
        if price is None or size is None:
            continue
        out.append(PMOrderLevel(price=price, size=size))
    out.sort(key=lambda level: level.price, reverse=reverse)
    return tuple(out)


def parse_book(raw: dict, *, market_id: str | None = None) -> PMOrderBook:
    return PMOrderBook(
        venue=VENUE,
        market_id=str(market_id or raw.get("asset_id") or raw.get("market") or ""),
        bids=_levels(raw.get("bids"), reverse=True),
        asks=_levels(raw.get("asks"), reverse=False),
        tick_size=_to_float(raw.get("tick_size")),
        timestamp=(int(float(raw["timestamp"])) if raw.get("timestamp") else None),
    )


def parse_midpoint(raw: object) -> float | None:
    if isinstance(raw, dict):
        return _to_float(raw.get("mid"))
    return _to_float(raw)


def parse_prices_history(raw: object) -> list[PMHistoryPoint]:
    rows = raw.get("history") if isinstance(raw, dict) else raw
    points: list[PMHistoryPoint] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ts = row.get("t")
        p = _to_float(row.get("p"))
        if ts is None or p is None:
            continue
        points.append(PMHistoryPoint(ts=int(ts), p=p))
    points.sort(key=lambda pt: pt.ts)
    return points


# ── fetching client ──────────────────────────────────────────────────────────


class PolymarketClient:
    """Thin fetch+parse wrapper. Inject ``fetch`` to test without network."""

    def __init__(
        self,
        *,
        gamma_base: str = GAMMA_BASE,
        clob_base: str = CLOB_BASE,
        fetch: FetchJson | None = None,
    ) -> None:
        self._gamma = gamma_base.rstrip("/")
        self._clob = clob_base.rstrip("/")
        self._fetch = fetch or (lambda url: http_get_json(url, label="polymarket"))

    def list_events(
        self, *, query: str | None = None, tag: str | None = None, limit: int = 40
    ) -> list[PMEvent]:
        params: list[tuple[str, str]] = [
            ("closed", "false"),
            ("limit", str(max(1, min(int(limit), 100)))),
            ("order", "volume24hr"),
            ("ascending", "false"),
        ]
        if tag:
            params.append(("tag_slug", tag))
        if query and query.strip():
            # A text query searches the FULL catalog via Gamma's dedicated
            # search endpoint — filtering the one top-volume page (the old
            # behaviour) silently missed everything below the fold (the
            # operator: "i cant seem to search through all markets").
            # Fail-open to the page-filter path if search errors.
            try:
                q = urlencode({"q": query.strip(), "limit_per_type": max(1, min(int(limit), 50)), "events_status": "active"})
                raw = self._fetch(f"{self._gamma}/public-search?{q}")
                found = parse_events(raw.get("events") if isinstance(raw, dict) else raw)
                if found:
                    return found[: int(limit)]
            except Exception:
                pass
        url = f"{self._gamma}/events?{urlencode(params)}"
        events = parse_events(self._fetch(url))
        if query:
            needle = query.strip().lower()
            events = [e for e in events if needle in e.title.lower()]
        return events

    def event(self, event_id: str) -> PMEvent:
        raw = self._fetch(f"{self._gamma}/events/{event_id}")
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if not isinstance(raw, dict):
            raise ValueError("polymarket event response was not an object")
        return parse_event(raw)

    def book(self, token_id: str) -> PMOrderBook:
        raw = self._fetch(f"{self._clob}/book?{urlencode({'token_id': token_id})}")
        if not isinstance(raw, dict):
            raise ValueError("polymarket book response was not an object")
        return parse_book(raw, market_id=token_id)

    def midpoint(self, token_id: str) -> float | None:
        return parse_midpoint(self._fetch(f"{self._clob}/midpoint?{urlencode({'token_id': token_id})}"))

    def prices_history(
        self, token_id: str, *, interval: str = "1w", fidelity: int = 180
    ) -> list[PMHistoryPoint]:
        params = urlencode({"market": token_id, "interval": interval, "fidelity": fidelity})
        return parse_prices_history(self._fetch(f"{self._clob}/prices-history?{params}"))


__all__ = [
    "GAMMA_BASE",
    "CLOB_BASE",
    "VENUE",
    "PolymarketClient",
    "parse_event",
    "parse_events",
    "parse_market",
    "parse_book",
    "parse_midpoint",
    "parse_prices_history",
]
