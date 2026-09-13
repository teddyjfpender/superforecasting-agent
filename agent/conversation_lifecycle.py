"""Own agents for isolated calls or a reusable sequential conversation batch."""

from __future__ import annotations

import logging
import math
import threading
import time
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

    def _run(
        self, agent: Any, message: str, system_message: str, deadline: float | None
    ) -> Any:
        expired = threading.Event()

        def interrupt() -> None:
            expired.set()
            try:
                agent.interrupt()
            except Exception:
                logging.getLogger(__name__).exception("Deadline interruption failed")

        timer = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Conversation deadline expired before execution")
            timer = threading.Timer(remaining, interrupt)
            timer.daemon = True
            timer.start()
        try:
            result = agent.run_conversation(message, system_message=system_message)
        except Exception as exc:
            if expired.is_set() or (
                deadline is not None and time.monotonic() >= deadline
            ):
                raise TimeoutError("Conversation deadline expired") from exc
            raise
        finally:
            if timer is not None:
                timer.cancel()
                # No delayed callback may interrupt a later use of this agent.
                timer.join()
        if expired.is_set() or (deadline is not None and time.monotonic() >= deadline):
            raise TimeoutError("Conversation deadline expired")
        return result

    def run(
        self, message: str, *, system_message: str, timeout: float | None = None
    ) -> Any:
        """Cancel at the deadline and reject late results; drain before disposal.

        Cancellation is cooperative: an unresponsive provider retains ownership
        until it returns. Queuing and construction consume the same budget.
        """
        if timeout is not None and (
            isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._workers.operation():
            if self._fresh:
                agent = self._create()
                try:
                    return self._run(agent, message, system_message, deadline)
                finally:
                    self._dispose(agent)
            # Queued calls retain admission, but cannot start after their deadline.
            with self._serial:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Conversation deadline expired while queued")
                if self._cached is None:
                    self._cached = self._create()
                agent = self._cached
                try:
                    return self._run(agent, message, system_message, deadline)
                except TimeoutError:
                    # An interrupted agent must not carry partial state forward.
                    self._cached = None
                    self._dispose(agent)
                    raise

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
