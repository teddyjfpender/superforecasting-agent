"""Retain exact transport allocations when HTTPX marks itself closed too early."""

from __future__ import annotations

import threading
from typing import Any

import httpx


class RetainedHTTPTransport(httpx.HTTPTransport):
    """Retry public connection closes after httpcore removes them from its pool.

    This adapter owns its pool from construction. It uses the pool's public
    connections/close interface; it never traverses streams or raw descriptors.
    HTTPX's private pool attribute is confined to this version-tested adapter.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cleanup_lock = threading.Lock()
        self._pending: list[Any] = []
        self._pool_close_failed = False

    def close(self) -> None:
        with self._cleanup_lock:
            if self._pool_close_failed:
                errors = []
                for connection in list(self._pending):
                    try:
                        connection.close()
                    except Exception as exc:
                        errors.append(exc)
                    else:
                        self._pending = [
                            item for item in self._pending if item is not connection
                        ]
                if errors:
                    raise RuntimeError(
                        "HTTP connection cleanup incomplete"
                    ) from errors[0]
            for connection in getattr(self._pool, "connections"):
                if not any(connection is item for item in self._pending):
                    self._pending.append(connection)
            try:
                super().close()
            except BaseException:
                self._pool_close_failed = True
                raise
            self._pending.clear()
            self._pool_close_failed = False


class OwnedHTTPClient(httpx.Client):
    """Close an explicitly supplied transport even after Client.is_closed flips."""

    def __init__(self, *, transport: httpx.BaseTransport, **kwargs: Any) -> None:
        self._owned_transport = transport
        self._cleanup_lock = threading.Lock()
        self._cleanup_complete = False
        super().__init__(transport=transport, trust_env=False, **kwargs)

    def close(self) -> None:
        with self._cleanup_lock:
            if self._cleanup_complete:
                return
            # Client.close performs its normal admission transition. If its first
            # call failed, the second is a no-op; the exact transport still needs
            # an explicit retry. Never look up a replacement client's transport.
            if self.is_closed:
                self._owned_transport.close()
            else:
                super().close()
            self._cleanup_complete = True
