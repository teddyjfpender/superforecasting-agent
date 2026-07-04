"""BLS (Bureau of Labor Statistics) provider — ported one-to-one from ``marketFetch.ts``.

The client parser's exact semantics carried over verbatim:
* ONE POST per series to ``/publicAPI/v2/timeseries/data/`` with a JSON body
  ``{registrationkey?, seriesid: [symbol], startyear, endyear}`` — the
  ``registrationkey`` is included ONLY when a key is present (``needs_key`` is
  False: the keyless quota technically works, so the provider is never skipped).
* ``value`` is the latest ``Results.series[0].data[0].value``; ``change`` is vs
  the prior data point (``data[1]``).
* ``asOf`` maps ``year`` + ``period`` (``"M05"`` → month 5) to
  ``YYYY-MM-01``; absent ``year`` → ``0`` (never a fabricated instant).
* An error / empty payload yields ``value = None`` (THE LAW) — absence renders
  "—", never a fabricated ``0``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import JsonGetter, default_get_json


def parse_bls(payload: object, series: SeriesRef) -> Quote:
    """Parse a BLS timeseries response into one :class:`Quote` for the series."""

    results = payload.get("Results") if isinstance(payload, dict) else None
    series_arr = results.get("series") if isinstance(results, dict) else None
    first_series = (
        series_arr[0] if isinstance(series_arr, list) and series_arr and isinstance(series_arr[0], dict) else {}
    )
    data = first_series.get("data")
    data = data if isinstance(data, list) else []

    top = data[0] if len(data) > 0 and isinstance(data[0], dict) else {}
    second = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
    value = num(top.get("value"))
    prev = num(second.get("value"))
    change, change_pct = change_columns(value, prev)

    year = top.get("year")
    if year:
        period = str(top.get("period") or "M01")
        # strip a leading "M" only (M05 → 05), exactly as the client's replace(/^M/,'').
        month = period[1:] if period[:1] == "M" else period
        as_of = epoch_ms(f"{year}-{month}-01")
    else:
        as_of = 0

    return Quote(
        symbol=series.symbol,
        provider="bls",
        name=series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=None,  # client omitted prevClose for BLS
        asOf=as_of,
        unit=series.unit,
        history=[],  # client omitted history for BLS
    )


class BlsProvider:
    name = "bls"
    needs_key = False  # keyless quota works (poorly); the key is optional

    URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def _body(self, symbol: str, api_key: str | None) -> bytes:
        this_year = datetime.now(timezone.utc).year
        payload: dict[str, object] = {
            "seriesid": [symbol],
            "startyear": str(this_year - 1),
            "endyear": str(this_year),
        }
        if api_key:
            payload["registrationkey"] = api_key
        return json.dumps(payload).encode("utf-8")

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        quotes: list[Quote] = []
        for s in series:
            payload = self._get_json(
                self.URL,
                data=self._body(s.symbol, api_key),
                headers={"Content-Type": "application/json"},
            )
            quotes.append(parse_bls(payload, s))
        return quotes


__all__ = ["BlsProvider", "parse_bls"]
