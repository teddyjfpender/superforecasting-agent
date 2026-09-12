"""Thread-owned prompt callbacks shared by runtime and tool adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

Callback = Callable[..., Any]
_callbacks = threading.local()


def get_sudo_password_callback() -> Callback | None:
    return getattr(_callbacks, "sudo_password", None)


def get_approval_callback() -> Callback | None:
    return getattr(_callbacks, "approval", None)


def set_sudo_password_callback(callback: Callback | None) -> None:
    _callbacks.sudo_password = callback


def set_approval_callback(callback: Callback | None) -> None:
    _callbacks.approval = callback


@contextmanager
def temporary_approval_callback(callback: Callback | None) -> Iterator[None]:
    """Restore the caller's exact callback after success, failure or interruption."""
    previous = get_approval_callback()
    set_approval_callback(callback)
    try:
        yield
    finally:
        set_approval_callback(previous)
