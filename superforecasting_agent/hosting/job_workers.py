"""Instance-owned cancellation handles for gateway job workers."""

from __future__ import annotations

import threading


class JobWorkers:
    """Identity-checked handles; durable job state remains in the job store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def install(self, job_id: str, event: threading.Event) -> None:
        with self._lock:
            self._events[job_id] = event

    def get(self, job_id: str) -> threading.Event | None:
        with self._lock:
            return self._events.get(job_id)

    def signal(self, job_id: str, expected: threading.Event | None) -> bool:
        with self._lock:
            if expected is None or self._events.get(job_id) is not expected:
                return False
            expected.set()
            return True

    def retire(self, job_id: str, expected: threading.Event) -> None:
        with self._lock:
            if self._events.get(job_id) is expected:
                del self._events[job_id]
