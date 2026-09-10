"""Load SOCRATA open-data evidence records."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .dates import _optional_epoch_or_iso_timestamp
from .economic_records import SocrataRecord
from .values import _first_present, _optional_str

def load_socrata_records(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://{domain}/resource/{dataset_id}.json",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[SocrataRecord]:
    """Load Socrata open-data portal rows as timestamped evidence."""

    if limit <= 0:
        raise ValidationError("socrata import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    domain, dataset_id, endpoint = _socrata_endpoint(source, api_base_url=api_base_url, limit=limit)
    payload = _read_json_endpoint(endpoint, "socrata records")
    if not isinstance(payload, list):
        raise ValidationError("socrata response must be an array of JSON objects")

    records: list[SocrataRecord] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            continue
        updated_at = _socrata_timestamp(
            _first_present(
                row.get(":updated_at"),
                row.get("updated_at"),
                row.get("last_updated"),
                row.get("modified_at"),
                row.get("date_updated"),
            )
        )
        observation_time = _socrata_timestamp(
            _first_present(
                row.get("date"),
                row.get("report_date"),
                row.get("period"),
                row.get("timestamp"),
                row.get("created_at"),
                row.get(":created_at"),
            )
        )
        available_at = updated_at or observation_time
        if since_dt is not None and available_at:
            available_dt = timestamp_to_datetime(available_at)
            if available_dt is not None and available_dt < since_dt:
                continue
        values = {
            str(key): value
            for key, value in row.items()
            if not str(key).startswith(":") and value not in (None, "")
        }
        row_id = _optional_str(_first_present(row.get(":id"), row.get("id"), row.get("row_id"), row.get("sid")))
        records.append(
            SocrataRecord(
                domain=domain,
                dataset_id=dataset_id,
                row_id=row_id,
                observation_time=observation_time,
                updated_at=updated_at,
                values=values,
                source_url=_socrata_public_source_url(endpoint),
                source_name="Socrata",
                entry_id=f"{domain}/{dataset_id}:{row_id or index}",
                raw={"row_index": index, **dict(row)},
            )
        )
        if len(records) >= limit:
            break
    return records


def _socrata_endpoint(source: str, *, api_base_url: str, limit: int) -> tuple[str, str, str]:
    raw = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source.strip()
    if not raw:
        raise ValidationError("socrata source must include a portal domain and dataset id")

    parsed = urlparse(raw)
    query_pairs: list[tuple[str, str]]
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        domain = parsed.netloc
        dataset_id = _socrata_dataset_id_from_path(parsed.path)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        endpoint_base = f"{parsed.scheme}://{domain}/resource/{quote(dataset_id, safe='')}.json"
    else:
        path, query = raw.split("?", 1) if "?" in raw else (raw, "")
        parts = [part for part in path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise ValidationError("socrata source must be domain/dataset-id or a Socrata API URL")
        domain = parts[0]
        dataset_id = parts[-1].removesuffix(".json")
        query_pairs = parse_qsl(query, keep_blank_values=True)
        base = api_base_url.strip()
        if not base:
            raise ValidationError("socrata import --api-base-url cannot be empty")
        if "{domain}" in base or "{dataset_id}" in base:
            endpoint_base = base.format(
                domain=quote(domain, safe=".:-"),
                dataset_id=quote(dataset_id, safe=""),
            )
        elif base.endswith(".json"):
            endpoint_base = base
        else:
            endpoint_base = f"{base.rstrip('/')}/resource/{quote(dataset_id, safe='')}.json"

    if not domain or not dataset_id:
        raise ValidationError("socrata source must include a portal domain and dataset id")
    if "$limit" not in {name for name, _ in query_pairs}:
        query_pairs.append(("$limit", str(min(limit, 50000))))
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(query_pairs)}" if query_pairs else endpoint_base
    return domain, dataset_id, endpoint


def _socrata_dataset_id_from_path(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if "resource" in parts:
        index = parts.index("resource")
        if index + 1 < len(parts):
            return parts[index + 1].removesuffix(".json")
    if "views" in parts:
        index = parts.index("views")
        if index + 1 < len(parts):
            return parts[index + 1].removesuffix(".json")
    if parts:
        return parts[-1].removesuffix(".json")
    raise ValidationError("socrata API URL must include a dataset id")


def _socrata_public_source_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    params = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name not in {"$$app_token", "$limit"}
    ]
    return parsed._replace(query=urlencode(params)).geturl()


def _socrata_timestamp(value: object) -> str | None:
    return _optional_epoch_or_iso_timestamp(value, field_name="socrata timestamp")
