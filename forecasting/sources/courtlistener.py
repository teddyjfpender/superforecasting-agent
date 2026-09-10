"""Load courtlistener public records as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import CourtListenerSearchResult
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _first_present, _optional_int, _optional_str

def load_courtlistener_search_results(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    search_type: str = "o",
    api_base_url: str = "https://www.courtlistener.com/api/rest/v4/search/",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CourtListenerSearchResult]:
    """Load CourtListener search results as timestamped legal evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source.strip()
    if not normalized_source:
        raise ValidationError("courtlistener import query or API URL is required")
    if limit <= 0:
        raise ValidationError("courtlistener import --limit must be positive")
    normalized_type = search_type.strip() or "o"
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _courtlistener_endpoint(
        normalized_source,
        limit=limit,
        search_type=normalized_type,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "courtlistener search")
    if isinstance(payload, dict):
        rows = payload.get("results")
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValidationError("courtlistener search response must include a results array")

    results: list[CourtListenerSearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_filed = _courtlistener_timestamp(
            _first_present(row.get("dateFiled"), row.get("date_filed"), row.get("dateFiledPretty"))
        )
        date_argued = _courtlistener_timestamp(
            _first_present(row.get("dateArgued"), row.get("date_argued"), row.get("dateReargued"))
        )
        available_at = date_filed or date_argued
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        title = _collapse_ws(
            _optional_str(_first_present(row.get("caseName"), row.get("caseNameFull"), row.get("title")))
            or "Untitled CourtListener result"
        )
        result_id = _optional_str(_first_present(row.get("id"), row.get("cluster_id"), row.get("opinion_id")))
        court = _optional_str(row.get("court"))
        court_id = _optional_str(row.get("court_id"))
        url = _courtlistener_result_url(
            _optional_str(_first_present(row.get("absolute_url"), row.get("absoluteUrl"), row.get("url")))
        )
        results.append(
            CourtListenerSearchResult(
                result_id=result_id,
                title=title,
                snippet=_collapse_ws(_optional_str(_first_present(row.get("snippet"), row.get("text"))) or ""),
                url=url,
                court=court,
                court_id=court_id,
                docket_number=_optional_str(_first_present(row.get("docketNumber"), row.get("docket_number"))),
                date_filed=date_filed,
                date_argued=date_argued,
                status=_optional_str(row.get("status")),
                citation=_courtlistener_citation(row),
                judge=_collapse_ws(_optional_str(row.get("judge")) or ""),
                cite_count=_optional_int(_first_present(row.get("citeCount"), row.get("cite_count"))),
                search_type=normalized_type,
                source_name=f"CourtListener {court_id}" if court_id else "CourtListener",
                entry_id=result_id or url or title,
                raw={
                    "id": row.get("id"),
                    "cluster_id": row.get("cluster_id"),
                    "opinion_id": row.get("opinion_id"),
                    "caseName": row.get("caseName"),
                    "court": court,
                    "court_id": court_id,
                    "docketNumber": row.get("docketNumber"),
                    "dateFiled": row.get("dateFiled"),
                    "query": normalized_source,
                    "search_type": normalized_type,
                },
            )
        )
        if len(results) >= limit:
            break
    return results


def _courtlistener_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='courtlistener timestamp')


def _courtlistener_endpoint(source: str, *, limit: int, search_type: str, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {
        "q": source,
        "type": search_type,
        "page_size": min(limit, 100),
    }
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _courtlistener_result_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("/"):
        return f"https://www.courtlistener.com{value}"
    return f"https://www.courtlistener.com/{value.lstrip('/')}"


def _courtlistener_citation(row: dict[str, object]) -> str | None:
    for key in ("citation", "citation_str", "neutralCite", "neutral_cite"):
        value = row.get(key)
        if isinstance(value, list):
            parts = [
                _optional_str(item.get("cite") if isinstance(item, dict) else item)
                for item in value
            ]
            citation = ", ".join(part for part in parts if part)
            if citation:
                return citation
        text = _optional_str(value)
        if text:
            return text
    citations = row.get("citations")
    if isinstance(citations, list):
        parts = [
            _optional_str(item.get("cite") if isinstance(item, dict) else item)
            for item in citations
        ]
        citation = ", ".join(part for part in parts if part)
        if citation:
            return citation
    return None
