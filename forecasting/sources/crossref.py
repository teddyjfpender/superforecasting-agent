"""Load and parse Crossref research evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from .values import _optional_str, _optional_int, _collapse_ws
from forecasting.models import ValidationError, parse_timestamp
from .research_records import CrossrefWork
from .dates import _fred_date

def load_crossref_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.crossref.org/works",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CrossrefWork]:
    """Load Crossref works as timestamped DOI/scholarly evidence."""

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("crossref:") else query.strip()
    if not normalized_query:
        raise ValidationError("crossref import query or DOI is required")
    if limit <= 0:
        raise ValidationError("crossref import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    params: dict[str, object] = {
        "query.bibliographic": normalized_query,
        "rows": min(limit, 100),
        "sort": "published",
        "order": "desc",
    }
    if since_date is not None:
        params["filter"] = f"from-pub-date:{since_date.isoformat()}"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "crossref works")
    rows: object
    if isinstance(payload, dict):
        message = payload.get("message")
        rows = message.get("items") if isinstance(message, dict) else payload.get("items")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("crossref works response must contain a message.items array")

    works: list[CrossrefWork] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _crossref_published_at(row)
        published_date = _fred_date(published_at[:10], field_name="crossref publication date") if published_at else None
        if since_date is not None and published_date is not None and published_date < since_date:
            continue
        title = _collapse_ws(_crossref_first(row.get("title")) or "Untitled Crossref work")
        abstract = _collapse_ws(_optional_str(row.get("abstract")) or "")
        doi = _optional_str(row.get("DOI"))
        container_title = _crossref_first(row.get("container-title"))
        publisher = _optional_str(row.get("publisher"))
        source_name = container_title or publisher or "Crossref"
        url = _optional_str(row.get("URL")) or (f"https://doi.org/{quote(doi, safe='/')}" if doi else None)
        entry_id = doi or _optional_str(row.get("member")) or title
        works.append(
            CrossrefWork(
                doi=doi,
                title=title,
                abstract=abstract,
                url=url,
                published_at=published_at,
                updated_at=_crossref_timestamp(row.get("deposited")),
                authors=_crossref_authors(row.get("author")),
                subjects=_crossref_string_list(row.get("subject")),
                container_title=container_title,
                publisher=publisher,
                work_type=_optional_str(row.get("type")),
                reference_count=_optional_int(row.get("reference-count")),
                cited_by_count=_optional_int(row.get("is-referenced-by-count")),
                source_name=source_name,
                entry_id=entry_id,
                raw={
                    "DOI": row.get("DOI"),
                    "URL": row.get("URL"),
                    "published_at": published_at,
                    "deposited": row.get("deposited"),
                    "publisher": row.get("publisher"),
                    "type": row.get("type"),
                    "container-title": row.get("container-title"),
                    "subject": row.get("subject"),
                    "query": normalized_query,
                },
            )
        )
        if len(works) >= limit:
            break
    return works


def _crossref_first(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _optional_str(item)
            if text:
                return _collapse_ws(text)
        return None
    text = _optional_str(value)
    return _collapse_ws(text) if text else None


def _crossref_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            items.append(_collapse_ws(text))
    return items


def _crossref_authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        name = _optional_str(row.get("name"))
        if not name:
            name = " ".join(
                part
                for part in (
                    _optional_str(row.get("given")),
                    _optional_str(row.get("family")),
                )
                if part
            )
        if name:
            authors.append(_collapse_ws(name))
    return authors


def _crossref_published_at(row: dict) -> str | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parsed = _crossref_date_parts(row.get(key))
        if parsed:
            return parsed
    return None


def _crossref_date_parts(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts:
        return None
    first = parts[0]
    if not isinstance(first, list) or not first:
        return None
    try:
        year = int(first[0])
        month = int(first[1]) if len(first) > 1 else 1
        day = int(first[2]) if len(first) > 2 else 1
    except (TypeError, ValueError):
        return None
    if month < 1 or month > 12:
        month = 1
    if day < 1 or day > 31:
        day = 1
    try:
        return datetime(year, month, day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime(year, month, 1, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _crossref_timestamp(value: object) -> str | None:
    if isinstance(value, dict):
        timestamp = _optional_str(value.get("date-time") or value.get("timestamp"))
    else:
        timestamp = _optional_str(value)
    if not timestamp:
        return None
    try:
        return parse_timestamp(timestamp, field_name="crossref timestamp")
    except ValidationError:
        return None
