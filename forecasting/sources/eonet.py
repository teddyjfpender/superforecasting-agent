"""Load eonet natural-hazard observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .environment_records import NasaEonetEvent
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _first_present, _optional_float, _optional_str

def load_nasa_eonet_events(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eonet.gsfc.nasa.gov/api/v3/events",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[NasaEonetEvent]:
    """Load NASA EONET natural events as timestamped hazard evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source.strip()
    if not normalized_source:
        raise ValidationError("eonet import query, category, or API URL is required")
    if limit <= 0:
        raise ValidationError("eonet import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _eonet_endpoint(
        normalized_source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "nasa eonet events")
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValidationError("nasa eonet response must include an events array")

    events: list[NasaEonetEvent] = []
    for row in payload["events"]:
        if not isinstance(row, dict):
            continue
        geometry = _eonet_latest_geometry(row.get("geometry"))
        latest_geometry_at = _eonet_timestamp(geometry.get("date")) if geometry else None
        latest_dt = timestamp_to_datetime(latest_geometry_at) if latest_geometry_at else None
        if since_dt is not None and latest_dt is not None and latest_dt < since_dt:
            continue
        longitude, latitude = _eonet_first_coordinate(geometry.get("coordinates") if geometry else None)
        event_id = _optional_str(row.get("id"))
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled NASA EONET event")
        events.append(
            NasaEonetEvent(
                event_id=event_id,
                title=title,
                description=_collapse_ws(_optional_str(row.get("description")) or ""),
                url=_optional_str(_first_present(row.get("link"), row.get("url"))),
                status=_optional_str(row.get("status")),
                closed_at=_eonet_timestamp(row.get("closed")),
                latest_geometry_at=latest_geometry_at,
                categories=_eonet_categories(row.get("categories")),
                source_names=_eonet_source_names(row.get("sources")),
                source_urls=_eonet_source_urls(row.get("sources")),
                longitude=longitude,
                latitude=latitude,
                source_name="NASA EONET",
                entry_id=event_id or title,
                raw=dict(row),
            )
        )
        if len(events) >= limit:
            break
    return events


def _eonet_endpoint(
    source: str,
    *,
    limit: int,
    since: str | None,
    api_base_url: str,
) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            params["category"] = value
    params["limit"] = min(limit, 1000)
    if since and not params.get("start"):
        params["start"] = since.strip()
    return f"{endpoint_base}?{urlencode(params)}"


def _eonet_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='nasa eonet timestamp')


def _eonet_latest_geometry(value: object) -> dict:
    if not isinstance(value, list):
        return {}
    rows = [row for row in value if isinstance(row, dict)]
    if not rows:
        return {}
    return rows[-1]


def _eonet_categories(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    categories: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        title = _optional_str(_first_present(row.get("title"), row.get("id")))
        if title:
            categories.append(title)
    return categories


def _eonet_source_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        source_id = _optional_str(row.get("id"))
        if source_id:
            names.append(source_id)
    return names


def _eonet_source_urls(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        url = _optional_str(row.get("url"))
        if url:
            urls.append(url)
    return urls


def _eonet_first_coordinate(value: object) -> tuple[float | None, float | None]:
    if not isinstance(value, list):
        return None, None
    if len(value) >= 2:
        longitude = _optional_float(value[0])
        latitude = _optional_float(value[1])
        if longitude is not None and latitude is not None:
            return longitude, latitude
    for item in value:
        longitude, latitude = _eonet_first_coordinate(item)
        if longitude is not None and latitude is not None:
            return longitude, latitude
    return None, None
