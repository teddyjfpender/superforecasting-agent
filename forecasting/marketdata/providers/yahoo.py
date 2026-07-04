"""Yahoo Finance provider — ported ONE-TO-ONE from ``marketFetch.ts`` /
``marketSearch.ts``.

Yahoo is the highest-volume provider and the LAST to move server-side (Arc C3),
so this port is deliberately conservative: the EXACT request shapes, the
``Outrider/1.0`` User-Agent, and Yahoo's informal rate tolerance are preserved,
with polite failure isolation (a symbol whose fetch fails is simply skipped — it
keeps its prior cache entry — exactly as the client did, never blanking the tape).

Two endpoints, both carried over verbatim:

* Quotes — ``/v8/finance/chart/{symbol}?range=1mo&interval=1d`` per symbol,
  fetched with a bounded concurrency pool (``POOL`` = 6, mirroring the client's
  ``pool(yahoo, 6, …)``). ``parse_yahoo`` reads ``regularMarketPrice`` +
  ``chartPreviousClose`` (change vs prior close), the day / 52-week ranges,
  volume, currency, exchange, and the daily-close ``history`` (last 40) for the
  sparkline. A malformed 200 payload yields ``value = None`` (THE LAW); a network
  failure (``get_json`` → ``None``) skips the symbol entirely (client parity).

* Search — ``/v1/finance/search?q=…&quotesCount=10&newsCount=0`` maps each hit's
  ``quoteType`` to one of our categories (``parse_yahoo_search`` /
  ``yahoo_type_to_category``); this is what ``market.search`` serves so the TUI's
  symbol lookup stops hitting Yahoo from the client.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, num
from forecasting.marketdata.provider import JsonGetter, default_get_json

POOL = 6  # max concurrent per-symbol chart fetches (client's pool size)


def _str(value: object) -> str:
    """Return ``value`` when it is a string, else ``""`` (the client's ``str``)."""

    return value if isinstance(value, str) else ""


# ── quotes ────────────────────────────────────────────────────────────────────


def parse_yahoo(payload: object, series: SeriesRef) -> Quote:
    """Parse a Yahoo ``chart`` response into a single :class:`Quote`.

    Mirrors ``parseYahoo`` exactly: ``value`` is ``regularMarketPrice``,
    ``prevClose`` is ``chartPreviousClose`` (falling back to ``previousClose``),
    the change columns derive from the two, and ``history`` is the daily-close
    series (last 40) — a malformed / empty payload → ``value = None`` (THE LAW).
    """

    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

    value = num(meta.get("regularMarketPrice"))
    prev = num(meta.get("chartPreviousClose"))
    if prev is None:
        prev = num(meta.get("previousClose"))
    change, change_pct = change_columns(value, prev)

    # Daily closes (drop nulls); keep the last 40 as the sparkline, only when >1.
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote_arr = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
    first_quote = quote_arr[0] if quote_arr and isinstance(quote_arr[0], dict) else {}
    raw_closes = first_quote.get("close") if isinstance(first_quote.get("close"), list) else []
    closes = [c for c in (num(x) for x in raw_closes) if c is not None]
    history = closes[-40:] if len(closes) > 1 else []

    market_time = num(meta.get("regularMarketTime"))
    as_of = int((market_time if market_time is not None else 0) * 1000)

    return Quote(
        symbol=series.symbol,
        provider="yahoo",
        name=_str(meta.get("shortName")) or _str(meta.get("longName")) or series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=prev,
        asOf=as_of,
        unit=series.unit,
        history=history,
        currency=_str(meta.get("currency")) or None,
        exchange=_str(meta.get("fullExchangeName")) or _str(meta.get("exchangeName")) or None,
        dayHigh=num(meta.get("regularMarketDayHigh")),
        dayLow=num(meta.get("regularMarketDayLow")),
        volume=num(meta.get("regularMarketVolume")),
        week52High=num(meta.get("fiftyTwoWeekHigh")),
        week52Low=num(meta.get("fiftyTwoWeekLow")),
    )


# ── search ────────────────────────────────────────────────────────────────────

_QUOTE_TYPE_CATEGORY = {
    "CRYPTOCURRENCY": "Crypto",
    "CURRENCY": "FX",
    "FUTURE": "Commodities",
    "INDEX": "Indices",
}


def yahoo_type_to_category(quote_type: object) -> str:
    """Map a Yahoo ``quoteType`` to one of our categories (default ``Stocks``)."""

    return _QUOTE_TYPE_CATEGORY.get(_str(quote_type).upper(), "Stocks")


@dataclass(frozen=True)
class SearchResult:
    """One symbol-search hit — a curated-series shape (``MarketSeries``)."""

    symbol: str
    provider: str
    name: str
    category: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "provider": self.provider,
            "name": self.name,
            "category": self.category,
        }


def parse_yahoo_search(payload: object) -> list[SearchResult]:
    """Parse a Yahoo ``search`` response into :class:`SearchResult` rows.

    Mirrors ``parseYahooSearch``: keep hits with a string ``symbol``, name from
    ``shortname`` / ``longname`` / ``symbol``, category from the ``quoteType``.
    """

    quotes = payload.get("quotes") if isinstance(payload, dict) else None
    quotes = quotes if isinstance(quotes, list) else []
    out: list[SearchResult] = []
    for q in quotes:
        if not isinstance(q, dict) or not isinstance(q.get("symbol"), str):
            continue
        symbol = q["symbol"]
        name = _str(q.get("shortname")) or _str(q.get("longname")) or symbol
        out.append(
            SearchResult(
                symbol=symbol,
                provider="yahoo",
                name=name,
                category=yahoo_type_to_category(q.get("quoteType")),
            )
        )
    return out


class YahooProvider:
    name = "yahoo"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def _chart_url(self, symbol: str) -> str:
        from urllib.parse import quote as _urlquote

        return (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{_urlquote(symbol, safe='')}?range=1mo&interval=1d"
        )

    def _search_url(self, query: str) -> str:
        from urllib.parse import quote as _urlquote

        return (
            "https://query1.finance.yahoo.com/v1/finance/search"
            f"?q={_urlquote(query, safe='')}&quotesCount=10&newsCount=0"
        )

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        """Resolve every series via a bounded pool; skip symbols whose fetch fails.

        A ``None`` payload (network / non-2xx) drops the symbol from the batch —
        the client did the same (``if (json) onBatch([parseYahoo(...)])``), so the
        tape keeps the symbol's prior cache rather than painting a phantom "—".
        """

        if not series:
            return []

        def _one(s: SeriesRef) -> Quote | None:
            payload = self._get_json(self._chart_url(s.symbol))
            return parse_yahoo(payload, s) if payload is not None else None

        workers = max(1, min(POOL, len(series)))
        if workers == 1:
            resolved = [_one(series[0])]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                resolved = list(pool.map(_one, series))
        return [q for q in resolved if q is not None]

    def search(self, query: str) -> list[SearchResult]:
        """The symbol lookup behind ``market.search`` — empty query → no hits."""

        q = (query or "").strip()
        if not q:
            return []
        payload = self._get_json(self._search_url(q))
        return parse_yahoo_search(payload)


__all__ = [
    "YahooProvider",
    "SearchResult",
    "parse_yahoo",
    "parse_yahoo_search",
    "yahoo_type_to_category",
    "POOL",
]
