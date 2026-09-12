"""Own background review admission, interruption, and exact cleanup handles."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from superforecasting_agent.hosting.workers import RuntimeWorkers

logger = logging.getLogger(__name__)
_creation_lock = threading.RLock()


@dataclass
class _Review:
    agent: Any
    memory_closed: bool = False
    client_closed: bool = False
    disposing: bool = False


class ReviewLifecycle:
    def __init__(self) -> None:
        self.workers = RuntimeWorkers()
        self._lock = threading.RLock()
        self._reviews: dict[int, _Review] = {}

    def register(self, child: Any) -> bool:
        with self._lock:
            self._reviews[id(child)] = _Review(child)
            return not self.workers.stopping

    def dispose(self, child: Any) -> None:
        with self._lock:
            entry = self._reviews.get(id(child))
            if entry is None or entry.disposing:
                return
            entry.disposing = True
        try:
            for field, operation in (
                ("memory_closed", child.shutdown_memory_provider),
                ("client_closed", child.close),
            ):
                if not getattr(entry, field):
                    try:
                        if operation() is False:
                            raise RuntimeError("review cleanup reported incomplete")
                        setattr(entry, field, True)
                    except Exception:
                        logger.warning(
                            "Review cleanup failed; retaining exact handle",
                            exc_info=True,
                        )
        finally:
            with self._lock:
                entry.disposing = False
                if entry.memory_closed and entry.client_closed:
                    self._reviews.pop(id(child), None)

    def stop(self) -> None:
        self.workers.stop()
        if not self.workers.drain(0):
            # Do not interrupt a completed/disposed child's recycled execution
            # thread. Disposal claims the entry under this same lock.
            with self._lock:
                for entry in self._reviews.values():
                    if not entry.disposing:
                        try:
                            entry.agent.interrupt()
                        except Exception:
                            logger.warning("Review interruption failed", exc_info=True)
            if not self.workers.drain(0):
                raise RuntimeError("Background review still running; retry cleanup")
        with self._lock:
            children = [entry.agent for entry in self._reviews.values()]
        for child in children:
            self.dispose(child)
        with self._lock:
            if self._reviews:
                raise RuntimeError(
                    "Background review cleanup incomplete; retry cleanup"
                )


def reviews_for(agent: Any) -> ReviewLifecycle:
    with _creation_lock:
        owner = getattr(agent, "_review_lifecycle", None)
        if owner is None:
            owner = ReviewLifecycle()
            if getattr(agent, "_resources_closed", False):
                owner.workers.stop()
            agent._review_lifecycle = owner
        return owner
