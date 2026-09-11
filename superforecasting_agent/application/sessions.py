"""Shared human-session selection for terminal and CLI resume surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from superforecasting_agent.storage.session import SessionDB


def list_resumable_sessions(
    db: SessionDB,
    *,
    limit: int = 200,
    source: str | None = None,
    exclude_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Return up to limit eligible conversations, including compression tips.

    Source selection is explicit: administrators may request internal sources;
    normal resume surfaces hide tool sessions but accept any human-facing source.
    Apply active-session exclusion after lineage projection and keep paging until
    the result is full or the store is exhausted.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError("session limit must be an integer between 1 and 10000")
    if source is not None and not isinstance(source, str):
        raise ValueError("session source must be text")
    excluded = set(exclude_ids)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_size = max(50, min(limit, 200))
    offset = 0
    while len(result) < limit:
        rows = db.list_sessions_rich(
            source=source,
            exclude_sources=None if source else ["tool"],
            limit=page_size,
            offset=offset,
        )
        for row in rows:
            key = row["id"]
            if key in excluded or key in seen:
                continue
            if not source and (row.get("source") or "").strip().lower() == "tool":
                continue
            seen.add(key)
            result.append(row)
            if len(result) == limit:
                break
        if len(rows) < page_size:
            break
        offset += page_size
    return result
