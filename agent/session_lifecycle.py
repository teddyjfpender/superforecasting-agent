"""Memory session boundaries, client eviction, and full task shutdown."""

from typing import Any

from tools.terminal_tool import cleanup_vm
from tools.browser_tool import cleanup_browser


def shutdown_memory_provider(self, messages: list = None) -> None:
    """Shut down the memory provider and context engine — call at actual session boundaries.

        This calls on_session_end() then shutdown_all() on the memory
        manager, and on_session_end() on the context engine.
        NOT called per-turn — only at CLI exit, /reset, gateway
        session expiry, etc.
        """
    if self._memory_manager:
        try:
            self._memory_manager.on_session_end(messages or [])
        except Exception:
            pass
        try:
            self._memory_manager.shutdown_all()
        except Exception:
            pass
    # Notify context engine of session end (flush DAG, close DBs, etc.)
    if hasattr(self, "context_compressor") and self.context_compressor:
        try:
            self.context_compressor.on_session_end(
                self.session_id or "",
                messages or [],
            )
        except Exception:
            pass


def commit_memory_session(self, messages: list = None) -> None:
    """Trigger end-of-session extraction without tearing providers down.
        Called when session_id rotates (e.g. /new, context compression);
        providers keep their state and continue running under the old
        session_id — they just flush pending extraction now."""
    if self._memory_manager:
        try:
            self._memory_manager.on_session_end(messages or [])
        except Exception:
            pass
    # Notify context engine of session end too — same lifecycle moment as
    # the memory manager's on_session_end. Without this, engines that
    # accumulate per-session state (DAGs, summaries) leak that state from
    # the rotated-out session into whatever comes next under the same
    # compressor instance. Mirrors the call in shutdown_memory_provider().
    # See issue #22394.
    if hasattr(self, "context_compressor") and self.context_compressor:
        try:
            self.context_compressor.on_session_end(
                self.session_id or "",
                messages or [],
            )
        except Exception:
            pass


def _sync_external_memory_for_turn(
    self,
    *,
    original_user_message: Any,
    final_response: Any,
    interrupted: bool,
) -> None:
    """Mirror a completed turn into external memory providers.

        Called at the end of ``run_conversation`` with the cleaned user
        message (``original_user_message``) and the finalised assistant
        response.  The external memory backend gets both ``sync_all`` (to
        persist the exchange) and ``queue_prefetch_all`` (to start
        warming context for the next turn) in one shot.

        Uses ``original_user_message`` rather than ``user_message``
        because the latter may carry injected skill content that bloats
        or breaks provider queries.

        Interrupted turns are skipped entirely (#15218).  A partial
        assistant output, an aborted tool chain, or a mid-stream reset
        is not durable conversational truth — mirroring it into an
        external memory backend pollutes future recall with state the
        user never saw completed.  The prefetch is gated on the same
        flag: the user's next message is almost certainly a retry of
        the same intent, and a prefetch keyed on the interrupted turn
        would fire against stale context.

        Normal completed turns still sync as before.  The whole body is
        wrapped in ``try/except Exception`` because external memory
        providers are strictly best-effort — a misconfigured or offline
        backend must not block the user from seeing their response.
        """
    if interrupted:
        return
    if not (self._memory_manager and final_response and original_user_message):
        return
    try:
        self._memory_manager.sync_all(
            original_user_message, final_response,
            session_id=self.session_id or "",
        )
        self._memory_manager.queue_prefetch_all(
            original_user_message,
            session_id=self.session_id or "",
        )
    except Exception:
        pass


def release_clients(self) -> None:
    """Release LLM client resources WITHOUT tearing down session tool state.

        Used by the gateway when evicting this agent from _agent_cache for
        memory-management reasons (LRU cap or idle TTL) — the session may
        resume at any time with a freshly-built AIAgent that reuses the
        same task_id / session_id, so we must NOT kill:
          - process_registry entries for task_id (user's bg shells)
          - terminal sandbox for task_id (cwd, env, shell state)
          - browser daemon for task_id (open tabs, cookies)
          - memory provider (has its own lifecycle; keeps running)

        We DO close:
          - OpenAI/httpx client pool (big chunk of held memory + sockets;
            the rebuilt agent gets a fresh client anyway)
          - Active child subagents (per-turn artefacts; safe to drop)

        Safe to call multiple times.  Distinct from close() — which is the
        hard teardown for actual session boundaries (/new, /reset, session
        expiry).
        """
    # Close active child agents (per-turn; no cross-turn persistence).
    try:
        with self._active_children_lock:
            children = list(self._active_children)
            self._active_children.clear()
        for child in children:
            try:
                child.release_clients()
            except Exception:
                # Fall back to full close on children; they're per-turn.
                try:
                    child.close()
                except Exception:
                    pass
    except Exception:
        pass

    # Close the OpenAI/httpx client to release sockets immediately.
    try:
        client = getattr(self, "client", None)
        if client is not None:
            self._close_openai_client(client, reason="cache_evict", shared=True)
            self.client = None
    except Exception:
        pass


def close(self) -> None:
    """Release all resources held by this agent instance.

        Cleans up subprocess resources that would otherwise become orphans:
        - Background processes tracked in ProcessRegistry
        - Terminal sandbox environments
        - Browser daemon sessions
        - Active child agents (subagent delegation)
        - OpenAI/httpx client connections

        Safe to call multiple times (idempotent).  Each cleanup step is
        independently guarded so a failure in one does not prevent the rest.
        """
    task_id = getattr(self, "session_id", None) or ""

    # 1. Kill background processes for this task
    try:
        from tools.process_registry import process_registry
        process_registry.kill_all(task_id=task_id)
    except Exception:
        pass

    # 2. Clean terminal sandbox environments
    try:
        cleanup_vm(task_id)
    except Exception:
        pass

    # 3. Clean browser daemon sessions
    try:
        cleanup_browser(task_id)
    except Exception:
        pass

    # 4. Close active child agents
    try:
        with self._active_children_lock:
            children = list(self._active_children)
            self._active_children.clear()
        for child in children:
            try:
                child.close()
            except Exception:
                pass
    except Exception:
        pass

    # 5. Close the OpenAI/httpx client
    try:
        client = getattr(self, "client", None)
        if client is not None:
            self._close_openai_client(client, reason="agent_close", shared=True)
            self.client = None
    except Exception:
        pass
