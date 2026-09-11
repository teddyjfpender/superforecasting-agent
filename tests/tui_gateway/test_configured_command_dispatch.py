"""Configured commands share validation and never execute in a second CLI runtime."""

import shlex
import sys
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway import server


@pytest.fixture
def configure(monkeypatch):
    monkeypatch.setattr(server, "_host", RuntimeHost())
    server._host.sessions["runtime"] = {"session_key": "durable", "history": []}
    monkeypatch.setattr(
        server,
        "_start_agent_build",
        Mock(side_effect=AssertionError("unexpected agent construction")),
    )
    monkeypatch.setattr(
        server,
        "_SlashWorker",
        Mock(side_effect=AssertionError("unexpected classic CLI worker")),
    )

    def setup(commands):
        monkeypatch.setattr(server, "_load_cfg", lambda: {"quick_commands": commands})

    return setup


def dispatch(name, arg=""):
    return server.handle_request({
        "id": 1,
        "method": "command.dispatch",
        "params": {"name": name, "arg": arg, "session_id": "runtime"},
    })


def slash(command):
    return server.handle_request({
        "id": 2,
        "method": "slash.exec",
        "params": {"command": command, "session_id": "runtime"},
    })


def test_nested_alias_is_resolved_without_constructing_an_agent(configure):
    configure({
        "custom": {"type": "alias", "target": "inner FixedArg"},
        "inner": {"type": "alias", "target": "/model CaseSensitiveModel"},
    })
    assert slash("custom UserArg")["error"]["code"] == 4018
    assert dispatch("custom", "UserArg")["result"] == {
        "type": "alias",
        "target": "model CaseSensitiveModel FixedArg",
    }  # The TUI appends UserArg exactly once when invoking this target.


def test_cycle_is_rejected_before_any_command_runs(configure):
    configure({
        "first": {"type": "alias", "target": "second"},
        "second": {"type": "alias", "target": "first"},
    })
    assert "cycle" in dispatch("first")["error"]["message"]
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


@pytest.mark.parametrize(
    "entry",
    [
        None,
        [],
        {"type": []},
        {"type": "alias", "target": {}},
        {"type": "exec", "command": 5},
        {"type": "exec", "command": ""},
    ],
)
def test_malformed_definition_reports_same_error_before_agent_or_execution(
    configure, entry
):
    configure({"custom": entry})
    assert slash("custom")["error"]["message"] == dispatch("custom")["error"]["message"]
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_builtin_cannot_be_overridden_by_configured_execution(configure, monkeypatch):
    configure({"retry": {"type": "exec", "command": "should not run"}})
    execute = Mock(side_effect=AssertionError("builtin override executed"))
    monkeypatch.setattr(server.subprocess, "run", execute)
    assert "no previous" in dispatch("retry")["error"]["message"]
    execute.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell quoting fixture")
