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


@pytest.fixture
def bundle_command(configure, monkeypatch):
    configure({})
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: None)
    monkeypatch.setattr("agent.skill_bundles.get_skill_bundles", lambda: {"/fixture-bundle": {"name": "Review pack"}})
    skill = Mock(side_effect=AssertionError("bundle must precede individual skill"))
    monkeypatch.setattr("agent.skill_commands.build_skill_invocation_message", skill)
    monkeypatch.setattr("agent.skill_commands.scan_skill_commands", lambda: {"/fixture-bundle": {"name": "shadowed"}})
    build = Mock(return_value=("shared payload", ["review"], ["missing"]))
    monkeypatch.setattr("agent.skill_bundles.build_bundle_invocation_message", build)
    return build


def test_bundle_dispatch_uses_shared_loader_without_agent(bundle_command):
    assert slash("fixture-bundle CaseSensitive")["error"]["data"] == {
        "dispatch": "command.dispatch", "execution_started": False,
    }
    bundle_command.assert_not_called()
    result = dispatch("fixture-bundle", "CaseSensitive")["result"]
    assert result == {
        "type": "send", "message": "shared payload",
        "notice": "Loading bundle: Review pack (1 skills)\nSkipped missing skills: missing",
    }
    bundle_command.assert_called_once_with("/fixture-bundle", "CaseSensitive", task_id="durable")
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("failure", [None, RuntimeError("bundle failed")])
def test_bundle_failure_never_hands_off_or_tries_individual_skill(bundle_command, failure):
    if isinstance(failure, Exception):
        bundle_command.side_effect = failure
    else:
        bundle_command.return_value = failure
    error = dispatch("fixture-bundle")["error"]
    assert error["code"] == (5030 if isinstance(failure, Exception) else 4018)
    assert "data" not in error
    bundle_command.assert_called_once()
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


def test_bundle_catalog_exposes_one_entry_with_bundle_precedence(bundle_command):
    result = server.handle_request({"id": 3, "method": "commands.catalog", "params": {}})["result"]
    assert result["canon"]["/fixture-bundle"] == "/fixture-bundle"
    assert [pair for pair in result["pairs"] if pair[0] == "/fixture-bundle"] == [
        ["/fixture-bundle", "Load a skill bundle"],
    ]
    assert {"name": "Skill bundles", "pairs": [["/fixture-bundle", "Load a skill bundle"]]} in result["categories"]
    bundle_command.assert_not_called()


def test_bundle_cannot_override_builtin_command(bundle_command, monkeypatch):
    monkeypatch.setattr("agent.skill_bundles.get_skill_bundles", lambda: {"/retry": {"name": "shadow"}})
    assert "no previous" in dispatch("retry")["error"]["message"]
    bundle_command.assert_not_called()


def test_native_builtin_cannot_be_overridden_by_plugin(configure, monkeypatch):
    configure({})
    plugin = Mock(side_effect=AssertionError("plugin overrode builtin"))
    monkeypatch.setattr("superforecasting_agent.runtime.plugins.get_plugin_command_handler", lambda name: plugin)
    assert "no previous" in dispatch("retry")["error"]["message"]
    plugin.assert_not_called()


