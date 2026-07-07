"""FRED (St. Louis Fed) provider.

FRED has TWO client paths (``needs_key`` is False — the provider degrades to the
keyless CSV rather than being skipped):
* WITH a key — the official JSON observations API
  (``/fred/series/observations?...&sort_order=desc&limit=30``), most reliable.
  ``parse_fred`` reads the DESC window, reverses it, and keeps the newest value +
  a ``history`` sparkline.
* WITHOUT a key — the keyless public CSV (``fredgraph.csv``), rows oldest→newest
  with ``"."`` for missing values. ``parse_fred_csv`` keeps the trailing REAL
  rows (the ``"."`` rows dropped as null).

Both paths now carry a ``history`` sparkline (the trailing ~30 REAL observations,
oldest→newest) and compute ``change`` against the prior DISTINCT observation date
— duplicate ``observation_date`` vintages are collapsed so the delta is never a
fabricated ``0`` measured against the newest reading itself. A genuinely flat
series (e.g. FEDFUNDS 3.63 → 3.63) still reports a MEASURED ``0.0`` — that is
honest, and distinct from ``None``. An error / empty payload yields
``value = None`` (THE LAW) — absence renders "—", never a fabricated ``0``.
``prevClose`` stays absent (the source does not publish a distinct prior close).

The missing-observation rule (``forecasting/observation_freshness.py``)
=====================================================================
Daily FRED series publish with a lag (``DCOILWTICO`` is typically T-1/T-2
business days) and carry NO row on weekends/holidays BY DESIGN. So ``asOf`` is
ALWAYS the newest observation's OWN date — never ``Date.now()`` — which lets the
tape report the publication lag honestly instead of fabricating a today-dated
row (a conjured ``2026-06-30`` when the last real row is ``2026-06-29 = 71.87``
is a lie; carrying ``71.87 as of 2026-06-29`` is truth). ``fetch`` then ages the
newest reading against today: an ORDINARY lag (within the series' own cadence)
keeps the value; an EXCESSIVE lag — the daily feed has gone dark past a full
trading week — blanks it to ``None`` (THE LAW) so a genuinely stale number is
never dressed as current. The threshold is cadence-aware (inferred from the
observation spacing), so a monthly series read a few weeks after its print is
NOT wrongly blanked. The pure parsers stay deterministic — aging happens only at
the ``fetch`` boundary, where "today" enters.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from urllib.parse import quote as _urlquote

from forecasting.marketdata.model import Quote, SeriesRef, change_columns, epoch_ms, num
from forecasting.marketdata.provider import (
    JsonGetter,
    TextGetter,
    default_get_json,
    default_get_text,
)
from forecasting.observation_freshness import (
    assess_observation_freshness,
    cadence_aware_max_business_days,
    infer_cadence_business_days,
)

_LINE_RE = re.compile(r"\r?\n")

# Trailing window kept for the sparkline (and fetched from the JSON API).
_HISTORY_LIMIT = 30


def _apply_missing_observation_rule(
    quote: Quote, date_strs: list[str], as_of_reference: date
) -> Quote:
    """Blank the value when the newest observation is EXCESSIVELY stale.

    Ordinary publication lag keeps the value (``asOf`` already carries the honest
    observation date). Excessive lag — the feed has gone dark past its own
    cadence — maps the value to ``None`` (THE LAW), preserving ``asOf`` +
    ``history`` so the age and shape stay visible. Cadence is inferred from the
    observation spacing so a monthly series is not blanked as a daily one.
    """

    dates = [d for d in date_strs if d]
    if not dates:
        return quote
    limit = cadence_aware_max_business_days(infer_cadence_business_days(dates))
    assessment = assess_observation_freshness(
        dates[-1], as_of_reference=as_of_reference, max_business_days=limit
    )
    if assessment.is_missing:
        return replace(quote, value=None, change=None, changePct=None)
    return quote


def _finalize(
    rows: list[tuple[str, float]],
    series: SeriesRef,
    *,
    as_of_reference: date | None = None,
) -> Quote:
    """Build a Quote from REAL ``(date, value)`` rows in oldest→newest order.

    Duplicate ``observation_date`` vintages are collapsed (last wins) so the
    ``change`` reaches back to the prior DISTINCT date instead of the newest
    reading itself; ``history`` is the trailing ``_HISTORY_LIMIT`` values. When
    ``as_of_reference`` is given (the ``fetch`` boundary passes today), the
    missing-observation rule blanks an excessively-stale value; when it is
    ``None`` (the pure-parser tests), the reading is never aged.
    """

    # Collapse duplicate observation dates (revision vintages), keeping the last
    # value seen for each date while preserving chronological order.
    deduped: list[tuple[str, float]] = []
    for obs_date, value in rows:
        if deduped and deduped[-1][0] == obs_date:
            deduped[-1] = (obs_date, value)
        else:
            deduped.append((obs_date, value))

    window = deduped[-_HISTORY_LIMIT:]
    history = [v for _, v in window]

    last = deduped[-1] if deduped else None
    prev = deduped[-2] if len(deduped) > 1 else None  # prior DISTINCT date
    value = last[1] if last else None
    change, change_pct = change_columns(value, prev[1] if prev else None)
    as_of = epoch_ms(last[0]) if last and last[0] else 0

    quote = Quote(
        symbol=series.symbol,
        provider="fred",
        name=series.name,
        category=series.category,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=None,  # FRED publishes no distinct prior close
        asOf=as_of,
        unit=series.unit,
        history=history,
    )
    if as_of_reference is not None and last is not None and value is not None:
        quote = _apply_missing_observation_rule(
            quote, [d for d, _ in deduped], as_of_reference
        )
    return quote


def parse_fred(
    payload: object, series: SeriesRef, *, as_of_reference: date | None = None
) -> Quote:
    """Parse the keyed JSON observations (DESC window): newest value + history."""

    obs = payload.get("observations") if isinstance(payload, dict) else None
    obs = obs if isinstance(obs, list) else []
    rows: list[tuple[str, float]] = []
    for entry in obs:  # arrives newest→oldest (sort_order=desc)
        if not isinstance(entry, dict):
            continue
        value = num(entry.get("value"))
        if value is None:  # "." missing observations drop as null
            continue
        obs_date = entry.get("date")
        rows.append((obs_date if isinstance(obs_date, str) else "", value))
    rows.reverse()  # → oldest→newest for history + prior-date change
    return _finalize(rows, series, as_of_reference=as_of_reference)


def parse_fred_csv(
    csv_text: str, series: SeriesRef, *, as_of_reference: date | None = None
) -> Quote:
    """Parse the keyless ``fredgraph.csv`` (oldest→newest, ``"."`` = missing).

    Keeps the trailing REAL rows (``"."`` values dropped as null) and builds a
    ``history`` sparkline + change vs the prior distinct observation date.
    """

    text = csv_text if isinstance(csv_text, str) else ""
    lines = _LINE_RE.split(text.strip())[1:]  # drop the header row
    rows: list[tuple[str, float]] = []
    for line in lines:
        comma = line.find(",")
        if comma < 0:
            continue
        obs_date = line[:comma]
        value = num(line[comma + 1 :])
        if value is not None:
            rows.append((obs_date, value))
    return _finalize(rows, series, as_of_reference=as_of_reference)


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
            f"&file_type=json&sort_order=desc&limit={_HISTORY_LIMIT}"
        )

    def _csv_url(self, symbol: str) -> str:
        return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={_urlquote(symbol, safe='')}"

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        reference = date.today()  # the impure boundary where "today" enters
        quotes: list[Quote] = []
        for s in series:
            if api_key:
                payload = self._get_json(self._json_url(s.symbol, api_key))
                quotes.append(parse_fred(payload, s, as_of_reference=reference))
            else:
                csv_text = self._get_text(self._csv_url(s.symbol))
                quotes.append(parse_fred_csv(csv_text or "", s, as_of_reference=reference))
        return quotes


__all__ = ["FredProvider", "parse_fred", "parse_fred_csv"]
