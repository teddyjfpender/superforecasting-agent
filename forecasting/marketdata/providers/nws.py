"""NWS alert events, kept separate from numeric quote and settlement models."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from pydantic import JsonValue

from forecasting.marketdata.catalog import DataSeries
from forecasting.marketdata.model import DataEvent, DataEvents
from forecasting.marketdata.provider import (
    JsonGetter,
    ProviderFailure,
    default_get_json,
)
from forecasting.sources.nws import load_nws_alerts


def fetch_nws_events(
    series: DataSeries, *, get_json: JsonGetter = default_get_json
) -> DataEvents:
    if (
        series.provider != "nws"
        or series.kind != "event"
        or not series.dimensions.get("area")
    ):
        raise ValueError("NWS event requests require a qualified alert-area binding")
    truncated = False

    def read(endpoint: str, label: str) -> JsonValue:
        nonlocal truncated
        payload = get_json(
            endpoint,
            headers={
                "Accept": "application/geo+json",
                "User-Agent": "Superforecasting-Agent (https://github.com/teddyjfpender/superforecasting-agent)",
            },
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("features"), list
        ):
            raise ProviderFailure(
                "invalid_response", "NWS returned an invalid alert collection"
            )
        seen = {}
        features = []
        for feature in payload["features"]:
            properties = (
                feature.get("properties") if isinstance(feature, dict) else None
            )
            if not isinstance(properties, dict):
                raise ProviderFailure(
                    "invalid_response", "NWS alert properties are missing"
                )
            if properties.get("status") != "Actual":
                continue  # Exercise and test messages are not active public alerts.
            geocode = properties.get("geocode")
            areas = geocode.get("UGC") if isinstance(geocode, dict) else None
            if not isinstance(areas, list) or not any(
                isinstance(code, str) and code.startswith(series.dimensions["area"])
                for code in areas
            ):
                raise ProviderFailure(
                    "invalid_response", "NWS alert does not match the selected area"
                )
            identity = properties.get("id") or feature.get("id")
            if not isinstance(identity, str) or not identity:
                raise ProviderFailure(
                    "invalid_response", "NWS alert identity is missing"
                )
            if identity in seen:
                if seen[identity] != feature:
                    raise ProviderFailure(
                        "invalid_response",
                        "NWS returned conflicting versions of one alert",
                    )
                continue
            seen[identity] = feature
            features.append(feature)
        payload = {**payload, "features": features}
        pagination = payload.get("pagination")
        truncated = len(payload["features"]) > 100 or bool(
            isinstance(pagination, dict) and pagination.get("next")
        )
        return payload

    records = load_nws_alerts(
        urlencode({"area": series.dimensions["area"]}),
        limit=100,
        _read_json_endpoint=read,
    )
    events = []
    for record in records:
        if not record.entry_id:
            raise ProviderFailure(
                "invalid_response", "NWS parser did not retain the alert identity"
            )
        events.append(
            DataEvent(
                event_id=record.entry_id,
                title=record.headline,
                description=record.description,
                area=record.area_desc,
                severity=record.severity,
                issued_at=record.sent_at,
                effective_at=record.effective_at,
                expires_at=record.expires_at,
                source_url=record.url,
            )
        )
    return DataEvents(
        series_id=series.id,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        truncated=truncated,
        events=events,
    )
