"""Strict SDMX CSV measurements for qualified ABS and BIS series.

The catalog pins the flow version, complete series key, units and base period.
A changed classification or rebasing fails visibly instead of reusing a label.
"""

from __future__ import annotations

import csv
import io
import logging
from urllib.parse import quote

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, num
from forecasting.marketdata.parsing import (
    catalog_entry,
    observation_quote,
    period_bounds,
)
from forecasting.marketdata.provider import (
    IndependentSeries,
    ProviderFailure,
    TextGetter,
    default_get_text,
)
from protocol.data_desk import ChangeBasis


def parse_sdmx_csv(
    text: str | None,
    ref: SeriesRef,
    dimensions: dict[str, str],
    *,
    basis: ChangeBasis = "previous_observation",
) -> Quote:
    reader = csv.DictReader(io.StringIO(text or ""))
    expected = {
        key: value for key, value in dimensions.items() if not key.startswith("_")
    }
    if not reader.fieldnames or not {"TIME_PERIOD", "OBS_VALUE", *expected}.issubset(
        reader.fieldnames
    ):
        raise ProviderFailure(
            "invalid_response", "SDMX response is missing measurement metadata"
        )
    points = []
    for row in reader:
        for key, value in expected.items():
            if row.get(key) != value:
                raise ProviderFailure(
                    "invalid_response", f"SDMX measurement mismatch: {key}"
                )
        start, end = period_bounds(row["TIME_PERIOD"])
        raw = row.get("OBS_VALUE")
        value = num(raw)
        if raw not in {"", None} and value is None:
            raise ProviderFailure(
                "invalid_response", "SDMX response has a nonnumeric observation"
            )
        points.append(
            DatedValue(
                period_start=start,
                period_end=end,
                value=value,
                status=row.get("OBS_STATUS") or None,
            )
        )
    return observation_quote(ref, points, basis=basis)


class SdmxProvider(IndependentSeries):
    needs_key = False

    def __init__(self, name: str, *, get_text: TextGetter | None = None):
        self.name = name
        if name not in {"abs", "bis", "oecd"}:
            raise ValueError("Unsupported SDMX source")
        self._get = get_text or (
            lambda url: default_get_text(
                url,
                headers={
                    "Accept": "application/vnd.sdmx.data+csv;version=2.0.0"
                    if name == "bis"
                    else "text/csv"
                },
            )
        )

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            entry = catalog_entry(ref)
            if self.name == "abs":
                endpoint = (
                    "https://data.api.abs.gov.au/rest/data/"
                    + quote(ref.symbol, safe="/.,")
                    + "?lastNObservations=24"
                )
            elif self.name == "oecd":
                endpoint = (
                    "https://sdmx.oecd.org/public/rest/v1/data/"
                    + quote(ref.symbol, safe="/.,")
                    + "?lastNObservations=24&format=csvfile"
                )
            else:
                endpoint = (
                    "https://stats.bis.org/api/v2/data/dataflow/BIS/"
                    + quote(ref.symbol, safe="/.,")
                    + "?lastNObservations=120&format=csv"
                )
            value = parse_sdmx_csv(
                self._get(endpoint), ref, entry.dimensions, basis=entry.change_basis
            )
            if (
                self.name == "bis"
                and entry.change_basis == "last_transition"
                and value.comparison is None
            ):
                try:
                    history = parse_sdmx_csv(
                        self._get(
                            endpoint.replace(
                                "lastNObservations=120", "lastNObservations=600"
                            )
                        ),
                        ref,
                        entry.dimensions,
                        basis=entry.change_basis,
                    )
                except ProviderFailure:
                    logging.getLogger(__name__).warning(
                        "BIS history unavailable for %s; retaining latest measurement",
                        ref.symbol,
                    )
                else:
                    if history.value == value.value and history.asOf == value.asOf:
                        value = history
            result.append(value)
        return result
