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


def branch_session(
    db: SessionDB,
    *,
    session_id: str,
    parent_session_id: str,
    history: list[dict[str, Any]],
    name: str = "",
    source: str,
    model: str | None = None,
    model_config: dict[str, Any] | None = None,
    end_parent: bool = False,
) -> str:
    """Copy a complete transcript atomically and return its validated title."""
    if not history:
        raise ValueError("nothing to branch — send a forecast note first")
    if not isinstance(name, str):
        raise ValueError("branch name must be text")
    if not session_id or not parent_session_id or session_id == parent_session_id:
        raise ValueError("branch requires distinct nonempty session identifiers")
    messages = [dict(message) for message in history]
    for message in messages:
        message["tool_name"] = message.get("tool_name") or message.get("name")
    title = name.strip() or db.get_next_title_in_lineage(
        db.get_session_title(parent_session_id) or "branch"
    )
    title = db.sanitize_title(title)
    if not title:
        raise ValueError("branch title must be nonempty")
    db.create_branch(
        session_id,
        parent_session_id,
        messages,
        title=title,
        source=source,
        model=model,
        model_config=model_config,
        end_parent=end_parent,
    )
    return title


def set_session_title(db: SessionDB, session_id: str, title: str) -> tuple[str, bool]:
    """Return the canonical title and whether it awaits session creation.

    Storage owns validation and transactional uniqueness. Never queue or report
    an unsanitized value, and never claim that an absent session was updated.
    """
    if not isinstance(title, str):
        raise ValueError("session title must be text")
    clean = db.sanitize_title(title)
    if not clean:
        raise ValueError(
            "Title is empty after cleanup. Please use printable characters."
        )
    if db.set_session_title(session_id, clean):
        return clean, False
    existing = db.get_session(session_id)
    if existing:
        return existing.get("title") or clean, False
    return clean, True
