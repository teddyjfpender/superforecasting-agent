"""FRED API, CSV, and series-page decoding with explicit readers."""

from __future__ import annotations

from collections.abc import Callable
import csv
import re
from urllib.parse import quote, urlencode
from forecasting.models import ValidationError
from .economic_records import FredObservation
from .dates import _fred_date, _fred_date_to_iso
from .values import _optional_float

def _load_fred_from_api(
    series_id: str, *, api_key: str, limit: int, since_date, timeout: float,
    _read_json_endpoint: Callable[..., object],
) -> list[FredObservation]:
    """Official FRED API path — reliable JSON, used when FRED_API_KEY is set."""

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": str(max(limit, 1)),
    }
    if since_date is not None:
        params["observation_start"] = since_date.isoformat()
    endpoint = f"https://api.stlouisfed.org/fred/series/observations?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "fred observations (api)", timeout=timeout)
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValidationError("fred api response did not include observations")
    observations: list[FredObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        observation_date = _fred_date(str(row.get("date") or "").strip(), field_name="fred observation date")
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        raw_value = str(row.get("value") or "").strip()
        if raw_value in {"", "."}:
            continue
        observations.append(_fred_make_observation(series_id, observation_date, raw_value, raw=dict(row)))
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def _load_fred_from_csv(
    series_id: str, *, api_base_url: str, limit: int, since_date, timeout: float,
    _read_text_endpoint: Callable[..., str],
) -> list[FredObservation]:
    """Public fredgraph.csv path (no key). Bounded by ``timeout``."""

    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode({'id': series_id})}"
    text = _read_text_endpoint(endpoint, "fred observations", timeout=timeout)
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("fred observations CSV has no header row")
    date_key = _fred_date_column(reader.fieldnames)
    value_key = _fred_value_column(reader.fieldnames, series_id, date_key)
    observations: list[FredObservation] = []
    for index, row in enumerate(reader):
        observation_date = _fred_date(str(row.get(date_key) or "").strip(), field_name="fred observation date")
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        raw_value = str(row.get(value_key) or "").strip()
        if raw_value in {"", "."}:
            continue
        observations.append(
            _fred_make_observation(series_id, observation_date, raw_value, raw={"row_index": index, **dict(row)})
        )
    return observations[-limit:]


def _load_fred_from_series_page(
    series_id: str, *, limit: int, since_date, timeout: float,
    _read_text_endpoint: Callable[..., str],
) -> list[FredObservation]:
    endpoint = f"https://fred.stlouisfed.org/series/{quote(series_id)}"
    html = _read_text_endpoint(endpoint, "fred series page", timeout=timeout)
    return _parse_fred_series_page(series_id, html, limit=limit, since_date=since_date)


def _fred_make_observation(
    series_id: str, observation_date, value, *, raw: dict
) -> FredObservation:
    observation_iso = _fred_date_to_iso(observation_date)
    numeric = _optional_float(str(value)) if value is not None else None
    return FredObservation(
        series_id=series_id,
        observation_date=observation_date.isoformat(),
        value=numeric if numeric is not None else value,
        published_at=observation_iso,
        source_url=f"https://fred.stlouisfed.org/series/{quote(series_id)}",
        source_name="FRED",
        entry_id=f"{series_id}:{observation_date.isoformat()}",
        raw=raw,
    )


def _parse_fred_series_page(series_id: str, html: str, *, limit: int, since_date) -> list[FredObservation]:
    """Best-effort extraction of the latest observation from a FRED series page.

    FRED renders the latest value/date in ``series-meta-observation-value`` /
    ``series-meta-observation-date`` markup. Tolerant: returns [] if the markup
    is not recognised, so the caller can surface a clean error rather than crash.
    """

    value_match = re.search(
        r'series-meta-observation-value[^>]*>\s*([-+]?[0-9][0-9,]*\.?[0-9]*)', html
    )
    date_match = re.search(
        r'series-meta-observation-date[^>]*>\s*([A-Za-z0-9 ,:-]+?)\s*<', html
    )
    if not value_match or not date_match:
        return []
    observation_date = _fred_date(date_match.group(1).strip(), field_name="fred observation date")
    if observation_date is None:
        return []
    if since_date is not None and observation_date < since_date:
        return []
    value = value_match.group(1).replace(",", "")
    observation = _fred_make_observation(
        series_id,
        observation_date,
        value,
        raw={"source": "series_page_html", "observation_date": date_match.group(1).strip()},
    )
    return [observation][-limit:]


def _fred_date_column(fieldnames: list[str]) -> str:
    for field in fieldnames:
        if field.strip().lower() in {"date", "observation_date"}:
            return field
    return fieldnames[0]


def _fred_value_column(fieldnames: list[str], series_id: str, date_key: str) -> str:
    lowered_series = series_id.strip().lower()
    for field in fieldnames:
        if field != date_key and field.strip().lower() == lowered_series:
            return field
    for field in fieldnames:
        if field != date_key:
            return field
    raise ValidationError("fred observations CSV has no value column")
