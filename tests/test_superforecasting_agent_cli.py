import os
import subprocess
import sys
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


def test_config_set_routes_to_inherited_runtime(monkeypatch):
    seen = {}
    monkeypatch.setattr(fork_cli, "_run_inherited_runtime", lambda argv: seen.update(argv=argv))

    fork_cli.main(["config", "set", "model.default", "example/model"])

    assert seen == {"argv": ["config", "set", "model.default", "example/model"]}


def test_config_doctor_remains_a_forecast_shorthand(monkeypatch):
    seen = {}
    monkeypatch.setattr(fork_cli, "forecast_main", lambda argv, prog: seen.update(argv=argv, prog=prog))

    fork_cli.main(["config", "doctor"])

    assert seen == {"argv": ["config", "doctor"], "prog": "superforecasting-agent"}


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


def test_version_fast_path_skips_heavy_imports():
    """`superforecasting-agent --version` short-circuits in the entry shim:
    it must print version info without importing forecasting.cli (parser
    build) or hermes_cli.main (inherited runtime)."""
    root = Path(__file__).resolve().parents[1]
    probe = (
        "import sys\n"
        "from superforecasting_agent.cli import main\n"
        "main(['--version'])\n"
        "assert 'forecasting.cli' not in sys.modules, 'forecasting.cli imported'\n"
        "assert 'hermes_cli.main' not in sys.modules, 'hermes_cli.main imported'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Superforecasting Agent v")
    assert "Python:" in result.stdout


def test_version_short_flag_matches_long_flag(capsys):
    fork_cli.main(["-V"])
    short = capsys.readouterr().out
    fork_cli.main(["--version"])
    long = capsys.readouterr().out
    assert short.splitlines()[0].startswith("Superforecasting Agent v")
    assert short.splitlines()[0] == long.splitlines()[0]
