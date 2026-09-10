"""Load mastodon public-attention evidence."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, unquote, urlencode, urlparse
from html import unescape
import re
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .public_records import MastodonStatus
from .values import _collapse_ws, _optional_int, _optional_str
from forecasting.sources.dates import _optional_iso_timestamp

def load_mastodon_statuses(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    local: bool = False,
    only_media: bool = False,
    api_base_url: str = "https://mastodon.social/api/v1/timelines/tag",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[MastodonStatus]:
    """Load Mastodon hashtag timeline statuses as timestamped public-attention evidence."""

    normalized_source = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source.strip()
    if not normalized_source:
        raise ValidationError("mastodon import tag, instance/tag, or API URL is required")
    if limit <= 0:
        raise ValidationError("mastodon import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _mastodon_endpoint(
        normalized_source,
        limit=limit,
        local=local,
        only_media=only_media,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "mastodon hashtag timeline")
    rows = _mastodon_status_rows(payload)

    statuses: list[MastodonStatus] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status_id = _optional_str(row.get("id"))
        if not status_id:
            continue
        created_at = _mastodon_timestamp(row.get("created_at"))
        created_dt = timestamp_to_datetime(created_at) if created_at else None
        if since_dt is not None and created_dt is not None and created_dt < since_dt:
            continue
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        card = row.get("card") if isinstance(row.get("card"), dict) else {}
        tags = _mastodon_tag_names(row.get("tags"))
        acct = _optional_str(account.get("acct"))
        statuses.append(
            MastodonStatus(
                status_id=status_id,
                uri=_optional_str(row.get("uri")),
                url=_optional_str(row.get("url")),
                content_text=_mastodon_content_text(row.get("content")),
                account_acct=acct,
                account_username=_optional_str(account.get("username")),
                account_display_name=_optional_str(account.get("display_name")),
                account_url=_optional_str(account.get("url")),
                created_at=created_at,
                replies_count=_optional_int(row.get("replies_count")),
                reblogs_count=_optional_int(row.get("reblogs_count")),
                favourites_count=_optional_int(row.get("favourites_count")),
                language=_optional_str(row.get("language")),
                visibility=_optional_str(row.get("visibility")),
                tags=tags,
                card_url=_optional_str(card.get("url")),
                card_title=_optional_str(card.get("title")),
                source_name=f"Mastodon @{acct}" if acct else "Mastodon",
                entry_id=status_id,
                raw={
                    "id": row.get("id"),
                    "uri": row.get("uri"),
                    "url": row.get("url"),
                    "created_at": row.get("created_at"),
                    "account": row.get("account"),
                    "replies_count": row.get("replies_count"),
                    "reblogs_count": row.get("reblogs_count"),
                    "favourites_count": row.get("favourites_count"),
                    "language": row.get("language"),
                    "visibility": row.get("visibility"),
                    "tags": row.get("tags"),
                    "card": row.get("card"),
                    "source": normalized_source,
                    "local": local,
                    "only_media": only_media,
                },
            )
        )
        if len(statuses) >= limit:
            break
    return statuses


def _mastodon_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='mastodon timestamp')


def _mastodon_endpoint(
    source: str,
    *,
    limit: int,
    local: bool,
    only_media: bool,
    api_base_url: str,
) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source
    instance, tag = _mastodon_source_parts(source)
    endpoint_base = api_base_url.rstrip("/")
    if instance and api_base_url == "https://mastodon.social/api/v1/timelines/tag":
        endpoint_base = f"https://{instance}/api/v1/timelines/tag"
    params: dict[str, object] = {"limit": min(limit, 40)}
    if local:
        params["local"] = "true"
    if only_media:
        params["only_media"] = "true"
    return f"{endpoint_base}/{quote(tag, safe='')}?{urlencode(params)}"


def _mastodon_source_parts(source: str) -> tuple[str | None, str]:
    value = source.strip().lstrip("#")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and parts[-2] in {"tags", "tag"}:
            tag = parts[-1]
        elif parts:
            tag = parts[-1]
        else:
            tag = ""
        if not tag:
            raise ValidationError("mastodon source URL must include a hashtag")
        return parsed.netloc, tag.lstrip("#")
    if "/" in value:
        instance, tag = value.split("/", 1)
        instance = instance.strip().removeprefix("@")
        tag = tag.strip().lstrip("#")
        if "." in instance and tag:
            return instance, tag
    tag = value.strip().lstrip("#")
    if not tag:
        raise ValidationError("mastodon source must include a hashtag")
    return None, tag


def _mastodon_status_rows(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("statuses"), list):
        return payload["statuses"]
    raise ValidationError("mastodon hashtag timeline response must be an array")


def _mastodon_tag_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _optional_str(item.get("name"))
        else:
            name = _optional_str(item)
        if name:
            tags.append(name)
    return tags


def _mastodon_content_text(value: object) -> str:
    text = _optional_str(value) or ""
    text = re.sub(r"<[^>]+>", " ", text)
    return _collapse_ws(unescape(text))