@pytest.mark.parametrize("selection,marker", [(None, "(*)"), ([], ""), (["forecasting"], "(*)")])
def test_toolset_command_shares_cli_inventory_without_worker(configure, monkeypatch, selection, marker):
    from types import SimpleNamespace
    from cli import ForecastCLI

    configure({})
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda: selection)
    monkeypatch.setattr("superforecasting_agent.tooling.toolsets.get_all_toolsets", lambda: {"forecasting": {}, "hermes-legacy": {}})
    monkeypatch.setattr("superforecasting_agent.tooling.toolsets.get_toolset_info", lambda name: {
        "description": "Fixture tools", "tool_count": 1, "resolved_tools": ["fixture"],
    })
    response = dispatch("toolsets")["result"]
    assert response["type"] == "exec"
    rendered = []
    monkeypatch.setitem(
        ForecastCLI.show_toolsets.__globals__, "print",
        lambda *parts, **kwargs: rendered.append(" ".join(str(part) for part in parts)),
    )
    ForecastCLI.show_toolsets(SimpleNamespace(enabled_toolsets=selection))
    classic = "\n".join(rendered)
    expected = f"{marker} forecasting [1 tools] - Fixture tools".strip()
    for surface, output in (("TUI", response["output"]), ("CLI", classic)):
        rows = [line for line in output.splitlines() if "Fixture tools" in line]
        assert len(rows) == 1, (surface, output)
        assert " ".join(rows[0].split()).replace("[ ", "[") == expected, (surface, output)
        assert "hermes-legacy" not in output
    assert slash("toolsets")["error"]["data"] == {
        "dispatch": "command.dispatch", "execution_started": False,
    }
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()



def test_profile_command_matches_classic_identity_without_agent(configure, monkeypatch, capsys):
    from superforecasting_agent.runtime.maintenance_commands import _handle_profile_command

    configure({})
    monkeypatch.setattr("superforecasting_agent.constants.get_active_profile_name", lambda: "fixture-profile")
    monkeypatch.setattr("superforecasting_agent.constants.display_agent_home", lambda: "~/fixture-profile")
    result = dispatch("profile")["result"]
    _handle_profile_command(None)
    assert "\n".join(line.removeprefix("  ") for line in capsys.readouterr().out.strip("\n").splitlines()) == result["output"]
    assert result["type"] == "exec"
    assert slash("profile")["error"]["data"]["dispatch"] == "command.dispatch"
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("installed", [False, True])
def test_native_bundle_inspection_reads_shared_inventory(configure, monkeypatch, tmp_path, installed):
    from agent.skill_bundles import save_bundle

    configure({})
    monkeypatch.setenv("HERMES_BUNDLES_DIR", str(tmp_path))
    if installed:
        save_bundle("review-pack", skills=["research", "calibration"], description="Review sources")
    result = dispatch("bundles")["result"]
    assert result["type"] == "exec"
    if installed:
        assert "/review-pack — Review sources (2 skills)" in result["output"]
        assert "· research" in result["output"]
        assert "· calibration" in result["output"]
    else:
        assert "No skill bundles installed." in result["output"]
        assert str(tmp_path) in result["output"]
    assert slash("bundles")["error"]["data"]["dispatch"] == "command.dispatch"
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_native_insights_uses_host_store_without_closing_it(configure, monkeypatch, failure):
    configure({})
    database = Mock()
    monkeypatch.setattr(server, "_get_db", lambda: database)
    engine = Mock()
    engine.generate.return_value = {"fixture": True}
    engine.format_terminal.return_value = "Fixture insights"
    if failure:
        engine.generate.side_effect = RuntimeError("fixture generation failure")
    constructor = Mock(return_value=engine)
    monkeypatch.setattr("agent.insights.InsightsEngine", constructor)
    response = dispatch("insights", "—days 7 --source cli")
    constructor.assert_called_once_with(database)
    engine.generate.assert_called_once_with(days=7, source="cli")
    if failure:
        assert response["error"] == {"code": 5017, "message": "fixture generation failure"}
    else:
        assert response["result"] == {"type": "exec", "output": "Fixture insights"}
    database.close.assert_not_called()
    assert slash("insights")["error"]["data"]["dispatch"] == "command.dispatch"
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_native_runtime_change_uses_host_config_and_preserves_live_agent(configure, monkeypatch, tmp_path):
    import yaml

    configure({})
    path = tmp_path / "config.yaml"
    path.write_text("model:\n  openai_runtime: codex_app_server\nother: retained\n", encoding="utf-8")
    owner = server._host.configuration
    monkeypatch.setattr(server, "_load_cfg", lambda: owner.load(path))
    monkeypatch.setattr(server, "_save_cfg", lambda cfg: owner.save(path, cfg))
    agent = object()
    server._host.sessions["runtime"]["agent"] = agent
    response = dispatch("codex-runtime", "off")
    assert "Effective on next session" in response["result"]["output"]
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "model": {"openai_runtime": "auto"}, "other": "retained",
    }
    assert server._host.sessions["runtime"]["agent"] is agent
    assert slash("/codex-runtime off")["error"]["data"]["execution_started"] is False


