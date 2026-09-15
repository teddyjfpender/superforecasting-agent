"""Brazil Central Bank SGS series; identifiers and units come from the catalog."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from pydantic import JsonValue

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, num
from forecasting.marketdata.parsing import catalog_entry, observation_quote
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    default_get_json,
)
from protocol.data_desk import ChangeBasis


def parse_bcb(
    payload: JsonValue,
    ref: SeriesRef,
    *,
    as_of: date | None = None,
    basis: ChangeBasis = "previous_observation",
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
    return observation_quote(ref, points, basis=basis)


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
            entry = catalog_entry(ref)
            if not ref.symbol.isdigit():
                raise ValueError("BCB requires a numeric SGS identifier")
            base = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{ref.symbol}/dados"
            today = self._clock()
            value = parse_bcb(
                self._get(base + "/ultimos/20?formato=json"),
                ref,
                as_of=today,
                basis=entry.change_basis,
            )
            if entry.change_basis == "last_transition" and value.comparison is None:
                for days in (365, 3650):
                    query = urlencode({
                        "formato": "json",
                        "dataInicial": (today - timedelta(days=days)).strftime(
                            "%d/%m/%Y"
                        ),
                        "dataFinal": today.strftime("%d/%m/%Y"),
                    })
                    try:
                        history = parse_bcb(
                            self._get(base + "?" + query),
                            ref,
                            as_of=today,
                            basis=entry.change_basis,
                        )
                    except ProviderFailure:
                        logging.getLogger(__name__).warning(
                            "BCB history unavailable for %s; retaining latest measurement",
                            ref.symbol,
                        )
                        break
                    if history.value == value.value and history.asOf == value.asOf:
                        value = history
                    if value.comparison is not None:
                        break
            result.append(value)
        return result
