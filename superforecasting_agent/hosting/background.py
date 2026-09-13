"""Session-owned background conversations and retryable resource disposal."""

import contextvars
import logging
import threading
import time
from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from typing import Any

from superforecasting_agent.hosting.delegations import ChildCleanup, register_subagent
from superforecasting_agent.hosting.sessions import SessionBusy
from superforecasting_agent.hosting.workers import RuntimeWorkers

logger = logging.getLogger(__name__)


def start_background(
    session: MutableMapping[str, Any],
    workers: RuntimeWorkers,
    *,
    task_id: str,
    text: str,
    options: Callable[[], dict[str, Any]],
    scope: Callable[[], AbstractContextManager[Any]],
    report: Callable[[str], None],
) -> None:
    """Reserve the session until execution and initial disposal have finished.

    Failed disposal transfers ownership to the existing session-scoped cleanup
    registry. Reporting errors never retry execution or discard cleanup handles.
    """
    session_key = session.get("session_key")
    if not isinstance(session_key, str) or not session_key:
        raise ValueError("background work requires a session owner")
    lock = session.setdefault("history_lock", threading.Lock())
    with lock:
        if any(
            session.get(key) for key in ("_closing", "_replacing", "_cleanup_pending")
        ):
            raise SessionBusy("session is closing or being replaced")
        session["_background_jobs"] = session.get("_background_jobs", 0) + 1

    def run() -> None:
        agent = None
        cleanup = None
        output = "background work stopped before execution"
        try:
            with scope():
                try:
                    from agent.agent_factory import build_agent

                    # Inherit the parent's already resolved account, never reroute it.
                    agent = build_agent(runtime={}, **options())
                    cleanup = ChildCleanup(
                        agent, subagent_id=task_id, session_key=session_key
                    )
                    with lock:
                        active = session.setdefault("_background_agents", {})
                        if task_id in active:
                            raise RuntimeError(
                                f"background task already registered: {task_id}"
                            )
                        active[task_id] = agent
                    register_subagent({
                        "subagent_id": task_id,
                        "agent": agent,
                        "session_key": session_key,
                        "parent_id": session_key,
                        "kind": "background",
                        "depth": 1,
                        "goal": text,
                        "model": getattr(agent, "model", ""),
                        "started_at": time.time(),
                        "tool_count": 0,
                        "status": "running",
                    })
                    if not workers.stopping:
                        result = agent.run_conversation(
                            user_message=text, task_id=task_id
                        )
                        output = (
                            str(result.get("final_response", str(result)))
                            if isinstance(result, dict)
                            else str(result)
                        )
                finally:
                    if cleanup is not None:
                        cleanup.close()
        except Exception as exc:
            output = f"error: {exc}"
        finally:
            with lock:
                active = session.get("_background_agents", {})
                if active.get(task_id) is agent:
                    active.pop(task_id, None)
                session["_background_jobs"] -= 1
        if cleanup is not None and not cleanup.closed:
            output += (
                f"\nCleanup pending: {cleanup.error}. Retry /stop or session close."
            )
        try:
            report(output)
        except Exception:
            logger.exception("could not report background completion: %s", task_id)

    context = contextvars.copy_context()
    try:
        workers.start(lambda: context.run(run), name="forecast-background")
    except BaseException:
        with lock:
            session["_background_jobs"] -= 1
        raise
