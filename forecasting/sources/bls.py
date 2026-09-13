"""Load U.S. Bureau of Labor Statistics evidence observations."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode

from superforecasting_agent.storage import forecast_configuration as appconfig
from forecasting.models import ValidationError
from .economic_records import BlsObservation
from .dates import _fred_date
from .bls_parsing import parse_bls_observations, _bls_observation_date

def load_bls_observations(
    series_id: str,
    *,
    limit: int = 10,
    since: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    api_base_url: str = "https://api.bls.gov/publicAPI/v2/timeseries/data",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[BlsObservation]:
    """Load BLS public time-series observations as timestamped evidence rows."""

    normalized_series = series_id.strip()
    if not normalized_series:
        raise ValidationError("bls import series id is required")
    if limit <= 0:
        raise ValidationError("bls import --limit must be positive")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValidationError("bls import --start-year cannot be after --end-year")
    since_date = _fred_date(since, field_name="since") if since else None
    api_key = (appconfig.secret("BLS_API_KEY", "") or "").strip() or None
    endpoint = _bls_endpoint(
        normalized_series,
        api_base_url=api_base_url,
        start_year=start_year,
        end_year=end_year,
        api_key=api_key,
    )
    payload = _read_json_endpoint(endpoint, "bls observations")
    return parse_bls_observations(payload, normalized_series, limit=limit, since=since)


def _bls_endpoint(
    series_id: str,
    *,
    api_base_url: str,
    start_year: int | None,
    end_year: int | None,
    api_key: str | None = None,
) -> str:
    endpoint_base = api_base_url.rstrip("/")
    if endpoint_base.endswith(f"/{quote(series_id)}"):
        endpoint = endpoint_base
    else:
        endpoint = f"{endpoint_base}/{quote(series_id)}"
    params: dict[str, int | str] = {}
    if start_year is not None:
        params["startyear"] = start_year
    if end_year is not None:
        params["endyear"] = end_year
    # Optional BLS registration key: lifts the public-API daily limit (25→500
    # queries/day) and unlocks longer history. The v2 GET endpoint accepts it as
    # a query parameter; without it, BLS still works at the lower limit.
    if api_key:
        params["registrationkey"] = api_key
    if params:
        endpoint = f"{endpoint}?{urlencode(params)}"
    return endpoint
