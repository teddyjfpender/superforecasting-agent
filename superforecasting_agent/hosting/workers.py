"""Explicit ownership and bounded draining of a runtime's background work."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")


class HostStopping(RuntimeError):
    """The host no longer admits new work."""


class RuntimeWorkers:
    """Own lazy RPC workers and dedicated threads without owning their resources.

    Callers request cooperative interruption before draining. A timeout never
    grants permission to close resources still used by these workers.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._max_workers = max_workers
        self._condition = threading.Condition()
        self._pool: ThreadPoolExecutor | None = None
        self._active = 0
        self._stopping = False

    @property
    def stopping(self) -> bool:
        with self._condition:
            return self._stopping

    def _admit(self) -> None:
        if self._stopping:
            raise HostStopping("runtime host is stopping")
        self._active += 1

    def _done(self) -> None:
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Count an inline request as work that must finish before cleanup."""
        with self._condition:
            self._admit()
        try:
            yield
        finally:
            self._done()

    def submit(self, function: Callable[[], T]) -> Future[T]:
        with self._condition:
            self._admit()
            try:
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(
                        max_workers=self._max_workers, thread_name_prefix="forecast-rpc"
                    )
                future = self._pool.submit(function)
            except BaseException:
                self._done()
                raise
            future.add_done_callback(lambda _: self._done())
            return future

    def start(self, function: Callable[[], None], *, name: str) -> threading.Thread:
        """Track dedicated work that must not occupy the bounded RPC pool."""

        def run() -> None:
            try:
                function()
            finally:
                self._done()

        with self._condition:
            self._admit()
            thread = threading.Thread(target=run, name=name, daemon=True)
            try:
                thread.start()
            except BaseException:
                self._done()
                raise
            return thread

    def stop(self) -> None:
        """Close admission and cancel queued RPCs; running work remains owned."""
        with self._condition:
            self._stopping = True
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)

    def drain(self, timeout: float) -> bool:
        """Wait up to timeout for all admitted work, supporting idempotent retries."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            if not self._stopping:
                raise RuntimeError("stop admission before draining runtime workers")
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True
