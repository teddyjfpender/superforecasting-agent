"""Load U.S. Census demographic and regional evidence records."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from forecasting import appconfig
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import CensusRecord
from .values import _optional_float

def load_census_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.census.gov/data",
    api_key: str | None = None,
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CensusRecord]:
    """Load U.S. Census API rows as timestamped demographic or regional evidence."""

    dataset, endpoint = _census_endpoint(source, api_base_url=api_base_url, api_key=api_key)
    if not dataset:
        raise ValidationError("census import dataset path or API URL is required")
    if limit <= 0:
        raise ValidationError("census import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "census data")
    records = _census_records_from_payload(payload, dataset=dataset, endpoint=endpoint)
    if since_dt is not None:
        records = [
            record
            for record in records
            if record.published_at is None or (timestamp_to_datetime(record.published_at) or since_dt) >= since_dt
        ]
    return records[:limit]


def _census_endpoint(source: str, *, api_base_url: str, api_key: str | None) -> tuple[str, str]:
    raw = source.strip()
    if raw.startswith("census:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return "", ""

    effective_key = api_key or appconfig.secret("CENSUS_API_KEY")
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        dataset = _census_dataset_from_path(unquote(parsed.path))
        params = parse_qsl(parsed.query, keep_blank_values=True)
        endpoint = raw.split("?", 1)[0]
    else:
        if "?" not in raw:
            raise ValidationError(
                "census source must be DATASET?get=...&for=..., "
                "e.g. 2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
            )
        dataset_part, query = raw.split("?", 1)
        dataset = dataset_part.strip("/")
        if not dataset:
            raise ValidationError("census source must include a dataset path")
        base = api_base_url.strip()
        if not base:
            raise ValidationError("census import --api-base-url cannot be empty")
        endpoint = f"{base.rstrip('/')}/{quote(dataset, safe='/')}"
        params = parse_qsl(query, keep_blank_values=True)

    param_names = {name for name, _ in params}
    if "get" not in param_names or "for" not in param_names:
        raise ValidationError("census source query must include get=... and for=... parameters")
    if "key" not in param_names and effective_key:
        params.append(("key", effective_key))
    if "key" not in {name for name, _ in params} and _census_requires_api_key(endpoint):
        raise ValidationError("census import requires CENSUS_API_KEY for api.census.gov requests")
    return dataset, f"{endpoint}?{urlencode(params)}"


def _census_dataset_from_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if "data" in parts:
        index = parts.index("data")
        dataset = "/".join(parts[index + 1 :])
        if dataset:
            return dataset
    return "/".join(parts)


def _census_requires_api_key(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    return parsed.netloc.lower() == "api.census.gov"


def _census_records_from_payload(payload: object, *, dataset: str, endpoint: str) -> list[CensusRecord]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValidationError("census data response must be a two-dimensional array with a header row")
    headers = [str(header) for header in payload[0]]
    if not headers:
        raise ValidationError("census data response has an empty header row")
    dataset_year = _census_dataset_year(dataset)
    observation_date = f"{dataset_year}-12-31" if dataset_year is not None else None
    published_at = f"{observation_date}T00:00:00Z" if observation_date else None
    source_url = _census_public_source_url(endpoint)
    records: list[CensusRecord] = []
    for index, raw_row in enumerate(payload[1:]):
        if not isinstance(raw_row, list):
            continue
        row = {header: raw_row[position] if position < len(raw_row) else None for position, header in enumerate(headers)}
        geography = {
            key: str(value)
            for key, value in row.items()
            if value not in (None, "") and _census_is_geography_header(key)
        }
        values = {
            key: _census_value(value)
            for key, value in row.items()
            if value not in (None, "") and key not in geography
        }
        if not values and not geography:
            continue
        records.append(
            CensusRecord(
                dataset=dataset,
                dataset_year=dataset_year,
                observation_date=observation_date,
                values=values,
                geography=geography,
                published_at=published_at,
                source_url=source_url,
                source_name="U.S. Census Bureau",
                entry_id=f"{dataset}:{observation_date or 'unknown'}:{index}",
                raw={"row_index": index, "headers": headers, "row": row},
            )
        )
    return records


def _census_public_source_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if not parsed.query:
        return endpoint
    params = [(name, value) for name, value in parse_qsl(parsed.query, keep_blank_values=True) if name.lower() != "key"]
    return parsed._replace(query=urlencode(params)).geturl()


def _census_dataset_year(dataset: str) -> int | None:
    for part in dataset.split("/"):
        if len(part) == 4 and part.isdigit():
            year = int(part)
            if 1900 <= year <= 2200:
                return year
    return None


def _census_is_geography_header(header: str) -> bool:
    normalized = header.strip().lower()
    if not normalized or normalized == "name":
        return False
    if normalized.startswith("ucgid"):
        return True
    if normalized in {
        "us",
        "region",
        "division",
        "state",
        "county",
        "county subdivision",
        "tract",
        "block group",
        "block",
        "place",
        "zip code tabulation area",
        "metropolitan statistical area/micropolitan statistical area",
        "congressional district",
        "school district (elementary)",
        "school district (secondary)",
        "school district (unified)",
    }:
        return True
    return normalized == header and not any(character.isdigit() for character in normalized)


def _census_value(value: object) -> float | str:
    text = str(value).strip()
    number = _optional_float(text)
    if number is None:
        return text
    return number
