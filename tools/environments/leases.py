"""Exact-object leases prevent terminal cleanup while analysis owns a backend."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.RLock()
_owners: dict[int, tuple[Any, int]] = {}


class EnvironmentLease:
    def __init__(self, environment: Any) -> None:
        self.environment = environment
        self.released = False
        with _lock:
            current, count = _owners.get(id(environment), (environment, 0))
            if current is not environment:
                raise RuntimeError("Environment ownership identity mismatch")
            _owners[id(environment)] = (environment, count + 1)

    def release(self) -> None:
        with _lock:
            if self.released:
                return
            current, count = _owners[id(self.environment)]
            if current is not self.environment:
                raise RuntimeError("Environment ownership identity changed")
            if count == 1:
                del _owners[id(self.environment)]
            else:
                _owners[id(self.environment)] = (current, count - 1)
            self.released = True


def is_retained(environment: Any) -> bool:
    with _lock:
        entry = _owners.get(id(environment))
        return entry is not None and entry[0] is environment


def acquire(task_id: str) -> tuple[Any, EnvironmentLease]:
    """Coordinate acquisition with the terminal owner's detach/reaper mutex."""
    from tools import terminal_tool
    from tools.code_execution_tool import _get_or_create_env

    environment, _ = _get_or_create_env(task_id)
    lookup = terminal_tool._resolve_container_task_id(task_id)
    with terminal_tool._env_lock:
        current = terminal_tool._active_environments.get(lookup)
        if current is not environment:
            raise RuntimeError(
                "Terminal environment changed during kernel admission; retry"
            )
        return environment, EnvironmentLease(environment)
