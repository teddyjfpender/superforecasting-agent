"""Request-local command output without replacing process streams."""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import sys
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)


class _CommandBuffer(io.StringIO):
    """Retain a bounded tail while delivering writes to an optional observer."""

    def __init__(self, limit: int | None, notify: Callable[[str], None] | None):
        super().__init__()
        self.limit = limit
        self.notify = notify
        self.truncated = False

    def write(self, text: str) -> int:
        if self.notify is not None and text:
            try:
                self.notify(text)
            except Exception:
                # Output delivery cannot turn an already-applied mutation into
                # an apparent operation failure or trigger duplicate execution.
                logger.exception("Command output observer failed")
                self.notify = None
        if self.limit is not None and self.tell() + len(text) > self.limit:
            tail = text[-self.limit :]
            if len(tail) < self.limit:
                tail = super().getvalue()[-(self.limit - len(tail)) :] + tail
            self.seek(0)
            self.truncate(0)
            super().write(tail)
            self.truncated = True
        else:
            super().write(text)
        return len(text)

    def getvalue(self) -> str:
        prefix = "[Earlier command output omitted]\n" if self.truncated else ""
        return prefix + super().getvalue()


_streams: ContextVar[tuple[io.StringIO, io.StringIO] | None] = ContextVar(
    "command_output_streams", default=None
)


@contextlib.contextmanager
def capture_output(
    *,
    limit: int | None = None,
    on_output: Callable[[str, str], None] | None = None,
) -> Iterator[tuple[io.StringIO, io.StringIO]]:
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Command output limit must be a positive character count")
    streams = (
        _CommandBuffer(
            limit, (lambda text: on_output("stdout", text)) if on_output else None
        ),
        _CommandBuffer(
            limit, (lambda text: on_output("stderr", text)) if on_output else None
        ),
    )
    token = _streams.set(streams)
    try:
        yield streams
    finally:
        _streams.reset(token)


def emit(*values: object, **kwargs: Any) -> None:
    streams = _streams.get()
    target = kwargs.get("file")
    if streams is not None:
        if target is None or target is sys.stdout:
            kwargs["file"] = streams[0]
        elif target is sys.stderr:
            kwargs["file"] = streams[1]
    print(*values, **kwargs)


class CommandArgumentParser(argparse.ArgumentParser):
    """Argparse help/errors use the same request-local output as operations."""

    def _print_message(self, message: str, file: Any = None) -> None:
        if message:
            emit(message, end="", file=file)
