"""Curator scheduling state with serialized, atomic field updates."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from superforecasting_agent.storage.files import atomic_json_write, yaml_update_lock


def default_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_duration_seconds": None,
        "last_run_summary": None,
        "last_run_summary_shown_at": None,
        "last_report_path": None,
        "paused": False,
        "run_count": 0,
    }


def _validate_state(data: Any) -> None:
    if not isinstance(data, dict):
        raise ValueError("Curator state must be a JSON object")
    if "paused" in data and not isinstance(data["paused"], bool):
        raise ValueError("Curator paused state must be a boolean")
    count = data.get("run_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Curator run_count must be a nonnegative integer")


def load_state(path: Path, *, strict: bool = False) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_state()
    except (OSError, ValueError):
        if strict:
            raise
        return default_state()
    if strict:
        _validate_state(data)
    result = default_state()
    if isinstance(data, dict):
        result.update({
            k: v for k, v in data.items() if k in result or k.startswith("_")
        })
    return result


def save_state(path: Path, data: dict[str, Any]) -> None:
    _validate_state(data)
    with yaml_update_lock(path):
        atomic_json_write(path, data, sort_keys=True)


def mutate_state(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    with yaml_update_lock(path):
        state = load_state(path, strict=True)
        mutate(state)
        _validate_state(state)
        atomic_json_write(path, state, sort_keys=True)
