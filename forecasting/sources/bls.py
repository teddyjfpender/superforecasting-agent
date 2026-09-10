"""Load U.S. Bureau of Labor Statistics evidence observations."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode

from forecasting import appconfig
from forecasting.models import ValidationError
from .economic_records import BlsObservation
from .dates import _fred_date, _fred_date_to_iso
from .values import _optional_float, _optional_str

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
    if not isinstance(payload, dict):
        raise ValidationError("bls observations response must be a JSON object")
    status = str(payload.get("status") or "").upper()
    if status and status != "REQUEST_SUCCEEDED":
        messages = payload.get("message")
        detail = "; ".join(str(item) for item in messages) if isinstance(messages, list) else str(messages or status)
        raise ValidationError(f"bls observations request failed: {detail}")
    results = payload.get("Results")
    series_rows = results.get("series") if isinstance(results, dict) else None
    if not isinstance(series_rows, list):
        raise ValidationError("bls observations response must contain Results.series")

    observations: list[BlsObservation] = []
    for series in series_rows:
        if not isinstance(series, dict):
            continue
        row_series_id = str(series.get("seriesID") or normalized_series).strip() or normalized_series
        data_rows = series.get("data")
        if not isinstance(data_rows, list):
            continue
        for row in data_rows:
            if not isinstance(row, dict):
                continue
            year = str(row.get("year") or "").strip()
            period = str(row.get("period") or "").strip()
            observation_date = _bls_observation_date(year, period)
            if observation_date is None:
                continue
            if since_date is not None and observation_date < since_date:
                continue
            raw_value = str(row.get("value") or "").strip()
            if raw_value in {"", "."}:
                continue
            value = _optional_float(raw_value)
            observation_iso = _fred_date_to_iso(observation_date)
            observations.append(
                BlsObservation(
                    series_id=row_series_id,
                    observation_date=observation_date.isoformat(),
                    period=period,
                    period_name=_optional_str(row.get("periodName")),
                    value=value if value is not None else raw_value,
                    published_at=observation_iso,
                    source_url=f"https://data.bls.gov/timeseries/{quote(row_series_id)}",
                    source_name="BLS",
                    entry_id=f"{row_series_id}:{year}:{period}",
                    raw=dict(row),
                )
            )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


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


def _bls_observation_date(year: str, period: str):
    from datetime import date

    if not year.isdigit():
        return None
    try:
        year_int = int(year)
    except ValueError:
        return None
    if not 1 <= year_int <= 9999:
        return None
    normalized_period = period.strip().upper()
    if len(normalized_period) == 3 and normalized_period.startswith("M") and normalized_period[1:].isdigit():
        month = int(normalized_period[1:])
        if 1 <= month <= 12:
            return date(year_int, month, 1)
        if month == 13:
            return date(year_int, 12, 31)
    if len(normalized_period) == 3 and normalized_period.startswith("Q") and normalized_period[1:].isdigit():
        quarter = int(normalized_period[1:])
        if 1 <= quarter <= 4:
            return date(year_int, 1 + (quarter - 1) * 3, 1)
    if normalized_period in {"A01", "Y01"}:
        return date(year_int, 12, 31)
    return None
