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


def test_superforecasting_agent_cli_entrypoint_delegates_runtime_commands(monkeypatch):
    calls = []
    fake_main_module = ModuleType("hermes_cli.main")

    def fake_main():
        calls.append(sys.argv[:])

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "hermes_cli.main", fake_main_module)

    forecast_cli.main(["dashboard", "--no-open"])

    assert calls == [["superforecasting-agent", "dashboard", "--no-open"]]