def test_native_runtime_rejects_invalid_args_before_save(configure, monkeypatch):
    configure({})
    save = Mock(side_effect=AssertionError("invalid runtime reached persistence"))
    monkeypatch.setattr(server, "_save_cfg", save)
    assert dispatch("codex-runtime", "off extra")["error"]["code"] == 4004
    save.assert_not_called()


def test_native_runtime_save_failure_does_not_fall_through(configure, monkeypatch):
    configure({})
    monkeypatch.setattr(server, "_load_cfg", lambda: {"model": {"openai_runtime": "codex_app_server"}})
    monkeypatch.setattr(server, "_save_cfg", Mock(side_effect=OSError("disk full")))
    response = dispatch("codex-runtime", "off")
    assert response["error"]["code"] == 5017
    assert "disk full" in response["error"]["message"]


@pytest.mark.parametrize("scenario", ["quota", "empty", "signed-out", "provider-error", "invalid"])
def test_google_quota_shared_with_cli_without_worker(configure, monkeypatch, scenario):
    from types import SimpleNamespace
    from agent.google_code_assist import QuotaBucket, CodeAssistError
    from agent.google_oauth import GoogleOAuthError
    from cli import ForecastCLI

    configure({})
    token = Mock(return_value="fixture-only-token")
    lookup = Mock(return_value=[QuotaBucket("z-model", remaining_fraction=0.25),
                               QuotaBucket("a-model", remaining_fraction=0.75)])
    if scenario == "empty":
        lookup.return_value = []
    elif scenario == "signed-out":
        token.side_effect = GoogleOAuthError("Sign in required")
    elif scenario == "provider-error":
        lookup.side_effect = CodeAssistError("quota unavailable")
    monkeypatch.setattr("agent.google_oauth.get_valid_access_token", token)
    monkeypatch.setattr("agent.google_oauth.load_credentials", lambda: SimpleNamespace(project_id="fixture-project"))
    monkeypatch.setattr("agent.google_code_assist.retrieve_user_quota", lookup)
    arg = "unexpected" if scenario == "invalid" else ""
    response = dispatch("gquota", arg)
    rendered = []
    ForecastCLI._handle_gquota_command(SimpleNamespace(_console_print=rendered.append), "/gquota " + arg)
    classic = "\n".join(rendered)
    if scenario == "invalid":
        assert response["error"]["code"] == 4004
        assert response["error"]["message"] == classic
        token.assert_not_called()
        lookup.assert_not_called()
    else:
        assert response["result"]["output"] == classic
        assert "fixture-only-token" not in classic
        if scenario == "quota":
            assert classic.index("a-model") < classic.index("z-model")
            assert "75%" in classic and "25%" in classic
    assert slash("/gquota")["error"]["data"]["execution_started"] is False
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("scenario", ["configured", "invalid", "unavailable"])
def test_platform_configuration_shared_with_cli(configure, monkeypatch, scenario):
    from types import SimpleNamespace
    from gateway.config import Platform
    from cli import ForecastCLI

    configure({})
    monkeypatch.setattr("superforecasting_agent.platform_registry.platform_registry.get", lambda _: None)
    config = SimpleNamespace(
        platforms={Platform.MATRIX: SimpleNamespace(enabled=True),
                   Platform.SIGNAL: SimpleNamespace(enabled=False)},
        get_home_channel=lambda platform: SimpleNamespace(name="Review desk") if platform == Platform.MATRIX else None,
        default_reset_policy=SimpleNamespace(mode="idle", at_hour=3, idle_minutes=60),
    )
    load = Mock(return_value=config)
    if scenario == "unavailable":
        load.side_effect = OSError("configuration unreadable")
    monkeypatch.setattr("gateway.config.load_gateway_config", load)
    arg = "unexpected" if scenario == "invalid" else ""
    response = dispatch("platforms", arg)
    rendered = []
    monkeypatch.setitem(ForecastCLI._show_gateway_status.__globals__, "print", rendered.append)
    ForecastCLI._show_gateway_status(None, "/platforms " + arg)
    classic = "\n".join(rendered)
    if scenario == "configured":
        assert response["result"]["output"] == classic
        assert "matrix: Enabled in configuration → Review desk" in classic
        assert "signal: Disabled in configuration" in classic
        assert "Live connections are not checked." in classic
        assert "superforecasting-agent gateway" in classic
        assert dispatch("gateway")["result"] == response["result"]
    else:
        assert response["error"]["message"] == classic
        if scenario == "invalid":
            load.assert_not_called()
    assert slash("/platforms")["error"]["data"]["execution_started"] is False
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize('argument,action', [
    ('list', 'list'),
    ('add "every 2h" "Review forecasts"', 'create'),
    ('edit job-1 --prompt "Review evidence"', 'update'),
    ('pause job-1', 'pause'), ('resume job-1', 'resume'),
    ('run job-1', 'run'), ('remove job-1', 'remove'),
])
def test_cron_shared_commands_execute_once_without_worker(configure, monkeypatch, argument, action):
    import json
    from cli import ForecastCLI
    from superforecasting_agent.runtime import cron_commands

    configure({})
    job = {'job_id': 'job-1', 'name': 'Review', 'schedule': 'every 2h',
           'next_run_at': '2026-10-01T00:00:00Z', 'repeat': 'forever'}
    api = Mock(return_value=json.dumps({'success': True, 'job': job, 'jobs': [job],
                                       'removed_job': job, **job}))
    monkeypatch.setattr('tools.cronjob_tools.cronjob', api)
    monkeypatch.setattr(cron_commands, 'get_job', lambda _: job)
    response = dispatch('cron', argument)
    assert 'error' not in response
    api.assert_called_once()
    assert api.call_args.kwargs['action'] == action
    output = []
    monkeypatch.setattr(cron_commands, 'print', output.append, raising=False)
    ForecastCLI._handle_cron_command(None, '/cron ' + argument)
    assert response['result']['output'] == output[0]
    assert api.call_count == 2
    assert slash('/cron ' + argument)['error']['data']['execution_started'] is False
    assert api.call_count == 2


