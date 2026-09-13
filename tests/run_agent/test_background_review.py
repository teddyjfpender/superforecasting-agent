"""Regression tests for background review agent cleanup."""

from __future__ import annotations

import run_agent as run_agent_module
from run_agent import AIAgent


def _bare_agent() -> AIAgent:
    agent = object.__new__(AIAgent)
    agent.model = "fake-model"
    agent.platform = "telegram"
    agent.provider = "openai"
    agent.base_url = ""
    agent.api_key = ""
    agent.api_mode = ""
    agent.session_id = "test-session"
    agent._parent_session_id = ""
    agent._credential_pool = None
    agent._memory_store = object()
    agent._memory_enabled = True
    agent._user_profile_enabled = False
    agent._cached_system_prompt = "test-cached-system-prompt"
    import datetime as _dt
    agent.session_start = _dt.datetime(2026, 1, 1, 12, 0, 0)
    agent._MEMORY_REVIEW_PROMPT = "review memory"
    agent._SKILL_REVIEW_PROMPT = "review skills"
    agent._COMBINED_REVIEW_PROMPT = "review both"
    agent.background_review_callback = None
    agent.status_callback = None
    agent._safe_print = lambda *_args, **_kwargs: None
    return agent


class ImmediateThread:
    def __init__(self, *, target, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()


def test_background_review_shuts_down_memory_provider_before_close(monkeypatch):
    events = []

    class FakeReviewAgent:
        def __init__(self, **kwargs):
            events.append(("init", kwargs))
            self._session_messages = []

        def run_conversation(self, **kwargs):
            events.append(("run_conversation", kwargs))

        def shutdown_memory_provider(self):
            events.append(("shutdown_memory_provider", None))

        def close(self):
            events.append(("close", None))

    monkeypatch.setattr(run_agent_module, "AIAgent", FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, "Thread", ImmediateThread)

    agent = _bare_agent()

    AIAgent._spawn_background_review(
        agent,
        messages_snapshot=[{"role": "user", "content": "hello"}],
        review_memory=True,
    )

    assert [name for name, _payload in events] == [
        "init",
        "run_conversation",
        "shutdown_memory_provider",
        "close",
    ]


def test_background_review_installs_auto_deny_approval_callback(monkeypatch):
    """Regression guard for #15216.

    The background review thread must install a non-interactive approval
    callback. If it doesn't, any dangerous-command guard the review agent
    trips falls back to input() on a daemon thread, which deadlocks against
    the parent's prompt_toolkit TUI.
    """
    import tools.terminal_tool as tt

    observed: dict = {"during_run": "<unread>", "after_finally": "<unread>"}

    class FakeReviewAgent:
        def __init__(self, **kwargs):
            self._session_messages = []

        def run_conversation(self, **kwargs):
            # Capture what the callback looks like mid-run. It must be
            # a callable (the auto-deny) -- not None.
            observed["during_run"] = tt._get_approval_callback()

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(run_agent_module, "AIAgent", FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, "Thread", ImmediateThread)

    # Start from a clean slot.
    tt.set_approval_callback(None)
    agent = _bare_agent()

    AIAgent._spawn_background_review(
        agent,
        messages_snapshot=[{"role": "user", "content": "hello"}],
        review_memory=True,
    )

    observed["after_finally"] = tt._get_approval_callback()

    assert callable(observed["during_run"]), (
        "Background review did not install an approval callback on its "
        "worker thread; dangerous-command prompts will deadlock against "
        "the parent TUI (#15216)."
    )
    # The installed callback must deny (it's a safety gate, not a prompt).
    assert observed["during_run"]("rm -rf /", "test") == "deny"

    assert observed["after_finally"] is None, (
        "Background review leaked its approval callback into the worker "
        "thread's TLS slot; a recycled thread-id could reuse it."
    )


def test_background_review_summary_is_attributed_to_self_improvement_loop(monkeypatch):
    """The CLI/gateway emission must identify the self-improvement loop.

    Users who miss the line in their terminal have no way to tell that the
    background review was what modified their skill/memory stores. The
    summary prefix ``💾 Self-improvement review: …`` makes the origin
    explicit so both the CLI and gateway deliveries are unambiguous.
    """
    import json

    captured_prints: list = []
    captured_bg_callback: list = []

    class FakeReviewAgent:
        def __init__(self, **kwargs):
            # Simulate a review that successfully updated memory so
            # _summarize_background_review_actions returns a real action.
            self._session_messages = [
                {
                    "role": "tool",
                    "tool_call_id": "call_bg",
                    "content": json.dumps(
                        {"success": True, "message": "Entry added", "target": "memory"}
                    ),
                }
            ]

        def run_conversation(self, **kwargs):
            pass

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(run_agent_module, "AIAgent", FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, "Thread", ImmediateThread)

    agent = _bare_agent()
    agent._safe_print = lambda *a, **kw: captured_prints.append(" ".join(str(x) for x in a))
    agent.background_review_callback = lambda msg: captured_bg_callback.append(msg)

    AIAgent._spawn_background_review(
        agent,
        messages_snapshot=[{"role": "user", "content": "hi"}],
        review_memory=True,
    )

    # Exactly one summary should have been emitted, and it must identify
    # the self-improvement review explicitly.
    assert len(captured_prints) == 1, captured_prints
    printed = captured_prints[0]
    assert "Self-improvement review" in printed, printed
    assert "Memory updated" in printed, printed

    # Gateway path gets the same prefix.
    assert len(captured_bg_callback) == 1
    assert captured_bg_callback[0].startswith("💾 Self-improvement review:"), (
        captured_bg_callback[0]
    )


def test_background_review_fork_skips_external_memory_plugins(monkeypatch):
    """The background review fork must NOT touch external memory plugins.

    Without skip_memory=True on the fork constructor, AIAgent.__init__
    rebuilds its own _memory_manager from config, scoped to the parent's
    session_id.  The review fork's run_conversation() then leaks the
    harness prompt into the user's real memory namespace via three
    ingestion sites: on_turn_start (cadence + turn message),
    prefetch_all (recall query), and sync_all (harness prompt + review
    output recorded as a (user, assistant) turn pair).  The fix is a
    single kwarg on the fork constructor — this test guards it.
    """
    captured_kwargs: dict = {}

    class FakeReviewAgent:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self._session_messages = []

        def run_conversation(self, **kwargs):
            pass

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(run_agent_module, "AIAgent", FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, "Thread", ImmediateThread)

    agent = _bare_agent()

    AIAgent._spawn_background_review(
        agent,
        messages_snapshot=[{"role": "user", "content": "hello"}],
        review_memory=True,
    )

    assert captured_kwargs.get("skip_memory") is True, (
        "Background review fork must be constructed with skip_memory=True "
        "so AIAgent.__init__ does not rebuild a _memory_manager wired to "
        "external plugins (honcho, mem0, supermemory, ...).  Without this "
        "the fork leaks harness prompts into the user's real memory "
        "namespace via on_turn_start / prefetch_all / sync_all."
    )


def test_background_review_never_replaces_foreground_streams(monkeypatch, capsys):
    """Hold a real review worker at run and cleanup while foreground output flows."""
    import sys
    import threading
    from agent.background_review import _run_review_in_thread

    entered = threading.Event()
    proceed = threading.Event()
    cleaning = threading.Event()
    finish = threading.Event()
    failures = []
    streams = (sys.stdout, sys.stderr)

    class FakeReviewAgent:
        def __init__(self, **kwargs):
            assert kwargs['quiet_mode'] is True
            self._session_messages = []
        def run_conversation(self, **kwargs):
            entered.set()
            assert proceed.wait(5)
            raise RuntimeError('injected review failure')
        def shutdown_memory_provider(self):
            cleaning.set()
            assert finish.wait(5)
        def close(self):
            pass

    monkeypatch.setattr(run_agent_module, 'AIAgent', FakeReviewAgent)
    agent = _bare_agent()
    agent._emit_auxiliary_failure = lambda *args: failures.append(args)
    worker = threading.Thread(target=_run_review_in_thread, args=(agent, [], 'review'))
    worker.start()
    try:
        assert entered.wait(5)
        assert (sys.stdout, sys.stderr) == streams
        print('foreground during review')
        assert 'foreground during review' in capsys.readouterr().out
        proceed.set()
        assert cleaning.wait(5)
        assert (sys.stdout, sys.stderr) == streams
        print('foreground during cleanup', file=sys.stderr)
        assert 'foreground during cleanup' in capsys.readouterr().err
    finally:
        proceed.set()
        finish.set()
        worker.join(5)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert 'injected review failure' in str(failures[0][1])
    assert (sys.stdout, sys.stderr) == streams


def test_review_borrows_parent_session_tools_but_closes_its_client(monkeypatch):
    import threading
    from unittest.mock import Mock
    from agent import session_lifecycle
    from tools import process_registry, terminal_tool

    parent = _bare_agent()
    environment = Mock()
    client = object()
    close_client = Mock()
    monkeypatch.setattr(terminal_tool, '_active_environments', {parent.session_id: environment})
    kill = Mock()
    browser = Mock()
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', kill)
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', browser)
    class FakeReviewAgent:
        def __init__(self, **kwargs):
            self._session_messages = []
            self._resource_close_lock = threading.RLock()
            self._active_children_lock = threading.Lock()
            self._active_children = []
            self.client = client
            self._close_openai_client = close_client
        def run_conversation(self, **kwargs):
            assert self.session_id == parent.session_id
            assert self._owns_session_tools is False
        def shutdown_memory_provider(self):
            pass
        def close(self):
            session_lifecycle.close(self)
    monkeypatch.setattr(run_agent_module, 'AIAgent', FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, 'Thread', ImmediateThread)
    AIAgent._spawn_background_review(parent, [], review_memory=True)
    assert terminal_tool._active_environments[parent.session_id] is environment
    environment.cleanup.assert_not_called()
    kill.assert_not_called()
    browser.assert_not_called()
    close_client.assert_called_once_with(client, reason='agent_close', shared=True)


def test_real_review_spawn_is_owned_until_parent_cleanup_can_finish(monkeypatch):
    import threading
    import pytest
    from unittest.mock import Mock
    from agent import session_lifecycle

    entered, leave, interrupted = threading.Event(), threading.Event(), threading.Event()
    constructed = []
    class FakeReviewAgent:
        def __init__(self, **kwargs):
            constructed.append(self)
            self._session_messages = []
        def run_conversation(self, **kwargs):
            entered.set()
            assert leave.wait(5)
        def interrupt(self):
            interrupted.set()
        def shutdown_memory_provider(self):
            pass
        def close(self):
            pass
    monkeypatch.setattr(run_agent_module, 'AIAgent', FakeReviewAgent)
    cleanup = Mock()
    monkeypatch.setattr(session_lifecycle, '_close_resources', cleanup)
    parent = _bare_agent()
    parent._resource_close_lock = threading.RLock()
    AIAgent._spawn_background_review(parent, [], review_memory=True)
    try:
        assert entered.wait(5)
        with pytest.raises(RuntimeError, match='still running'):
            session_lifecycle.close(parent)
        assert interrupted.is_set()
        cleanup.assert_not_called()
        AIAgent._spawn_background_review(parent, [], review_memory=True)
        assert len(constructed) == 1
    finally:
        leave.set()
        assert parent._review_lifecycle.workers.drain(5)
    session_lifecycle.close(parent)
    cleanup.assert_called_once()
