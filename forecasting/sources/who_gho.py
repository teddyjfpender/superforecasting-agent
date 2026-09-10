"""Load who_gho indicator observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import re
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import WhoGhoObservation
from .values import _collapse_optional, _first_present, _optional_float, _optional_str

def load_who_gho_observations(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    country: str | None = None,
    dimensions: dict[str, str] | list[str] | None = None,
    api_base_url: str = "https://ghoapi.azureedge.net/api",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[WhoGhoObservation]:
    """Load WHO Global Health Observatory indicator rows as evidence."""

    if limit <= 0:
        raise ValidationError("whogho import --limit must be positive")
    indicator, endpoint = _who_gho_endpoint(
        source,
        limit=limit,
        country=country,
        dimensions=dimensions,
        api_base_url=api_base_url,
    )
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "WHO GHO observations")
    if isinstance(payload, dict):
        rows = next((payload[key] for key in ("value", "results", "data")
                     if isinstance(payload.get(key), list)), None)
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("WHO GHO response must include a value array")

    observations: list[WhoGhoObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_indicator = _optional_str(_first_present(row.get("IndicatorCode"), row.get("indicator"))) or indicator
        spatial_dim = _optional_str(_first_present(row.get("SpatialDim"), row.get("SpatialDimensionValue")))
        time_dim = _optional_str(_first_present(row.get("TimeDim"), row.get("TimeDimensionValue"), row.get("Time")))
        published_at = _who_gho_timestamp(
            _first_present(row.get("Date"), row.get("TimeDim"), row.get("TimeDimensionValue"), row.get("Time"))
        )
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        numeric_value = _optional_float(_first_present(row.get("NumericValue"), row.get("numericValue")))
        raw_value = _first_present(row.get("Value"), row.get("value"), row.get("TextValue"))
        value = numeric_value if numeric_value is not None else _collapse_optional(raw_value)
        low = _optional_float(_first_present(row.get("Low"), row.get("low")))
        high = _optional_float(_first_present(row.get("High"), row.get("high")))
        dim1 = _optional_str(row.get("Dim1"))
        dim2 = _optional_str(row.get("Dim2"))
        dim3 = _optional_str(row.get("Dim3"))
        row_id = _optional_str(_first_present(row.get("Id"), row.get("id"), row.get("DataSourceDim")))
        entry_id = row_id or ":".join(
            part
            for part in [
                row_indicator,
                spatial_dim,
                time_dim,
                dim1,
                dim2,
                dim3,
            ]
            if part
        )
        if not entry_id:
            continue
        observations.append(
            WhoGhoObservation(
                indicator=row_indicator,
                spatial_dim=spatial_dim,
                time_dim=time_dim,
                dim1=dim1,
                dim2=dim2,
                dim3=dim3,
                value=value,
                numeric_value=numeric_value,
                low=low,
                high=high,
                published_at=published_at,
                source_url=endpoint,
                source_name="WHO Global Health Observatory",
                entry_id=entry_id,
                raw=dict(row),
            )
        )
        if len(observations) >= limit:
            break
    return observations


def _who_gho_endpoint(
    source: str,
    *,
    limit: int,
    country: str | None,
    dimensions: dict[str, str] | list[str] | None,
    api_base_url: str,
) -> tuple[str, str]:
    value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source.strip()
    if not value:
        raise ValidationError("whogho source indicator, API URL, or indicator query is required")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        indicator = Path(parsed.path.rstrip("/")).name or "who-gho"
        return indicator, value

    indicator, raw_query = (value.split("?", 1) + [""])[:2] if "?" in value else (value, "")
    indicator = indicator.strip().strip("/")
    if not indicator or "/" in indicator:
        raise ValidationError("whogho source must be a WHO GHO indicator code or API URL")
    query_filters = dict(parse_qsl(raw_query, keep_blank_values=False))
    filters: list[tuple[str, str]] = []
    if country:
        filters.append(("SpatialDim", country.strip().upper()))
    for key, raw_value in query_filters.items():
        if key.startswith("$"):
            continue
        filter_key = "SpatialDim" if key.lower() in {"country", "spatial"} else key
        filters.append((filter_key, raw_value))
    for key, raw_value in _who_gho_dimensions(dimensions).items():
        filters.append((key, raw_value))

    params = {
        "$top": min(max(limit, 1), 1000),
        "$orderby": "TimeDim desc",
    }
    existing_filter = query_filters.get("$filter")
    filter_parts = [existing_filter] if existing_filter else []
    filter_parts.extend(_who_gho_filter_expression(key, raw_value) for key, raw_value in filters if raw_value)
    if filter_parts:
        params["$filter"] = " and ".join(filter_parts)
    endpoint = f"{api_base_url.rstrip('/')}/{quote(indicator, safe='')}"
    return indicator, f"{endpoint}?{urlencode(params)}"


def _who_gho_dimensions(dimensions: dict[str, str] | list[str] | None) -> dict[str, str]:
    if not dimensions:
        return {}
    if isinstance(dimensions, dict):
        items = dimensions.items()
    else:
        parsed: list[tuple[str, str]] = []
        for item in dimensions:
            text = _optional_str(item)
            if not text:
                continue
            if "=" not in text:
                raise ValidationError("whogho --dimension values must use KEY=VALUE")
            key, value = text.split("=", 1)
            parsed.append((key.strip(), value.strip()))
        items = parsed
    return {key.strip(): str(value).strip() for key, value in items if key and str(value).strip()}


def _who_gho_filter_expression(field: str, value: str) -> str:
    field_name = field.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field_name):
        raise ValidationError("whogho filter field names must be alphanumeric identifiers")
    escaped_value = value.replace("'", "''")
    return f"{field_name} eq '{escaped_value}'"


def _who_gho_timestamp(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        text = str(int(value))
    else:
        text = str(value).strip()
    if text.isdigit() and len(text) == 4:
        text = f"{text}-01-01"
    try:
        return parse_timestamp(text, field_name="WHO GHO timestamp")
    except ValidationError:
        return None
