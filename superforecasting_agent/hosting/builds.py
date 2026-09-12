"""Admission and retry ownership for deferred session initialization."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, MutableMapping
from typing import Any, Literal


def start_build(
    session: MutableMapping[str, Any],
    *,
    build: Callable[[threading.Event], None],
    start: Callable[[Callable[[], None]], Any],
) -> None:
    with session.setdefault("agent_build_lock", threading.Lock()):
        ready = session.get("agent_ready")
        if ready is None:
            return
        with session.setdefault("history_lock", threading.Lock()):
            if session.get("_closing") or session.get("_cleanup_pending"):
                session["agent_error"] = "session is closing"
                ready.set()
                return
            if ready.is_set() or session.get("agent_build_started"):
                return
            session["agent_build_started"] = True
        try:
            start(lambda: build(ready))
        except BaseException as exc:
            session["agent_error"] = f"agent initialization could not start: {exc}"
            ready.set()
            raise


def retry_build(
    session: MutableMapping[str, Any],
    *,
    cleanup: Callable[[], None],
    start: Callable[[], None],
    timeout: float = 30,
) -> Literal["ready", "started", "unavailable"]:
    """Wait for an existing build and clean failed resources before retry.

    The caller reserves session use against close/replacement. Failed cleanup
    retains the error and resources; the next retry must finish that cleanup.
    """
    ready = session.get("agent_ready")
    if ready is None:
        return "ready" if session.get("agent") is not None else "unavailable"
    if session.get("agent_build_started") and not ready.wait(timeout):
        return "unavailable"
    with session.setdefault("agent_build_lock", threading.Lock()):
        with session.setdefault("history_lock", threading.Lock()):
            if session.get("_closing") or session.get("_cleanup_pending"):
                return "unavailable"
        current = session.get("agent_ready")
        if current is not ready:
            return "unavailable"
        if session.get("agent_error"):
            try:
                cleanup()
            except Exception as exc:
                session["agent_error"] = f"agent initialization cleanup pending: {exc}"
                return "unavailable"
            session["agent"] = None
            session["agent_error"] = None
            session["agent_ready"] = threading.Event()
            session["agent_build_started"] = False
        elif session.get("agent") is not None:
            return "ready"
    start()
    return "started"


def execute_build(
    session: MutableMapping[str, Any],
    ready: threading.Event,
    *,
    construct: Callable[[], Any],
    initialize: Callable[[Any], None],
    report_error: Callable[[str], None],
) -> None:
    """Complete an admitted build, retaining partial resources for retry cleanup.

    start_build reserves the session until ready is set; registry retirement
    cannot detach it during construction or adapter initialization. Publish the
    exact agent before adapter setup so failed setup never loses its owner.
    """
    try:
        agent = construct()
        session["agent"] = agent
        initialize(agent)
    except BaseException as exc:
        message = str(exc) or type(exc).__name__
        session["agent_error"] = message
        try:
            report_error(message)
        except Exception:
            logging.getLogger(__name__).exception(
                "could not report agent initialization failure"
            )
        if not isinstance(exc, Exception):
            raise
    finally:
        ready.set()
