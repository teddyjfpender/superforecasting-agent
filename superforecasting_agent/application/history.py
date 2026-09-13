"""Detached history edits shared by conversation interfaces."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UndoPlan:
    history: list[dict[str, Any]]
    removed: int
    preview: str


def prepare_undo(history: Sequence[Mapping[str, Any]]) -> UndoPlan | None:
    """Remove the complete last user exchange; preserve orphaned history.

    The caller owns locking and persistence. No message content is interpreted
    as a new request, so even malformed or attachment-only notes can be removed.
    """
    index = next(
        (
            i
            for i in range(len(history) - 1, -1, -1)
            if history[i].get("role") == "user"
        ),
        None,
    )
    if index is None:
        return None
    content = history[index].get("content", "")
    if isinstance(content, list):
        preview = " ".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        preview = preview or "[attachments]"
    else:
        preview = str(content)
    return UndoPlan(
        deepcopy([dict(row) for row in history[:index]]), len(history) - index, preview
    )
