"""Load federal_register public records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import FederalRegisterDocument
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _optional_str

def load_federal_register_documents(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.federalregister.gov/api/v1/documents.json",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[FederalRegisterDocument]:
    """Load Federal Register documents as timestamped policy evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("federalregister import query is required")
    if limit <= 0:
        raise ValidationError("federalregister import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    base = api_base_url.rstrip("/")
    endpoint_base = base if base.endswith(".json") else f"{base}/documents.json"
    params: dict[str, object] = {
        "conditions[term]": normalized_query,
        "order": "newest",
        "per_page": min(limit, 100),
    }
    if since_ts:
        params["conditions[publication_date][gte]"] = since_ts[:10]
    endpoint = f"{endpoint_base}?{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "federal register documents")
    if isinstance(payload, dict):
        rows = payload.get("results")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("federal register documents response must include a results array")

    documents: list[FederalRegisterDocument] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published_at = _federalregister_timestamp(row.get("publication_date"))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and published_dt is not None and published_dt < since_dt:
            continue
        agencies_raw = row.get("agencies") if isinstance(row.get("agencies"), list) else []
        agencies = [
            name
            for agency in agencies_raw
            if isinstance(agency, dict)
            for name in [_optional_str(agency.get("name"))]
            if name
        ]
        document_number = _optional_str(row.get("document_number"))
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Federal Register document")
        documents.append(
            FederalRegisterDocument(
                document_number=document_number,
                title=title,
                abstract=_collapse_ws(_optional_str(row.get("abstract")) or ""),
                url=_optional_str(row.get("html_url")),
                pdf_url=_optional_str(row.get("pdf_url")),
                published_at=published_at,
                document_type=_optional_str(row.get("type")) or _optional_str(row.get("document_type")),
                agencies=agencies,
                citation=_optional_str(row.get("citation")),
                source_name="Federal Register",
                entry_id=document_number or _optional_str(row.get("html_url")) or title,
                raw={
                    "document_number": row.get("document_number"),
                    "title": row.get("title"),
                    "publication_date": row.get("publication_date"),
                    "type": row.get("type"),
                    "agencies": agencies,
                    "query": normalized_query,
                },
            )
        )
        if len(documents) >= limit:
            break
    return documents


def _federalregister_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='federal register timestamp')