@pytest.mark.parametrize('argument', [
    'add "every 2h" "prompt" --typo',
    'edit job-1 --name', 'edit job-1 --name --clear-skills',
    'add "unterminated', 'add "every 2h" "prompt" --repeat nope',
])
def test_cron_invalid_input_never_reaches_storage(configure, monkeypatch, argument):
    from superforecasting_agent.runtime import cron_commands
    configure({})
    api = Mock(side_effect=AssertionError('invalid command reached tool'))
    lookup = Mock(side_effect=AssertionError('invalid command reached storage'))
    monkeypatch.setattr('tools.cronjob_tools.cronjob', api)
    monkeypatch.setattr(cron_commands, 'get_job', lookup)
    result = dispatch('cron', argument)
    assert result['result']['output']
    api.assert_not_called()
    lookup.assert_not_called()


def test_cron_failure_never_requests_second_dispatch(configure, monkeypatch):
    configure({})
    api = Mock(side_effect=OSError('storage unavailable'))
    monkeypatch.setattr('tools.cronjob_tools.cronjob', api)
    result = dispatch('cron', 'list')
    assert result['error']['code'] == 5017
    assert 'data' not in result['error']
    api.assert_called_once()


@pytest.mark.parametrize('argument', ['', 'list'])
def test_cron_list_failure_is_not_reported_as_empty_schedule(configure, monkeypatch, argument):
    configure({})
    monkeypatch.setattr('tools.cronjob_tools.cronjob', lambda **_: '{"success": false, "error": "unreadable schedule"}')
    output = dispatch('cron', argument)['result']['output']
    assert 'Failed to list jobs: unreadable schedule' in output
    assert 'No scheduled' not in output


