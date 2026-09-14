"""BLS monthly series using the shared source identity and revision parser.

Observation periods remain separate from publication. Annual-average M13 values
are excluded from monthly histories. Network and schema failures are explicit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, num
from forecasting.marketdata.provider import (
    IndependentSeries,
    JsonGetter,
    ProviderFailure,
    default_get_json,
)


def parse_bls(payload: object, series: SeriesRef) -> Quote:
    """Reuse the source contract for catalog-bound monthly BLS measurements."""
    from forecasting.marketdata.parsing import observation_quote, period_bounds
    from forecasting.models import ValidationError
    from forecasting.sources.bls_parsing import parse_bls_observations

    try:
        records = parse_bls_observations(payload, series.symbol, limit=36)
    except ValidationError:
        raise ProviderFailure(
            "invalid_response",
            "BLS returned an invalid measurement or rejected the request",
        ) from None
    points = []
    for record in records:
        # M13 is an annual average, not a thirteenth monthly observation.
        if record.period == "M13":
            continue
        if not record.period.startswith("M"):
            raise ProviderFailure(
                "invalid_response", "BLS returned a different observation frequency"
            )
        start, end = period_bounds(record.observation_date[:7])
        points.append(
            DatedValue(period_start=start, period_end=end, value=num(record.value))
        )
    return observation_quote(series, points)


class BlsProvider(IndependentSeries):
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

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
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
