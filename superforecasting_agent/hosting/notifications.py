"""Session ownership policy for background notifications."""

from collections.abc import Mapping
from typing import Literal


def route_notification(
    event: Mapping[str, object], session_key: str | None
) -> Literal["consume", "requeue"]:
    """Never redirect a session-bound result based on retry count or timing.

    Legacy unscoped events retain single-session delivery. Process session IDs
    identify processes, not conversations, and must not be used as routing keys.
    """
    owner = event.get("session_key")
    if owner and owner != session_key:
        return "requeue"
    return "consume"