@pytest.mark.parametrize("argument,paused", [("pause", True), ("resume", False)])
def test_curator_shared_operation_without_classic_worker(configure, monkeypatch, capsys, argument, paused):
    from agent import curator
    from superforecasting_agent.runtime.maintenance_commands import _handle_curator_command

    configure({})
    mutation = Mock()
    monkeypatch.setattr(curator, "set_paused", mutation)
    result = dispatch("curator", argument)
    mutation.assert_called_once_with(paused)
    _handle_curator_command(None, "/curator " + argument)
    assert capsys.readouterr().out.strip() == result["result"]["output"]
    assert mutation.call_count == 2
    handoff = slash("/curator " + argument)
    assert handoff["error"]["data"]["execution_started"] is False
    assert mutation.call_count == 2
    server._start_agent_build.assert_not_called()
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("answer,approved", [("", False), ("No", False), ("Yes", True)])
def test_curator_prune_confirmation_uses_preview_and_cancels_safely(configure, monkeypatch, answer, approved):
    from superforecasting_agent.runtime import curator
    from tools import skill_usage

    configure({})
    monkeypatch.setattr(skill_usage, "agent_created_report", lambda: [
        {"name": "stale-weather-guidance", "state": "active", "pinned": False},
    ])
    monkeypatch.setattr(curator, "_idle_days", lambda record: 120)
    archive = Mock(return_value=(True, "archived"))
    monkeypatch.setattr(skill_usage, "archive_skill", archive)
    prompt = Mock(return_value=answer)
    monkeypatch.setattr(server, "_block", prompt)
    response = dispatch("curator", "prune --days 90")
    prompt.assert_called_once()
    event, sid, payload = prompt.call_args.args
    assert (event, sid) == ("clarify.request", "runtime")
    assert "stale-weather-guidance" in payload["question"]
    assert "120d" in payload["question"]
    assert payload["choices"] == ["No", "Yes"]
    if approved:
        archive.assert_called_once_with("stale-weather-guidance")
        assert "archived 1/1" in response["result"]["output"]
    else:
        archive.assert_not_called()
        assert "aborted" in response["error"]["message"]
        assert "data" not in response["error"]
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


@pytest.mark.parametrize("argument", ['pin "unterminated', "pause --typo", "prune --days nope"])
def test_curator_invalid_input_does_not_mutate_or_write_rpc_stdout(configure, monkeypatch, capsys, argument):
    from agent import curator
    from tools import skill_usage

    configure({})
    mutation = Mock(side_effect=AssertionError("invalid command mutated state"))
    monkeypatch.setattr(curator, "set_paused", mutation)
    monkeypatch.setattr(skill_usage, "archive_skill", mutation)
    response = dispatch("curator", argument)
    assert response["error"]["message"]
    assert "data" not in response["error"]
    mutation.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_curator_failure_cannot_trigger_worker_retry(configure, monkeypatch):
    from agent import curator

    configure({})
    mutation = Mock(side_effect=OSError("state store unavailable"))
    monkeypatch.setattr(curator, "set_paused", mutation)
    response = dispatch("curator", "pause")
    assert "state store unavailable" in response["error"]["message"]
    assert "data" not in response["error"]
    mutation.assert_called_once_with(True)
    server._SlashWorker.assert_not_called()


