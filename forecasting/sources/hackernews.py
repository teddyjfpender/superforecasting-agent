"""Load hackernews public-attention evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import HackerNewsItem
from .values import _collapse_ws, _first_present, _optional_int, _optional_str
from forecasting.sources.dates import _optional_iso_timestamp

def load_hackernews_items(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://hn.algolia.com/api/v1/search_by_date",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[HackerNewsItem]:
    """Load Hacker News search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source.strip()
    if not normalized_source:
        raise ValidationError("hackernews import query or API URL is required")
    if limit <= 0:
        raise ValidationError("hackernews import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _hackernews_endpoint(normalized_source, limit=limit, since_ts=since_ts, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "hackernews search")
    hits = _hackernews_hits(payload)

    items: list[HackerNewsItem] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        object_id = _optional_str(hit.get("objectID"))
        if not object_id:
            continue
        created_at = _hackernews_timestamp(hit.get("created_at"))
        created_dt = timestamp_to_datetime(created_at) if created_at else None
        if since_dt is not None and created_dt is not None and created_dt < since_dt:
            continue
        title = _collapse_ws(
            _optional_str(
                _first_present(hit.get("title"), hit.get("story_title"), hit.get("comment_text"))
            )
            or "Untitled Hacker News item"
        )
        story_id = _optional_int(_first_present(hit.get("story_id"), hit.get("objectID")))
        hn_url = f"https://news.ycombinator.com/item?id={story_id or object_id}"
        items.append(
            HackerNewsItem(
                object_id=object_id,
                title=title,
                url=_optional_str(_first_present(hit.get("url"), hit.get("story_url"))),
                hn_url=hn_url,
                author=_optional_str(hit.get("author")),
                created_at=created_at,
                points=_optional_int(hit.get("points")),
                comments=_optional_int(hit.get("num_comments")),
                story_id=story_id,
                story_text=_collapse_ws(_optional_str(_first_present(hit.get("story_text"), hit.get("comment_text"))) or ""),
                source_name="Hacker News",
                entry_id=object_id,
                raw={
                    "objectID": hit.get("objectID"),
                    "title": hit.get("title"),
                    "story_title": hit.get("story_title"),
                    "url": hit.get("url"),
                    "story_url": hit.get("story_url"),
                    "author": hit.get("author"),
                    "created_at": hit.get("created_at"),
                    "points": hit.get("points"),
                    "num_comments": hit.get("num_comments"),
                    "query": normalized_source,
                },
            )
        )
        if len(items) >= limit:
            break
    return items


def _hackernews_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='hackernews timestamp')


def _hackernews_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "query": source,
        "tags": "story",
        "hitsPerPage": min(limit, 1000),
    }
    if since_ts:
        since_dt = timestamp_to_datetime(since_ts)
        if since_dt is not None:
            params["numericFilters"] = f"created_at_i>{int(since_dt.timestamp())}"
    return f"{api_base_url.rstrip('/')}?{urlencode(params)}"


def _hackernews_hits(payload: object) -> list:
    if isinstance(payload, dict) and isinstance(payload.get("hits"), list):
        return payload["hits"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("hackernews search response must include a hits array")
