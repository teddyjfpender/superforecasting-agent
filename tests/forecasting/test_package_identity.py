from __future__ import annotations

import re
import sys
from types import ModuleType

import pytest

from forecasting.ledger import ForecastLedger
import superforecasting_agent.cli as forecast_cli
from superforecasting_agent import ForecastLedger as PublicForecastLedger
from superforecasting_agent import PRODUCT_NAME, PRODUCT_SLUG
from superforecasting_agent.cli import main as forecast_main


def test_superforecasting_agent_namespace_exports_forecast_primitives():
    assert PublicForecastLedger is ForecastLedger
    assert PRODUCT_NAME == "Superforecasting Agent"
    assert PRODUCT_SLUG == "superforecasting-agent"


def test_superforecasting_agent_cli_entrypoint_runs_forecast_lifecycle(tmp_path, capsys):
    db = str(tmp_path / "forecasting.db")

    forecast_main(
        [
            "--db",
            db,
            "new",
            "Will native package entrypoint work?",
            "--resolution-criteria",
            "Resolved yes if the fork-native package can run the forecast CLI.",
        ]
    )
    output = capsys.readouterr().out

    assert re.search(r"created forecast question fq_[a-f0-9]+", output)


def test_superforecasting_agent_cli_help_uses_fork_native_prog(capsys):
    with pytest.raises(SystemExit) as exc:
        forecast_main(["performance", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "usage: superforecasting-agent performance" in output
    assert "forecast forecast" not in output


def test_superforecasting_agent_cli_accepts_explicit_forecast_namespace(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "forecasting.db")

    def fail_inherited_runtime(argv):
        raise AssertionError(f"unexpected inherited runtime dispatch: {argv}")

    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fail_inherited_runtime)

    forecast_main(["--db", db, "forecast", "status", "--json"])
    output = capsys.readouterr().out

    assert '"slug": "superforecasting-agent"' in output
    assert '"question_counts": {' in output


def test_superforecasting_agent_cli_accepts_db_after_forecast_command(tmp_path, capsys, monkeypatch):
    db = str(tmp_path / "forecasting.db")

    def fail_inherited_runtime(argv):
        raise AssertionError(f"unexpected inherited runtime dispatch: {argv}")

    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fail_inherited_runtime)

    forecast_main(["status", "--db", db, "--json"])
    output = capsys.readouterr().out

    assert '"slug": "superforecasting-agent"' in output
    assert '"ledger_path":' in output
    assert db in output


def test_superforecasting_agent_cli_forecast_namespace_help_uses_fork_native_prog(capsys, monkeypatch):
    def fail_inherited_runtime(argv):
        raise AssertionError(f"unexpected inherited runtime dispatch: {argv}")

    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fail_inherited_runtime)

    with pytest.raises(SystemExit) as exc:
        forecast_main(["forecast", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "usage: superforecasting-agent" in output
    assert "forecast forecast" not in output


def test_legacy_hermes_agent_entrypoint_warns_and_still_runs_forecast_cli(
    tmp_path, capsys, monkeypatch
):
    db = str(tmp_path / "forecasting.db")
    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes-agent", "--db", db, "forecast", "status", "--json"],
    )
    monkeypatch.setattr(forecast_cli, "_legacy_entrypoint_notice_shown", False)

    forecast_cli.main()
    captured = capsys.readouterr()

    assert "`hermes-agent` is a compatibility alias" in captured.err
    assert "Use `superforecasting-agent` or `forecast`" in captured.err
    assert '"slug": "superforecasting-agent"' in captured.out


def test_fork_native_entrypoint_does_not_warn_for_forecast_cli(
    tmp_path, capsys, monkeypatch
):
    db = str(tmp_path / "forecasting.db")
    monkeypatch.setattr(
        sys,
        "argv",
        ["superforecasting-agent", "--db", db, "forecast", "status", "--json"],
    )
    monkeypatch.setattr(forecast_cli, "_legacy_entrypoint_notice_shown", False)

    forecast_cli.main()
    captured = capsys.readouterr()

    assert "compatibility alias" not in captured.err
    assert '"slug": "superforecasting-agent"' in captured.out


def test_superforecasting_agent_cli_profiled_forecast_namespace_avoids_inherited_runtime(
    tmp_path, capsys, monkeypatch
):
    db = str(tmp_path / "forecasting.db")
    profiles = []

    def fake_apply_profile(profile_name):
        profiles.append(profile_name)

    def fail_inherited_runtime(argv):
        raise AssertionError(f"unexpected inherited runtime dispatch: {argv}")

    monkeypatch.setattr(forecast_cli, "_apply_profile", fake_apply_profile)
    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fail_inherited_runtime)

    forecast_main(["-p", "macro", "--db", db, "forecast", "status", "--json"])
    output = capsys.readouterr().out

    assert profiles == ["macro"]
    assert '"slug": "superforecasting-agent"' in output