@pytest.mark.parametrize("answer,approved", [("", False), ("Yes", True)])
def test_curator_rollback_confirmation_binds_displayed_snapshot(configure, monkeypatch, tmp_path, answer, approved):
    from agent import curator_backup

    configure({})
    target = tmp_path / "20260912-snapshot"
    monkeypatch.setattr(curator_backup, "_resolve_backup", lambda backup_id: target)
    monkeypatch.setattr(curator_backup, "_read_manifest", lambda path: {
        "reason": "before consolidation", "skill_files": 3,
        "cron_jobs": {"backed_up": True, "jobs_count": 2},
    })
    restore = Mock(return_value=(True, "restored", {}))
    monkeypatch.setattr(curator_backup, "rollback", restore)
    prompt = Mock(return_value=answer)
    monkeypatch.setattr(server, "_block", prompt)
    result = dispatch("curator", "rollback")
    question = prompt.call_args.args[2]["question"]
    assert target.name in question
    assert "before consolidation" in question
    assert "skill files: 3" in question
    assert "safety snapshot" in question
    if approved:
        restore.assert_called_once_with(backup_id=target.name)
        assert "restored" in result["result"]["output"]
    else:
        restore.assert_not_called()
        assert "cancelled" in result["error"]["message"]


def test_concurrent_curator_commands_keep_output_separate(configure, monkeypatch, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from agent import curator

    configure({})
    barrier = Barrier(2)
    monkeypatch.setattr(curator, "set_paused", lambda paused: barrier.wait(timeout=5))
    with ThreadPoolExecutor(max_workers=2) as executor:
        pause = executor.submit(dispatch, "curator", "pause")
        resume = executor.submit(dispatch, "curator", "resume")
        assert pause.result(timeout=10)["result"]["output"] == "curator: paused"
        assert resume.result(timeout=10)["result"]["output"] == "curator: resumed"
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("canonical", [
    "plugins", "toolsets", "profile", "bundles", "insights", "codex-runtime",
    "gquota", "platforms", "cron", "curator",
])
def test_native_handoff_covers_registry_aliases(configure, canonical):
    from superforecasting_agent.application.command_catalog import resolve_command

    configure({})
    definition = resolve_command(canonical)
    for name in (definition.name, *definition.aliases):
        response = slash(f"/{name.upper()}")
        assert response["error"]["data"] == {
            "dispatch": "command.dispatch", "execution_started": False,
        }
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_runtime_alias_executes_shared_operation_once(configure, monkeypatch):
    configure({})
    monkeypatch.setattr(server, "_load_cfg", lambda: {
        "model": {"openai_runtime": "codex_app_server"},
    })
    save = Mock()
    monkeypatch.setattr(server, "_save_cfg", save)
    handoff = slash("/codex_runtime off")
    assert handoff["error"]["data"]["execution_started"] is False
    save.assert_not_called()
    response = dispatch("codex_runtime", "off")
    assert response["result"]["type"] == "exec"
    save.assert_called_once()
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_snapshot_native_lifecycle_and_cli_listing_parity(configure, monkeypatch, tmp_path, capsys):
    from superforecasting_agent.runtime.checkpoint_commands import _handle_snapshot_command
    from superforecasting_agent.storage.snapshots import list_quick_snapshots

    configure({})
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("model: test-model\n", encoding="utf-8")
    assert slash('/snap create "before upgrade"')["error"]["data"]["execution_started"] is False
    assert not (tmp_path / "state-snapshots").exists()
    created = dispatch("snap", 'create "before upgrade"')
    assert "Snapshot created:" in created["result"]["output"]
    snapshots = list_quick_snapshots(hermes_home=tmp_path)
    assert len(snapshots) == 1 and snapshots[0]["label"] == "before upgrade"
    listed = dispatch("snapshot", "list")["result"]["output"]
    _handle_snapshot_command(None, "/snap ls")
    assert capsys.readouterr().out.strip() == listed
    assert dispatch("snapshot", "prune 0")["result"]["output"] == "Pruned 1 old snapshot(s) (keeping 0)."
    assert list_quick_snapshots(hermes_home=tmp_path) == []
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


@pytest.mark.parametrize("argument", ["list extra", "prune -1", "prune 2 extra", 'create "', "create ../escape", "unknown"])
def test_snapshot_validation_matches_cli_without_worker(configure, monkeypatch, tmp_path, capsys, argument):
    from superforecasting_agent.runtime.checkpoint_commands import _handle_snapshot_command

    configure({})
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    response = dispatch("snapshot", argument)
    assert response["error"]["code"] == 4004
    _handle_snapshot_command(None, "/snapshot " + argument)
    assert capsys.readouterr().out.strip() == response["error"]["message"]
    assert not (tmp_path / "state-snapshots").exists()
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_snapshot_restore_admission_and_storage_failure_never_fall_through(configure, monkeypatch):
    from superforecasting_agent.storage import snapshots

    configure({})
    restore = Mock(side_effect=AssertionError("live database restore attempted"))
    monkeypatch.setattr(snapshots, "restore_quick_snapshot", restore)
    assert "blocked in the TUI" in dispatch("snap", "rewind 1")["result"]["output"]
    restore.assert_not_called()
    create = Mock(side_effect=OSError("injected storage failure"))
    monkeypatch.setattr(snapshots, "create_quick_snapshot", create)
    response = dispatch("snapshot", "create")
    assert response["error"]["code"] == 5017
    assert "data" not in response["error"]
    create.assert_called_once()
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_native_kanban_uses_shared_operation_without_classic_worker(configure, monkeypatch, tmp_path):
    from superforecasting_agent.runtime import kanban_db

    configure({})
    monkeypatch.setattr(kanban_db, "kanban_home", lambda: tmp_path)
    result = slash('/kanban create "native task"')
    assert "Created" in result["result"]["output"]
    with kanban_db.connection() as db:
        assert [task.title for task in kanban_db.list_tasks(db)] == ["native task"]
    assert not server._host.sessions["runtime"].get("_command_stops")
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_async_native_watch_accepts_session_interrupt_and_preserves_transport(configure, monkeypatch, tmp_path):
    import queue
    import threading
    from types import SimpleNamespace
    from superforecasting_agent.runtime import kanban, kanban_db

    configure({})
    monkeypatch.setattr(kanban_db, "kanban_home", lambda: tmp_path)
    started = threading.Event()
    watch = kanban._cmd_watch
    def watching(args):
        started.set()
        return watch(args)
    monkeypatch.setattr(kanban, "_cmd_watch", watching)
    responses = queue.Queue()
    transport = SimpleNamespace(write=lambda value: responses.put(value) or True)
    try:
        assert server.dispatch({"id": 20, "method": "slash.exec", "params": {
            "command": "kanban watch --interval 3600", "session_id": "runtime",
        }}, transport) is None
        assert started.wait(3)
        response = server.dispatch({"id": 21, "method": "session.interrupt", "params": {
            "session_id": "runtime",
        }}, transport)
        assert response["result"]["status"] == "cancelling"
        finished = responses.get(timeout=3)
        assert finished["id"] == 20
        assert "stopped" in finished["result"]["output"]
        assert not server._host.sessions["runtime"].get("_command_stops")
    finally:
        server._host.interrupt_commands(server._host.sessions["runtime"])
        server._host.workers.stop()
        assert server._host.workers.drain(3)
    server._SlashWorker.assert_not_called()
    server._start_agent_build.assert_not_called()


def test_native_command_rejects_stopping_host_without_work(configure, monkeypatch):
    from superforecasting_agent.runtime import kanban

    configure({})
    operation = Mock(side_effect=AssertionError("stopping host executed command"))
    monkeypatch.setattr(kanban, "run_slash", operation)
    server._host.workers.stop()
    response = slash("kanban list")
    assert response["error"] == {"code": 5030, "message": "runtime host is stopping"}
    operation.assert_not_called()
    assert server._host.workers.drain(0)
