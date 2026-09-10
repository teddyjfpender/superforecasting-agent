"""Load country indicators from World Bank and IMF DataMapper."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode

from forecasting.models import ValidationError
from .economic_records import WorldBankObservation, ImfDataMapperObservation
from .dates import _fred_date, _fred_date_to_iso
from .values import _first_present, _optional_float, _optional_str

def load_worldbank_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.worldbank.org/v2",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[WorldBankObservation]:
    """Load World Bank country indicator observations as timestamped evidence rows."""

    country, indicator = _worldbank_source_parts(source)
    if limit <= 0:
        raise ValidationError("worldbank import --limit must be positive")
    since_date = _worldbank_since_date(since) if since else None
    endpoint = _worldbank_endpoint(country, indicator, api_base_url=api_base_url, per_page=max(limit, 100))
    payload = _read_json_endpoint(endpoint, "worldbank observations")
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ValidationError("worldbank observations response must be a metadata/data array")

    observations: list[WorldBankObservation] = []
    for row in payload[1]:
        if not isinstance(row, dict):
            continue
        year = str(row.get("date") or "").strip()
        observation_date = _worldbank_observation_date(year)
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        raw_value = row.get("value")
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        country_payload = row.get("country")
        indicator_payload = row.get("indicator")
        row_country = _optional_str(country_payload.get("id")) if isinstance(country_payload, dict) else country
        row_country_name = _optional_str(country_payload.get("value")) if isinstance(country_payload, dict) else None
        row_indicator = _optional_str(indicator_payload.get("id")) if isinstance(indicator_payload, dict) else indicator
        row_indicator_name = _optional_str(indicator_payload.get("value")) if isinstance(indicator_payload, dict) else None
        observation_iso = _fred_date_to_iso(observation_date)
        observations.append(
            WorldBankObservation(
                country=row_country or country,
                country_name=row_country_name,
                indicator=row_indicator or indicator,
                indicator_name=row_indicator_name,
                observation_date=observation_date.isoformat(),
                value=value if value is not None else str(raw_value),
                published_at=observation_iso,
                source_url=f"https://data.worldbank.org/indicator/{quote(row_indicator or indicator)}?locations={quote(row_country or country)}",
                source_name="World Bank",
                entry_id=f"{row_country or country}:{row_indicator or indicator}:{year}",
                raw=dict(row),
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def load_imf_datamapper_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.imf.org/external/datamapper/api/v1",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[ImfDataMapperObservation]:
    """Load IMF DataMapper country indicator observations as timestamped evidence rows."""

    indicator, country = _imf_source_parts(source)
    if limit <= 0:
        raise ValidationError("imf import --limit must be positive")
    since_date = _worldbank_since_date(since) if since else None
    endpoint = _imf_endpoint(indicator, country, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "imf datamapper observations")
    values = _imf_values_for(payload, indicator=indicator, country=country)
    country_name = _imf_metadata_label(payload, "countries", country)
    indicator_name = _imf_metadata_label(payload, "indicators", indicator)

    observations: list[ImfDataMapperObservation] = []
    for year, raw_value in values.items():
        observation_date = _worldbank_observation_date(str(year).strip())
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        observation_iso = _fred_date_to_iso(observation_date)
        observations.append(
            ImfDataMapperObservation(
                indicator=indicator,
                indicator_name=indicator_name,
                country=country,
                country_name=country_name,
                observation_date=observation_date.isoformat(),
                value=value if value is not None else str(raw_value),
                published_at=observation_iso,
                source_url=endpoint,
                source_name="IMF DataMapper",
                entry_id=f"{indicator}:{country}:{year}",
                raw={"year": year, "value": raw_value},
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def _worldbank_source_parts(source: str) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith("worldbank:"):
        raw = raw.split(":", 1)[1].strip()
    if "/" in raw:
        country, indicator = raw.split("/", 1)
    elif ":" in raw:
        country, indicator = raw.split(":", 1)
    else:
        raise ValidationError("worldbank source must be COUNTRY/INDICATOR, e.g. USA/NY.GDP.MKTP.CD")
    country = country.strip()
    indicator = indicator.strip()
    if not country or not indicator:
        raise ValidationError("worldbank source must include both country and indicator")
    return country, indicator


def _worldbank_endpoint(country: str, indicator: str, *, api_base_url: str, per_page: int) -> str:
    endpoint_base = api_base_url.rstrip("/")
    endpoint = f"{endpoint_base}/country/{quote(country)}/indicator/{quote(indicator)}"
    return f"{endpoint}?{urlencode({'format': 'json', 'per_page': per_page})}"


def _worldbank_since_date(value: str | None):
    if value in (None, ""):
        return None
    from datetime import date

    raw = str(value).strip()
    if len(raw) == 4 and raw.isdigit():
        return date(int(raw), 1, 1)
    return _fred_date(raw, field_name="since")


def _worldbank_observation_date(year: str):
    if len(year) != 4 or not year.isdigit():
        return None
    from datetime import date

    return date(int(year), 12, 31)


def _imf_source_parts(source: str) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith("imf:"):
        raw = raw.split(":", 1)[1].strip()
    if "/" in raw:
        indicator, country = raw.split("/", 1)
    elif ":" in raw:
        indicator, country = raw.split(":", 1)
    else:
        raise ValidationError("imf source must be INDICATOR/COUNTRY, e.g. NGDP_RPCH/USA")
    indicator = indicator.strip().upper()
    country = country.strip().upper()
    if not indicator or not country:
        raise ValidationError("imf source must include both indicator and country")
    return indicator, country


def _imf_endpoint(indicator: str, country: str, *, api_base_url: str) -> str:
    endpoint_base = api_base_url.rstrip("/")
    if not endpoint_base:
        raise ValidationError("imf import --api-base-url cannot be empty")
    if "{indicator}" in endpoint_base or "{country}" in endpoint_base:
        return endpoint_base.format(indicator=quote(indicator), country=quote(country))
    return f"{endpoint_base}/{quote(indicator)}/{quote(country)}"


def _imf_values_for(payload: object, *, indicator: str, country: str) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("imf datamapper response must be a JSON object")
    values = payload.get("values")
    if not isinstance(values, dict):
        raise ValidationError("imf datamapper response must include a values object")
    if _imf_year_value_mapping(values):
        return values
    indicator_values = _dict_value_case_insensitive(values, indicator)
    if isinstance(indicator_values, dict):
        country_values = _dict_value_case_insensitive(indicator_values, country)
        if isinstance(country_values, dict):
            return country_values
    country_values = _dict_value_case_insensitive(values, country)
    if isinstance(country_values, dict):
        indicator_values = _dict_value_case_insensitive(country_values, indicator)
        if isinstance(indicator_values, dict):
            return indicator_values
    raise ValidationError("imf datamapper response does not include indicator/country values")


def _imf_year_value_mapping(value: dict) -> bool:
    return bool(value) and all(_worldbank_observation_date(str(key).strip()) is not None for key in value)


def _imf_metadata_label(payload: object, key: str, code: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    container = payload.get(key)
    if not isinstance(container, dict):
        return None
    metadata = _dict_value_case_insensitive(container, code)
    if isinstance(metadata, dict):
        return _optional_str(
            _first_present(
                metadata.get("label"),
                metadata.get("name"),
                metadata.get("title"),
                metadata.get("description"),
            )
        )
    return _optional_str(metadata)


def _dict_value_case_insensitive(mapping: dict, key: str) -> object | None:
    if key in mapping:
        return mapping[key]
    lowered = key.lower()
    for candidate, value in mapping.items():
        if str(candidate).lower() == lowered:
            return value
    return None