def test_failed_shell_command_executes_once_across_tui_fallback(configure, tmp_path):
    marker = tmp_path / "executions"
    code = (
        f"from pathlib import Path; p=Path({str(marker)!r}); "
        'p.write_text(str(int(p.read_text())+1) if p.exists() else "1"); '
        'print("fixture failure"); raise SystemExit(1)'
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    configure({"custom": {"type": "exec", "command": command}})
    assert slash("custom")["error"]["code"] == 4018
    assert not marker.exists()
    response = dispatch("custom")
    assert "fixture failure" in response["error"]["message"]
    assert marker.read_text() == "1"


@pytest.mark.parametrize(
    "entry", [None, {"type": "alias", "target": 5}, {"type": "exec", "command": ""}]
)
def test_classic_cli_and_tui_report_identical_definition_errors(configure, entry):
    from types import SimpleNamespace
    from cli import ForecastCLI

    configured = {"custom": entry}
    configure(configured)
    output = Mock()
    classic = SimpleNamespace(
        config={"quick_commands": configured}, _console_print=output
    )
    assert ForecastCLI.process_command(classic, "/custom") is True
    output.assert_called_once_with(dispatch("custom")["error"]["message"])


@pytest.mark.parametrize("command", ["queue note", "q note", "goal status", "retry", "steer note", "snapshot restore", "plugins"])
def test_native_handoff_does_not_need_provider_initialization(configure, command):
    configure({})
    response = slash(command)
    assert response["error"]["code"] == 4018
    assert "command.dispatch" in response["error"]["message"]
    assert response["error"]["data"] == {
        "dispatch": "command.dispatch", "execution_started": False,
    }
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_skill_handoff_does_not_need_provider_initialization(configure, monkeypatch):
    configure({})
    monkeypatch.setattr(
        "agent.skill_commands.get_skill_commands",
        lambda: {"/fixture-skill": {"name": "fixture-skill"}},
    )
    assert "skill command" in slash("fixture-skill note")["error"]["message"]
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_plugin_command_does_not_construct_an_unrelated_agent(configure, monkeypatch):
    configure({})
    monkeypatch.setattr("agent.skill_commands.get_skill_commands", lambda: {})
    plugin = Mock(return_value="fixture output")
    monkeypatch.setattr(
        "superforecasting_agent.runtime.plugins.get_plugin_command_handler",
        lambda name: plugin if name == "fixture-plugin" else None,
    )
    assert slash("fixture-plugin CaseSensitive")["result"] == {"output": "fixture output"}
    plugin.assert_called_once_with("CaseSensitive")
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_native_known_legacy_command_hands_off_without_execution(configure, monkeypatch):
    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    response = dispatch("help")
    assert response["error"]["data"] == {"dispatch": "slash.exec", "execution_started": False}
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_native_plugin_failure_never_becomes_a_legacy_handoff(configure, monkeypatch):
    configure({})
    plugin = Mock(side_effect=RuntimeError("failed after effect"))
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: plugin)
    response = dispatch("fixture-plugin", "args")
    assert response["error"]["code"] == 5030
    assert "failed after effect" in response["error"]["message"]
    assert "data" not in response["error"]
    plugin.assert_called_once_with("args")
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("result", [None, RuntimeError("fixture skill failed")])
def test_owned_skill_failure_does_not_fall_back_to_legacy(configure, monkeypatch, result):
    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {"/fixture-skill": {"name": "fixture-skill"}})
    build = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    monkeypatch.setattr("agent.skill_commands.build_skill_invocation_message", build)
    response = dispatch("fixture-skill")
    assert "error" in response
    assert "data" not in response["error"]
    build.assert_called_once()
    server._start_agent_build.assert_not_called()


@pytest.mark.parametrize("invoke", [dispatch, slash])
@pytest.mark.parametrize("command", ["fixture-unknown", "/fixture-unknown"])
def test_unknown_command_rejected_before_runtime_construction(configure, monkeypatch, invoke, command):
    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    monkeypatch.setattr("agent.skill_commands.get_skill_commands", lambda: {})
    response = invoke(command)
    assert response["error"] == {"code": 4011, "message": "unknown command: fixture-unknown"}
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("plugins", [[], [
    {"name": "fixture", "enabled": False, "version": "1.2", "tools": 2,
     "hooks": 0, "commands": 1, "error": "fixture disabled"},
]])
def test_plugin_inspection_matches_classic_without_agent(configure, monkeypatch, capsys, plugins):
    from types import SimpleNamespace
    from cli import ForecastCLI

    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    manager = Mock()
    manager.list_plugins.return_value = plugins
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_manager", lambda: manager)
    response = dispatch("plugins")
    assert response["result"]["type"] == "exec"
    classic = SimpleNamespace(config={"quick_commands": {}})
    assert ForecastCLI.process_command(classic, "/plugins") is True
    assert capsys.readouterr().out.rstrip() == response["result"]["output"]
    if plugins:
        assert "✗ fixture v1.2 (2 tools, 1 commands) — fixture disabled" in response["result"]["output"]
    else:
        assert "No plugins installed." in response["result"]["output"]
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_plugin_inspection_failure_preserves_native_error(configure, monkeypatch):
    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_manager", Mock(side_effect=RuntimeError("inspection failed")))
    assert dispatch("plugins")["error"] == {"code": 5030, "message": "Plugin system error: inspection failed"}
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()