def test_superforecasting_agent_no_arg_entrypoint_honors_tui_env(monkeypatch):
    calls = []

    def fake_inherited_runtime(argv):
        calls.append(argv)

    def fail_forecast_main(argv, prog=None):
        raise AssertionError(f"unexpected forecast CLI dispatch: {argv} {prog}")

    monkeypatch.setenv("FORECAST_TUI", "1")
    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fake_inherited_runtime)
    monkeypatch.setattr(forecast_cli, "forecast_main", fail_forecast_main)

    forecast_cli.main([])

    assert calls == [["desk"]]


def test_superforecasting_agent_profiled_no_arg_entrypoint_honors_tui_env(
    monkeypatch,
):
    calls = []

    def fake_inherited_runtime(argv):
        calls.append(argv)

    def fail_forecast_main(argv, prog=None):
        raise AssertionError(f"unexpected forecast CLI dispatch: {argv} {prog}")

    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI", "true")
    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fake_inherited_runtime)
    monkeypatch.setattr(forecast_cli, "forecast_main", fail_forecast_main)

    forecast_cli.main(["--profile", "macro"])

    assert calls == [["--profile", "macro", "desk"]]


def test_superforecasting_agent_no_arg_entrypoint_ignores_false_tui_env(
    monkeypatch,
):
    calls = []

    def fake_forecast_main(argv, prog=None):
        calls.append((argv, prog))

    def fail_inherited_runtime(argv):
        raise AssertionError(f"unexpected inherited runtime dispatch: {argv}")

    monkeypatch.setenv("FORECAST_TUI", "0")
    monkeypatch.setattr(forecast_cli, "forecast_main", fake_forecast_main)
    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fail_inherited_runtime)

    forecast_cli.main([])

    assert calls == [([], "superforecasting-agent")]


def test_superforecasting_agent_tui_shorthand_routes_to_tui_flag(monkeypatch):
    calls = []

    def fake_inherited_runtime(argv):
        calls.append(argv)

    def fail_forecast_main(argv, prog=None):
        raise AssertionError(f"unexpected forecast CLI dispatch: {argv} {prog}")

    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fake_inherited_runtime)
    monkeypatch.setattr(forecast_cli, "forecast_main", fail_forecast_main)

    forecast_cli.main(["tui", "--continue"])

    assert calls == [["--tui", "--continue"]]


def test_superforecasting_agent_profiled_tui_shorthand_preserves_profile(
    monkeypatch,
):
    calls = []

    def fake_inherited_runtime(argv):
        calls.append(argv)

    def fail_forecast_main(argv, prog=None):
        raise AssertionError(f"unexpected forecast CLI dispatch: {argv} {prog}")

    monkeypatch.setattr(forecast_cli, "_run_inherited_runtime", fake_inherited_runtime)
    monkeypatch.setattr(forecast_cli, "forecast_main", fail_forecast_main)

    forecast_cli.main(["--profile", "macro", "tui", "--resume", "macro desk"])

    assert calls == [["--profile", "macro", "--tui", "--resume", "macro desk"]]


def test_superforecasting_agent_cli_entrypoint_delegates_runtime_commands(monkeypatch):
    calls = []
    fake_main_module = ModuleType("superforecasting_agent.runtime.main")

    def fake_main():
        calls.append(sys.argv[:])

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "superforecasting_agent.runtime.main", fake_main_module)

    forecast_cli.main(["dashboard", "--no-open"])

    assert calls == [["superforecasting-agent", "dashboard", "--no-open"]]


@pytest.mark.parametrize("runtime_command", ["desk", "chat"])
def test_runtime_command_missing_optional_dependency_gets_forecast_native_guidance(
    capsys,
    monkeypatch,
    runtime_command,
):
    def fail_import(name, *args, **kwargs):
        if name == "superforecasting_agent.runtime.main":
            raise ModuleNotFoundError("No module named 'dotenv'", name="dotenv")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    with pytest.raises(SystemExit) as exc:
        forecast_cli.main([runtime_command, "--help"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "optional CLI runtime dependencies" in captured.err
    assert "Use `forecast ...` or `superforecasting-agent status`" in captured.err
    assert 'uv pip install -e ".[all,dev]"' in captured.err
    assert "Traceback" not in captured.err


def test_late_runtime_command_missing_optional_dependency_gets_forecast_native_guidance(
    capsys,
    monkeypatch,
):
    fake_main_module = ModuleType("superforecasting_agent.runtime.main")

    def fake_main():
        raise ModuleNotFoundError("No module named 'rich'", name="rich")

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "superforecasting_agent.runtime.main", fake_main_module)

    with pytest.raises(SystemExit) as exc:
        forecast_cli.main(["dashboard", "--no-open"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "optional CLI runtime dependencies" in captured.err
    assert "Use `forecast ...` or `superforecasting-agent status`" in captured.err
    assert 'uv pip install -e ".[all,dev]"' in captured.err
    assert "Traceback" not in captured.err
