"""Kalshi read-only client + RSA-PSS signer helper.

REST market data is PUBLIC (no auth) — that is the keyless default. The signer
is only needed for the authed websocket handshake in S2; ``cryptography`` is
imported lazily so the package works when it is absent.

REST  https://api.elections.kalshi.com/trade-api/v2
  /events?with_nested_markets=true, /markets/{ticker}/orderbook,
  /series/{s}/markets/{t}/candlesticks (period_interval ∈ {1,60,1440})
"""

from __future__ import annotations

import base64
from typing import Any, Callable
from urllib.parse import urlencode

from forecasting.pm._http import http_get_json
from forecasting.pm.model import (
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_PATH = "/trade-api/ws/v2"
VENUE = "kalshi"

FetchJson = Callable[[str], object]


# ── parsing (pure) ───────────────────────────────────────────────────────────


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(raw: dict, dollar_key: str, cents_key: str) -> float | None:
    """Kalshi returns either ``*_dollars`` strings (0-1) or cents ints."""
    if raw.get(dollar_key) is not None:
        return _to_float(raw.get(dollar_key))
    cents = _to_float(raw.get(cents_key))
    return None if cents is None else cents / 100.0


def _nonzero_price(raw: dict, dollar_key: str, cents_key: str) -> float | None:
    value = _price(raw, dollar_key, cents_key)
    return None if value is None or value <= 0.0 else value


def _market_url(ticker: str | None) -> str | None:
    return f"https://kalshi.com/markets/{ticker}" if ticker else None


def parse_market(raw: dict, *, event_id: str | None = None) -> PMMarket:
    ticker = raw.get("ticker")
    label = str(raw.get("yes_sub_title") or raw.get("title") or ticker or "").strip()
    return PMMarket(
        venue=VENUE,
        market_id=str(ticker or ""),
        label=label or "Yes",
        question=str(raw.get("title") or label or "").strip(),
        event_id=event_id or (str(raw.get("event_ticker")) if raw.get("event_ticker") else None),
        yes_bid=_price(raw, "yes_bid_dollars", "yes_bid"),
        yes_ask=_price(raw, "yes_ask_dollars", "yes_ask"),
        # last_price=0 on Kalshi means NO TRADE YET, not a 0% probability —
        # feeding it through as 0.0 would render dead markets as "0.00%"
        # (the same fabrication class as the placeholder-outcomePrices bug).
        last_price=_nonzero_price(raw, "last_price_dollars", "last_price"),
        volume=_to_float(raw.get("volume_fp")) if raw.get("volume_fp") is not None else _to_float(raw.get("volume")),
        open_interest=_to_float(raw.get("open_interest_fp")) if raw.get("open_interest_fp") is not None else _to_float(raw.get("open_interest")),
        close_time=(str(raw.get("close_time")) if raw.get("close_time") else None),
        status=(str(raw.get("status")) if raw.get("status") else None),
        url=_market_url(str(ticker) if ticker else None),
    )


# Bounded catalog scan for text search (Kalshi has no search endpoint):
# up to 5 cursor pages x 200 events per query, plus a series-catalog match
# (2 pages x 200 series; events fetched for the top matches) so whole market
# FAMILIES (daily temperature series etc.) are reachable by name.
_SEARCH_MAX_PAGES = 5
_SERIES_MAX_PAGES = 2
_SERIES_EVENT_FETCHES = 4
_SERIES_CATALOG_TTL = 3600.0  # seconds


def parse_event(raw: dict) -> PMEvent:
    event_id = str(raw.get("event_ticker") or "")
    markets = tuple(
        parse_market(m, event_id=event_id)
        for m in (raw.get("markets") or [])
        if isinstance(m, dict)
    )
    close_time = None
    for m in markets:
        if m.close_time:
            close_time = m.close_time
            break
    volume = sum((m.volume or 0.0) for m in markets) or None
    return PMEvent(
        venue=VENUE,
        event_id=event_id,
        title=str(raw.get("title") or "").strip(),
        markets=markets,
        slug=(str(raw.get("series_ticker")) if raw.get("series_ticker") else None),
        category=(str(raw.get("category")) if raw.get("category") else None),
        close_time=close_time,
        volume=volume,
        url=(f"https://kalshi.com/markets/{raw.get('series_ticker')}" if raw.get("series_ticker") else None),
        mutually_exclusive=bool(raw.get("mutually_exclusive", True)),
    )


def parse_events(raw: object) -> list[PMEvent]:
    rows = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [parse_event(r) for r in rows if isinstance(r, dict)]


def _ladder(rows: object, *, transform: Callable[[float], float], reverse: bool) -> tuple[PMOrderLevel, ...]:
    out: list[PMOrderLevel] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _to_float(row[0])
        size = _to_float(row[1])
        if price is None or size is None:
            continue
        out.append(PMOrderLevel(price=transform(price), size=size))
    out.sort(key=lambda level: level.price, reverse=reverse)
    return tuple(out)


def parse_orderbook(raw: dict, *, market_id: str | None = None) -> PMOrderBook:
    """Normalise a Kalshi book to a YES view.

    Kalshi quotes both sides as *bids*: ``yes`` levels are YES bids; a ``no`` bid
    at price p is willingness to sell YES at (1 - p), i.e. a YES ask. Handles the
    ``orderbook_fp`` (dollar strings) and legacy ``orderbook`` (cents) shapes.
    """
    book = raw.get("orderbook_fp") or raw.get("orderbook") or raw
    is_cents = "orderbook_fp" not in raw and isinstance(book, dict) and (
        "yes" in book or "no" in book
    )
    yes_rows = book.get("yes_dollars") if isinstance(book, dict) else None
    no_rows = book.get("no_dollars") if isinstance(book, dict) else None
    if yes_rows is None and no_rows is None and isinstance(book, dict):
        yes_rows, no_rows = book.get("yes"), book.get("no")
    scale = (lambda p: p / 100.0) if is_cents else (lambda p: p)
    bids = _ladder(yes_rows, transform=scale, reverse=True)
    asks = _ladder(no_rows, transform=lambda p: 1.0 - scale(p), reverse=False)
    return PMOrderBook(
        venue=VENUE,
        market_id=str(market_id or ""),
        bids=bids,
        asks=asks,
    )


def _candle_price(candle: dict) -> float | None:
    price = candle.get("price")
    if isinstance(price, dict):
        for key in ("mean_dollars", "close_dollars"):
            value = _to_float(price.get(key))
            if value is not None:
                return value
        cents = _to_float(price.get("mean")) or _to_float(price.get("close"))
        if cents is not None:
            return cents / 100.0
    bid = candle.get("yes_bid")
    ask = candle.get("yes_ask")
    bid_c = _to_float(bid.get("close_dollars")) if isinstance(bid, dict) else None
    ask_c = _to_float(ask.get("close_dollars")) if isinstance(ask, dict) else None
    if bid_c is not None and ask_c is not None:
        return (bid_c + ask_c) / 2.0
    return bid_c if bid_c is not None else ask_c


def parse_candlesticks(raw: object) -> list[PMHistoryPoint]:
    rows = raw.get("candlesticks") if isinstance(raw, dict) else raw
    points: list[PMHistoryPoint] = []
    for candle in rows or []:
        if not isinstance(candle, dict):
            continue
        ts = candle.get("end_period_ts") or candle.get("ts")
        price = _candle_price(candle)
        if ts is None or price is None:
            continue
        points.append(PMHistoryPoint(ts=int(ts), p=price))
    points.sort(key=lambda pt: pt.ts)
    return points


# ── RSA-PSS signer (lazy cryptography) ───────────────────────────────────────


class KalshiSignerUnavailable(RuntimeError):
    """``cryptography`` is not installed — websocket auth cannot be signed."""


def sign_kalshi_message(private_key_pem: str | bytes, message: str) -> str:
    """RSA-PSS-SHA256 sign ``message`` with the Kalshi private key → base64.

    Salt length = digest length, per Kalshi's documented scheme. Raises
    :class:`KalshiSignerUnavailable` when ``cryptography`` is absent.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover - optional dep
        raise KalshiSignerUnavailable(
            "install 'cryptography' to sign Kalshi websocket handshakes"
        ) from exc

    pem = private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem
    key = serialization.load_pem_private_key(pem, password=None)
    signature = key.sign(
        message.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def kalshi_auth_headers(
    key_id: str,
    private_key_pem: str | bytes,
    method: str,
    path: str,
    *,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    """Signed headers for a Kalshi authed request/handshake.

    The signed message is ``timestamp_ms + METHOD + path`` (path includes
    ``/trade-api``). ``timestamp_ms`` defaults to now.
    """
    if timestamp_ms is None:
        import time

        timestamp_ms = int(time.time() * 1000)
    ts = str(timestamp_ms)
    message = f"{ts}{method.upper()}{path}"
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sign_kalshi_message(private_key_pem, message),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


# ── fetching client ──────────────────────────────────────────────────────────


class KalshiClient:
    """Thin REST fetch+parse wrapper. Inject ``fetch`` to test without network."""

    def __init__(self, *, base_url: str = KALSHI_BASE, fetch: FetchJson | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._fetch = fetch or (lambda url: http_get_json(url, label="kalshi"))

    def _series_catalog(self) -> list[tuple[str, str]]:
        """(ticker, searchable-haystack) for every series — cached for an hour:
        the catalog changes rarely, and re-fetching 2x200 rows per keystroke-
        debounced query was the dominant search cost (measured seconds)."""
        now = time.monotonic()
        cached = getattr(self, "_series_cache", None)
        if cached and now - cached[0] < _SERIES_CATALOG_TTL:
            return cached[1]
        catalog: list[tuple[str, str]] = []
        cursor: str | None = None
        for _ in range(_SERIES_MAX_PAGES):
            sp: dict[str, str] = {"limit": "200"}
            if cursor:
                sp["cursor"] = cursor
            raw = self._fetch(f"{self._base}/series?{urlencode(sp)}")
            page = raw.get("series") if isinstance(raw, dict) else []
            for s in page or []:
                ticker = str(s.get("ticker") or "")
                if ticker:
                    catalog.append((ticker, f"{s.get('title') or ''} {ticker}".lower()))
            cursor = raw.get("cursor") if isinstance(raw, dict) else None
            if not cursor or not page:
                break
        self._series_cache = (now, catalog)
        return catalog

    def list_events(self, *, query: str | None = None, limit: int = 60) -> list[PMEvent]:
        if query and query.strip():
            # Kalshi has no text-search endpoint: scan the open-events catalog
            # via cursor pagination (bounded — up to _SEARCH_MAX_PAGES x 200)
            # and filter client-side, early-exiting once `limit` matches land.
            # One top page (the old behaviour) missed everything below it.
            needle = query.strip().lower()
            matches: list[PMEvent] = []
            seen: set[str] = set()

            def _add(events: list[PMEvent]) -> None:
                for e in events:
                    if e.event_id not in seen:
                        seen.add(e.event_id)
                        matches.append(e)

            # PHASE 1 — SERIES search: whole market families (e.g. the daily
            # max-temperature series) never surface in the event scan because
            # their events sit thousands deep; matching the series CATALOG by
            # title/ticker reaches them directly (the operator: "i can't see
            # any max temperature markets").
            try:
                series_hits = [
                    t for t, hay in self._series_catalog() if needle in hay
                ][:_SERIES_EVENT_FETCHES]
                if series_hits:
                    # Parallel per-series event fetches (serial cost = seconds).
                    from concurrent.futures import ThreadPoolExecutor

                    def _events_for(ticker: str) -> list[PMEvent]:
                        ep = urlencode({
                            "series_ticker": ticker, "status": "open",
                            "with_nested_markets": "true", "limit": "50",
                        })
                        return parse_events(self._fetch(f"{self._base}/events?{ep}"))

                    with ThreadPoolExecutor(max_workers=min(4, len(series_hits))) as pool:
                        for fut in [pool.submit(_events_for, t) for t in series_hits]:
                            try:
                                _add(fut.result())
                            except Exception:
                                continue
                    if len(matches) >= int(limit):
                        return matches[: int(limit)]
            except Exception:
                pass  # fail-open: the event scan below still runs

            # PHASE 2 — bounded cursor scan of open events, filtered by title.
            # LIGHT pages (no nested markets — the scan only reads titles; the
            # heavy payloads were the dominant search cost), then matches are
            # hydrated in parallel. When the series phase already found precise
            # hits, the fuzzy net shrinks to 2 pages.
            scan_pages = _SEARCH_MAX_PAGES if not matches else 2
            hit_tickers: list[str] = []
            cursor = None
            for _ in range(scan_pages):
                page_params: dict[str, str] = {"status": "open", "limit": "200"}
                if cursor:
                    page_params["cursor"] = cursor
                raw = self._fetch(f"{self._base}/events?{urlencode(page_params)}")
                page_raw = raw.get("events") if isinstance(raw, dict) else []
                for ev in page_raw or []:
                    title = str(ev.get("title") or "")
                    ticker = str(ev.get("event_ticker") or "")
                    if ticker and needle in title.lower():
                        hit_tickers.append(ticker)
                if len(matches) + len(hit_tickers) >= int(limit):
                    break
                cursor = raw.get("cursor") if isinstance(raw, dict) else None
                if not cursor or not page_raw:
                    break
            if hit_tickers:
                from concurrent.futures import ThreadPoolExecutor

                def _hydrate(ticker: str) -> PMEvent | None:
                    try:
                        return self.event(ticker)
                    except Exception:
                        return None

                budget = max(0, int(limit) - len(matches))
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(_hydrate, t) for t in hit_tickers[:budget]]
                    _add([ev for ev in (f.result() for f in futures) if ev is not None])
            return matches[: int(limit)]
        params = urlencode(
            {"with_nested_markets": "true", "status": "open", "limit": max(1, min(int(limit), 200))}
        )
        events = parse_events(self._fetch(f"{self._base}/events?{params}"))
        return events

    def event(self, event_ticker: str) -> PMEvent:
        params = urlencode({"with_nested_markets": "true"})
        raw = self._fetch(f"{self._base}/events/{event_ticker}?{params}")
        if isinstance(raw, dict) and isinstance(raw.get("event"), dict):
            raw = raw["event"]
        if not isinstance(raw, dict):
            raise ValueError("kalshi event response was not an object")
        return parse_event(raw)

    def orderbook(self, ticker: str) -> PMOrderBook:
        raw = self._fetch(f"{self._base}/markets/{ticker}/orderbook")
        if not isinstance(raw, dict):
            raise ValueError("kalshi orderbook response was not an object")
        return parse_orderbook(raw, market_id=ticker)

    def candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        *,
        period_interval: int = 60,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[PMHistoryPoint]:
        if period_interval not in (1, 60, 1440):
            raise ValueError("period_interval must be one of 1, 60, 1440")
        params: dict[str, Any] = {"period_interval": period_interval}
        if start_ts is not None:
            params["start_ts"] = int(start_ts)
        if end_ts is not None:
            params["end_ts"] = int(end_ts)
        url = f"{self._base}/series/{series_ticker}/markets/{ticker}/candlesticks?{urlencode(params)}"
        return parse_candlesticks(self._fetch(url))


__all__ = [
    "KALSHI_BASE",
    "KALSHI_WS_PATH",
    "VENUE",
    "KalshiClient",
    "KalshiSignerUnavailable",
    "sign_kalshi_message",
    "kalshi_auth_headers",
    "parse_event",
    "parse_events",
    "parse_market",
    "parse_orderbook",
    "parse_candlesticks",
]
