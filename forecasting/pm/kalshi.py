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
# up to 5 cursor pages x 200 events per query.
_SEARCH_MAX_PAGES = 5


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

    def list_events(self, *, query: str | None = None, limit: int = 60) -> list[PMEvent]:
        if query and query.strip():
            # Kalshi has no text-search endpoint: scan the open-events catalog
            # via cursor pagination (bounded — up to _SEARCH_MAX_PAGES x 200)
            # and filter client-side, early-exiting once `limit` matches land.
            # One top page (the old behaviour) missed everything below it.
            needle = query.strip().lower()
            matches: list[PMEvent] = []
            cursor: str | None = None
            for _ in range(_SEARCH_MAX_PAGES):
                page_params: dict[str, str] = {
                    "with_nested_markets": "true", "status": "open", "limit": "200",
                }
                if cursor:
                    page_params["cursor"] = cursor
                raw = self._fetch(f"{self._base}/events?{urlencode(page_params)}")
                page = parse_events(raw)
                matches.extend(e for e in page if needle in e.title.lower())
                if len(matches) >= int(limit):
                    break
                cursor = raw.get("cursor") if isinstance(raw, dict) else None
                if not cursor or not page:
                    break
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
