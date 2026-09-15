"""Open-Meteo forecast, air-quality and reanalysis desk adapters.

Reuse the ingestion parsers. Blended forecasts have no single published issue
instant; retrieval time must never be substituted for it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pydantic import JsonValue

from forecasting.marketdata.model import DatedValue, Quote, SeriesRef, epoch_ms, num
from forecasting.marketdata.parsing import catalog_entry, observation_quote
from forecasting.marketdata.provider import (
    JsonGetter,
    ProviderFailure,
    default_get_json,
)
from forecasting.sources.openmeteo import (
    load_openmeteo_air_quality_forecasts,
    load_openmeteo_daily_forecasts,
    load_openmeteo_historical_weather,
)

UNITS = {
    "temperature_2m_max": "°C",
    "temperature_2m_min": "°C",
    "temperature_2m_mean": "°C",
    "precipitation_sum": "mm",
    "wind_speed_10m_max": "km/h",
    "pm2_5": "μg/m³",
    "us_aqi": "USAQI",
}


class OpenMeteoProvider:
    name = "openmeteo"
    needs_key = False

    def __init__(
        self,
        get_json: JsonGetter | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self._get = get_json or default_get_json
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def batch_key(self, ref: SeriesRef) -> str:
        # All variables at one location/dataset share a single source request.
        return ref.symbol.rpartition("/")[0]

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        result = []
        groups: dict[tuple[float, float, str], list] = {}
        for ref in series:
            entry = catalog_entry(ref)
            mode = entry.dimensions.get("dataset", "forecast")
            if (
                entry.location is None
                or entry.dimensions.get("variable") not in UNITS
                or mode not in {"forecast", "airquality", "reanalysis"}
            ):
                raise ValueError(
                    "Open-Meteo requires a qualified location, dataset and variable"
                )
            groups.setdefault(
                (entry.location.latitude, entry.location.longitude, mode), []
            ).append((ref, entry))
        now = self._clock()
        for (latitude, longitude, mode), entries in groups.items():

            def read(endpoint: str, label: str) -> JsonValue:
                payload = self._get(endpoint)
                if not isinstance(payload, dict):
                    raise ProviderFailure(
                        "invalid_response", "Open-Meteo returned an invalid measurement"
                    )
                lat, lon = num(payload.get("latitude")), num(payload.get("longitude"))
                if (
                    lat is None
                    or lon is None
                    or abs(lat - latitude) > 0.5
                    or abs(lon - longitude) > 0.5
                ):
                    raise ProviderFailure(
                        "invalid_response",
                        "Open-Meteo grid does not match the requested location",
                    )
                if payload.get("utc_offset_seconds") != 0:
                    raise ProviderFailure(
                        "invalid_response", "Open-Meteo returned a different time zone"
                    )
                units = payload.get(
                    "hourly_units" if mode == "airquality" else "daily_units", {}
                )
                if not isinstance(units, dict) or any(
                    units.get(entry.dimensions["variable"])
                    != UNITS[entry.dimensions["variable"]]
                    for _, entry in entries
                ):
                    raise ProviderFailure(
                        "invalid_response",
                        "Open-Meteo returned different measurement units",
                    )
                return payload

            location = f"{latitude},{longitude}"
            if mode == "airquality":
                records = load_openmeteo_air_quality_forecasts(
                    location, limit=120, forecast_days=5, _read_json_endpoint=read
                )
                date_field = "forecast_time"
            elif mode == "reanalysis":
                end = now.date() - timedelta(days=7)
                records = load_openmeteo_historical_weather(
                    location,
                    limit=30,
                    start_date=(end - timedelta(days=29)).isoformat(),
                    end_date=end.isoformat(),
                    _read_json_endpoint=read,
                )
                date_field = "observation_date"
            else:
                records = load_openmeteo_daily_forecasts(
                    location, limit=7, forecast_days=7, _read_json_endpoint=read
                )
                date_field = "forecast_date"
            for ref, entry in entries:
                variable = entry.dimensions["variable"]
                points = [
                    DatedValue(
                        period_start=getattr(row, date_field),
                        period_end=getattr(row, date_field),
                        value=getattr(row, variable),
                    )
                    for row in records
                ]
                quote = observation_quote(ref, points)
                if mode == "reanalysis":
                    result.append(replace(quote, kind="reanalysis"))
                    continue
                upcoming = (
                    [
                        point
                        for point in points
                        if epoch_ms(point.period_start)
                        >= int(
                            now.replace(minute=0, second=0, microsecond=0).timestamp()
                            * 1000
                        )
                    ]
                    if mode == "airquality"
                    else points
                )
                first = upcoming[0] if upcoming else None
                end = None
                if first:
                    start = datetime.fromisoformat(
                        first.period_start.replace("Z", "+00:00")
                    )
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    end = (
                        start + timedelta(hours=1)
                        if mode == "airquality"
                        else start + timedelta(days=1)
                    ).isoformat()
                result.append(
                    replace(
                        quote,
                        value=first.value if first else None,
                        asOf=epoch_ms(first.period_start) if first else 0,
                        change=None,
                        changePct=None,
                        kind="forecast",
                        dated_history=points,
                        history=[
                            point.value for point in points if point.value is not None
                        ],
                        valid_from=first.period_start if first else None,
                        valid_until=end,
                    )
                )
        return result
