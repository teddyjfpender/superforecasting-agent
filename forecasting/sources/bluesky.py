"""Load bluesky public-attention evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import BlueskyPost
from .values import _collapse_ws, _optional_int, _optional_str
from forecasting.sources.dates import _optional_iso_timestamp

def load_bluesky_posts(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    sort: str = "latest",
    author: str | None = None,
    lang: str | None = None,
    link_domain: str | None = None,
    url_filter: str | None = None,
    api_base_url: str = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[BlueskyPost]:
    """Load Bluesky public search results as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source.strip()
    if not normalized_source:
        raise ValidationError("bluesky import query or API URL is required")
    if limit <= 0:
        raise ValidationError("bluesky import --limit must be positive")
    if sort not in {"latest", "top"}:
        raise ValidationError("bluesky import --sort must be latest or top")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _bluesky_endpoint(
        normalized_source,
        limit=limit,
        since_ts=since_ts,
        sort=sort,
        author=author,
        lang=lang,
        link_domain=link_domain,
        url_filter=url_filter,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "bluesky search")
    rows = _bluesky_posts(payload)

    posts: list[BlueskyPost] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        author_row = row.get("author") if isinstance(row.get("author"), dict) else {}
        post_uri = _optional_str(row.get("uri"))
        cid = _optional_str(row.get("cid"))
        if not post_uri:
            continue
        text = _collapse_ws(_optional_str(record.get("text")) or "")
        created_at = _bluesky_timestamp(record.get("createdAt"))
        indexed_at = _bluesky_timestamp(row.get("indexedAt"))
        comparison_time = timestamp_to_datetime(created_at or indexed_at) if (created_at or indexed_at) else None
        if since_dt is not None and comparison_time is not None and comparison_time < since_dt:
            continue
        author_handle = _optional_str(author_row.get("handle"))
        author_did = _optional_str(author_row.get("did"))
        post_url = _bluesky_post_url(post_uri, author_handle or author_did)
        entry_id = post_uri or cid
        posts.append(
            BlueskyPost(
                post_uri=post_uri,
                cid=cid,
                text=text,
                author_handle=author_handle,
                author_display_name=_optional_str(author_row.get("displayName")),
                author_did=author_did,
                created_at=created_at,
                indexed_at=indexed_at,
                reply_count=_optional_int(row.get("replyCount")),
                repost_count=_optional_int(row.get("repostCount")),
                like_count=_optional_int(row.get("likeCount")),
                quote_count=_optional_int(row.get("quoteCount")),
                url=post_url,
                source_name=f"Bluesky @{author_handle}" if author_handle else "Bluesky",
                entry_id=entry_id,
                raw={
                    "uri": row.get("uri"),
                    "cid": row.get("cid"),
                    "author": row.get("author"),
                    "record": row.get("record"),
                    "indexedAt": row.get("indexedAt"),
                    "replyCount": row.get("replyCount"),
                    "repostCount": row.get("repostCount"),
                    "likeCount": row.get("likeCount"),
                    "quoteCount": row.get("quoteCount"),
                    "query": normalized_source,
                    "sort": sort,
                    "author_filter": author,
                    "lang_filter": lang,
                    "link_domain_filter": link_domain,
                    "url_filter": url_filter,
                },
            )
        )
        if len(posts) >= limit:
            break
    return posts


def _bluesky_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='bluesky timestamp')


def _bluesky_endpoint(
    source: str,
    *,
    limit: int,
    since_ts: str | None,
    sort: str,
    author: str | None,
    lang: str | None,
    link_domain: str | None,
    url_filter: str | None,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    params: dict[str, object] = {
        "q": source,
        "sort": sort,
        "limit": min(limit, 100),
    }
    if since_ts:
        params["since"] = since_ts
    if author:
        params["author"] = author
    if lang:
        params["lang"] = lang
    if link_domain:
        params["domain"] = link_domain
    if url_filter:
        params["url"] = url_filter
    separator = "&" if "?" in api_base_url else "?"
    return f"{api_base_url.rstrip('/')}{separator}{urlencode(params)}"


def _bluesky_posts(payload: object) -> list:
    if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
        return payload["posts"]
    if isinstance(payload, list):
        return payload
    raise ValidationError("bluesky search response must include a posts array")


def _bluesky_post_url(post_uri: str | None, actor: str | None) -> str | None:
    if not post_uri:
        return None
    parsed = urlparse(post_uri)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return post_uri
    if not post_uri.startswith("at://"):
        return None
    parts = post_uri[5:].split("/")
    if len(parts) < 3:
        return None
    profile = actor or parts[0]
    rkey = parts[-1]
    if not profile or not rkey:
        return None
    return f"https://bsky.app/profile/{quote(profile, safe=':.')}/post/{quote(rkey, safe='')}"
