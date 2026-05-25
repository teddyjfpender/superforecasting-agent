import os
import subprocess
from pathlib import Path

import superforecasting_agent.cli as fork_cli


def test_fork_native_cli_defaults_to_superforecasting_home(tmp_path, monkeypatch):
    legacy_home = tmp_path / ".hermes"
    legacy_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SUPERFORECASTING_AGENT_HOME", raising=False)
    monkeypatch.delenv("FORECAST_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)

    fork_cli._apply_profile(None)

    assert os.environ["HERMES_HOME"] == str(tmp_path / ".superforecasting-agent")


def test_fork_native_cli_respects_forecast_home_alias(tmp_path, monkeypatch):
    forecast_home = tmp_path / "forecast-home"
    monkeypatch.delenv("SUPERFORECASTING_AGENT_HOME", raising=False)
    monkeypatch.setenv("FORECAST_HOME", str(forecast_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    fork_cli._apply_profile(None)

    assert os.environ["HERMES_HOME"] == str(forecast_home)


def test_fork_native_main_sets_native_home_before_forecast_dispatch(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SUPERFORECASTING_AGENT_HOME", raising=False)
    monkeypatch.delenv("FORECAST_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(fork_cli, "forecast_main", lambda argv, prog: seen.update(argv=argv, prog=prog))

    fork_cli.main(["status"])

    assert seen == {"argv": ["status"], "prog": "superforecasting-agent"}
    assert os.environ["HERMES_HOME"] == str(tmp_path / ".superforecasting-agent")


def test_source_tree_superforecasting_launcher_renders_forecast_help():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "superforecasting-agent"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: superforecasting-agent" in result.stdout
    assert "Superforecasting Agent: create, update, review" in result.stdout
