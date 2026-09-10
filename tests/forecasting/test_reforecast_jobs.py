"""Tests for the Desk "mass LLM re-run" + task jobs — now the REFORECAST / TASK
TYPES on the one detached-job runtime (Arc B2), reached through the byte-compatible
``forecast.reforecast.*`` / ``forecast.desk.task`` aliases.

The chain that runs per question is unchanged (``forecasting.cli.run_forecast_chain``
through the gated ``_run_update_agent``); the LLM stages can't run in a test, so we
stub ``forecasting.cli._run_update_agent`` (the module-level seam every stage drives
through) exactly as ``tests/forecasting/test_full_forecast_chain.py`` does, and the
task session's ``forecasting.jobs.types.task._run_task_agent``. We assert: the type
runs the chain per question sequentially, records honest per-question results,
isolates a single failing question, validates/caps the batch, the aliases return the
current shapes, a legacy ``rf_`` file on disk still answers, and the ``forecast
rerun`` CLI verbs enqueue + poll.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import pytest

import forecasting.cli as cli
from forecasting.jobs.types import quorum as quorum_jobs
from forecasting.jobs.types import reforecast as rf
from forecasting.jobs.types import task as tk
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    # get_agent_home() checks SUPERFORECASTING_AGENT_HOME first, then HERMES_HOME;
    # pin both so the JobStore, the legacy jobs_dir() AND the default ForecastLedger()
    # land in the tempdir.
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


# ── REFORECAST type lifecycle (runtime + monkeypatched agent stages) ──────────


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
    assert run_id.startswith("job_")  # new runs live on the shared JobStore
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


# ── gateway alias parity: forecast.reforecast.* over the runtime ──────────────


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


def test_reforecast_active_rpc_lists_live_jobs_only(home):
    """The desk re-attaches to in-flight jobs on mount: .active returns only
    queued|running jobs (newest first) with their target question_ids — a
    done job is terminal and must not resurrect row indicators."""
    from tui_gateway import server

    rf.write_job({
        "run_id": "rf_liveact1", "status": "running", "created_at": rf._now_iso(),
        "spec": {"question_ids": ["q1", "q2"], "mode": "reforecast"},
        "total": 2, "done_count": 1, "current": {"question_id": "q2"}, "results": [], "error": None,
    })
    rf.write_job({
        "run_id": "rf_doneact1", "status": "done", "created_at": rf._now_iso(),
        "spec": {"question_ids": ["q9"]},
        "total": 1, "done_count": 1, "current": None, "results": [], "error": None,
    })

    resp = server.handle_request({"id": "1", "method": "forecast.reforecast.active", "params": {}})
    jobs = resp["result"]["jobs"]
    assert [j["run_id"] for j in jobs] == ["rf_liveact1"]
    assert jobs[0]["question_ids"] == ["q1", "q2"]
    assert jobs[0]["mode"] == "reforecast"
    assert jobs[0]["done_count"] == 1 and jobs[0]["total"] == 2


# ── legacy rf_ read-shim (a run in flight across the migration) ───────────────


def test_legacy_rf_file_on_disk_still_answers(home):
    """A real pre-migration rf_ job file (old shape, no job_id/type, living in the
    legacy reforecast_runs dir) must still answer status + active queries — a run in
    flight when the runtime was upgraded must not vanish."""
    from tui_gateway import server

    legacy_dir = rf.jobs_dir()  # {home}/reforecast_runs
    (legacy_dir / "rf_legacy01.json").write_text(
        json.dumps({
            "run_id": "rf_legacy01",
            "status": "running",
            "created_at": rf._now_iso(),
            "spec": {"question_ids": ["qa", "qb"], "mode": "reforecast"},
            "total": 2,
            "done_count": 1,
            "current": {"question_id": "qb", "stage": "research"},
            "results": [{"question_id": "qa", "committed": True}],
            "error": None,
        }),
        encoding="utf-8",
    )

    status = server.handle_request({
        "id": "1", "method": "forecast.reforecast.status", "params": {"run_id": "rf_legacy01"},
    })["result"]
    assert status["run_id"] == "rf_legacy01"
    assert status["status"] == "running"
    assert status["done_count"] == 1 and status["total"] == 2
    assert status["current"]["question_id"] == "qb"

    active = server.handle_request({
        "id": "2", "method": "forecast.reforecast.active", "params": {},
    })["result"]["jobs"]
    assert "rf_legacy01" in [j["run_id"] for j in active]


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


# ── TASK type (the operator's free-text fix loop) ─────────────────────────────


def _capture_task_agent(monkeypatch, response=None, raises=None):
    captured: dict = {}

    def fake(user_message, *, system_message, model, provider, max_iterations):
        captured["user_message"] = user_message
        captured["system_message"] = system_message
        captured["model"] = model
        captured["provider"] = provider
        captured["max_iterations"] = max_iterations
        if raises is not None:
            raise raises
        return response if response is not None else {"final_response": "task summary"}

    monkeypatch.setattr(tk, "_run_task_agent", fake)
    return captured


def test_task_job_runs_one_session_with_gaps_in_prompt_and_writes_progress(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    # One bare question (missing watches/components/ref-classes/triggers) + one with
    # a watch already, so the composed prompt shows differing gaps per question.
    q1 = _make_question(ledger, 1)
    q2 = _make_question(ledger, 2)
    ledger.add_watched_source(scope_type="question", scope_ref=q2.id, source="fred:X")

    captured = _capture_task_agent(monkeypatch, response={"final_response": "added 2 watched sources", "api_calls": 4, "completed": True})

    run_id = rf.start_job(
        {
            "mode": "task",
            "instruction": "Add watched sources to every question in scope.",
            "question_ids": [q1.id, q2.id],
            "db": db,
            "triggered_by": "desk_task",
        },
        wait=True,
    )
    job = rf.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    assert job["done_count"] == 2
    assert job["current"] is None
    assert job["task_summary"] == "added 2 watched sources"
    assert job["task_result"]["completed"] is True

    # Progress notes: started → working → done (staged into the job file).
    stages = [p["stage"] for p in job["progress"]]
    assert stages[0] == "start"
    assert "working" in stages
    assert stages[-1] == "done"

    # The composed session: ONE call, the forecasting system prompt, the instruction,
    # both ids, and each question's readiness GAPS (so the agent sees WHAT is missing).
    from forecasting.protocol import SYSTEM_PROMPT

    assert captured["system_message"] == SYSTEM_PROMPT.strip()
    user = captured["user_message"]
    assert "Add watched sources to every question in scope." in user
    assert q1.id in user and q2.id in user
    assert "MISSING watched sources" in user  # q1 has no watch -> the gap is surfaced
    assert "machine-readiness" in user
    assert captured["max_iterations"] == tk.DEFAULT_TASK_MAX_ITERATIONS


def test_task_job_empty_instruction_errors_before_agent(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    called = {"n": 0}
    monkeypatch.setattr(tk, "_run_task_agent", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {})

    run_id = rf.start_job(
        {"mode": "task", "instruction": "   ", "question_ids": [q1.id], "db": db},
        wait=True,
    )
    job = rf.read_job(run_id)
    assert job["status"] == "error"
    assert "instruction" in job["error"]
    assert called["n"] == 0  # never reached the agent


def test_task_job_agent_failure_is_honest(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    _capture_task_agent(monkeypatch, raises=RuntimeError("provider exploded"))

    run_id = rf.start_job(
        {"mode": "task", "instruction": "do the thing", "question_ids": [q1.id], "db": db},
        wait=True,
    )
    job = rf.read_job(run_id)
    assert job["status"] == "error"
    assert "provider exploded" in job["error"]
    assert job["progress"][-1]["stage"] == "error"


# ── forecast.desk.task alias ──────────────────────────────────────────────────


def test_desk_task_rpc_enqueues(home, tmp_path, monkeypatch):
    from tui_gateway import server

    ledger = ForecastLedger()
    q1 = _make_question(ledger, 1)
    q2 = _make_question(ledger, 2)

    captured = {}

    def fake_start(spec, *, wait=False):
        captured["spec"] = spec
        captured["wait"] = wait
        return "rf_task0001"

    monkeypatch.setattr(rf, "start_job", fake_start)
    resp = server.handle_request({
        "id": "1", "method": "forecast.desk.task",
        "params": {"instruction": "set executable triggers", "question_ids": [q1.id, q2.id]},
    })
    result = resp["result"]
    assert result["run_id"] == "rf_task0001"
    assert result["total"] == 2
    assert "poll forecast.reforecast.status" in result["note"]
    assert captured["wait"] is False
    assert captured["spec"]["mode"] == "task"
    assert captured["spec"]["instruction"] == "set executable triggers"
    assert captured["spec"]["question_ids"] == [q1.id, q2.id]
    assert captured["spec"]["triggered_by"] == "desk_task"


def test_desk_task_rpc_requires_instruction(home, monkeypatch):
    from tui_gateway import server

    ForecastLedger()
    called = {"n": 0}
    monkeypatch.setattr(rf, "start_job", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "rf_x")
    resp = server.handle_request({
        "id": "1", "method": "forecast.desk.task",
        "params": {"instruction": "  ", "question_ids": ["fq_x"]},
    })
    assert "error" in resp
    assert "instruction" in resp["error"]["message"]
    assert called["n"] == 0


def test_desk_task_rpc_requires_ids(home):
    from tui_gateway import server

    resp = server.handle_request({
        "id": "1", "method": "forecast.desk.task",
        "params": {"instruction": "do it", "question_ids": []},
    })
    assert "error" in resp
    assert "non-empty question_ids" in resp["error"]["message"]


def test_desk_task_rpc_validates_ids_via_shared_validator(home, monkeypatch):
    from tui_gateway import server

    ForecastLedger()
    called = {"n": 0}
    monkeypatch.setattr(rf, "start_job", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "rf_x")
    resp = server.handle_request({
        "id": "1", "method": "forecast.desk.task",
        "params": {"instruction": "do it", "question_ids": ["fq_nope"]},
    })
    assert "error" in resp
    assert "no such question" in resp["error"]["message"]
    assert called["n"] == 0  # refused before any job was enqueued


# ── forecast.question.readiness RPC (unchanged — still in server.py) ──────────


def test_question_readiness_rpc_roundtrip(home, tmp_path):
    from tui_gateway import server

    ledger = ForecastLedger()
    q1 = _make_question(ledger, 1, close_time="2026-12-31T00:00:00Z", impact="high")

    resp = server.handle_request({
        "id": "1", "method": "forecast.question.readiness",
        "params": {"question_id": q1.id},
    })
    result = resp["result"]
    assert result["question_id"] == q1.id
    assert result["title"] == q1.title
    assert 0 <= result["score"] <= 100
    assert result["src_count"] == 0
    keys = {g["key"] for g in result["gaps"]}
    assert {"watches", "components", "ref_classes", "triggers"} <= keys
    for gap in result["gaps"]:
        assert {"key", "label", "fix_hint"} <= set(gap)


def test_question_readiness_rpc_requires_id(home):
    from tui_gateway import server

    resp = server.handle_request({
        "id": "1", "method": "forecast.question.readiness", "params": {},
    })
    assert "error" in resp
    assert "question_id" in resp["error"]["message"]


def test_question_readiness_rpc_unknown_id(home):
    from tui_gateway import server

    ForecastLedger()
    resp = server.handle_request({
        "id": "1", "method": "forecast.question.readiness",
        "params": {"question_id": "fq_missing"},
    })
    assert "error" in resp


# ── forecast rerun CLI verbs ──────────────────────────────────────────────────


def _rerun_args(**over):
    base = dict(
        ids=[], model=None, provider=None, max_iterations=None, wait=False, json=False, db=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_cli_rerun_no_ids_prints_usage(home, capsys):
    cli._cmd_rerun(_rerun_args(ids=[]))
    out = capsys.readouterr().out
    assert "mass LLM re-run" in out
    assert "forecast rerun status" in out


def test_cli_rerun_wait_runs_chain_and_prints(home, tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    _commit_agent(monkeypatch)

    cli._cmd_rerun(_rerun_args(ids=[q1.id], wait=True, db=db))
    out = capsys.readouterr().out
    assert "reforecast run job_" in out  # new job_ id echoed
    assert "done" in out
    assert "committed" in out  # the per-question result line


def test_cli_rerun_status_lists_runs(home, tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q1 = _make_question(ledger, 1)
    _commit_agent(monkeypatch)
    cli._cmd_rerun(_rerun_args(ids=[q1.id], wait=True, db=db))
    capsys.readouterr()  # drain the run output

    cli._cmd_rerun(_rerun_args(ids=["status"], db=db))
    out = capsys.readouterr().out
    assert "Status" in out  # the table header
    assert "job_" in out  # the run listed


# ── detached-worker entrypoint (the runtime's `python -m forecasting.jobs`) ────


def test_python_m_entrypoint_parses():
    proc = subprocess.run(
        [sys.executable, "-m", "forecasting.jobs"],
        capture_output=True, text=True, cwd=str(rf._repo_root()),
    )
    assert proc.returncode == 2
    assert "usage: python -m forecasting.jobs run <job_id>" in proc.stderr
