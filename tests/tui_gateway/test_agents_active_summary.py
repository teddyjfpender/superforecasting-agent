"""Tests for the ``agents.active.summary`` gateway RPC.

The operator wanted a glanceable "N agents running · …" heuristic in the TUI
status bar. Since Arc B the RPC is ONE cheap aggregate over the ONE detached-job
store (reforecast/task/quorum records in a single scan) plus the in-memory process
registry (proc_ batches — the one non-jobs source). These tests seed real
legacy-shaped job files (which the store's read-shim surfaces through the generic
scan) + stub the process registry (mirroring tests/forecasting/test_reforecast_jobs.py's
RPC pattern, including the ``_ok`` envelope: ``resp["result"]``) and assert the
aggregate count, the per-kind breakdown, the newest-item headline label,
quiet-at-rest, and the fail-safe when the store read errors.
"""

from __future__ import annotations

import pytest

from forecasting.jobs.types import quorum as qr
from forecasting.jobs.types import reforecast as rf


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


def test_dead_proc_reported_running_is_not_counted(home, monkeypatch):
    """Reproduces the stuck-chip bug (server layer 3): a session can linger in the
    process registry's _running set with a DEAD child — the reader thread only flips
    ``exited`` on stdout EOF, so an orphaned-pipe hang (issue #17327) leaves it
    "running" forever, and ``list_sessions()`` (unlike ``poll()``) never reconciles.
    A finished chat-spawned agent would keep the chip lit. The summary now gates proc
    counting on real host-pid liveness: a "running" proc whose pid is dead is NOT
    counted, a live pid IS, and a proc with no pid (env/sandbox-backed, unprovable)
    still counts."""
    import os

    from tui_gateway import server

    _stub_registry(
        monkeypatch,
        [
            # pid 999999999 is (virtually) certainly dead → excluded despite "running".
            {"session_id": "dead", "command": "agent run", "status": "running", "uptime_seconds": 30, "pid": 999999999},
            # our own pid is alive → counted.
            {"session_id": "live", "command": "agent run 2", "status": "running", "uptime_seconds": 5, "pid": os.getpid()},
            # no pid (env-backed) → can't be proven dead → still counted.
            {"session_id": "nopid", "command": "env task", "status": "running", "uptime_seconds": 3},
        ],
    )

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    # live + nopid = 2 procs; the dead one is gated out.
    assert result["kinds"]["procs"] == 2
    assert result["count"] == 2


def test_failsafe_when_the_store_errors(home, monkeypatch):
    """The job-store read raising must contribute 0 and NEVER break the RPC — the
    process-registry source still counts (each source is guarded independently)."""
    from tui_gateway import server

    _stub_registry(monkeypatch, [{"session_id": "p", "command": "run", "status": "running", "uptime_seconds": 5}])

    # Break the ONE job store: active() raises.
    from forecasting.jobs.store import JobStore

    def _boom(*a, **k):
        raise RuntimeError("job store exploded")

    monkeypatch.setattr(JobStore, "active", _boom)

    resp = server.handle_request({"id": "1", "method": "agents.active.summary", "params": {}})
    result = resp["result"]

    # No error surfaced; the working source (1 proc) still counts.
    assert "error" not in resp
    assert result["count"] == 1
    assert result["kinds"] == {"procs": 1, "reforecast": 0, "quorum": 0}
