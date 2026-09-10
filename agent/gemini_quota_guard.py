"""Cross-session circuit breaker for hard Gemini quota exhaustion."""

from __future__ import annotations

import json
import os
import tempfile
import time

from superforecasting_agent.storage.files import atomic_replace

_COOLDOWN_SECONDS = 60 * 60


def _state_path() -> str:
    from superforecasting_agent.constants import get_agent_home

    return os.path.join(get_agent_home(), "rate_limits", "gemini.json")


def is_gemini_endpoint(provider: str | None, base_url: str | None) -> bool:
    return str(provider or "").lower() in {"gemini", "google", "google-gemini"} or (
        "generativelanguage.googleapis.com" in str(base_url or "").lower()
    )


def record_gemini_quota(*, cooldown_seconds: float = _COOLDOWN_SECONDS) -> None:
    path = _state_path()
    state_dir = os.path.dirname(path)
    os.makedirs(state_dir, exist_ok=True)
    now = time.time()
    fd, temporary = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {"recorded_at": now, "reset_at": now + max(cooldown_seconds, 1)},
                handle,
            )
        atomic_replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def gemini_quota_remaining() -> float | None:
    path = _state_path()
    try:
        with open(path, encoding="utf-8") as handle:
            reset_at = float(json.load(handle).get("reset_at") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    remaining = reset_at - time.time()
    if remaining > 0:
        return remaining
    clear_gemini_quota()
    return None


def clear_gemini_quota() -> None:
    try:
        os.unlink(_state_path())
    except FileNotFoundError:
        pass
