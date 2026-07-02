"""The gateway review due-sweeper: close the gap between a review going "due" on
the Desk and something actually acting on it (historically only the nightly cron
did). Rides the cron ticker; runs the SAME deterministic sweep the nightly runs
(run_due_reviews defaults — NO agent/LLM); guards against concurrent sweeps and
against doubling the nightly cron's work; emits review.sweep events; and exposes
forecast.reviews.next for the TUI countdown.
"""

from __future__ import annotations

import forecasting.cron_runner as cr
import tui_gateway.server as server


class _FakeLedger:
    """Stands in for ForecastLedger inside _run_review_sweep / the RPC."""

    def __init__(self, due=0, soonest=None):
        self._due = due
        self._soonest = soonest

    def count_due_scheduled_reviews(self, *, now=None):
        return self._due

    def next_scheduled_review_at(self):
        return self._soonest


def _reset(monkeypatch, tmp_path, *, interval=10, due=0, nightly=None):
    """Wire the sweeper to fakes and a temp HERMES_HOME (for the state file)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    server._review_sweep_running = False
    server._review_sweep_next_tick_at = None
    monkeypatch.setattr(cr, "resolve_review_sweep_interval_minutes", lambda explicit=None: interval)
    monkeypatch.setattr("forecasting.ledger.ForecastLedger", lambda *a, **k: _FakeLedger(due=due))
    monkeypatch.setattr(server, "_nightly_self_check_job", lambda: nightly)
    events: list[dict] = []
    monkeypatch.setattr(server, "write_json", lambda obj: events.append(obj) or True)
    calls: list[bool] = []
    monkeypatch.setattr(cr, "run_due_reviews", lambda *a, **k: (calls.append(True) or "alerts: 2\ncommitted: 1\n"))
    return events, calls


def _sweep_events(events):
    return [e for e in events if (e.get("params") or {}).get("type") == "review.sweep"]


def test_runs_the_sweep_when_due_and_emits_events(monkeypatch, tmp_path):
    events, calls = _reset(monkeypatch, tmp_path, due=2)
    result = server._run_review_sweep(now="2026-07-02T12:00:00Z")

    assert result["ran"] is True
    assert result["due_count"] == 2
    assert result["refreshed"] == 1 and result["alerts"] == 2
    assert calls == [True], "the deterministic sweep must run exactly once"

    sweeps = _sweep_events(events)
    assert [(e["params"]["payload"]["phase"]) for e in sweeps] == ["started", "done"]
    assert sweeps[0]["params"]["payload"]["due_count"] == 2
    done = sweeps[1]["params"]["payload"]
    assert done["refreshed"] == 1 and done["alerts"] == 2
    assert "duration_ms" in done

    # State file recorded the run for `forecast doctor`.
    state = cr.read_review_sweeper_state()
    assert state["ran"] is True and state["due_count"] == 2


def test_skips_when_nothing_due(monkeypatch, tmp_path):
    events, calls = _reset(monkeypatch, tmp_path, due=0)
    result = server._run_review_sweep(now="2026-07-02T12:00:00Z")

    assert result["ran"] is False
    assert result["skipped_reason"] == "none_due"
    assert calls == [], "no sweep when nothing is due"
    assert _sweep_events(events) == [], "no events when nothing is due"


def test_respects_disabled_interval_zero(monkeypatch, tmp_path):
    events, calls = _reset(monkeypatch, tmp_path, interval=0, due=5)
    # _run_review_sweep short-circuits to disabled...
    result = server._run_review_sweep(now="2026-07-02T12:00:00Z")
    assert result["skipped_reason"] == "disabled"
    assert calls == []
    # ...and _maybe_run_review_sweep never even calls into it.
    assert server._maybe_run_review_sweep() is None
    assert calls == []


def test_no_concurrent_sweeps(monkeypatch, tmp_path):
    events, calls = _reset(monkeypatch, tmp_path, due=3)
    server._review_sweep_running = True  # a sweep is already in flight
    result = server._run_review_sweep(now="2026-07-02T12:00:00Z")
    assert result["skipped_reason"] == "already_running"
    assert calls == [], "must not start a second concurrent sweep"


def test_nightly_dedupe_guard(monkeypatch, tmp_path):
    # The nightly self-check cron ran 4 minutes ago; interval is 10 → within window.
    nightly = {"last_run_at": "2026-07-02T11:56:00Z", "next_run_at": "2026-07-03T08:00:00Z"}
    events, calls = _reset(monkeypatch, tmp_path, due=3, nightly=nightly)
    result = server._run_review_sweep(now="2026-07-02T12:00:00Z")
    assert result["skipped_reason"] == "nightly_recent"
    assert calls == [], "must not double the work the nightly cron just did"

    # But an OLD nightly run (well outside the window) does not block the sweep.
    old = {"last_run_at": "2026-07-02T08:00:00Z", "next_run_at": "2026-07-03T08:00:00Z"}
    monkeypatch.setattr(server, "_nightly_self_check_job", lambda: old)
    result2 = server._run_review_sweep(now="2026-07-02T12:00:00Z")
    assert result2["ran"] is True
    assert calls == [True]


def test_maybe_run_respects_cadence_gate(monkeypatch, tmp_path):
    events, calls = _reset(monkeypatch, tmp_path, due=2)
    # Not yet time: next eligible tick is in the future.
    server._review_sweep_next_tick_at = "2999-01-01T00:00:00Z"
    assert server._maybe_run_review_sweep() is None
    assert calls == []

    # Time now: a None gate runs immediately and advances the gate.
    server._review_sweep_next_tick_at = None
    result = server._maybe_run_review_sweep()
    assert result is not None and result["ran"] is True
    assert server._review_sweep_next_tick_at is not None  # advanced


def test_reviews_next_rpc_payload_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    server._review_sweep_running = False
    server._review_sweep_next_tick_at = "2026-07-02T12:10:00Z"
    monkeypatch.setattr(cr, "resolve_review_sweep_interval_minutes", lambda explicit=None: 10)
    monkeypatch.setattr(
        "forecasting.ledger.ForecastLedger",
        lambda *a, **k: _FakeLedger(due=2, soonest="2026-07-02T09:00:00Z"),
    )
    monkeypatch.setattr(
        server,
        "_nightly_self_check_job",
        lambda: {"next_run_at": "2026-07-03T08:00:00Z", "last_run_at": "2026-07-02T08:00:00Z"},
    )

    resp = server.handle_request({"id": "1", "method": "forecast.reviews.next", "params": {}})
    assert "result" in resp, resp
    res = resp["result"]
    assert res["next_due_at"] == "2026-07-02T09:00:00Z"
    assert res["due_count"] == 2
    assert res["sweeper"] == {
        "enabled": True,
        "interval_minutes": 10,
        "next_tick_at": "2026-07-02T12:10:00Z",
        "running": False,
    }
    assert res["nightly"]["installed"] is True
    assert res["nightly"]["next_run_at"] == "2026-07-03T08:00:00Z"


def test_reviews_next_rpc_reports_disabled_and_no_nightly(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    server._review_sweep_next_tick_at = None
    monkeypatch.setattr(cr, "resolve_review_sweep_interval_minutes", lambda explicit=None: 0)
    monkeypatch.setattr("forecasting.ledger.ForecastLedger", lambda *a, **k: _FakeLedger(due=0))
    monkeypatch.setattr(server, "_nightly_self_check_job", lambda: None)

    resp = server.handle_request({"id": "2", "method": "forecast.reviews.next", "params": {}})
    res = resp["result"]
    assert res["sweeper"]["enabled"] is False
    assert res["sweeper"]["interval_minutes"] == 0
    assert res["nightly"] == {"installed": False, "next_run_at": None, "last_run_at": None}
