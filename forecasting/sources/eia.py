"""Load EIA energy observations from current and legacy API responses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from forecasting import appconfig
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import EiaObservation
from .values import _first_present, _optional_float, _optional_str

def load_eia_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.eia.gov/series/",
    api_key: str | None = None,
    _read_json_endpoint: Callable[[str, str], object],
) -> list[EiaObservation]:
    """Load EIA energy time-series observations as timestamped evidence rows.

    The EIA Open Data API (both the v1 ``/series/`` route and the current v2
    ``/v2/...`` routes) REQUIRES an ``api_key`` query parameter. A keyless
    request is rejected with HTTP 403 ``{"error":{"code":"API_KEY_MISSING"}}`` —
    so rather than pass that bare 403 through, we fail fast BEFORE the request
    with a teaching error naming ``EIA_API_KEY`` and the free registration URL.
    The key is read from the ``api_key`` argument or the ``EIA_API_KEY`` env var
    and injected when the caller's endpoint does not already carry one. Prefer
    FRED for energy series (``GASREGW`` gasoline, ``DCOILWTICO`` crude), which
    serve the same numbers keyless.
    """

    series_id, endpoint = _eia_endpoint(source, api_base_url=api_base_url)
    if not series_id:
        raise ValidationError("eia import series id or API URL is required")
    if limit <= 0:
        raise ValidationError("eia import --limit must be positive")
    resolved_key = (api_key or appconfig.secret("EIA_API_KEY") or "").strip()
    endpoint_has_key = "api_key=" in endpoint
    if not resolved_key and not endpoint_has_key:
        # EIA rejects keyless requests with HTTP 403 (API_KEY_MISSING). Teach the
        # fix instead of letting a bare 403 surface to the agent.
        raise ValidationError(
            "eia import requires an API key: the EIA API rejects keyless requests "
            "with HTTP 403 (API_KEY_MISSING). Set EIA_API_KEY — register free at "
            "https://www.eia.gov/opendata/register.php, then `forecast api-key set "
            "eia <key>`. Or use FRED for the same energy series with no key "
            "(e.g. `import fred DCOILWTICO` for WTI crude, `fred GASREGW` for "
            "gasoline)."
        )
    if resolved_key and not endpoint_has_key:
        separator = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{separator}{urlencode({'api_key': resolved_key})}"
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "eia observations")
    observations = _eia_observations_from_payload(payload, series_id=series_id, endpoint=endpoint)
    if since_dt is not None:
        observations = [
            observation
            for observation in observations
            if (timestamp_to_datetime(observation.published_at) or since_dt) >= since_dt
        ]
    observations.sort(key=lambda item: item.published_at)
    return observations[-limit:]


def _eia_endpoint(source: str, *, api_base_url: str) -> tuple[str, str]:
    raw = source.strip()
    if not raw:
        return "", ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        series_id = (
            params.get("series_id")
            or params.get("seriesId")
            or params.get("series")
            or Path(unquote(parsed.path)).name
        )
        return str(series_id or raw), raw
    series_id = raw.split(":", 1)[1].strip() if raw.startswith("eia:") else raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("eia import --api-base-url cannot be empty")
    if "{series_id}" in base:
        return series_id, base.replace("{series_id}", quote(series_id, safe=""))
    separator = "&" if "?" in base else "?"
    return series_id, f"{base.rstrip('?&')}{separator}{urlencode({'series_id': series_id})}"


def _eia_observations_from_payload(payload: object, *, series_id: str, endpoint: str) -> list[EiaObservation]:
    if not isinstance(payload, dict):
        raise ValidationError("eia observations response must be a JSON object")
    rows: list[dict[str, object]] = []
    series_name: str | None = None
    unit: str | None = None
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        rows = [row for row in response["data"] if isinstance(row, dict)]
        series_name = _optional_str(
            _first_present(
                payload.get("name"),
                response.get("series-description"),
                response.get("seriesDescription"),
                response.get("description"),
            )
        )
    elif isinstance(payload.get("data"), list):
        rows = [row for row in payload["data"] if isinstance(row, dict)]
        series_name = _optional_str(_first_present(payload.get("name"), payload.get("description")))
    elif isinstance(payload.get("series"), list):
        series_rows = [row for row in payload["series"] if isinstance(row, dict)]
        rows = _eia_legacy_series_rows(series_rows, series_id=series_id)
        if series_rows:
            series_name = _optional_str(series_rows[0].get("name"))
            unit = _optional_str(series_rows[0].get("units"))
    else:
        raise ValidationError("eia observations response must contain response.data, data, or series")

    # Request authentication must not become a durable evidence citation.
    parsed = urlparse(endpoint)
    public_params = [(name, value) for name, value in parse_qsl(parsed.query, keep_blank_values=True)
                     if name.lower() != "api_key"]
    source_url = parsed._replace(query=urlencode(public_params)).geturl()
    observations: list[EiaObservation] = []
    for index, row in enumerate(rows):
        row_series_id = _optional_str(_first_present(row.get("series_id"), row.get("seriesId"), row.get("series"))) or series_id
        period = _optional_str(_first_present(row.get("period"), row.get("date"), row.get("timestamp")))
        if not period:
            continue
        published_at = _eia_period_to_iso(period)
        if not published_at:
            continue
        raw_value = _first_present(row.get("value"), row.get("price"), row.get("generation"), row.get("consumption"))
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        row_unit = _optional_str(
            _first_present(row.get("units"), row.get("unit"), row.get("value-units"), row.get("value_units"))
        )
        row_series_name = _optional_str(
            _first_present(
                row.get("series-description"),
                row.get("seriesDescription"),
                row.get("series_name"),
                row.get("name"),
            )
        )
        observations.append(
            EiaObservation(
                series_id=row_series_id,
                series_name=row_series_name or series_name,
                observation_period=str(period),
                value=value if value is not None else str(raw_value),
                unit=row_unit or unit,
                published_at=published_at,
                source_url=source_url,
                source_name="EIA",
                entry_id=f"{row_series_id}:{period}",
                raw={"row_index": index, **dict(row)},
            )
        )
    return observations


def _eia_legacy_series_rows(series_rows: list[dict[str, object]], *, series_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for series in series_rows:
        row_series_id = _optional_str(series.get("series_id")) or series_id
        unit = _optional_str(series.get("units"))
        name = _optional_str(series.get("name"))
        data_rows = series.get("data")
        if not isinstance(data_rows, list):
            continue
        for item in data_rows:
            if isinstance(item, list) and len(item) >= 2:
                rows.append(
                    {
                        "series_id": row_series_id,
                        "period": item[0],
                        "value": item[1],
                        "units": unit,
                        "name": name,
                    }
                )
    return rows


def _eia_period_to_iso(value: str) -> str | None:
    raw = str(value).strip()
    if not raw:
        return None
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-01-01T00:00:00Z"
    if len(raw) == 6 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:]}-01T00:00:00Z"
    if len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        return f"{raw}-01T00:00:00Z"
    upper = raw.upper()
    if len(upper) == 6 and upper[:4].isdigit() and upper[4] == "Q" and upper[5] in "1234":
        month = {"1": "01", "2": "04", "3": "07", "4": "10"}[upper[5]]
        return f"{upper[:4]}-{month}-01T00:00:00Z"
    try:
        timestamp = parse_timestamp(raw, field_name="eia period")
        parsed = timestamp_to_datetime(timestamp)
        if parsed is None:
            return None
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValidationError:
        return None
