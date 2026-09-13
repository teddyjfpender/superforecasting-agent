"""Load EIA energy observations from current and legacy API responses."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from superforecasting_agent.storage import forecast_configuration as appconfig
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import EiaObservation
from .eia_parser import (
    _eia_observations_from_payload, _eia_period_to_iso,
    _eia_legacy_series_rows as _eia_legacy_series_rows,
)

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
            if (timestamp_to_datetime(_eia_period_to_iso(observation.observation_period)) or since_dt) >= since_dt
        ]
    observations.sort(key=lambda item: _eia_period_to_iso(item.observation_period))
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
