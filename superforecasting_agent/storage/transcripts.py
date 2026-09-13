"""Atomic transcript exports shared by terminal and RPC consumers."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from superforecasting_agent.storage.files import atomic_json_write


def save_transcript(
    home: Path,
    *,
    messages: list[dict[str, Any]],
    model: str,
    session_id: str,
    session_key: str | None = None,
    session_start: str | None = None,
) -> Path:
    """Write an independent export of a caller-owned history snapshot.

    Callers with concurrent history writers must capture messages under their
    history lock. Optional metadata preserves each consumer's existing format.
    """
    if not messages:
        raise ValueError("No forecast transcript to save.")
    payload: dict[str, Any] = {
        "model": model,
        "session_id": session_id,
        "messages": copy.deepcopy(messages),
    }
    if session_key is not None:
        payload["session_key"] = session_key
    if session_start is not None:
        payload["session_start"] = session_start
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = (
        Path(home)
        / "sessions"
        / "saved"
        / f"forecast_transcript_{stamp}_{uuid.uuid4().hex}.json"
    )
    atomic_json_write(path, payload)
    return path
