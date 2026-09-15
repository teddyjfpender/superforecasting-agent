"""Eurostat JSON-stat and ECB SDMX CSV adapters with exact dimension checks."""

from __future__ import annotations

import csv
import io
from urllib.parse import quote, urlencode

from pydantic import JsonValue

from forecasting.marketdata.model import (
    DatedValue,
    Quote,
    SeriesRef,
    num,
)
from forecasting.marketdata.parsing import (
    catalog_entry,
    observation_quote,
    period_bounds,
)
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    TextGetter,
    default_get_json,
    default_get_text,
)


def parse_eurostat(
    payload: JsonValue, ref: SeriesRef, dimensions: dict[str, str]
) -> Quote:
    if not isinstance(payload, dict) or payload.get("class") != "dataset":
        raise ProviderFailure(
            "invalid_response", "Eurostat did not return a statistical dataset"
        )
    ids, sizes, dimension = (
        payload.get("id"),
        payload.get("size"),
        payload.get("dimension"),
    )
    if (
        not isinstance(ids, list)
        or not isinstance(sizes, list)
        or not isinstance(dimension, dict)
        or len(ids) != len(sizes)
    ):
        raise ProviderFailure(
            "invalid_response", "Eurostat dimension metadata is missing"
        )
    if set(ids) != {*dimensions, "time"} or len(ids) != len(set(ids)):
        raise ProviderFailure(
            "invalid_response",
            "Eurostat response does not contain every bound dimension",
        )
    if any(type(size) is not int or size < 1 for size in sizes):
        raise ProviderFailure(
            "invalid_response", "Eurostat returned invalid dimension sizes"
        )
    for name, size in zip(ids, sizes):
        if name == "time":
            continue
        item = dimension.get(name)
        category = item.get("category") if isinstance(item, dict) else None
        if not isinstance(category, dict):
            raise ProviderFailure(
                "invalid_response", "Eurostat dimension metadata is malformed"
            )
        indices = category.get("index", {})
        if isinstance(indices, list):
            indices = {code: index for index, code in enumerate(indices)}
        if size != 1 or indices != {dimensions.get(name): 0}:
            raise ProviderFailure(
                "invalid_response", f"Eurostat dimension mismatch: {name}"
            )
    time_dimension = dimension.get("time")
    time_category = (
        time_dimension.get("category") if isinstance(time_dimension, dict) else None
    )
    if not isinstance(time_category, dict):
        raise ProviderFailure("invalid_response", "Eurostat time metadata is malformed")
    times = time_category.get("index", {})
    if isinstance(times, list):
        times = {code: index for index, code in enumerate(times)}
    time_size = sizes[ids.index("time")]
    if (
        not isinstance(times, dict)
        or len(times) != time_size
        or any(type(index) is not int for index in times.values())
        or set(times.values()) != set(range(time_size))
    ):
        raise ProviderFailure(
            "invalid_response", "Eurostat time indices do not match their dimension"
        )
    values = payload.get("value", {})
    statuses = payload.get("status", {})

    for container in (values, statuses):
        if isinstance(container, dict):
            if any(
                not isinstance(key, str)
                or not key.isdigit()
                or str(int(key)) != key
                or int(key) >= time_size
                for key in container
            ):
                raise ProviderFailure(
                    "invalid_response", "Eurostat observation index is out of bounds"
                )
        elif not isinstance(container, list) or len(container) != time_size:
            raise ProviderFailure(
                "invalid_response", "Eurostat observation array has the wrong size"
            )

    def indexed(container, index):
        return (
            container.get(str(index))
            if isinstance(container, dict)
            else container[index]
            if isinstance(container, list) and index < len(container)
            else None
        )

    points = []
    for period, index in times.items():
        start, end = period_bounds(period)
        raw = indexed(values, index)
        value = num(raw)
        if raw is not None and value is None:
            raise ProviderFailure(
                "invalid_response", "Eurostat returned a nonnumeric measurement"
            )
        status = indexed(statuses, index)
        points.append(
            DatedValue(
                period_start=start,
                period_end=end,
                value=value,
                status=str(status) if status else None,
            )
        )
    # Dataset "updated" is a dataset refresh, not a per-observation publication.
    return observation_quote(ref, points)


def parse_ecb(text: str | None, ref: SeriesRef, dimensions: dict[str, str]) -> Quote:
    points = []
    reader = csv.DictReader(io.StringIO(text or ""))
    if not reader.fieldnames or not {
        "KEY",
        "UNIT",
        "UNIT_MULT",
        "TIME_PERIOD",
        "OBS_VALUE",
    }.issubset(reader.fieldnames):
        raise ProviderFailure(
            "invalid_response", "ECB response is missing measurement metadata"
        )
    for row in reader:
        if row.get("KEY") != dimensions["flow"] + "." + ref.symbol:
            raise ProviderFailure(
                "invalid_response", "ECB returned a different series identity"
            )
        if (
            row.get("UNIT") != dimensions["unit"]
            or row.get("UNIT_MULT") != dimensions["unit_mult"]
        ):
            raise ProviderFailure(
                "invalid_response", "ECB returned different measurement units"
            )
        start, end = period_bounds(row["TIME_PERIOD"])
        raw = row.get("OBS_VALUE")
        value = num(raw)
        if raw not in {"", None} and value is None:
            raise ProviderFailure(
                "invalid_response", "ECB returned a nonnumeric measurement"
            )
        points.append(
            DatedValue(
                period_start=start,
                period_end=end,
                value=value,
                status=row.get("OBS_STATUS") or None,
            )
        )
    return observation_quote(ref, points)


class EurostatProvider(IndependentSeries):
    name = "eurostat"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None):
        self._get = get_json or default_get_json

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            entry = catalog_entry(ref)
            dimensions = dict(entry.dimensions)
            dataset = dimensions.pop("dataset")
            endpoint = (
                "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
                + quote(dataset, safe="")
            )
            params = {**dimensions, "lang": "EN", "lastTimePeriod": "24"}
            result.append(
                parse_eurostat(
                    self._get(endpoint + "?" + urlencode(params)), ref, dimensions
                )
            )
        return result


class EcbProvider(IndependentSeries):
    name = "ecb"
    needs_key = False

    def __init__(self, get_text: TextGetter | None = None):
        self._get = get_text or default_get_text

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            entry = catalog_entry(ref)
            endpoint = (
                "https://data-api.ecb.europa.eu/service/data/"
                + quote(entry.dimensions["flow"], safe="")
                + "/"
                + quote(ref.symbol, safe="")
            )
            result.append(
                parse_ecb(
                    self._get(endpoint + "?format=csvdata&lastNObservations=30"),
                    ref,
                    entry.dimensions,
                )
            )
        return result
