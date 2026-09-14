"""Silence Python output from one execution context without closing shared streams.

Tool workers must not replace the process-wide output target with /dev/null:
that also silences the gateway and unrelated sessions. Routing proxies borrow
existing streams; they never close them or allocate descriptors. Native writes
through file descriptors are outside this Python-level routing boundary.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_muted: ContextVar[bool] = ContextVar("tool_output_muted", default=False)
_install_lock = threading.Lock()


class _RoutingStream:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() requires text")
        if _muted.get():
            return len(text)
        return self._stream.write(text)

    def flush(self) -> None:
        if not _muted.get():
            self._stream.flush()

    def writelines(self, lines: Iterator[str]) -> None:
        for line in lines:
            self.write(line)

    def isatty(self) -> bool:
        return False if _muted.get() else bool(self._stream.isatty())

    def close(self) -> None:
        # This proxy borrows its target; disposal belongs to the installing host.
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


@contextmanager
def thread_scoped_silence() -> Iterator[None]:
    """Nested scopes restore their caller; other threads retain normal output."""
    with _install_lock:
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name)
            if stream is not None and not isinstance(stream, _RoutingStream):
                setattr(sys, name, _RoutingStream(stream))
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)
