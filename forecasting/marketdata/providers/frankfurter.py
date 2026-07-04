"""Frankfurter (ECB) FX provider — ported one-to-one from ``marketFetch.ts``.

The fixed logic + live-probed quirks carried over verbatim:
* ONE ranged call — ``/{from}..?base=USD&symbols=...`` over ~35 calendar days —
  gives the latest value, the day change, AND the 1MO sparkline in a single
  request (the ``/latest`` endpoint starved the change columns + history, which
  the operator flagged as FX "missing fundamental information").
* A date-range payload (``{rates: {"2026-06-02": {EUR: ..}, ...}}``) parses to
  value + prevClose + change + history; a ``/latest``-shaped payload
  (``{rates: {EUR: number}}``) still parses value-only (backward compatible).
* FX has no volume — that column stays honestly absent.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import JsonGetter, default_get_json

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RANGE_DAYS = 35


def parse_frankfurter(payload: object, series_list: list[SeriesRef]) -> list[Quote]:
    """Parse a Frankfurter response into one :class:`Quote` per series."""

    data = payload if isinstance(payload, dict) else {}
    rates = data.get("rates") if isinstance(data.get("rates"), dict) else {}

    date_keys = sorted(k for k in rates if isinstance(k, str) and _DATE_RE.match(k))

    # ── /latest-shaped (or empty) payload: value-only, no change/history ──────
    if not date_keys:
        as_of = epoch_ms(data.get("date")) if isinstance(data.get("date"), str) else 0
        return [
            Quote(
                symbol=s.symbol,
                provider="frankfurter",
                name=s.name,
                category=s.category,
                value=num(rates.get(s.symbol)),
                change=None,
                changePct=None,
                prevClose=None,
                asOf=as_of,
                unit=s.unit,
                history=[],
            )
            for s in series_list
        ]

    # ── date-range payload: value + day change + the 1MO sparkline ────────────
    as_of = epoch_ms(date_keys[-1])
    quotes: list[Quote] = []
    for s in series_list:
        closes: list[float] = []
        for d in date_keys:
            row = rates.get(d)
            v = num(row.get(s.symbol)) if isinstance(row, dict) else None
            if v is not None:
                closes.append(v)
        value = closes[-1] if closes else None
        prev_close = closes[-2] if len(closes) > 1 else None
        change, change_pct = change_columns(value, prev_close)
        quotes.append(
            Quote(
                symbol=s.symbol,
                provider="frankfurter",
                name=s.name,
                category=s.category,
                value=value,
                change=change,
                changePct=change_pct,
                prevClose=prev_close,
                asOf=as_of,
                unit=s.unit,
                history=closes,
            )
        )
    return quotes


class FrankfurterProvider:
    name = "frankfurter"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def _url(self, symbols: list[str]) -> str:
        start = (datetime.now(timezone.utc) - timedelta(days=RANGE_DAYS)).strftime("%Y-%m-%d")
        joined = ",".join(symbols)
        return f"https://api.frankfurter.app/{start}..?base=USD&symbols={joined}"

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        if not series:
            return []
        payload = self._get_json(self._url([s.symbol for s in series]))
        return parse_frankfurter(payload, series)


__all__ = ["FrankfurterProvider", "parse_frankfurter", "RANGE_DAYS"]
