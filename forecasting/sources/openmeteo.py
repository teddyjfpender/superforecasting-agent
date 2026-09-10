"""Load and parse Open-Meteo weather and air-quality evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .environment_records import (
    OpenMeteoDailyForecast, OpenMeteoAirQualityForecast,
    OpenMeteoHistoricalWeatherObservation,
)
from .values import _optional_str, _optional_float

def load_openmeteo_daily_forecasts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    forecast_days: int = 7,
    api_base_url: str = "https://api.open-meteo.com/v1/forecast",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[OpenMeteoDailyForecast]:
    """Load Open-Meteo daily forecast rows as weather evidence."""

    latitude, longitude = _openmeteo_coordinates(source)
    if limit <= 0:
        raise ValidationError("openmeteo import --limit must be positive")
    if forecast_days <= 0 or forecast_days > 16:
        raise ValidationError("openmeteo import --forecast-days must be between 1 and 16")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo forecast")
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValidationError("openmeteo forecast response must include a daily object")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list):
        raise ValidationError("openmeteo forecast daily response must include time")

    forecasts: list[OpenMeteoDailyForecast] = []
    for index, raw_date in enumerate(dates):
        forecast_date = _optional_str(raw_date)
        if not forecast_date:
            continue
        forecast_ts = _openmeteo_date_to_iso(forecast_date)
        forecast_dt = timestamp_to_datetime(forecast_ts) if forecast_ts else None
        if since_dt is not None and forecast_dt is not None and forecast_dt < since_dt:
            continue
        forecasts.append(
            OpenMeteoDailyForecast(
                latitude=latitude,
                longitude=longitude,
                forecast_date=forecast_date,
                temperature_2m_max=_openmeteo_daily_float(daily, "temperature_2m_max", index),
                temperature_2m_min=_openmeteo_daily_float(daily, "temperature_2m_min", index),
                precipitation_sum=_openmeteo_daily_float(daily, "precipitation_sum", index),
                wind_speed_10m_max=_openmeteo_daily_float(daily, "wind_speed_10m_max", index),
                source_name="Open-Meteo",
                entry_id=f"{latitude},{longitude}:{forecast_date}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "forecast_date": forecast_date,
                    "daily_units": payload.get("daily_units") if isinstance(payload.get("daily_units"), dict) else {},
                },
            )
        )
        if len(forecasts) >= limit:
            break
    return forecasts


def load_openmeteo_air_quality_forecasts(
    source: str,
    *,
    limit: int = 24,
    since: str | None = None,
    forecast_days: int = 5,
    api_base_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[OpenMeteoAirQualityForecast]:
    """Load Open-Meteo hourly air-quality forecast rows as evidence."""

    latitude, longitude = _openmeteo_coordinates(source, label="airquality")
    if limit <= 0:
        raise ValidationError("airquality import --limit must be positive")
    if forecast_days <= 0 or forecast_days > 7:
        raise ValidationError("airquality import --forecast-days must be between 1 and 7")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(
            [
                "us_aqi",
                "european_aqi",
                "pm10",
                "pm2_5",
                "carbon_monoxide",
                "nitrogen_dioxide",
                "ozone",
            ]
        ),
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo air quality")
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ValidationError("airquality response must include an hourly object")
    hourly = payload["hourly"]
    times = hourly.get("time")
    if not isinstance(times, list):
        raise ValidationError("airquality hourly response must include time")

    forecasts: list[OpenMeteoAirQualityForecast] = []
    for index, raw_time in enumerate(times):
        forecast_time = _optional_str(raw_time)
        if not forecast_time:
            continue
        forecast_ts = _openmeteo_time_to_iso(forecast_time)
        forecast_dt = timestamp_to_datetime(forecast_ts) if forecast_ts else None
        if since_dt is not None and forecast_dt is not None and forecast_dt < since_dt:
            continue
        stored_time = forecast_ts or forecast_time
        forecasts.append(
            OpenMeteoAirQualityForecast(
                latitude=latitude,
                longitude=longitude,
                forecast_time=stored_time,
                us_aqi=_openmeteo_hourly_float(hourly, "us_aqi", index),
                european_aqi=_openmeteo_hourly_float(hourly, "european_aqi", index),
                pm10=_openmeteo_hourly_float(hourly, "pm10", index),
                pm2_5=_openmeteo_hourly_float(hourly, "pm2_5", index),
                carbon_monoxide=_openmeteo_hourly_float(hourly, "carbon_monoxide", index),
                nitrogen_dioxide=_openmeteo_hourly_float(hourly, "nitrogen_dioxide", index),
                ozone=_openmeteo_hourly_float(hourly, "ozone", index),
                source_name="Open-Meteo Air Quality",
                entry_id=f"{latitude},{longitude}:{stored_time}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "forecast_time": stored_time,
                    "hourly_units": payload.get("hourly_units") if isinstance(payload.get("hourly_units"), dict) else {},
                },
            )
        )
        if len(forecasts) >= limit:
            break
    return forecasts


def load_openmeteo_historical_weather(
    source: str,
    *,
    limit: int = 30,
    since: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    api_base_url: str = "https://archive-api.open-meteo.com/v1/archive",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[OpenMeteoHistoricalWeatherObservation]:
    """Load Open-Meteo historical daily weather observations as evidence."""

    latitude, longitude, start_day, end_day = _openmeteo_history_request(
        source,
        start_date=start_date,
        end_date=end_date,
    )
    if limit <= 0:
        raise ValidationError("weatherhistory import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_day,
        "end_date": end_day,
        "daily": ",".join(
            [
                "temperature_2m_mean",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
        "timezone": "UTC",
    }
    endpoint = f"{api_base_url.rstrip('/')}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openmeteo historical weather")
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValidationError("weatherhistory response must include a daily object")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list):
        raise ValidationError("weatherhistory daily response must include time")

    observations: list[OpenMeteoHistoricalWeatherObservation] = []
    for index, raw_date in enumerate(dates):
        observation_date = _optional_str(raw_date)
        if not observation_date:
            continue
        observation_ts = _openmeteo_date_to_iso(observation_date)
        observation_dt = timestamp_to_datetime(observation_ts) if observation_ts else None
        if since_dt is not None and observation_dt is not None and observation_dt < since_dt:
            continue
        observations.append(
            OpenMeteoHistoricalWeatherObservation(
                latitude=latitude,
                longitude=longitude,
                observation_date=observation_date,
                temperature_2m_mean=_openmeteo_daily_float(daily, "temperature_2m_mean", index),
                temperature_2m_max=_openmeteo_daily_float(daily, "temperature_2m_max", index),
                temperature_2m_min=_openmeteo_daily_float(daily, "temperature_2m_min", index),
                precipitation_sum=_openmeteo_daily_float(daily, "precipitation_sum", index),
                wind_speed_10m_max=_openmeteo_daily_float(daily, "wind_speed_10m_max", index),
                source_name="Open-Meteo Historical Weather",
                entry_id=f"{latitude},{longitude}:{observation_date}",
                raw={
                    "latitude": payload.get("latitude", latitude),
                    "longitude": payload.get("longitude", longitude),
                    "observation_date": observation_date,
                    "daily_units": payload.get("daily_units") if isinstance(payload.get("daily_units"), dict) else {},
                },
            )
        )
        if len(observations) >= limit:
            break
    return observations


def _openmeteo_coordinates(source: str, *, label: str = "openmeteo") -> tuple[float, float]:
    value = (
        source.split(":", 1)[1].strip()
        if source.startswith(("openmeteo:", "airquality:", "weatherhistory:"))
        else source.strip()
    )
    parts = [part.strip() for part in value.replace("/", ",").split(",") if part.strip()]
    if len(parts) != 2:
        raise ValidationError(f"{label} source must be latitude,longitude")
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError as exc:
        raise ValidationError(f"{label} source must use numeric latitude and longitude") from exc
    if not -90 <= latitude <= 90:
        raise ValidationError(f"{label} latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValidationError(f"{label} longitude must be between -180 and 180")
    return latitude, longitude


def _openmeteo_history_request(
    source: str,
    *,
    start_date: str | None,
    end_date: str | None,
) -> tuple[float, float, str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source.strip()
    location = value
    query = ""
    if "?" in value:
        location, query = value.split("?", 1)
    query_params = dict(parse_qsl(query, keep_blank_values=False))
    start_value = start_date or query_params.get("start") or query_params.get("start_date")
    end_value = end_date or query_params.get("end") or query_params.get("end_date")
    if not start_value or not end_value:
        raise ValidationError("weatherhistory import requires --start-date and --end-date or source query start/end")
    latitude, longitude = _openmeteo_coordinates(location, label="weatherhistory")
    start_day = _openmeteo_history_date(start_value, field_name="weatherhistory start date")
    end_day = _openmeteo_history_date(end_value, field_name="weatherhistory end date")
    if start_day > end_day:
        raise ValidationError("weatherhistory start date must be on or before end date")
    return latitude, longitude, start_day, end_day


def _openmeteo_history_date(value: str, *, field_name: str) -> str:
    parsed = parse_timestamp(value, field_name=field_name)
    if not parsed:
        raise ValidationError(f"{field_name} is required")
    return parsed[:10]


def _openmeteo_date_to_iso(value: str) -> str | None:
    try:
        return parse_timestamp(value, field_name="openmeteo forecast date")
    except ValidationError:
        return None


def _openmeteo_time_to_iso(value: str) -> str | None:
    try:
        return parse_timestamp(value, field_name="openmeteo forecast time")
    except ValidationError:
        return None


def _openmeteo_daily_float(daily: dict, key: str, index: int) -> float | None:
    rows = daily.get(key)
    if not isinstance(rows, list) or index >= len(rows):
        return None
    return _optional_float(rows[index])


def _openmeteo_hourly_float(hourly: dict, key: str, index: int) -> float | None:
    rows = hourly.get(key)
    if not isinstance(rows, list) or index >= len(rows):
        return None
    return _optional_float(rows[index])
