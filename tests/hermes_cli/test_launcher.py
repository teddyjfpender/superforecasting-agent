"""Tests for the top-level `./hermes` launcher script."""

import runpy
import sys
import types
from pathlib import Path

import pytest


def test_launcher_delegates_to_argparse_entrypoint(monkeypatch):
    """`./hermes` should use `hermes_cli.main`, not the legacy Fire wrapper."""
    launcher_path = Path(__file__).resolve().parents[2] / "hermes"
    called = []

    fake_main_module = types.ModuleType("hermes_cli.main")

    def fake_main():
        called.append("hermes_cli.main")

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "hermes_cli.main", fake_main_module)

    fake_cli_module = types.ModuleType("cli")

    def legacy_cli_main(*args, **kwargs):
        raise AssertionError("launcher should not import cli.main")

    fake_cli_module.main = legacy_cli_main
    monkeypatch.setitem(sys.modules, "cli", fake_cli_module)

    fake_fire_module = types.ModuleType("fire")

    def legacy_fire(*args, **kwargs):
        raise AssertionError("launcher should not invoke fire.Fire")

    fake_fire_module.Fire = legacy_fire
    monkeypatch.setitem(sys.modules, "fire", fake_fire_module)

    monkeypatch.setattr(sys, "argv", [str(launcher_path), "gateway", "status"])

    runpy.run_path(str(launcher_path), run_name="__main__")

    assert called == ["hermes_cli.main"]


def test_launcher_missing_runtime_dependency_points_to_forecast_desk(monkeypatch, capsys):
    launcher_path = Path(__file__).resolve().parents[2] / "hermes"
    original_import = __import__

    def fail_import(name, *args, **kwargs):
        if name == "hermes_cli.main":
            raise ModuleNotFoundError("No module named 'dotenv'", name="dotenv")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_import)
    monkeypatch.setattr(sys, "argv", [str(launcher_path), "chat", "--help"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(launcher_path), run_name="__main__")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    # Since 52b980048 `./hermes` routes through superforecasting_agent.cli,
    # which emits the fork-native compatibility-alias warning and the
    # missing-runtime-dependency guidance.
    assert "`hermes` is a compatibility alias" in captured.err
    assert "needs optional CLI runtime" in captured.err
    assert "forecast desk" in captured.err
    assert 'uv pip install -e ".[all,dev]"' in captured.err
    assert "Traceback" not in captured.err


def test_launcher_late_missing_runtime_dependency_points_to_forecast_desk(
    monkeypatch,
    capsys,
):
    launcher_path = Path(__file__).resolve().parents[2] / "hermes"
    fake_main_module = types.ModuleType("hermes_cli.main")

    def fake_main():
        raise ModuleNotFoundError("No module named 'rich'", name="rich")

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "hermes_cli.main", fake_main_module)
    monkeypatch.setattr(sys, "argv", [str(launcher_path), "dashboard", "--no-open"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(launcher_path), run_name="__main__")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    # Same fork-native guidance for late import failures inside hermes_cli.main.
    assert "needs optional CLI runtime" in captured.err
    assert "forecast desk" in captured.err
    assert 'uv pip install -e ".[all,dev]"' in captured.err
    assert "Traceback" not in captured.err
