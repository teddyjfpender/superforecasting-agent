"""Atomic persistence of context estimates without replacing session settings."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from superforecasting_agent.storage.session import SessionDB

_KEY = "_context_usage_anchor"


def save_context_usage(
    self: SessionDB, session_id: str, anchor: dict[str, Any]
) -> bool:
    # Encode before acquiring a write lock. Invalid values cannot partially write.
    encoded = json.dumps(anchor, allow_nan=False)

    def write(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT model_config FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return False
        config = json.loads(row[0]) if row[0] else {}
        if not isinstance(config, dict):
            raise ValueError("Session model configuration must be an object")
        config[_KEY] = json.loads(encoded)
        conn.execute(
            "UPDATE sessions SET model_config = ? WHERE id = ?",
            (json.dumps(config, allow_nan=False), session_id),
        )
        return True

    return self._execute_write(write)


def load_context_usage(self: SessionDB, session_id: str) -> Any:
    session = self.get_session(session_id)
    if session is None:
        return None
    try:
        config = json.loads(session["model_config"]) if session["model_config"] else {}
    except (TypeError, ValueError):
        return None
    return config.get(_KEY) if isinstance(config, dict) else None
