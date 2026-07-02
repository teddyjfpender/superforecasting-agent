"""Tests for the Desk "mass LLM re-run" background job runner + its gateway RPCs.

The operator multi-selects Desk questions and wants the FULL formal forecast flow
per question, detached, with a pollable status contract. The LLM stages can't run
in a test, so we stub ``forecasting.cli._run_update_agent`` (the module-level seam
``run_forecast_chain`` drives every stage through) exactly as
``tests/forecasting/test_full_forecast_chain.py`` does, and assert the wiring:
the job runs the chain per question sequentially, records honest per-question
results, isolates a single failing question, and validates/caps the batch.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import forecasting.cli as cli
from forecasting import reforecast_jobs as rf
from forecasting import quorum_jobs
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    # get_hermes_home() checks SUPERFORECASTING_AGENT_HOME first, then HERMES_HOME;
    # pin both so jobs_dir() AND the default ForecastLedger() land in the tempdir.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    return tmp_path


def _stage_side_effects(ledger, qid, stage):
    """The artifacts each pipeline stage would land, so the pipeline gate unlocks.
    Mirrors tests/forecasting/test_full_forecast_chain.py so the research-adequacy
    audit passes on the first pass (no extra research round)."""
    if stage == "research":
        from datetime import datetime, timezone

        fresh = datetime.now(timezone.utc).isoformat()
        ledger.add_evidence(question_id=qid, source_or_note="BLS prior prints", source_name="bls", available_at=fresh, stance="supports")
        ledger.add_evidence(question_id=qid, source_or_note="skeptic take", source_name="analyst-b", available_at=fresh, stance="opposes")
        ledger.add_evidence(question_id=qid, source_or_note="market read", source_name="market-c", available_at=fresh, stance="context")
    elif stage == "base_rate":
        ledger.add_reference_class(question_id=qid, name="recent CPI prints", inclusion_criteria="last 12 prints", base_rate=0.4)
    elif stage == "update":
        ledger.create_snapshot(question_id=qid, probability_or_distribution=0.42, rationale="committed forecast", require_panel=False)


def _make_question(ledger, n=1, **over):
    defaults = dict(
        title=f"Will CPI YoY be below 3.0% for the release #{n}?",
        resolution_criteria=f"Resolves yes if BLS CPI-U YoY for release #{n} is below 3.0%; otherwise no.",
    )
    defaults.update(over)
    return ledger.create_question(**defaults)


def _commit_agent(monkeypatch, seen=None):
    def fake_agent(led, qid, *, stage="update", **kw):
        if seen is not None:
            seen.append((qid, stage))
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} done"}

    monkeypatch.setattr(cli, "_run_update_agent", fake_agent)


# ── job lifecycle ─────────────────────────────────────────────────────────────


def test_start_job_runs_full_chain_per_question_and_records_honest_results(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    q2 = _make_question(ledger, 2)
    _commit_agent(monkeypatch)

    run_id = rf.start_job(
        {"question_ids": [q1.id, q2.id], "db": db, "triggered_by": "desk_mass_agent"},
        wait=True,
    )
    assert run_id.startswith("rf_")
    job = rf.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    assert job["total"] == 2
    assert job["done_count"] == 2
    assert job["current"] is None  # cleared when finished
    assert job["spec"]["triggered_by"] == "desk_mass_agent"

    by_qid = {r["question_id"]: r for r in job["results"]}
    assert set(by_qid) == {q1.id, q2.id}
    for r in by_qid.values():
        assert r["committed"] is True
        assert r["forecast_id"]
        assert [s["stage"] for s in r["stages"]] == ["research", "base_rate", "update"]
        assert r["error"] is None
        assert r["quorum_autorun"] is None  # no quorum config -> none auto-started
        assert "saturation" in r  # field present (may be None for a raw commit)


def test_running_progress_is_streamed_per_question(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    observations: list[tuple[str, object]] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        # Mid-run the persisted job must read as running with a current question.
        live = rf.list_jobs()[0]
        observations.append((live["status"], live.get("current")))
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} done"}

    monkeypatch.setattr(cli, "_run_update_agent", fake_agent)
    rf.start_job({"question_ids": [q1.id], "db": db}, wait=True)

    assert observations, "the agent must have run"
    assert all(status == "running" for status, _ in observations)
    assert any(cur and cur.get("question_id") == q1.id for _, cur in observations)


def test_per_question_failure_isolation(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    good = _make_question(ledger, 1)
    _commit_agent(monkeypatch)

    # A bogus id (never validated because we call start_job directly) must error in
    # isolation while the good question still commits, and the job still completes.
    run_id = rf.start_job({"question_ids": ["fq_does_not_exist", good.id], "db": db}, wait=True)
    job = rf.read_job(run_id)

    assert job["status"] == "done"
    assert job["done_count"] == 2
    by_qid = {r["question_id"]: r for r in job["results"]}
    assert by_qid["fq_does_not_exist"]["error"] is not None
    assert by_qid["fq_does_not_exist"]["committed"] is False
    assert by_qid[good.id]["committed"] is True


def test_chain_level_stage_failure_does_not_abort_batch(home, tmp_path, monkeypatch):
    """A stage that RAISES is captured by run_forecast_chain (fail-open); the
    question is recorded uncommitted and the batch continues."""
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    q2 = _make_question(ledger, 2)

    def fake_agent(led, qid, *, stage="update", **kw):
        if qid == q1.id:
            raise RuntimeError("model provider 503")  # every stage raises for q1
        _stage_side_effects(led, qid, stage)
        return {"final_response": "ok"}

    monkeypatch.setattr(cli, "_run_update_agent", fake_agent)
    run_id = rf.start_job({"question_ids": [q1.id, q2.id], "db": db}, wait=True)
    job = rf.read_job(run_id)

    assert job["status"] == "done"
    by_qid = {r["question_id"]: r for r in job["results"]}
    # q1 never committed but the chain did not raise out of the batch
    assert by_qid[q1.id]["committed"] is False
    assert by_qid[q1.id]["error"] is None
    assert by_qid[q2.id]["committed"] is True


def test_quorum_autorun_is_surfaced_honestly(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    _commit_agent(monkeypatch)

    # Simulate a detached quorum starting DURING the chain: the first (pre-chain)
    # scan sees no live quorum, later (post-chain) scans see a new one for the qid.
    calls = {"n": 0}

    def fake_active(limit=40):
        calls["n"] += 1
        if calls["n"] <= 1:
            return {}
        return {q1.id: {"run_id": "qr_new123", "status": "queued", "created_at": "t0"}}

    monkeypatch.setattr(quorum_jobs, "active_jobs_by_question", fake_active)
    run_id = rf.start_job({"question_ids": [q1.id], "db": db}, wait=True)
    job = rf.read_job(run_id)

    qa = job["results"][0]["quorum_autorun"]
    assert qa is not None
    assert qa["run_id"] == "qr_new123"
    assert qa["status"] == "queued"


# ── validation + batch cap ────────────────────────────────────────────────────


def test_validate_reforecast_ids(home, tmp_path):
    ledger = ForecastLedger(str(tmp_path / "forecasts.db"))
    a = _make_question(ledger, 1)
    b = _make_question(ledger, 2)
    resolved = _make_question(ledger, 3)
    with ledger._connect() as conn:  # flip to a non-active status
        conn.execute("UPDATE forecast_questions SET status='resolved' WHERE id=?", (resolved.id,))

    # dedupe + accept active ids in order
    accepted, errors = rf.validate_reforecast_ids(ledger, [a.id, a.id, b.id])
    assert accepted == [a.id, b.id]
    assert errors == []

    # unknown id
    accepted, errors = rf.validate_reforecast_ids(ledger, [a.id, "fq_nope"])
    assert accepted == [a.id]
    assert any("no such question" in e for e in errors)

    # inactive id
    accepted, errors = rf.validate_reforecast_ids(ledger, [resolved.id])
    assert accepted == [resolved.id] or accepted == []  # accepted list irrelevant; refusal is present
    assert any("not active" in e for e in errors)

    # batch cap clears the whole selection (over-cap can never start)
    accepted, errors = rf.validate_reforecast_ids(ledger, [a.id, b.id, _make_question(ledger, 4).id], max_batch=2)
    assert accepted == []
    assert any("exceeds the reforecast cap of 2" in e for e in errors)


# ── gateway RPCs ──────────────────────────────────────────────────────────────


def test_reforecast_start_rpc_enqueues(home, tmp_path, monkeypatch):
    from tui_gateway import server

    ledger = ForecastLedger()  # default home db — the same the RPC handler opens
    q1 = _make_question(ledger, 1)
    q2 = _make_question(ledger, 2)

    captured = {}

    def fake_start(spec, *, wait=False):
        captured["spec"] = spec
        captured["wait"] = wait
        return "rf_fake0001"

    monkeypatch.setattr(rf, "start_job", fake_start)
    resp = server.handle_request({
        "id": "1", "method": "forecast.reforecast.start",
        "params": {"question_ids": [q1.id, q2.id], "model": "openai/gpt-5.5"},
    })
    result = resp["result"]
    assert result["run_id"] == "rf_fake0001"
    assert result["total"] == 2
    assert "poll forecast.reforecast.status" in result["note"]
    assert captured["wait"] is False
    assert captured["spec"]["question_ids"] == [q1.id, q2.id]
    assert captured["spec"]["triggered_by"] == "desk_mass_agent"
    assert captured["spec"]["model"] == "openai/gpt-5.5"


def test_reforecast_start_rpc_refuses_unknown_id(home, monkeypatch):
    from tui_gateway import server

    ForecastLedger()  # ensure the schema exists
    called = {"n": 0}
    monkeypatch.setattr(rf, "start_job", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "rf_x")

    resp = server.handle_request({
        "id": "1", "method": "forecast.reforecast.start",
        "params": {"question_ids": ["fq_nope"]},
    })
    assert "error" in resp
    assert "no such question" in resp["error"]["message"]
    assert called["n"] == 0  # refused before any job was enqueued


def test_reforecast_start_rpc_requires_ids(home):
    from tui_gateway import server

    resp = server.handle_request({
        "id": "1", "method": "forecast.reforecast.start", "params": {"question_ids": []},
    })
    assert "error" in resp
    assert "non-empty question_ids" in resp["error"]["message"]


def test_reforecast_status_rpc_roundtrip(home):
    from tui_gateway import server

    job = {
        "run_id": "rf_statustest1",
        "status": "done",
        "created_at": rf._now_iso(),
        "spec": {"question_ids": ["q1", "q2"]},
        "total": 2,
        "done_count": 2,
        "current": None,
        "results": [
            {"question_id": "q1", "committed": True, "forecast_id": "fc1", "quorum_autorun": {"run_id": "qr_1"}},
            {"question_id": "q2", "committed": False, "quorum_autorun": None},
        ],
        "error": None,
    }
    rf.write_job(job)

    resp = server.handle_request({
        "id": "1", "method": "forecast.reforecast.status", "params": {"run_id": "rf_statustest1"},
    })
    result = resp["result"]
    assert result["status"] == "done"
    assert result["done_count"] == 2
    assert result["total"] == 2
    assert result["quorums_started"] == 1
    assert len(result["results"]) == 2


def test_reforecast_status_rpc_unknown_run(home):
    from tui_gateway import server

    resp = server.handle_request({
        "id": "1", "method": "forecast.reforecast.status", "params": {"run_id": "rf_missing"},
    })
    assert "error" in resp
    assert "no reforecast run" in resp["error"]["message"]


# ── desk-chip helper ──────────────────────────────────────────────────────────


def test_active_jobs_by_question_maps_every_member(home):
    rf.write_job({
        "run_id": "rf_live0001",
        "status": "running",
        "created_at": rf._now_iso(),
        "spec": {"question_ids": ["qa", "qb"]},
        "total": 2, "done_count": 0, "current": None, "results": [], "error": None,
    })
    rf.write_job({
        "run_id": "rf_done0001",
        "status": "done",
        "created_at": rf._now_iso(),
        "spec": {"question_ids": ["qc"]},
        "total": 1, "done_count": 1, "current": None, "results": [], "error": None,
    })

    mapping = rf.active_jobs_by_question()
    assert set(mapping) == {"qa", "qb"}  # only the LIVE job's members are chipped
    assert mapping["qa"]["run_id"] == "rf_live0001"
    assert mapping["qa"]["status"] == "running"
    assert "qc" not in mapping  # terminal job never chipped


# ── detached-worker entrypoint ────────────────────────────────────────────────


def test_python_m_entrypoint_parses():
    proc = subprocess.run(
        [sys.executable, "-m", "forecasting.reforecast_jobs"],
        capture_output=True, text=True, cwd=str(rf._repo_root()),
    )
    assert proc.returncode == 2
    assert "usage: python -m forecasting.reforecast_jobs" in proc.stderr
