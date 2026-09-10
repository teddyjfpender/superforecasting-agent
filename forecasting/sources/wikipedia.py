"""Load wikipedia reference evidence through explicit reader callbacks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timezone
from urllib.parse import quote, urlencode
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import WikipediaPage
from .dates import _optional_iso_timestamp
from .values import _collapse_ws, _optional_str

def load_wikipedia_pages(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    as_of: str | None = None,
    api_base_url: str = "https://en.wikipedia.org/w/api.php",
    _read_json_endpoint: Callable[[str, str], object],
    _wikipedia_revision_as_of: Callable[..., dict[str, object] | None],
) -> list[WikipediaPage]:
    """Load Wikipedia/MediaWiki pages as timestamped reference evidence.

    When ``as_of`` is ``None`` (the default), behaviour is UNCHANGED: the live
    intro extract and latest-revision timestamp are returned. When ``as_of`` is
    set (the backtest path), each page is pinned to the NEWEST revision whose
    timestamp is ``<= as_of`` via the MediaWiki revisions API
    (``prop=revisions&rvstart=<as_of>&rvlimit=1&rvdir=older``); the page text is
    taken from that historical revision and ``updated_at`` is set to the revision
    timestamp so the resulting evidence's ``available_at`` predates the cutoff
    (no Sub-type-B time travel).
    """

    normalized_query = query.split(":", 1)[1].strip() if query.startswith("wikipedia:") else query.strip()
    if not normalized_query:
        raise ValidationError("wikipedia import query is required")
    if limit <= 0:
        raise ValidationError("wikipedia import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    as_of_ts = parse_timestamp(as_of, field_name="as_of") if as_of else None
    params: dict[str, object] = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": normalized_query,
        "gsrlimit": min(limit, 50),
        "prop": "extracts|info|revisions",
        "exintro": 1,
        "explaintext": 1,
        "inprop": "url",
        "rvprop": "timestamp",
    }
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "wikipedia pages")
    if not isinstance(payload, dict):
        raise ValidationError("wikipedia pages response must be a JSON object")
    query_payload = payload.get("query")
    if not isinstance(query_payload, dict):
        return []
    raw_pages = query_payload.get("pages")
    if isinstance(raw_pages, dict):
        rows = list(raw_pages.values())
    elif isinstance(raw_pages, list):
        rows = raw_pages
    else:
        rows = []
    rows = sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda row: (
            int(row.get("index") or 10_000_000),
            str(row.get("title") or ""),
        ),
    )

    pages: list[WikipediaPage] = []
    for row in rows:
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Wikipedia page")
        revisions = row.get("revisions") if isinstance(row.get("revisions"), list) else []
        revision = revisions[0] if revisions and isinstance(revisions[0], dict) else {}
        updated_at = _wikipedia_timestamp(revision.get("timestamp"))
        page_id = _optional_str(row.get("pageid"))
        extract = _collapse_ws(_optional_str(row.get("extract")) or "")
        raw: dict[str, object] = {
            "pageid": row.get("pageid"),
            "title": row.get("title"),
            "updated_at": updated_at,
            "query": normalized_query,
        }

        # AIA P2.4 — when pinned to a historical `as_of`, replace the LIVE page
        # text + timestamp with the newest revision dated <= as_of. With no
        # as_of this branch is skipped and the live page is served unchanged.
        if as_of_ts is not None:
            pinned = _wikipedia_revision_as_of(
                page_id=page_id,
                title=title,
                as_of=as_of_ts,
                endpoint_base=endpoint_base,
            )
            if pinned is None:
                # No revision predates the cutoff: the page did not yet exist as
                # of `as_of`, so it is not admissible historical evidence.
                continue
            updated_at = pinned["timestamp"]
            extract = _collapse_ws(pinned.get("extract") or "")
            raw["updated_at"] = updated_at
            raw["pinned_as_of"] = as_of_ts
            raw["pinned_revision_id"] = pinned.get("revid")

        updated_dt = timestamp_to_datetime(updated_at) if updated_at else None
        if since_dt is not None and updated_dt is not None and updated_dt < since_dt:
            continue
        pages.append(
            WikipediaPage(
                page_id=page_id,
                title=title,
                extract=extract,
                url=_optional_str(row.get("fullurl"))
                or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                updated_at=updated_at,
                source_name="Wikipedia",
                entry_id=page_id or title,
                raw=raw,
            )
        )
        if len(pages) >= limit:
            break
    return pages


def _wikipedia_revision_as_of(
    *,
    page_id: str | None,
    title: str,
    as_of: str,
    endpoint_base: str,
    _read_json_endpoint: Callable[[str, str], object],
) -> dict[str, object] | None:
    """Resolve the newest revision of a page dated ``<= as_of``.

    Returns ``{"timestamp", "revid", "extract"}`` for that revision, or ``None``
    when the page has no revision at-or-before ``as_of`` (i.e. it did not yet
    exist). Network access goes through the same JSON client the module already
    uses, so tests mock it the same way.
    """

    params: dict[str, object] = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "rvprop": "timestamp|ids|content",
        "rvslots": "main",
        "rvlimit": 1,
        "rvdir": "older",
        "rvstart": _wikipedia_api_timestamp(as_of),
    }
    if page_id:
        params["pageids"] = page_id
    else:
        params["titles"] = title
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(params)}"
    payload = _read_json_endpoint(endpoint, "wikipedia revision as-of")
    if not isinstance(payload, dict):
        return None
    query_payload = payload.get("query")
    if not isinstance(query_payload, dict):
        return None
    raw_pages = query_payload.get("pages")
    if isinstance(raw_pages, dict):
        page_rows = list(raw_pages.values())
    elif isinstance(raw_pages, list):
        page_rows = raw_pages
    else:
        return None
    for page_row in page_rows:
        if not isinstance(page_row, dict):
            continue
        revisions = page_row.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            continue
        revision = revisions[0]
        if not isinstance(revision, dict):
            continue
        timestamp = _wikipedia_timestamp(revision.get("timestamp"))
        if not timestamp:
            continue
        return {
            "timestamp": timestamp,
            "revid": revision.get("revid"),
            "extract": _wikipedia_revision_text(revision),
        }
    return None


def _wikipedia_revision_text(revision: dict) -> str:
    """Best-effort plain text from a revisions API row (slots or legacy '*')."""
    slots = revision.get("slots")
    if isinstance(slots, dict):
        main = slots.get("main")
        if isinstance(main, dict):
            content = main.get("content") or main.get("*")
            if isinstance(content, str):
                return content
    content = revision.get("content") or revision.get("*")
    return content if isinstance(content, str) else ""


def _wikipedia_api_timestamp(value: str) -> str:
    """Normalize an ISO timestamp to the ``YYYY-MM-DDTHH:MM:SSZ`` form the
    MediaWiki ``rvstart`` parameter expects."""
    dt = timestamp_to_datetime(value)
    if dt is None:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wikipedia_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='wikipedia timestamp')
