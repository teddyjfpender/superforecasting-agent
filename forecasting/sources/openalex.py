"""Load and parse Openalex research evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode
from .values import _optional_str, _collapse_ws, _first_present
from forecasting.models import ValidationError, parse_timestamp
from .research_records import OpenAlexWork
from .dates import _fred_date, _fred_date_to_iso

def load_openalex_works(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.openalex.org/works",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[OpenAlexWork]:
    """Load OpenAlex scholarly works as timestamped research evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("openalex import query is required")
    if limit <= 0:
        raise ValidationError("openalex import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    params: dict[str, object] = {
        "search": normalized_query,
        "per-page": min(limit, 200),
        "sort": "publication_date:desc",
    }
    if since_date is not None:
        params["filter"] = f"from_publication_date:{since_date.isoformat()}"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "openalex works")
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("works") or payload.get("data")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValidationError("openalex works response must contain a results array")

    works: list[OpenAlexWork] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        publication_date = _fred_date(_optional_str(row.get("publication_date")), field_name="openalex publication date")
        if publication_date is not None and since_date is not None and publication_date < since_date:
            continue
        title = _collapse_ws(
            _optional_str(_first_present(row.get("display_name"), row.get("title"))) or "Untitled OpenAlex work"
        )
        location = row.get("primary_location") if isinstance(row.get("primary_location"), dict) else {}
        source = location.get("source") if isinstance(location.get("source"), dict) else {}
        url = _optional_str(
            _first_present(
                location.get("landing_page_url"),
                location.get("pdf_url"),
                row.get("doi"),
                row.get("id"),
            )
        )
        authors = _openalex_authors(row.get("authorships"))
        concepts = _openalex_concepts(row.get("concepts"))
        works.append(
            OpenAlexWork(
                work_id=_optional_str(row.get("id")),
                title=title,
                abstract=_openalex_abstract(row.get("abstract_inverted_index")),
                url=url,
                doi=_optional_str(row.get("doi")),
                published_at=_fred_date_to_iso(publication_date) if publication_date is not None else None,
                updated_at=_openalex_timestamp(row.get("updated_date")),
                authors=authors,
                concepts=concepts,
                source_name=_optional_str(source.get("display_name")) or "OpenAlex",
                entry_id=_optional_str(row.get("id")) or _optional_str(row.get("doi")) or title,
                raw={
                    "id": row.get("id"),
                    "doi": row.get("doi"),
                    "publication_date": row.get("publication_date"),
                    "updated_date": row.get("updated_date"),
                    "authors": authors,
                    "concepts": concepts,
                    "query": normalized_query,
                },
            )
        )
        if len(works) >= limit:
            break
    return works


def _openalex_abstract(value: object) -> str:
    if isinstance(value, str):
        return _collapse_ws(value)
    if not isinstance(value, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, raw_indexes in value.items():
        if not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            try:
                positions.append((int(raw_index), str(word)))
            except (TypeError, ValueError):
                continue
    return _collapse_ws(" ".join(word for _, word in sorted(positions)))


def _openalex_authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        author = row.get("author")
        if isinstance(author, dict):
            name = _optional_str(author.get("display_name"))
            if name:
                authors.append(name)
    return authors


def _openalex_concepts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    concepts: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        name = _optional_str(row.get("display_name"))
        if name:
            concepts.append(name)
    return concepts


def _openalex_timestamp(value: object) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="openalex timestamp")
    except ValidationError:
        parsed_date = _fred_date(text, field_name="openalex timestamp")
        return _fred_date_to_iso(parsed_date) if parsed_date is not None else None
