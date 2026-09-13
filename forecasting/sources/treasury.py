"""Load and parse U.S. Treasury Fiscal Data evidence records."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import TreasuryRecord
from .values import _first_present, _optional_float, _optional_str

def load_treasury_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    date_field: str = "record_date",
    value_field: str | None = None,
    api_base_url: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[TreasuryRecord]:
    """Load U.S. Treasury Fiscal Data API rows as timestamped evidence."""

    dataset, endpoint = _treasury_endpoint(
        source,
        api_base_url=api_base_url,
        date_field=date_field,
        limit=max(limit, 100),
    )
    if not dataset:
        raise ValidationError("treasury import dataset path or API URL is required")
    if limit <= 0:
        raise ValidationError("treasury import --limit must be positive")
    if not date_field.strip():
        raise ValidationError("treasury import --date-field cannot be empty")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    payload = _read_json_endpoint(endpoint, "treasury fiscal data")
    records = _treasury_records_from_payload(
        payload,
        dataset=dataset,
        endpoint=endpoint,
        date_field=date_field,
        value_field=value_field,
    )
    if since_dt is not None:
        records = [
            record
            for record in records
            if (timestamp_to_datetime(_treasury_date_to_iso(record.record_date)) or since_dt) >= since_dt
        ]
    records.sort(key=lambda item: item.record_date)
    return records[-limit:]


def _treasury_endpoint(source: str, *, api_base_url: str, date_field: str, limit: int) -> tuple[str, str]:
    raw = source.strip()
    if not raw:
        return "", ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        dataset = unquote(parsed.path).split("/fiscal_service/", 1)[-1].strip("/") or Path(unquote(parsed.path)).name
        return dataset or raw, raw
    dataset = raw.split(":", 1)[1].strip() if raw.startswith("treasury:") else raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("treasury import --api-base-url cannot be empty")
    if "{dataset}" in base:
        endpoint = base.replace("{dataset}", quote(dataset, safe="/?:=&[]-,"))
    else:
        endpoint = f"{base.rstrip('/')}/{dataset.lstrip('/')}"
    parsed = urlparse(endpoint)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    additions: dict[str, str] = {}
    if "page[size]" not in params and "page%5Bsize%5D" not in parsed.query:
        additions["page[size]"] = str(limit)
    if "sort" not in params and date_field:
        additions["sort"] = f"-{date_field}"
    if additions:
        separator = "&" if parsed.query else "?"
        endpoint = f"{endpoint}{separator}{urlencode(additions)}"
    return dataset, endpoint


def _treasury_records_from_payload(
    payload: object,
    *,
    dataset: str,
    endpoint: str,
    date_field: str,
    value_field: str | None,
) -> list[TreasuryRecord]:
    if not isinstance(payload, dict):
        raise ValidationError("treasury fiscal data response must be a JSON object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValidationError("treasury fiscal data response must contain data rows")
    meta = payload.get("meta")
    labels = meta.get("labels") if isinstance(meta, dict) and isinstance(meta.get("labels"), dict) else {}
    records: list[TreasuryRecord] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        raw_date = row.get(date_field)
        if raw_date is None:
            raise ValidationError("treasury response is missing requested date field")
        record_date = _optional_str(raw_date)
        if not record_date:
            continue
        published_at = _treasury_date_to_iso(record_date)
        if not published_at:
            continue
        selected_field, raw_value = _treasury_value(row, date_field=date_field, value_field=value_field)
        value = _optional_float(raw_value) if raw_value is not None else None
        label = _optional_str(labels.get(selected_field)) if selected_field and isinstance(labels, dict) else None
        records.append(
            TreasuryRecord(
                dataset=dataset,
                record_date=record_date,
                value=value if value is not None else (_optional_str(raw_value) if raw_value is not None else None),
                value_field=selected_field,
                value_label=label,
                published_at=None,
                source_url=endpoint,
                source_name="U.S. Treasury Fiscal Data",
                entry_id=f"{dataset}:{record_date}:{index}",
                raw={"row_index": index, "labels": dict(labels) if isinstance(labels, dict) else {}, **dict(row)},
            )
        )
    return records


def _treasury_value(row: dict[str, object], *, date_field: str, value_field: str | None) -> tuple[str | None, object | None]:
    if value_field:
        if value_field not in row:
            raise ValidationError("treasury response is missing requested value field")
        return value_field, row[value_field]
    ignored = {date_field, "record_date", "effective_date", "auction_date", "reporting_date", "calendar_date"}
    candidates = [(str(key), value) for key, value in row.items()
                  if key not in ignored and value not in (None, "") and _optional_float(value) is not None]
    if len(candidates) > 1:
        raise ValidationError("treasury measurement is ambiguous; specify --value-field")
    return candidates[0] if candidates else (None, None)


def _treasury_date_to_iso(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = parse_timestamp(raw, field_name="treasury date")
    except ValidationError:
        return None
    return parsed
