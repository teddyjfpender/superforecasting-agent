"""Environment records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsgsEarthquakeEvent:
    event_id: str | None
    title: str
    url: str | None
    time: str | None
    updated_at: str | None
    magnitude: float | None
    place: str | None
    event_type: str | None
    status: str | None
    tsunami: int | None
    significance: int | None
    longitude: float | None
    latitude: float | None
    depth_km: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class NasaEonetEvent:
    event_id: str | None
    title: str
    description: str
    url: str | None
    status: str | None
    closed_at: str | None
    latest_geometry_at: str | None
    categories: list[str]
    source_names: list[str]
    source_urls: list[str]
    longitude: float | None
    latitude: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class NwsAlert:
    alert_id: str | None
    event: str
    headline: str
    description: str
    instruction: str
    url: str | None
    area_desc: str | None
    severity: str | None
    certainty: str | None
    urgency: str | None
    status: str | None
    message_type: str | None
    category: str | None
    response: str | None
    sent_at: str | None
    effective_at: str | None
    onset_at: str | None
    expires_at: str | None
    ends_at: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenMeteoDailyForecast:
    latitude: float
    longitude: float
    forecast_date: str
    temperature_2m_max: float | None
    temperature_2m_min: float | None
    precipitation_sum: float | None
    wind_speed_10m_max: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenMeteoAirQualityForecast:
    latitude: float
    longitude: float
    forecast_time: str
    us_aqi: float | None
    european_aqi: float | None
    pm10: float | None
    pm2_5: float | None
    carbon_monoxide: float | None
    nitrogen_dioxide: float | None
    ozone: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenMeteoHistoricalWeatherObservation:
    latitude: float
    longitude: float
    observation_date: str
    temperature_2m_mean: float | None
    temperature_2m_max: float | None
    temperature_2m_min: float | None
    precipitation_sum: float | None
    wind_speed_10m_max: float | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class FemaDisasterDeclaration:
    disaster_number: int | None
    declaration_string: str | None
    state: str | None
    declaration_type: str | None
    declaration_date: str | None
    fiscal_year: int | None
    incident_type: str | None
    title: str
    designated_area: str | None
    incident_begin_date: str | None
    incident_end_date: str | None
    individual_assistance: bool | None
    public_assistance: bool | None
    hazard_mitigation: bool | None
    last_refresh: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict
