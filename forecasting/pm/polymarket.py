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
from urllib.parse import quote, urlencode, urlparse

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


# ── id-form routing (pure) ───────────────────────────────────────────────────
# One place the venue's id-form quirks live, so BOTH the watched-source adapter
# (forecasting/source_adapters.load_polymarket_market) and the resolution reader
# resolve the same market from the same string — no split-brain where a bare
# slug/id/event-URL misses in the importer but works through pm_query.


def is_condition_id(value: str) -> bool:
    """True when ``value`` is a Polymarket *conditionId* — a ``0x``-prefixed hex
    string (the on-chain condition hash).

    Gamma's ``/markets`` endpoint keys its ``id`` filter on the NUMERIC market id
    (decimal); passing a conditionId there returns HTTP 422 — it must go through
    the dedicated ``condition_ids`` filter. Numeric ids and kebab slugs never
    start with ``0x``, so the prefix is an unambiguous discriminator."""
    v = value.strip().lower()
    if not v.startswith("0x"):
        return False
    body = v[2:]
    return bool(body) and all(c in "0123456789abcdef" for c in body)


def market_endpoint_candidates(source: str, *, gamma_base: str = GAMMA_BASE) -> list[str]:
    """Ordered Gamma endpoints that resolve ANY Polymarket id form to a market.

    MARKET forms (slug / numeric id / ``0x`` conditionId) come FIRST so a source
    that already resolved as a market resolves byte-for-byte as before; the EVENT
    forms — the market-only importer's split-brain miss — are appended as
    fallbacks. An event page URL (``polymarket.com/event/{slug}``), a bare event
    slug, and a numeric EVENT id all resolve through the singular
    ``/events/slug/{slug}`` | ``/events/{id}`` endpoints, which carry full nested
    market detail (the ``/events?slug=`` *filter* drops each market's question).

    A ``0x`` conditionId is NEVER an event, so it gets no event fallback (guarding
    the resolution reader's conditionId path). Raises ``ValueError`` for a
    structurally empty id/slug or a polymarket.com URL with no slug segment."""
    base = gamma_base.rstrip("/")
    source = source.strip()
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc == "gamma-api.polymarket.com":
            return [source]  # already a Gamma endpoint — pass through unchanged
        if parsed.netloc.endswith("polymarket.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if not parts:
                raise ValueError("polymarket URL must include a market or event slug")
            slug = parts[-1]
            # A public URL is ``/event/{event-slug}[/{market-slug}]``: the event
            # slug is the segment after "event"; else fall back to the last seg.
            if "event" in parts and parts.index("event") + 1 < len(parts):
                event_slug = parts[parts.index("event") + 1]
            else:
                event_slug = slug
            candidates = [
                f"{base}/markets?{urlencode({'slug': slug})}",
                f"{base}/events/slug/{quote(event_slug)}",
            ]
            if event_slug != slug:
                candidates.append(f"{base}/events/slug/{quote(slug)}")
            return candidates
        return [source]  # some other API URL — pass through unchanged
    if source.startswith("id:"):
        value = source.split(":", 1)[1].strip()
    else:
        value = source.removeprefix("slug:").strip()
    if not value:
        raise ValueError("polymarket market id/slug is empty")
    if is_condition_id(value):
        return [f"{base}/markets?{urlencode({'condition_ids': value})}"]
    if value.isdigit():
        # Numeric: try the MARKET id filter, then the EVENT id endpoint (Gamma
        # keys ``/markets?id`` on the market id; an event id only resolves at
        # ``/events/{id}``).
        return [
            f"{base}/markets?{urlencode({'id': value})}",
            f"{base}/events/{quote(value)}",
        ]
    # kebab/text slug: market slug first, then the singular event-slug endpoint.
    return [
        f"{base}/markets?{urlencode({'slug': value})}",
        f"{base}/events/slug/{quote(value)}",
    ]


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

    def catalog_events(self) -> list[dict[str, Any]]:
        """Return every open event via Gamma's stable keyset pagination.

        The public sitemap contains only a small promoted subset. The keyset
        endpoint is the venue's complete, cursor-paginated event source and
        includes nested markets, whose questions must also be searchable.
        """
        rows: list[dict[str, Any]] = []
        cursor = ""
        seen_cursors: set[str] = set()
        while True:
            params = {"closed": "false", "limit": "100"}
            if cursor:
                params["after_cursor"] = cursor
            raw = self._fetch(f"{self._gamma}/events/keyset?{urlencode(params)}")
            page = raw.get("events") if isinstance(raw, dict) else None
            if not isinstance(page, list) or not page:
                break
            for event in page:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("id") or event.get("slug") or "")
                if not event_id:
                    continue
                slug = str(event.get("slug") or "")
                title = str(event.get("title") or "").strip()
                markets = [market for market in (event.get("markets") or []) if isinstance(market, dict)]
                tags = [tag for tag in (event.get("tags") or []) if isinstance(tag, dict)]
                market_text = " ".join(
                    " ".join(
                        (
                            str(market.get("question") or ""),
                            str(market.get("groupItemTitle") or ""),
                            " ".join(str(value) for value in _json_list(market.get("outcomes"))),
                        )
                    )
                    for market in markets
                )
                rows.append(
                    {
                        "venue": VENUE,
                        "event_id": event_id,
                        "title": title,
                        "sub_title": str(event.get("subtitle") or "").strip(),
                        "slug": slug,
                        "category": str(event.get("category") or (tags[0].get("label") if tags else "")),
                        "close_time": str(event.get("endDate") or ""),
                        "volume": _to_float(event.get("volume")),
                        "url": f"https://polymarket.com/event/{slug}" if slug else "",
                        "market_count": len(markets),
                        "search": " ".join(
                            (
                                title,
                                str(event.get("subtitle") or ""),
                                slug,
                                " ".join(str(tag.get("label") or "") for tag in tags),
                                market_text,
                            )
                        ).casefold(),
                    }
                )
            next_cursor = str(raw.get("next_cursor") or "") if isinstance(raw, dict) else ""
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return rows

    def catalog_event(self, event_ref: str) -> PMEvent:
        return self.event(event_ref)

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
    "is_condition_id",
    "market_endpoint_candidates",
    "parse_event",
    "parse_events",
    "parse_market",
    "parse_book",
    "parse_midpoint",
    "parse_prices_history",
]
