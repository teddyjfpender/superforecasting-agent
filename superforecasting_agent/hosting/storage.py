"""Own one lazy session store for a serving lifetime, independent of transport."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from superforecasting_agent.hosting.workers import HostStopping

logger = logging.getLogger(__name__)


def _open_session_store() -> Any:
    from superforecasting_agent.storage.session import SessionDB

    return SessionDB()


class SessionStore:
    """Serialize initialization and close; the host must drain users before close.

    Failed initialization is retryable and retains its diagnostic. Once closed,
    stale callers cannot silently open a new database; only explicit host startup
    can admit a new lifetime. A failed close retains ownership for a retry.
    """

    def __init__(self, factory: Callable[[], Any] = _open_session_store) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._connection: Any = None
        self._closed = False
        self.last_error: str | None = None

    @property
    def current(self) -> Any:
        """Inspect ownership without lazily opening a database."""
        with self._lock:
            return self._connection

    def get(self) -> Any:
        with self._lock:
            if self._closed:
                raise HostStopping("session store belongs to a stopped host")
            if self._connection is None:
                try:
                    self._connection = self._factory()
                except Exception as exc:
                    self.last_error = str(exc)
                    logger.warning("Session store unavailable: %s", exc)
                    return None
                self.last_error = None
            return self._connection

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def start(self) -> None:
        with self._lock:
            if self._connection is not None:
                raise RuntimeError("previous session store is still owned")
            self.last_error = None
            self._closed = False
