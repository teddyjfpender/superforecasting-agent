"""Brazil Central Bank SGS series; identifiers and units come from the catalog."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone

from pydantic import JsonValue

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, num
from forecasting.marketdata.parsing import catalog_entry, observation_quote
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    default_get_json,
)


def parse_bcb(
    payload: JsonValue, ref: SeriesRef, *, as_of: date | None = None
) -> Quote:
    if not isinstance(payload, list):
        raise ProviderFailure(
            "invalid_response", "BCB did not return an observation list"
        )
    points = []
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("data"), str):
            raise ProviderFailure("invalid_response", "BCB observation date is missing")
        period = datetime.strptime(row["data"], "%d/%m/%Y").date().isoformat()
        if as_of is not None and period > as_of.isoformat():
            continue  # Future effective rates are not current observations.
        value = num(row.get("valor"))
        if value is None:
            raise ProviderFailure(
                "invalid_response", "BCB returned an invalid numeric measurement"
            )
        points.append(DatedValue(period_start=period, period_end=period, value=value))
    return observation_quote(ref, points)


class BcbProvider(IndependentSeries):
    name = "bcb"
    needs_key = False

    def __init__(
        self,
        get_json: JsonGetter | None = None,
        *,
        clock: Callable[[], date] | None = None,
    ):
        self._get = get_json or default_get_json
        self._clock = clock or (lambda: datetime.now(timezone.utc).date())

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        for ref in series:
            catalog_entry(ref)
            if not ref.symbol.isdigit():
                raise ValueError("BCB requires a numeric SGS identifier")
            endpoint = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{ref.symbol}/dados/ultimos/20?formato=json"
            result.append(parse_bcb(self._get(endpoint), ref, as_of=self._clock()))
        return result
