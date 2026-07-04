"""FRED (St. Louis Fed) provider — ported one-to-one from ``marketFetch.ts``.

FRED has TWO client paths, both carried over verbatim (``needs_key`` is False —
the provider degrades to the keyless CSV rather than being skipped):
* WITH a key — the official JSON observations API
  (``/fred/series/observations?...&sort_order=desc&limit=2``), most reliable.
  ``parse_fred`` reads the two DESC observations: latest value + change vs prior.
* WITHOUT a key — the keyless public CSV (``fredgraph.csv``), rows oldest→newest
  with ``"."`` for missing values. ``parse_fred_csv`` takes the last two REAL
  values (the ``"."`` rows dropped as null).

Neither path carries a ``prevClose`` or ``history`` (the client omitted both —
``change`` is computed, ``prevClose`` stays absent). An error / empty payload
yields ``value = None`` (THE LAW) — absence renders "—", never a fabricated ``0``.
"""

from __future__ import annotations

import re
from urllib.parse import quote as _urlquote

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import (
    JsonGetter,
    TextGetter,
    default_get_json,
    default_get_text,
)

_LINE_RE = re.compile(r"\r?\n")


def _quote(symbol: str, series: SeriesRef, value, change, change_pct, as_of: int) -> Quote:
    return Quote(
        symbol=series.symbol,
        provider="fred",
        name=series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=None,  # client omitted prevClose for FRED
        asOf=as_of,
        unit=series.unit,
        history=[],  # client omitted history for FRED
    )


def parse_fred(payload: object, series: SeriesRef) -> Quote:
    """Parse the keyed JSON observations (DESC, limit 2): latest + change vs prior."""

    obs = payload.get("observations") if isinstance(payload, dict) else None
    obs = obs if isinstance(obs, list) else []
    first = obs[0] if len(obs) > 0 and isinstance(obs[0], dict) else {}
    second = obs[1] if len(obs) > 1 and isinstance(obs[1], dict) else {}
    value = num(first.get("value"))
    prev = num(second.get("value"))
    change, change_pct = change_columns(value, prev)
    date = first.get("date")
    as_of = epoch_ms(date) if isinstance(date, str) and date else 0
    return _quote(series.symbol, series, value, change, change_pct, as_of)


def parse_fred_csv(csv_text: str, series: SeriesRef) -> Quote:
    """Parse the keyless ``fredgraph.csv`` (oldest→newest, ``"."`` = missing).

    Takes the last two REAL rows (``"."`` values dropped as null), exactly as the
    client's ``parseFredCsv``.
    """

    text = csv_text if isinstance(csv_text, str) else ""
    lines = _LINE_RE.split(text.strip())[1:]  # drop the header row
    rows: list[tuple[str, float]] = []
    for line in lines:
        comma = line.find(",")
        date = line[:comma]
        value = num(line[comma + 1 :])
        if value is not None:
            rows.append((date, value))

    last = rows[-1] if rows else None
    prev = rows[-2] if len(rows) > 1 else None
    value = last[1] if last else None
    change, change_pct = change_columns(value, prev[1] if prev else None)
    as_of = epoch_ms(last[0]) if last and last[0] else 0
    return _quote(series.symbol, series, value, change, change_pct, as_of)


class FredProvider:
    name = "fred"
    needs_key = False  # degrades to the keyless CSV, never skipped

    def __init__(
        self, get_json: JsonGetter | None = None, get_text: TextGetter | None = None
    ) -> None:
        self._get_json = get_json or default_get_json
        self._get_text = get_text or default_get_text

    def _json_url(self, symbol: str, api_key: str) -> str:
        return (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={_urlquote(symbol, safe='')}&api_key={api_key}"
            "&file_type=json&sort_order=desc&limit=2"
        )

    def _csv_url(self, symbol: str) -> str:
        return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={_urlquote(symbol, safe='')}"

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        quotes: list[Quote] = []
        for s in series:
            if api_key:
                payload = self._get_json(self._json_url(s.symbol, api_key))
                quotes.append(parse_fred(payload, s))
            else:
                csv_text = self._get_text(self._csv_url(s.symbol))
                quotes.append(parse_fred_csv(csv_text or "", s))
        return quotes


__all__ = ["FredProvider", "parse_fred", "parse_fred_csv"]
