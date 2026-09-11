"""Presentation-independent serving lifetime and resource ownership."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from superforecasting_agent.hosting.configuration import ProfileConfiguration
from superforecasting_agent.hosting.device_auth import DeviceSignIn
from superforecasting_agent.hosting.registry import SessionRegistry
from superforecasting_agent.hosting.storage import SessionStore
from superforecasting_agent.hosting.workers import RuntimeWorkers

logger = logging.getLogger(__name__)


class RuntimeHost:
    """Own admission, session membership, storage and ordered shutdown.

    Adapters supply protocol-specific interruption and durable-turn callbacks.
    They cannot reopen admission until every previous resource is relinquished.
    """

    def __init__(self, *, max_workers: int = 4) -> None:
        self._lock = threading.Lock()
        self._max_workers = max_workers
        self._shutdown_complete = False
        self.workers = RuntimeWorkers(max_workers=max_workers)
        self.sessions = SessionRegistry()
        self.store = SessionStore()
        self.configuration = ProfileConfiguration()
        self.sign_in = DeviceSignIn()

    def start(self, *, reset_services: Callable[[], None]) -> None:
        with self._lock:
            if not self.workers.stopping:
                return
            if (
                not self._shutdown_complete
                or not self.workers.drain(0)
                or self.sessions
                or self.store.current is not None
            ):
                raise RuntimeError("previous runtime shutdown is incomplete")
            reset_services()
            self.sign_in = DeviceSignIn()
            self.store.start()
            self.workers = RuntimeWorkers(max_workers=self._max_workers)
            self._shutdown_complete = False

    def shutdown(
        self,
        timeout: float,
        *,
        stop_services: Callable[[], None],
        release_prompts: Callable[[str, dict[str, Any]], None],
        interrupt_delegations: Callable[[], None],
        close_session: Callable[[str, dict[str, Any], Any], None],
    ) -> bool:
        """Drain before disposal; retain failed resources for an explicit retry."""
        with self._lock:
            if self._shutdown_complete:
                return True
            self.workers.stop()
            self.sign_in.cancel()
            interruption_failed = False
            try:
                stop_services()
            except Exception:
                interruption_failed = True
                logger.exception("failed to stop runtime services")
            for sid, session in self.sessions.items():
                session["cancel_requested"] = True
                stop = session.get("_notif_stop")
                if stop is not None:
                    stop.set()
                agents = [session.get("agent")]
                with session.setdefault("history_lock", threading.Lock()):
                    agents.extend(session.get("_background_agents", {}).values())
                for agent in agents:
                    if agent is not None and hasattr(agent, "interrupt"):
                        try:
                            agent.interrupt()
                        except Exception:
                            logger.exception(
                                "failed to interrupt runtime session %s", sid
                            )
                try:
                    release_prompts(sid, session)
                except Exception:
                    interruption_failed = True
                    logger.exception("failed to release runtime prompts for %s", sid)
            try:
                interrupt_delegations()
            except Exception:
                interruption_failed = True
                logger.exception("failed to interrupt runtime delegations")
            if not self.workers.drain(timeout):
                logger.error("runtime shutdown incomplete: workers still own resources")
                return False
            if interruption_failed:
                return False
            cleanup_failed = False
            for sid, session in self.sessions.items():
                try:
                    close_session(sid, session, self.store.current)
                except Exception:
                    cleanup_failed = True
                    logger.exception("runtime session cleanup incomplete: %s", sid)
            if cleanup_failed or self.sessions:
                return False
            try:
                self.store.close()
            except Exception:
                logger.exception("runtime session store cleanup incomplete")
                return False
            self._shutdown_complete = True
            return True
