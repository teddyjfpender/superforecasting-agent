"""Tests for /goal handling in tui_gateway.

The TUI routes ``/goal`` through ``command.dispatch`` (not ``slash.exec``)
because the CLI's ``_handle_goal_command`` queues the kickoff message onto
``_pending_input``, which the slash-worker subprocess has no reader for.
Instead we handle ``/goal`` directly in the server and return a
``{"type": "send", "notice": ..., "message": ...}`` payload the TUI client
uses to render a system line and fire the kickoff prompt.
"""

from __future__ import annotations

import importlib
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


from tests.runtime_session_cleanup import retire_test_sessions


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    yield home


@pytest.fixture()
def server(hermes_home):
    with patch.dict(
        "sys.modules",
        {
            "superforecasting_agent.runtime.env_loader": MagicMock(),
            "superforecasting_agent.runtime.banner": MagicMock(),
        },
    ):
        mod = importlib.import_module("tui_gateway.server")
        yield mod
        retire_test_sessions(mod)
        mod._pending.clear()
        mod._answers.clear()
        mod._methods.clear()
        importlib.reload(mod)


@pytest.fixture()
def session(server):
    sid = "sid-test"
    session_key = "tui-goal-session-1"
    s = {
        "session_key": session_key,
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "cols": 120,
    }
    server._host.sessions[sid] = s
    return sid, session_key, s


def _call(server, method, **params):
    handler = server._methods[method]
    return handler(1, params)


# ── command.dispatch /goal ────────────────────────────────────────────


