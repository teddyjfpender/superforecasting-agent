"""Load scholarly papers from the arXiv Atom API."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode
from xml.etree import ElementTree

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import ArxivPaper
from .feeds import _namespaced_findall, _namespaced_text, _normalize_feed_timestamp, _arxiv_entry_url, _arxiv_pdf_url, _arxiv_id_from_entry_id
from .values import _collapse_ws, _optional_str

def load_arxiv_papers(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://export.arxiv.org/api/query",
    _read_text_endpoint: Callable[[str, str], str],
) -> list[ArxivPaper]:
    """Load recent arXiv API papers as timestamped evidence rows."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("arxiv import query is required")
    if limit <= 0:
        raise ValidationError("arxiv import --limit must be positive")
    since_dt = timestamp_to_datetime(parse_timestamp(since, field_name="since")) if since else None
    params = {
        "search_query": normalized_query,
        "start": 0,
        "max_results": min(limit, 100),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    text = _read_text_endpoint(endpoint, "arxiv papers")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValidationError("arxiv papers response is not valid Atom XML") from exc

    papers: list[ArxivPaper] = []
    for entry in _namespaced_findall(root, "entry"):
        published_at = _normalize_feed_timestamp(
            _namespaced_text(entry, "published") or _namespaced_text(entry, "updated")
        )
        updated_at = _normalize_feed_timestamp(_namespaced_text(entry, "updated"))
        candidate_dt = timestamp_to_datetime(published_at or updated_at)
        if since_dt is not None and (candidate_dt is None or candidate_dt < since_dt):
            continue
        title = _collapse_ws(_namespaced_text(entry, "title") or "Untitled arXiv paper")
        abstract = _collapse_ws(_namespaced_text(entry, "summary") or "")
        entry_id = _optional_str(_namespaced_text(entry, "id"))
        url = _arxiv_entry_url(entry, entry_id)
        pdf_url = _arxiv_pdf_url(entry)
        authors = [
            name
            for author in _namespaced_findall(entry, "author")
            for name in [_optional_str(_namespaced_text(author, "name"))]
            if name
        ]
        categories = [
            term
            for category in _namespaced_findall(entry, "category")
            for term in [_optional_str(category.attrib.get("term"))]
            if term
        ]
        arxiv_id = _arxiv_id_from_entry_id(entry_id)
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                title=title,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                published_at=published_at,
                updated_at=updated_at,
                authors=authors,
                categories=categories,
                source_name="arXiv",
                entry_id=entry_id or arxiv_id or title,
                raw={
                    "id": entry_id,
                    "published": published_at,
                    "updated": updated_at,
                    "authors": authors,
                    "categories": categories,
                    "query": normalized_query,
                },
            )
        )
        if len(papers) >= limit:
            break
    return papers
