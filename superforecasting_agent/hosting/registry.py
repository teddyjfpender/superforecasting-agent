"""Host-owned live session registration, stable enumeration and retirement."""

from __future__ import annotations

import threading
from collections.abc import Callable, ItemsView, Iterator, MutableMapping, ValuesView
from typing import Any

from superforecasting_agent.hosting.sessions import SessionBusy, reserve_close


class SessionRegistry(MutableMapping[str, dict[str, Any]]):
    """Own live runtime membership; each session retains its own history lock.

    Enumeration snapshots membership so concurrent creation/retirement cannot
    invalidate a shutdown or notification traversal. The shared lock also covers
    multi-step replacement admission. Session content is deliberately not copied.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    def __getitem__(self, key: str) -> dict[str, Any]:
        with self.lock:
            return self._entries[key]

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        with self.lock:
            previous = self._entries.get(key)
            if previous is not None and previous is not value:
                raise SessionBusy("runtime session identifier is already registered")
            self._entries[key] = value

    def __delitem__(self, key: str) -> None:
        with self.lock:
            del self._entries[key]

    def __iter__(self) -> Iterator[str]:
        with self.lock:
            return iter(tuple(self._entries))

    def __len__(self) -> int:
        with self.lock:
            return len(self._entries)

    def items(self) -> ItemsView[str, dict[str, Any]]:
        with self.lock:
            return self._entries.copy().items()

    def values(self) -> ValuesView[dict[str, Any]]:
        with self.lock:
            return self._entries.copy().values()

    def register(self, key: str, session: dict[str, Any]) -> None:
        with self.lock:
            if key in self._entries:
                raise SessionBusy("runtime session identifier is already registered")
            self._entries[key] = session

    def retire(
        self,
        key: str,
        finalize: Callable[[dict[str, Any]], None],
        *,
        reserved: bool = False,
        drained: bool = False,
    ) -> dict[str, Any] | None:
        """Reserve cleanup, retain membership on failure, detach after success."""
        with self.lock:
            session = self._entries.get(key)
            if session is None:
                return None
            reserve_close(session, reserved=reserved, drained=drained)
        try:
            finalize(session)
        except BaseException:
            with session["history_lock"]:
                session["_closing"] = False
            raise
        with self.lock:
            if self._entries.get(key) is not session:
                raise RuntimeError(
                    "runtime session ownership changed during retirement"
                )
            del self._entries[key]
        return session
