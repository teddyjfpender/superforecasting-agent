"""Tests for fork-native log command guidance."""

import pytest

from hermes_cli import logs


def test_list_logs_missing_directory_uses_display_home(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / ".superforecasting-agent"))

    logs.list_logs()

    out = capsys.readouterr().out
    assert "No logs directory at" in out
    assert ".superforecasting-agent/logs/" in out


def test_list_logs_empty_directory_uses_forecast_native_run_hint(monkeypatch, capsys, tmp_path):
    home = tmp_path / ".superforecasting-agent"
    (home / "logs").mkdir(parents=True)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))

    logs.list_logs()

    out = capsys.readouterr().out
    assert "superforecasting-agent" in out
    assert "superforecasting-agent chat" not in out
    assert "hermes chat" not in out


def test_tail_missing_log_uses_forecast_native_run_hint(monkeypatch, capsys, tmp_path):
    home = tmp_path / ".superforecasting-agent"
    (home / "logs").mkdir(parents=True)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))

    with pytest.raises(SystemExit):
        logs.tail_log("agent")

    out = capsys.readouterr().out
    assert "Superforecasting Agent runs" in out
    assert "superforecasting-agent" in out
    assert "superforecasting-agent chat" not in out
    assert "hermes chat" not in out
