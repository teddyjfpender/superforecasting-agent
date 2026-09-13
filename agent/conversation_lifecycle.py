"""Own agents for isolated calls or a reusable sequential conversation batch."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from superforecasting_agent.hosting.workers import RuntimeWorkers


class AgentConversations:
    def __init__(self, factory: Callable[[], Any], *, fresh: bool) -> None:
        self._factory = factory
        self._fresh = fresh
        self._workers = RuntimeWorkers()
        self._lock = threading.Lock()
        self._serial = threading.Lock()
        self._agents: dict[int, Any] = {}
        self._cached: Any = None

    def _create(self) -> Any:
        agent = self._factory()
        with self._lock:
            self._agents[id(agent)] = agent
        return agent

    def _dispose(self, agent: Any) -> None:
        close = getattr(agent, "close", None)
        if callable(close):
            if close() is False:
                raise RuntimeError("agent cleanup reported incomplete")
        with self._lock:
            self._agents.pop(id(agent), None)

    def run(self, message: str, *, system_message: str) -> Any:
        with self._workers.operation():
            if self._fresh:
                agent = self._create()
                try:
                    return agent.run_conversation(
                        message, system_message=system_message
                    )
                finally:
                    self._dispose(agent)
            # Reused agents carry mutable conversation state. Admission counts
            # queued calls too, so shutdown cannot dispose an agent they still own.
            with self._serial:
                if self._cached is None:
                    self._cached = self._create()
                return self._cached.run_conversation(
                    message, system_message=system_message
                )

    def close(self) -> None:
        self._workers.stop()
        if not self._workers.drain(0):
            raise RuntimeError("agent conversations still running; retry cleanup")
        # Serialize repeated close calls; each completed handle is removed once.
        with self._serial:
            with self._lock:
                agents = list(self._agents.values())
            errors = []
            for agent in agents:
                try:
                    self._dispose(agent)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError(
                    "agent cleanup incomplete; retry: " + "; ".join(errors)
                )
            self._cached = None
