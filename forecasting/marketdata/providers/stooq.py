"""Stooq (daily OHLC CSV) provider — a server-side data-plane provider.

Stooq has no client parser (it was never in ``marketFetch.ts``); it enters the
plane server-side directly. The shape mirrors the desk's existing Stooq source
adapter (``forecasting/source_adapters.py``) and the client's CSV discipline
(``parseFredCsv``):
* ONE GET per symbol to ``/q/d/l/?s={symbol}&i=d`` returns a daily OHLC CSV
  (header ``Date,Open,High,Low,Close,Volume``, rows oldest→newest). Missing
  values are ``N/D`` / ``-`` / blank.
* The CLOSE column drives the tape: ``value`` is the last real close,
  ``prevClose`` the prior real close, ``change`` / ``changePct`` between them,
  and ``history`` is the ordered close series (oldest→newest) — the sparkline.
* An error / empty payload (or a symbol Stooq does not know) yields
  ``value = None`` (THE LAW) — absence renders "—", never a fabricated ``0``.
"""

from __future__ import annotations

import re
from urllib.parse import quote as _urlquote

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import TextGetter, default_get_text

_LINE_RE = re.compile(r"\r?\n")


def _column(header: list[str], name: str) -> int:
    """Index of the named column (case-insensitive), else ``-1``."""

    for i, field in enumerate(header):
        if field.strip().lower() == name:
            return i
    return -1


def parse_stooq(csv_text: str, series: SeriesRef) -> Quote:
    """Parse a Stooq daily CSV into value / change / history off the CLOSE column."""

    text = csv_text if isinstance(csv_text, str) else ""
    lines = [ln for ln in _LINE_RE.split(text.strip()) if ln.strip()]

    def _null() -> Quote:
        return Quote(
            symbol=series.symbol,
            provider="stooq",
            name=series.name,
            category=series.category,
            value=None,
            change=None,
            changePct=None,
            prevClose=None,
            asOf=0,
            unit=series.unit,
            history=[],
        )

    if len(lines) < 2:
        return _null()

    header = lines[0].split(",")
    date_idx = _column(header, "date")
    close_idx = _column(header, "close")
    if close_idx < 0:
        return _null()

    dates: list[str] = []
    closes: list[float] = []
    for line in lines[1:]:
        cols = line.split(",")
        if close_idx >= len(cols):
            continue
        close = num(cols[close_idx])
        if close is None:
            continue
        closes.append(close)
        dates.append(cols[date_idx].strip() if 0 <= date_idx < len(cols) else "")

    value = closes[-1] if closes else None
    prev_close = closes[-2] if len(closes) > 1 else None
    change, change_pct = change_columns(value, prev_close)
    as_of = epoch_ms(dates[-1]) if dates and dates[-1] else 0

    return Quote(
        symbol=series.symbol,
        provider="stooq",
        name=series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=prev_close,
        asOf=as_of,
        unit=series.unit,
        history=closes,
    )


class StooqProvider:
    name = "stooq"
    needs_key = False

    def __init__(self, get_text: TextGetter | None = None) -> None:
        self._get_text = get_text or default_get_text

    def _url(self, symbol: str) -> str:
        # Stooq symbols are lowercased in the query, exactly as the source adapter.
        return f"https://stooq.com/q/d/l/?s={_urlquote(symbol.lower(), safe='')}&i=d"

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        quotes: list[Quote] = []
        for s in series:
            csv_text = self._get_text(self._url(s.symbol))
            quotes.append(parse_stooq(csv_text or "", s))
        return quotes


__all__ = ["StooqProvider", "parse_stooq"]
