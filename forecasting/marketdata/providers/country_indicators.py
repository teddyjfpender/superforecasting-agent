"""World Bank and IMF desk adapters using the existing evidence-source parsers.

DataMapper values remain estimates: its endpoint does not identify the observed
versus projected boundary for each country. Neither source supplies a reliable
per-observation publication time, so retrieval time must not stand in for it.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from pydantic import JsonValue

from forecasting.marketdata.model import (
    DatedValue,
    Quote,
    SeriesRef,
    change_columns,
    epoch_ms,
    num,
)
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    default_get_json,
)
from forecasting.sources.macroeconomic import (
    _imf_observations_from_payload,
    _imf_source_parts,
    _worldbank_observations_from_payload,
    _worldbank_source_parts,
)


def _annual_quote(series: SeriesRef, observations: list) -> Quote:
    points: dict[str, DatedValue] = {}
    for observation in observations:
        year = observation.observation_date[:4]
        point = DatedValue(
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            value=num(observation.value),
            published_at=observation.published_at,
        )
        if year in points and points[year] != point:
            raise ProviderFailure(
                "invalid_response", "Provider returned conflicting annual observations"
            )
        points[year] = point
    history = [point for _, point in sorted(points.items()) if point.value is not None][
        -30:
    ]
    latest = history[-1] if history else None
    previous = history[-2].value if len(history) > 1 else None
    value = latest.value if latest else None
    change, change_pct = change_columns(value, previous)
    return Quote(
        symbol=series.symbol,
        provider=series.provider,
        name=series.name,
        category=series.category,
        unit=series.unit,
        value=value,
        change=change,
        changePct=change_pct,
        prevClose=None,
        asOf=epoch_ms(latest.period_end) if latest else 0,
        history=[p.value for p in history if p.value is not None],
        dated_history=history,
        kind="estimate" if series.provider == "imf" else "observation",
    )


def parse_worldbank(payload: JsonValue, series: SeriesRef) -> Quote:
    country, indicator = _worldbank_source_parts(series.symbol)
    observations = _worldbank_observations_from_payload(
        payload, country=country, indicator=indicator
    )
    return _annual_quote(series, observations)


def parse_imf(payload: JsonValue, series: SeriesRef, *, endpoint: str) -> Quote:
    indicator, country = _imf_source_parts(series.symbol)
    observations = _imf_observations_from_payload(
        payload, indicator=indicator, country=country, endpoint=endpoint
    )
    return _annual_quote(series, observations)


class WorldBankProvider(IndependentSeries):
    name = "worldbank"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            country, indicator = _worldbank_source_parts(ref.symbol)
            endpoint = f"https://api.worldbank.org/v2/country/{quote(country, safe='')}/indicator/{quote(indicator, safe='')}"
            result.append(
                parse_worldbank(
                    self._get_json(
                        endpoint + "?" + urlencode({"format": "json", "per_page": 100})
                    ),
                    ref,
                )
            )
        return result


class ImfProvider(IndependentSeries):
    name = "imf"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            indicator, country = _imf_source_parts(ref.symbol)
            endpoint = f"https://www.imf.org/external/datamapper/api/v1/{quote(indicator, safe='')}/{quote(country, safe='')}"
            result.append(parse_imf(self._get_json(endpoint), ref, endpoint=endpoint))
        return result
