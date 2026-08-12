"""Config resolver, state file, and report parser for the gateway due-sweeper.

These are the cron_runner-level primitives the gateway thread and `forecast
doctor` share so both agree on the sweeper's cadence, last result, and counts.
"""

from __future__ import annotations

import forecasting.cron_runner as cr


def test_resolve_interval_precedence(monkeypatch):
    # Explicit arg wins.
    assert cr.resolve_review_sweep_interval_minutes(5) == 5
    # 0 is honored as "disabled", not treated as unset.
    assert cr.resolve_review_sweep_interval_minutes(0) == 0
    # Negative / unparseable explicit falls through to config/default.
    monkeypatch.setattr(cr, "_reviews_config", lambda: {})
    assert cr.resolve_review_sweep_interval_minutes(-3) == cr._REVIEW_SWEEP_INTERVAL_DEFAULT
    assert cr.resolve_review_sweep_interval_minutes("bad") == cr._REVIEW_SWEEP_INTERVAL_DEFAULT


def test_resolve_interval_reads_config(monkeypatch):
    monkeypatch.setattr(cr, "_reviews_config", lambda: {"sweep_interval_minutes": 3})
    assert cr.resolve_review_sweep_interval_minutes() == 3
    monkeypatch.setattr(cr, "_reviews_config", lambda: {"sweep_interval_minutes": 0})
    assert cr.resolve_review_sweep_interval_minutes() == 0
    # Garbage in config → default.
    monkeypatch.setattr(cr, "_reviews_config", lambda: {"sweep_interval_minutes": "x"})
    assert cr.resolve_review_sweep_interval_minutes() == cr._REVIEW_SWEEP_INTERVAL_DEFAULT


def test_default_interval_is_ten(monkeypatch):
    monkeypatch.setattr(cr, "_reviews_config", lambda: {})
    assert cr.resolve_review_sweep_interval_minutes() == 10


def test_parse_review_sweep_report():
    report = (
        "Forecast self-check alerts\n"
        "scheduled_reviews: 2\n"
        "alerts: 3\n\n"
        "Deterministic refresh\n"
        "proposals: 4  no_change/skipped: 1  errors: 0\n"
    )
    assert cr.parse_review_sweep_report(report) == {"proposals": 4, "alerts": 3}
    # Fail-open: a quiet sweep (no sections) → zeros.
    assert cr.parse_review_sweep_report("nothing here") == {"proposals": 0, "alerts": 0}
    assert cr.parse_review_sweep_report(None) == {"proposals": 0, "alerts": 0}


def test_state_roundtrip(tmp_path):
    path = tmp_path / "review_sweeper_state.json"
    # Missing file → {}.
    assert cr.read_review_sweeper_state(path) == {}
    payload = {"ran": True, "due_count": 2, "refreshed": 1, "alerts": 0}
    cr.write_review_sweeper_state(payload, path)
    assert cr.read_review_sweeper_state(path) == payload


def test_state_path_uses_hermes_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    path = cr._review_sweeper_state_path()
    assert path.name == "review_sweeper_state.json"
    assert "cron" in path.parts
