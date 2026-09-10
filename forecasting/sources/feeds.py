"""Parse RSS/Atom records and namespaced XML feed metadata."""

from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from forecasting.models import ValidationError, parse_timestamp
from .public_records import NewsFeedItem


def _arxiv_entry_url(entry: ElementTree.Element, entry_id: str | None) -> str | None:
    for link in _namespaced_findall(entry, "link"):
        attrs = dict(link.attrib)
        if attrs.get("rel", "alternate") == "alternate" and attrs.get("href"):
            return attrs["href"]
    return entry_id


def _arxiv_pdf_url(entry: ElementTree.Element) -> str | None:
    for link in _namespaced_findall(entry, "link"):
        attrs = dict(link.attrib)
        if attrs.get("title") == "pdf" and attrs.get("href"):
            return attrs["href"]
    return None


def _arxiv_id_from_entry_id(entry_id: str | None) -> str | None:
    if not entry_id:
        return None
    parsed = urlparse(entry_id)
    candidate = parsed.path.rsplit("/", 1)[-1] if parsed.scheme else entry_id.rsplit("/", 1)[-1]
    return candidate.strip() or None


def _parse_rss_items(root: ElementTree.Element) -> list[NewsFeedItem]:
    channel = root.find("channel")
    if channel is None:
        return []
    source_name = _text(channel, "title")
    items = []
    for item in channel.findall("item"):
        title = _text(item, "title") or "Untitled feed item"
        summary = _text(item, "description") or ""
        url = _text(item, "link")
        published_at = _normalize_feed_timestamp(_text(item, "pubDate") or _text(item, "published"))
        entry_id = _text(item, "guid") or url
        items.append(
            NewsFeedItem(
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=entry_id,
            )
        )
    return items


def _parse_atom_items(root: ElementTree.Element) -> list[NewsFeedItem]:
    source_name = _namespaced_text(root, "title")
    items = []
    for entry in _namespaced_findall(root, "entry"):
        title = _namespaced_text(entry, "title") or "Untitled feed item"
        summary = _namespaced_text(entry, "summary") or _namespaced_text(entry, "content") or ""
        published_at = _normalize_feed_timestamp(
            _namespaced_text(entry, "published") or _namespaced_text(entry, "updated")
        )
        url = None
        for link in _namespaced_findall(entry, "link"):
            link_attrs = dict(link.attrib)
            if link_attrs.get("rel", "alternate") == "alternate" and link_attrs.get("href"):
                url = link_attrs["href"]
                break
        entry_id = _namespaced_text(entry, "id") or url
        items.append(
            NewsFeedItem(
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                source_name=source_name,
                entry_id=entry_id,
            )
        )
    return items


def _normalize_feed_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parse_timestamp(value, field_name="feed timestamp")
    except ValidationError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(parent: ElementTree.Element, tag: str) -> str | None:
    child = parent.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _namespaced_text(parent: ElementTree.Element, tag: str) -> str | None:
    child = _namespaced_find(parent, tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _namespaced_find(parent: ElementTree.Element, tag: str) -> ElementTree.Element | None:
    for child in parent:
        if _local_name(child.tag) == tag:
            return child
    return None


def _namespaced_findall(parent: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return [child for child in parent if _local_name(child.tag) == tag]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