def test_goal_bare_shows_status_when_none_set(server, session):
    sid, _, _ = session
    r = _call(server, "command.dispatch", name="goal", arg="", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "No active goal" in r["result"]["output"]


def test_goal_whitespace_only_shows_status(server, session):
    sid, _, _ = session
    r = _call(server, "command.dispatch", name="goal", arg="   ", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "No active goal" in r["result"]["output"]


def test_goal_status_alias_shows_status(server, session):
    sid, _, _ = session
    r = _call(server, "command.dispatch", name="goal", arg="status", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "No active goal" in r["result"]["output"]


def test_goal_set_returns_send_with_notice(server, session):
    sid, session_key, _ = session
    r = _call(server, "command.dispatch", name="goal", arg="build a rocket", session_id=sid)
    result = r["result"]
    assert result["type"] == "send"
    assert result["message"] == "build a rocket"
    assert "notice" in result
    assert "Goal set" in result["notice"]
    assert "20-turn budget" in result["notice"]

    # Persisted in SessionDB
    from superforecasting_agent.runtime.goals import GoalManager

    mgr = GoalManager(session_key)
    assert mgr.state is not None
    assert mgr.state.goal == "build a rocket"
    assert mgr.state.status == "active"


def test_goal_pause_after_set(server, session):
    sid, session_key, _ = session
    _call(server, "command.dispatch", name="goal", arg="write a story", session_id=sid)
    r = _call(server, "command.dispatch", name="goal", arg="pause", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "paused" in r["result"]["output"].lower()

    from superforecasting_agent.runtime.goals import GoalManager

    assert GoalManager(session_key).state.status == "paused"


def test_goal_resume_reactivates(server, session):
    sid, session_key, _ = session
    _call(server, "command.dispatch", name="goal", arg="write a story", session_id=sid)
    _call(server, "command.dispatch", name="goal", arg="pause", session_id=sid)
    r = _call(server, "command.dispatch", name="goal", arg="resume", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "resumed" in r["result"]["output"].lower()

    from superforecasting_agent.runtime.goals import GoalManager

    assert GoalManager(session_key).state.status == "active"


def test_goal_clear_removes_active_goal(server, session):
    sid, session_key, _ = session
    _call(server, "command.dispatch", name="goal", arg="write a story", session_id=sid)
    r = _call(server, "command.dispatch", name="goal", arg="clear", session_id=sid)
    assert r["result"]["type"] == "exec"
    assert "cleared" in r["result"]["output"].lower()

    from superforecasting_agent.runtime.goals import GoalManager

    # After clear the row is marked status=cleared (kept for audit);
    # ``has_goal()`` / ``is_active()`` return False so the goal loop
    # stays off and ``status`` reports "No active goal".
    mgr = GoalManager(session_key)
    assert not mgr.has_goal()
    assert not mgr.is_active()
    assert "No active goal" in mgr.status_line()


def test_goal_stop_and_done_are_clear_aliases(server, session):
    sid, _, _ = session
    _call(server, "command.dispatch", name="goal", arg="first goal", session_id=sid)
    r = _call(server, "command.dispatch", name="goal", arg="stop", session_id=sid)
    assert "cleared" in r["result"]["output"].lower()

    _call(server, "command.dispatch", name="goal", arg="second goal", session_id=sid)
    r = _call(server, "command.dispatch", name="goal", arg="done", session_id=sid)
    assert "cleared" in r["result"]["output"].lower()


def test_goal_requires_session(server):
    r = _call(server, "command.dispatch", name="goal", arg="nope", session_id="unknown")
    assert "error" in r
    assert r["error"]["code"] == 4001


# ── slash.exec /goal routing ──────────────────────────────────────────


def test_slash_exec_rejects_goal_routes_to_command_dispatch(server, session):
    """slash.exec must reject /goal with 4018 so the TUI client falls through
    to command.dispatch. Without this, the HermesCLI slash-worker subprocess
    would set the goal but silently drop the kickoff — the queue is in-proc."""
    sid, _, _ = session
    r = _call(server, "slash.exec", command="goal status", session_id=sid)
    assert "error" in r
    assert r["error"]["code"] == 4018
    assert "command.dispatch" in r["error"]["message"]


def test_pending_input_commands_includes_goal(server):
    """Guard: _PENDING_INPUT_COMMANDS must list 'goal' — removing it would
    silently re-break the TUI."""
    assert "goal" in server._PENDING_INPUT_COMMANDS


@pytest.mark.parametrize("argument", ["", "Evidence must be timestamped", "remove", "remove nope", "remove 1", "clear", "remove 1 2", "clear extra", "Preserve  internal spacing"])
def test_subgoal_consumers_share_results_and_durable_state(server, session, monkeypatch, argument):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock
    from gateway.run import GatewayRunner
    from superforecasting_agent.runtime.goal_commands import _handle_subgoal_command
    from superforecasting_agent.runtime.goals import GoalManager

    sid, key, live = session
    live["running"] = True  # Criteria may be changed while a model turn runs.
    monkeypatch.setattr(server, "_start_agent_build", Mock(side_effect=AssertionError("agent construction")))
    monkeypatch.setattr(server, "_SlashWorker", Mock(side_effect=AssertionError("classic worker")))
    managers = [GoalManager(session_id=value) for value in (key, "classic", "messaging")]
    for manager in managers:
        manager.set("Review a forecast")
        manager.add_subgoal("Original criterion")

    native = _call(server, "command.dispatch", name="subgoal", arg=argument, session_id=sid)
    assert native["result"]["type"] == "exec"
    expected = native["result"]["output"]
    # Capture the command's rendering boundary: prompt_toolkit can retain an
    # output stream created before pytest installs this test's sys.stdout capture.
    rendered = []
    monkeypatch.setattr("superforecasting_agent.runtime.goal_commands._cprint", rendered.append)
    _handle_subgoal_command(SimpleNamespace(_get_goal_manager=lambda: managers[1]), f"/subgoal {argument}")
    assert "\n".join(line.removeprefix("  ") for line in rendered) == expected
    messaging = SimpleNamespace(_get_goal_manager_for_event=lambda event: (managers[2], None))
    event = SimpleNamespace(get_command_args=lambda: argument)
    assert asyncio.run(GatewayRunner._handle_subgoal_command(messaging, event)) == expected
    persisted = [GoalManager(session_id=value).state.subgoals for value in (key, "classic", "messaging")]
    assert persisted[0] == persisted[1] == persisted[2]
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_subgoal_legacy_rpc_hands_off_before_build(server, session, monkeypatch):
    from unittest.mock import Mock

    sid, _, _ = session
    monkeypatch.setattr(server, "_start_agent_build", Mock(side_effect=AssertionError("agent construction")))
    response = _call(server, "slash.exec", command="subgoal require sources", session_id=sid)
    assert response["error"]["data"] == {"dispatch": "command.dispatch", "execution_started": False}
    server._start_agent_build.assert_not_called()


@pytest.mark.parametrize("argument", ["remove 1 2", "clear extra"])
def test_malformed_destructive_subgoal_command_preserves_criteria(server, session, argument):
    from superforecasting_agent.runtime.goals import GoalManager

    sid, key, _ = session
    manager = GoalManager(session_id=key)
    manager.set("Review forecast")
    manager.add_subgoal("Keep this criterion")
    result = _call(server, "command.dispatch", name="subgoal", arg=argument, session_id=sid)
    assert "✓" not in result["result"]["output"]
    assert GoalManager(session_id=key).state.subgoals == ["Keep this criterion"]


@pytest.mark.parametrize('value, budget', [(True, 20), (2.5, 20), (-1, 20), ('7', 7)])
def test_goal_command_uses_shared_budget_policy(server, session, monkeypatch, value, budget):
    sid, _, _ = session
    monkeypatch.setattr(server, '_load_cfg', lambda: {'goals': {'max_turns': value}})
    result = _call(server, 'command.dispatch', name='goal', arg='Check sources', session_id=sid)
    assert result['result']['type'] == 'send'
    assert f'{budget}-turn budget' in result['result']['notice']
