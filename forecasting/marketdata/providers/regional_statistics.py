"""SingStat and IBGE measurements with explicit table, row and unit bindings."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from pydantic import JsonValue

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, num
from forecasting.marketdata.parsing import (
    catalog_entry,
    observation_quote,
    period_bounds,
)
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    default_get_json,
)

_MONTHS = {
    month: i + 1
    for i, month in enumerate((
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ))
}


def parse_singstat(
    payload: JsonValue, ref: SeriesRef, dimensions: dict[str, str]
) -> Quote:
    data = payload.get("Data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ProviderFailure("invalid_response", "SingStat returned no table metadata")
    for key in ("id", "title", "frequency"):
        if data.get(key) != dimensions[key]:
            raise ProviderFailure(
                "invalid_response", f"SingStat measurement mismatch: {key}"
            )
    rows = data.get("row")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ProviderFailure(
            "invalid_response", "SingStat must return the selected row only"
        )
    row = rows[0]
    for key in ("seriesNo", "rowText", "uoM"):
        if row.get(key) != dimensions[key]:
            raise ProviderFailure("invalid_response", f"SingStat row mismatch: {key}")
    points = []
    columns = row.get("columns")
    if not isinstance(columns, list):
        raise ProviderFailure("invalid_response", "SingStat observations are missing")
    for column in columns:
        year, month = column["key"].split()
        start, end = period_bounds(f"{year}-{_MONTHS[month]:02}")
        value = num(column.get("value"))
        if value is None:
            raise ProviderFailure(
                "invalid_response",
                "SingStat returned a missing or nonnumeric observation",
            )
        points.append(DatedValue(period_start=start, period_end=end, value=value))
    # dataLastUpdated describes the table; dateGenerated describes the request.
    # Neither establishes when each individual observation was first released.
    return observation_quote(ref, points)


def parse_ibge(payload: JsonValue, ref: SeriesRef, dimensions: dict[str, str]) -> Quote:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ProviderFailure(
            "invalid_response", "IBGE did not return a table with metadata"
        )
    points = []
    for row in payload[1:]:
        if not isinstance(row, dict):
            raise ProviderFailure("invalid_response", "IBGE returned an invalid row")
        for key, value in dimensions.items():
            if key != "_table" and row.get(key) != value:
                raise ProviderFailure(
                    "invalid_response", f"IBGE measurement mismatch: {key}"
                )
        period = row.get("D3C", "")
        if len(period) != 6 or not period.isdigit():
            raise ProviderFailure(
                "invalid_response", "IBGE returned an invalid monthly period"
            )
        start, end = period_bounds(period[:4] + "-" + period[4:])
        raw = row.get("V")
        value = num(raw)
        if value is None and raw not in {"...", "..", "-", None, ""}:
            raise ProviderFailure(
                "invalid_response", "IBGE returned a nonnumeric observation"
            )
        points.append(DatedValue(period_start=start, period_end=end, value=value))
    return observation_quote(ref, points)


class SingStatProvider(IndependentSeries):
    name = "singstat"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None):
        self._get = get_json or default_get_json

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            entry = catalog_entry(ref)
            query = urlencode({
                "seriesNoORrowNo": entry.dimensions["seriesNo"],
                "limit": 24,
                "sortBy": "key desc",
            })
            endpoint = (
                "https://tablebuilder.singstat.gov.sg/api/table/tabledata/"
                + quote(entry.dimensions["id"], safe="")
                + "?"
                + query
            )
            result.append(parse_singstat(self._get(endpoint), ref, entry.dimensions))
        return result


class IbgeProvider(IndependentSeries):
    name = "ibge"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None):
        self._get = get_json or default_get_json

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            entry = catalog_entry(ref)
            dimensions = entry.dimensions
            endpoint = (
                "https://apisidra.ibge.gov.br/values/t/"
                + quote(dimensions["_table"], safe="")
                + "/n1/1/v/"
                + quote(dimensions["D2C"], safe="")
                + "/p/last%2024?formato=json"
            )
            result.append(parse_ibge(self._get(endpoint), ref, dimensions))
        return result
