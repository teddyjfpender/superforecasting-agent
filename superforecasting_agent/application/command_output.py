"""Request-local command output without replacing process streams."""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

_streams: ContextVar[tuple[io.StringIO, io.StringIO] | None] = ContextVar(
    "command_output_streams", default=None
)


@contextlib.contextmanager
def capture_output() -> Iterator[tuple[io.StringIO, io.StringIO]]:
    streams = io.StringIO(), io.StringIO()
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
