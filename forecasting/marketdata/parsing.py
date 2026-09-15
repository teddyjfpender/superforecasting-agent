"""Shared dated-measurement assembly and exact catalog binding lookup.

No fetching or ledger writes live here. Provider parsers retain ownership of
source-specific dimensions, units and revision semantics.
"""

from __future__ import annotations

import calendar
from datetime import date

from forecasting.marketdata.catalog import DataSeries, load_catalog
from forecasting.marketdata.model import (
    DatedValue,
    Quote,
    SeriesRef,
    change_columns,
    epoch_ms,
)
from forecasting.marketdata.provider import ProviderFailure


def period_bounds(value: str) -> tuple[str, str]:
    """Return the declared period, never treating its boundary as publication."""
    if len(value) == 4 and value.isdigit():
        return date(int(value), 1, 1).isoformat(), date(int(value), 12, 31).isoformat()
    if len(value) == 7 and value[4:6] == "-Q" and value[6] in "1234":
        year, quarter = int(value[:4]), int(value[6])
        month = quarter * 3
        return date(year, month - 2, 1).isoformat(), date(
            year, month, calendar.monthrange(year, month)[1]
        ).isoformat()
    if len(value) == 7:
        year, month = map(int, value.split("-"))
        return date(year, month, 1).isoformat(), date(
            year, month, calendar.monthrange(year, month)[1]
        ).isoformat()
    parsed = date.fromisoformat(value)
    return parsed.isoformat(), parsed.isoformat()


def observation_quote(ref: SeriesRef, points: list[DatedValue]) -> Quote:
    unique: dict[str, DatedValue] = {}
    for point in points:
        if point.period_start in unique and unique[point.period_start] != point:
            raise ProviderFailure(
                "invalid_response",
                "Provider returned conflicting observations for one period",
            )
        unique[point.period_start] = point
    history = sorted(unique.values(), key=lambda point: point.period_start)[-36:]
    usable = [point for point in history if point.value is not None]
    last = usable[-1] if usable else None
    previous = usable[-2].value if len(usable) > 1 else None
    change, percent = change_columns(last.value if last else None, previous)
    return Quote(
        symbol=ref.symbol,
        provider=ref.provider,
        name=ref.name,
        category=ref.category,
        value=last.value if last else None,
        change=change,
        changePct=percent,
        prevClose=None,
        asOf=epoch_ms(last.period_start) if last else 0,
        unit=ref.unit,
        history=[point.value for point in usable if point.value is not None],
        dated_history=history,
        kind="observation",
    )


def catalog_entry(ref: SeriesRef) -> DataSeries:
    entry = next(
        (entry for entry in load_catalog().series if entry.id == ref.catalog_id), None
    )
    if entry is None or entry.provider != ref.provider or entry.symbol != ref.symbol:
        raise ValueError("This source requires an exact catalog measurement binding")
    return entry
