"""Load nws natural-hazard observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .environment_records import NwsAlert
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _first_present, _optional_str

def load_nws_alerts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.weather.gov/alerts/active",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[NwsAlert]:
    """Load National Weather Service active alerts as timestamped operational evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("nws:") else source.strip()
    if not normalized_source:
        raise ValidationError("nws import area, point, event query, or API URL is required")
    if limit <= 0:
        raise ValidationError("nws import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _nws_alerts_endpoint(normalized_source, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "nws alerts")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValidationError("nws alerts response must be GeoJSON with a features array")

    alerts: list[NwsAlert] = []
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        sent_at = _nws_alert_timestamp(properties.get("sent"))
        effective_at = _nws_alert_timestamp(properties.get("effective"))
        onset_at = _nws_alert_timestamp(properties.get("onset"))
        updated_at = sent_at or effective_at or onset_at
        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue
        alert_id = _optional_str(_first_present(properties.get("id"), properties.get("@id"), feature.get("id")))
        event = _collapse_ws(_optional_str(properties.get("event")) or "NWS alert")
        headline = _collapse_ws(_optional_str(properties.get("headline")) or event)
        alerts.append(
            NwsAlert(
                alert_id=alert_id,
                event=event,
                headline=headline,
                description=_collapse_ws(_optional_str(properties.get("description")) or ""),
                instruction=_collapse_ws(_optional_str(properties.get("instruction")) or ""),
                url=_optional_str(_first_present(properties.get("@id"), feature.get("id"))),
                area_desc=_collapse_ws(_optional_str(properties.get("areaDesc")) or ""),
                severity=_optional_str(properties.get("severity")),
                certainty=_optional_str(properties.get("certainty")),
                urgency=_optional_str(properties.get("urgency")),
                status=_optional_str(properties.get("status")),
                message_type=_optional_str(properties.get("messageType")),
                category=_optional_str(properties.get("category")),
                response=_optional_str(properties.get("response")),
                sent_at=sent_at,
                effective_at=effective_at,
                onset_at=onset_at,
                expires_at=_nws_alert_timestamp(properties.get("expires")),
                ends_at=_nws_alert_timestamp(properties.get("ends")),
                source_name=_optional_str(properties.get("senderName")) or "National Weather Service",
                entry_id=alert_id or headline,
                raw=dict(feature),
            )
        )
        if len(alerts) >= limit:
            break
    return alerts


def _nws_alerts_endpoint(source: str, *, api_base_url: str) -> str:
    value = source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        endpoint_base = value.split("?", 1)[0].rstrip("?&")
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    else:
        endpoint_base = api_base_url.rstrip("?&")
        params = dict(parse_qsl(value.lstrip("?"), keep_blank_values=True)) if "=" in value else {}
        if not params:
            if _looks_like_lat_lon(value):
                params["point"] = value
            elif len(value) == 2 and value.isalpha():
                params["area"] = value.upper()
            else:
                params["event"] = value
    return f"{endpoint_base}?{urlencode(params)}" if params else endpoint_base


def _nws_alert_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='nws alert timestamp')


def _looks_like_lat_lon(value: str) -> bool:
    parts = [part.strip() for part in value.split(",", 1)]
    if len(parts) != 2:
        return False
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180
