"""Tests for the TUI gateway's background cron ticker.

The full gateway runs a cron ticker so scheduled jobs fire automatically; the
TUI gateway historically had none, so a user running only the TUI never saw
their cron jobs fire and a manual ``cronjob run`` (which only marks a job due
for "the next scheduler tick") silently never executed. These tests guard the
ticker that closes that gap.
"""
import threading
import time

import cron.scheduler as sched
import tui_gateway.server as server


def _reset_ticker():
    server._cron_ticker_stop = threading.Event()
    server._cron_ticker_thread = None


def test_disabled_via_env(monkeypatch):
    for falsey in ("0", "off", "false", "no", "OFF"):
        monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER", falsey)
        assert server._cron_ticker_disabled() is True


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER", raising=False)
    monkeypatch.delenv("FORECAST_TUI_CRON_TICKER", raising=False)
    monkeypatch.delenv("HERMES_TUI_CRON_TICKER", raising=False)
    assert server._cron_ticker_disabled() is False


def test_interval_override_and_fallback(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER_INTERVAL", "5")
    assert server._cron_ticker_interval() == 5
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER_INTERVAL", "bad")
    assert server._cron_ticker_interval() == 60
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER_INTERVAL", "-3")
    assert server._cron_ticker_interval() == 60


def test_disabled_ticker_does_not_start(monkeypatch):
    _reset_ticker()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER", "0")
    server.start_cron_ticker()
    assert server._cron_ticker_thread is None


def test_ticker_runs_tick_and_stops(monkeypatch):
    _reset_ticker()
    monkeypatch.delenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER", raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER_INTERVAL", "1")

    calls = []
    monkeypatch.setattr(
        sched, "tick", lambda verbose=True, adapters=None, loop=None: (calls.append(1) or 0)
    )

    server.start_cron_ticker()
    thread = server._cron_ticker_thread
    assert thread is not None and thread.is_alive()

    # A second start is idempotent — no new thread.
    server.start_cron_ticker()
    assert server._cron_ticker_thread is thread

    # The first tick fires immediately (catch up overdue jobs on TUI open).
    time.sleep(0.3)
    assert len(calls) >= 1

    server._stop_cron_ticker()
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_a_failing_tick_does_not_kill_the_loop(monkeypatch):
    _reset_ticker()
    monkeypatch.delenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER", raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_CRON_TICKER_INTERVAL", "1")

    calls = []

    def _boom(verbose=True, adapters=None, loop=None):
        calls.append(1)
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(sched, "tick", _boom)

    server.start_cron_ticker()
    thread = server._cron_ticker_thread
    time.sleep(0.3)
    # Thread survived the exception and is still looping.
    assert thread is not None and thread.is_alive()
    assert len(calls) >= 1

    server._stop_cron_ticker()
    thread.join(timeout=3)
