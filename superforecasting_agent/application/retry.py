"""Prepare a retry without mutating history or performing transport delivery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class RetryUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class RetryPlan:
    message: str | list[dict[str, Any]]
    history: list[dict[str, Any]]


def prepare_retry(
    history: Sequence[Mapping[str, Any]], *, structured_messages: bool = False
) -> RetryPlan:
    """Retain the last user request exactly, or reject unsupported content.

    Text-only consumers must not silently drop images or other content blocks.
    A detached plan lets the caller validate first, then commit under its own
    history lock or storage transaction before requeueing the request.
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
        raise RetryUnavailable("no previous forecast note to retry")
    content = history[index].get("content", "")
    if isinstance(content, list):
        if not content or any(not isinstance(part, dict) for part in content):
            raise RetryUnavailable("last forecast note has invalid content")
        if any(
            part.get("type") == "text" and not isinstance(part.get("text"), str)
            for part in content
        ):
            raise RetryUnavailable("last forecast note has invalid text")
        if all(part.get("type") == "text" for part in content) and not any(
            part["text"].strip() for part in content
        ):
            raise RetryUnavailable("last forecast note is empty")
        if not structured_messages:
            if any(part.get("type") != "text" for part in content):
                raise RetryUnavailable(
                    "retry contains attachments this interface cannot resend; history was preserved"
                )
            content = " ".join(part["text"] for part in content)
    elif not isinstance(content, str):
        raise RetryUnavailable("last forecast note has invalid content")
    if isinstance(content, str) and not content.strip():
        raise RetryUnavailable("last forecast note is empty")
    return RetryPlan(
        deepcopy(content), deepcopy([dict(row) for row in history[:index]])
    )
