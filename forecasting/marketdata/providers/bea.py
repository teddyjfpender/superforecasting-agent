"""BEA (NIPA) provider — ported one-to-one from ``marketFetch.ts``.

The fixed logic + live-probed quirks carried over verbatim (this is the code the
BEA ``0.0000`` wall was fixed in — it lived client-side where the honesty tests
could not see it; now it is server-side and covered):
* ``Year=LAST5`` is INVALID for NIPA (API error 201 → empty ``Data`` → the old
  ``num('') === 0`` fabricated a ``0.0000`` on every row). We send TWO EXPLICIT
  years (last year + this year) covering the latest + prior quarters.
* NIPA responses carry EVERY LINE of the table (31 for T20305); filter to the
  HEADLINE line (``LineNumber == '1'``) with a per-series ``line`` override.
* ``DataValue`` is comma-grouped (``"21,634,948"``) — strip commas before
  parsing.
* An error / empty payload yields ``value = None`` (THE LAW) — absence renders
  "—", never a fabricated zero.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from forecasting.marketdata.model import Quote, SeriesRef, num

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
_YEAR_RE = re.compile(r"^\d{4}$")


def _parse_val(row: dict | None) -> float | None:
    if not row:
        return None
    raw = row.get("DataValue")
    if raw in (None, ""):
        return None
    return num(str(raw).replace(",", ""))


def _period_as_of(period: str) -> int:
    """Map a BEA ``TimePeriod`` (``"2026Q1"`` / ``"2026"``) to epoch ms, else 0."""

    m = _QUARTER_RE.match(period or "")
    if m:
        month = (int(m.group(2)) - 1) * 3 + 1
        dt = datetime(int(m.group(1)), month, 1, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if _YEAR_RE.match(period or ""):
        dt = datetime(int(period), 1, 1, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    return 0


def parse_bea(payload: object, series: SeriesRef) -> Quote:
    """Parse a BEA NIPA response into a single headline-line :class:`Quote`."""

    data = payload if isinstance(payload, dict) else {}
    results = (((data.get("BEAAPI") or {}).get("Results") or {}) if isinstance(data.get("BEAAPI"), dict) else {})
    rows = results.get("Data") if isinstance(results, dict) else None
    rows = rows if isinstance(rows, list) else []

    line = series.line or "1"
    line_rows = sorted(
        (
            r
            for r in rows
            if isinstance(r, dict) and str(r.get("LineNumber") or "1") == line and r.get("TimePeriod")
        ),
        key=lambda r: str(r.get("TimePeriod")),
    )

    last = line_rows[-1] if line_rows else None
    prev = line_rows[-2] if len(line_rows) > 1 else None
    value = _parse_val(last)
    prev_value = _parse_val(prev)
    change = value - prev_value if value is not None and prev_value is not None else None
    change_pct = (change / prev_value * 100.0) if change is not None and prev_value else None

    period = str(last.get("TimePeriod")) if last and last.get("TimePeriod") else ""
    history = [v for v in (_parse_val(r) for r in line_rows) if v is not None][-12:]

    return Quote(
        symbol=series.symbol,
        provider="bea",
        name=series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=prev_value,
        asOf=_period_as_of(period),
        unit=series.unit,
        history=history,
    )


class BeaProvider:
    name = "bea"
    needs_key = True

    def __init__(self, get_json=None) -> None:
        from forecasting.marketdata.provider import default_get_json

        self._get_json = get_json or default_get_json

    def _url(self, table: str, api_key: str) -> str:
        this_year = datetime.now(timezone.utc).year
        # Two explicit years cover latest + prior quarters (NEVER Year=LAST5).
        years = f"{this_year - 1},{this_year}"
        return (
            f"https://apps.bea.gov/api/data/?UserID={api_key}&method=GetData"
            f"&datasetname=NIPA&TableName={table}&Frequency=Q&Year={years}&ResultFormat=JSON"
        )

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        if not api_key:
            return []  # keyed provider with no key → skipped (client parity)
        quotes: list[Quote] = []
        for s in series:
            payload = self._get_json(self._url(s.symbol, api_key))
            quotes.append(parse_bea(payload, s))
        return quotes


__all__ = ["BeaProvider", "parse_bea"]
