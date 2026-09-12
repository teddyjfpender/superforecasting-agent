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


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    result = default_state()
    if isinstance(data, dict):
        result.update({
            k: v for k, v in data.items() if k in result or k.startswith("_")
        })
    return result


def save_state(path: Path, data: dict[str, Any]) -> None:
    with yaml_update_lock(path):
        atomic_json_write(path, data, sort_keys=True)


def mutate_state(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    with yaml_update_lock(path):
        state = load_state(path)
        mutate(state)
        atomic_json_write(path, state, sort_keys=True)
