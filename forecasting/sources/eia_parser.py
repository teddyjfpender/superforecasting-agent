"""Pure EIA payload parsing; observation periods are not publication times."""
import math
from datetime import timezone
from urllib.parse import parse_qsl, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import EiaObservation
from .values import _first_present, _optional_float, _optional_str

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
        if row_series_id != series_id:
            raise ValidationError("eia response series does not match requested series")
        period = _optional_str(_first_present(row.get("period"), row.get("date"), row.get("timestamp")))
        if not period:
            continue
        if not _eia_period_to_iso(period):
            continue
        raw_value = _first_present(row.get("value"), row.get("price"), row.get("generation"), row.get("consumption"))
        if raw_value in (None, ""):
            continue
        value = _optional_float(raw_value)
        if isinstance(raw_value, bool) or value is None or not math.isfinite(value):
            raise ValidationError("eia value must be a finite numeric measurement")
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
                published_at=None,
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
        row_series_id = _optional_str(series.get("series_id"))
        if row_series_id != series_id:
            raise ValidationError("eia legacy response series does not match requested series")
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
        return _eia_period_to_iso(f"{raw}-01-01")
    if len(raw) == 6 and raw.isdigit():
        return _eia_period_to_iso(f"{raw[:4]}-{raw[4:]}-01")
    if len(raw) == 7 and raw[4] == "-" and raw[:4].isdigit() and raw[5:].isdigit():
        return _eia_period_to_iso(f"{raw}-01")
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
