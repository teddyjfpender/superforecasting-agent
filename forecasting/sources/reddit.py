"""Load reddit public-attention evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import RedditPost
from .values import _collapse_ws, _first_present, _optional_float, _optional_int, _optional_str

def load_reddit_posts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://www.reddit.com/search.json",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[RedditPost]:
    """Load Reddit search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source.strip()
    if not normalized_source:
        raise ValidationError("reddit import query or API URL is required")
    if limit <= 0:
        raise ValidationError("reddit import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _reddit_endpoint(normalized_source, limit=limit, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "reddit search")
    children = _reddit_children(payload)

    posts: list[RedditPost] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        row = child.get("data") if isinstance(child.get("data"), dict) else child
        if not isinstance(row, dict):
            continue
        post_id = _optional_str(_first_present(row.get("name"), row.get("id")))
        if not post_id:
            continue
        created_at = _reddit_timestamp(_first_present(row.get("created_utc"), row.get("created")))
        created_dt = timestamp_to_datetime(created_at) if created_at else None
        if since_dt is not None and created_dt is not None and created_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled Reddit post")
        subreddit = _optional_str(row.get("subreddit"))
        permalink = _reddit_permalink(_optional_str(row.get("permalink")))
        posts.append(
            RedditPost(
                post_id=post_id,
                title=title,
                subreddit=subreddit,
                author=_optional_str(row.get("author")),
                url=_optional_str(_first_present(row.get("url_overridden_by_dest"), row.get("url"))),
                permalink=permalink,
                created_at=created_at,
                score=_optional_int(row.get("score")),
                comments=_optional_int(row.get("num_comments")),
                upvote_ratio=_optional_float(row.get("upvote_ratio")),
                selftext=_collapse_ws(_optional_str(row.get("selftext")) or ""),
                source_name=f"Reddit r/{subreddit}" if subreddit else "Reddit",
                entry_id=post_id,
                raw={
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "title": row.get("title"),
                    "subreddit": row.get("subreddit"),
                    "author": row.get("author"),
                    "created_utc": row.get("created_utc"),
                    "score": row.get("score"),
                    "num_comments": row.get("num_comments"),
                    "upvote_ratio": row.get("upvote_ratio"),
                    "query": normalized_source,
                },
            )
        )
        if len(posts) >= limit:
            break
    return posts


def _reddit_timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
        except (ValueError, OverflowError, OSError):
            return None
    text = _optional_str(value)
    if not text:
        return None
    try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    except (ValueError, OverflowError, OSError):
        pass
    try:
        return parse_timestamp(text, field_name="reddit timestamp")
    except ValidationError:
        return None


def _reddit_endpoint(source: str, *, limit: int, api_base_url: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "q": source,
        "sort": "new",
        "limit": min(limit, 100),
        "raw_json": 1,
        "type": "link",
    }
    separator = "&" if "?" in api_base_url else "?"
    return f"{api_base_url.rstrip('/')}{separator}{urlencode(params)}"


def _reddit_children(payload: object) -> list:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("children"), list):
            return data["children"]
        if isinstance(payload.get("children"), list):
            return payload["children"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("reddit search response must include data.children")


def _reddit_permalink(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if value.startswith("/"):
        return f"https://www.reddit.com{value}"
    return f"https://www.reddit.com/{value}"
