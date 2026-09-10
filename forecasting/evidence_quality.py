"""Shared conservative identity rules for evidence audits and source diversity.

Different URLs are not independent observations. Host diversity is a proxy;
syndicated reports should declare metadata.independence_group or original_source_url.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def revision_key(entry_id: str, raw: dict) -> str:
    """Idempotent capture of an upstream record, retaining changed revisions."""
    import hashlib
    import json

    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"{entry_id}:{digest}"


def source_domain(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower().removeprefix("www.") if host else None


def source_identity(item: Any) -> str | None:
    metadata = getattr(item, "metadata", None) or {}
    group = str(metadata.get("independence_group") or "").strip().lower()
    if group:
        return group
    for url in (metadata.get("original_source_url"), getattr(item, "source_url", None)):
        host = source_domain(url)
        if host:
            return host
    name = str(getattr(item, "source_name", None) or "").strip().lower()
    return name or str(getattr(item, "source_type", None) or "").strip().lower() or None


def observation_identity(item: Any) -> tuple:
    """Ignore URL tracking and fragment differences, preserving substantive queries.

    A changed claim or observation time remains a separate observation. Exact
    mirrored claims with an explicit shared origin also collapse in the audit.
    The original evidence rows are retained unchanged for provenance.
    """
    metadata = getattr(item, "metadata", None) or {}
    url = str(metadata.get("original_source_url") or getattr(item, "source_url", None) or "")
    try:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        url = urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."),
                          parts.path.rstrip("/"), urlencode(sorted(query)), ""))
    except ValueError:
        pass
    claim = " ".join(str(getattr(item, "claim", None) or getattr(item, "summary", None) or "").split())
    # Publication identifies an observation; re-capture time must not make copies new.
    published = getattr(item, "published_at", None)
    if not url and not claim:
        return (getattr(item, "id", id(item)),)
    return (source_identity(item), url, claim, published)
