"""Load usgs natural-hazard observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timezone
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .environment_records import UsgsEarthquakeEvent
from .values import _collapse_ws, _first_present, _optional_float, _optional_int, _optional_str

def load_usgs_earthquakes(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[UsgsEarthquakeEvent]:
    """Load USGS earthquake GeoJSON events as timestamped geophysical evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source.strip()
    if not normalized_source:
        raise ValidationError("usgs import query, event id, or API URL is required")
    if limit <= 0:
        raise ValidationError("usgs import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _usgs_earthquake_endpoint(
        normalized_source,
        limit=limit,
        since=since,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "usgs earthquakes")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValidationError("usgs earthquake response must be GeoJSON with a features array")

    events: list[UsgsEarthquakeEvent] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict):
            continue
        geometry = geometry if isinstance(geometry, dict) else {}
        time = _usgs_ms_to_iso(properties.get("time"))
        time_dt = timestamp_to_datetime(time) if time else None
        if since_dt is not None and time_dt is not None and time_dt < since_dt:
            continue
        event_id = _optional_str(feature.get("id")) or _optional_str(properties.get("code"))
        magnitude = _optional_float(properties.get("mag"))
        place = _optional_str(properties.get("place"))
        event_type = _optional_str(properties.get("type"))
        title = _collapse_ws(
            _optional_str(properties.get("title")) or _usgs_event_title(magnitude=magnitude, place=place)
        )
        longitude, latitude, depth_km = _usgs_coordinates(geometry.get("coordinates"))
        events.append(
            UsgsEarthquakeEvent(
                event_id=event_id,
                title=title,
                url=_optional_str(_first_present(properties.get("url"), properties.get("detail"))),
                time=time,
                updated_at=_usgs_ms_to_iso(properties.get("updated")),
                magnitude=magnitude,
                place=place,
                event_type=event_type,
                status=_optional_str(properties.get("status")),
                tsunami=_optional_int(properties.get("tsunami")),
                significance=_optional_int(properties.get("sig")),
                longitude=longitude,
                latitude=latitude,
                depth_km=depth_km,
                source_name="USGS Earthquake Catalog",
                entry_id=event_id or title,
                raw=dict(feature),
            )
        )
        if len(events) >= limit:
            break
    return events


def _usgs_earthquake_endpoint(
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
            params["eventid"] = value
    params["format"] = "geojson"
    params.setdefault("orderby", "time")
    params["limit"] = min(limit, 20000)
    if since and not params.get("starttime"):
        params["starttime"] = since.strip()
    return f"{endpoint_base}?{urlencode(params)}"


def _usgs_ms_to_iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    number = _optional_float(value)
    if number is None:
        try:
            return parse_timestamp(str(value), field_name="usgs timestamp")
        except ValidationError:
            return None
    from datetime import datetime

    seconds = number / 1000 if number > 10_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _usgs_coordinates(value: object) -> tuple[float | None, float | None, float | None]:
    if not isinstance(value, list):
        return None, None, None
    longitude = _optional_float(value[0]) if len(value) > 0 else None
    latitude = _optional_float(value[1]) if len(value) > 1 else None
    depth_km = _optional_float(value[2]) if len(value) > 2 else None
    return longitude, latitude, depth_km


def _usgs_event_title(*, magnitude: float | None, place: str | None) -> str:
    magnitude_label = f"M {magnitude:g}" if magnitude is not None else "USGS event"
    return f"{magnitude_label} - {place}" if place else magnitude_label
