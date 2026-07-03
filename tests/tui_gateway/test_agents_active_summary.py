"""Tests for the ``agents.active.summary`` gateway RPC.

The operator wanted a glanceable "N agents running · …" heuristic in the TUI
status bar. The RPC is ONE cheap aggregate over the three detached job stores —
background processes (proc_ batches), mass reforecast/desk-task jobs, and quorum
forecasts. These tests seed real job files + stub the in-memory process registry
(mirroring tests/forecasting/test_reforecast_jobs.py's RPC pattern, including the
``_ok`` envelope: ``resp["result"]``) and assert the aggregate count, the
per-kind breakdown, the newest-item headline label, quiet-at-rest, and the
fail-safe when a single store errors.
"""

from __future__ import annotations

import pytest

from forecasting import quorum_jobs as qr
from forecasting import reforecast_jobs as rf


@pytest.fixture
def home(tmp_path, monkeypatch):
    # get_hermes_home() checks SUPERFORECASTING_AGENT_HOME first, then HERMES_HOME;
    # pin both so the reforecast + quorum jobs_dir() land in the tempdir.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    return tmp_path


def _seed_reforecast(status="running", *, run_id="rf_live0001", created_at=None, mode="reforecast", n=2):
    rf.write_job(
        {
            "run_id": run_id,
            "status": status,
            "created_at": created_at or rf._now_iso(),
            "spec": {"question_ids": [f"q{i}" for i in range(n)], "mode": mode},
            "total": n,
            "done_count": 0,
            "current": None,
            "results": [],
            "error": None,
        }
    )


def _seed_quorum(status="running", *, run_id="qr_live0001", created_at=None, question_id="fq_senate"):
    qr.write_job(
        {
            "run_id": run_id,
            "question_id": question_id,
            "status": status,
            "created_at": created_at or qr._now_iso(),
            "spec": {"question_id": question_id},
            "progress": [],
            "result": None,
            "panel_run_id": None,
            "error": None,
        }
    )


def _stub_registry(monkeypatch, sessions):
    from tools.process_registry import process_registry

    monkeypatch.setattr(process_registry, "list_sessions", lambda *a, **k: sessions)


def test_aggregates_all_three_stores(home, monkeypatch):
    from tui_gateway import server

    _seed_reforecast(status="running", n=5)
    _seed_quorum(status="queued")
    _stub_registry(
        monkeypatch,
        [
            {"session_id": "proc_a", "command": "pytest -q", "status": "running", "uptime_seconds": 12},
            {"session_id": "proc_b", "command": "old build", "status": "exited", "uptime_seconds": 99},
        ],
    )

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    # 1 running proc (the exited one is skipped) + 1 reforecast + 1 quorum.
    assert result["count"] == 3
    assert result["kinds"] == {"procs": 1, "reforecast": 1, "quorum": 1}
    assert result["headline"].startswith("3 agents running · ")


def test_quiet_at_rest_returns_empty_headline(home, monkeypatch):
    from tui_gateway import server

    _stub_registry(monkeypatch, [])  # no live jobs anywhere

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    assert result["count"] == 0
    assert result["kinds"] == {"procs": 0, "reforecast": 0, "quorum": 0}
    assert result["headline"] == ""


def test_headline_labels_the_newest_live_item(home, monkeypatch):
    from tui_gateway import server

    # Reforecast is OLD, quorum is NEW → the headline label comes from the quorum.
    _seed_reforecast(status="running", created_at="2026-06-01T00:00:00+00:00", n=3)
    _seed_quorum(status="running", created_at="2026-07-01T00:00:00+00:00", question_id="fq_new")
    _stub_registry(monkeypatch, [])

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    assert result["count"] == 2
    assert result["headline"] == "2 agents running · quorum · fq_new"


def test_reforecast_task_mode_and_singular_plural(home, monkeypatch):
    from tui_gateway import server

    _seed_quorum(status="done")  # terminal → not counted
    _seed_reforecast(status="running", mode="task", n=1)
    _stub_registry(monkeypatch, [])

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    assert result["count"] == 1
    assert result["kinds"]["reforecast"] == 1
    # 1 agent (singular) and a singular "question", labelled "desk task".
    assert result["headline"] == "1 agent running · desk task · 1 question"


def test_terminal_jobs_are_never_counted(home, monkeypatch):
    from tui_gateway import server

    _seed_reforecast(status="done", run_id="rf_done1")
    _seed_quorum(status="error", run_id="qr_err1")
    _stub_registry(monkeypatch, [{"session_id": "p", "command": "x", "status": "exited", "uptime_seconds": 1}])

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    assert resp["result"]["count"] == 0


def test_failsafe_when_one_store_errors(home, monkeypatch):
    """A store raising must contribute 0 and NEVER break the RPC — the other
    stores still count."""
    from tui_gateway import server

    _seed_quorum(status="running")  # this store works
    _stub_registry(monkeypatch, [{"session_id": "p", "command": "run", "status": "running", "uptime_seconds": 5}])

    # Break the reforecast store: its list_jobs raises.
    def _boom(*a, **k):
        raise RuntimeError("reforecast store exploded")

    monkeypatch.setattr(rf, "list_jobs", _boom)

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    # No error surfaced; the working stores still count (1 proc + 1 quorum).
    assert "error" not in resp
    assert result["count"] == 2
    assert result["kinds"] == {"procs": 1, "reforecast": 0, "quorum": 1}
