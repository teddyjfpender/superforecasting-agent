"""Pure BLS response parsing; observation periods are not publication dates."""
import math
from urllib.parse import quote
from forecasting.models import ValidationError
from .economic_records import BlsObservation
from .dates import _fred_date
from .values import _optional_float, _optional_str


def parse_bls_observations(payload, series_id, *, limit=10, since=None):
    normalized_series = series_id.strip()
    if not normalized_series or limit <= 0:
        raise ValidationError("bls requires a series and positive limit")
    since_date = _fred_date(since, field_name="since") if since else None
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
    seen = {}
    for series in series_rows:
        if not isinstance(series, dict):
            continue
        row_series_id = series.get("seriesID")
        if row_series_id != normalized_series:
            raise ValidationError("bls response series identity differs from the requested series")
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
            raw = row.get("value")
            if isinstance(raw, bool):
                raise ValidationError("bls observation value must be numeric")
            raw_value = str(raw).strip() if raw is not None else ""
            if raw_value in {"", "."}:
                continue
            value = _optional_float(raw_value)
            if value is None or not math.isfinite(value):
                raise ValidationError("bls observation value must be finite and numeric")
            identity = (row_series_id, year, period)
            if identity in seen:
                if seen[identity] != row:
                    raise ValidationError("bls response contains conflicting revisions for one observation")
                continue
            seen[identity] = row
            observations.append(
                BlsObservation(
                    series_id=row_series_id,
                    observation_date=observation_date.isoformat(),
                    period=period,
                    period_name=_optional_str(row.get("periodName")),
                    value=value if value is not None else raw_value,
                    published_at=None,
                    source_url=f"https://data.bls.gov/timeseries/{quote(row_series_id)}",
                    source_name="BLS",
                    entry_id=f"{row_series_id}:{year}:{period}",
                    raw=dict(row),
                )
            )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


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
