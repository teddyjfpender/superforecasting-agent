"""Background job runner for quorum forecasts.

A quorum dispatches several models (each researching with web search) plus a
judge synthesis pass — minutes of wall-clock, far past the TUI's 45s slash
timeout. So a quorum runs as a **detached background job**: the CLI enqueues
it (returning a run-id immediately) and a separate process executes it,
streaming progress to a per-run JSON file under the agent home. ``forecast
quorum status <run-id>`` reads that file.

A detached child process (not a thread) is used deliberately: a one-shot
``forecast quorum <id>`` CLI invocation exits as soon as it has the run-id, so
a thread would be killed; a child with ``start_new_session=True`` survives.
The persistent TUI slash-worker subprocess works the same way.

State machine: ``queued`` → ``running`` → ``done`` | ``error``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def jobs_dir() -> Path:
    path = get_hermes_home() / "quorum_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(run_id: str) -> Path:
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise ValueError(f"invalid quorum run id: {run_id!r}")
    return jobs_dir() / f"{run_id}.json"


def write_job(job: dict[str, Any]) -> None:
    """Atomically persist a job record."""

    job["updated_at"] = _now_iso()
    path = _job_path(job["run_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_job(run_id: str) -> dict[str, Any]:
    path = _job_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"no quorum run '{run_id}' (looked in {jobs_dir()})")
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in jobs_dir().glob("qr_*.json"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]


def new_run_id() -> str:
    return f"qr_{uuid.uuid4().hex[:12]}"


def start_job(spec: dict[str, Any], *, wait: bool = False) -> str:
    """Create a queued job and execute it (inline if ``wait`` else detached).

    ``spec`` keys: ``question_id`` (required), ``db``, ``preset``, ``models``,
    ``judge``, ``pool_method``, ``trim``, ``self_fusion``, ``samples``,
    ``triggered_by``, ``attach_snapshot``, ``active_model``.
    """

    run_id = new_run_id()
    job = {
        "run_id": run_id,
        "question_id": spec.get("question_id"),
        "status": "queued",
        "created_at": _now_iso(),
        "spec": spec,
        "progress": [],
        "result": None,
        "panel_run_id": None,
        "error": None,
    }
    write_job(job)

    if wait:
        execute_job(run_id)
        return run_id

    env = dict(os.environ)
    # Propagate the agent-home override so the child writes to the same place.
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "forecasting.quorum_jobs", run_id],
        cwd=str(_repo_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
        **popen_kwargs,
    )
    return run_id


def _append_progress(job: dict[str, Any], stage: str, detail: str) -> None:
    job["progress"].append({"stage": stage, "detail": detail, "at": _now_iso()})
    write_job(job)


def execute_job(run_id: str) -> dict[str, Any]:
    """Run the quorum for ``run_id`` to completion, persisting state as it goes."""

    from forecasting.ledger import ForecastLedger
    from forecasting.protocol import build_context_packet
    from forecasting.quorum import (
        DEFAULT_JUDGE_MODEL,
        make_aiagent_runner,
        resolve_models,
        run_quorum,
    )

    job = read_job(run_id)
    spec = job.get("spec") or {}
    job["status"] = "running"
    _append_progress(job, "start", "resolving question and panel")

    try:
        ledger = ForecastLedger(spec.get("db"))
        question = ledger.get_question(spec["question_id"])
        snapshot = ledger.get_current_snapshot(question.id)
        context = build_context_packet(ledger, question, snapshot)
        evidence_cutoff = getattr(snapshot, "as_of", None) if snapshot else None

        models, preset_judge = resolve_models(
            spec.get("preset"),
            spec.get("models") or None,
            active_model=spec.get("active_model"),
        )
        # The judge synthesis is the core of a quorum (a model paired with
        # itself still gains from it), so it always runs: explicit judge →
        # preset judge → global default.
        judge_model = spec.get("judge") or preset_judge or DEFAULT_JUDGE_MODEL
        self_fusion = bool(spec.get("self_fusion")) or spec.get("preset") == "self"

        runner = make_aiagent_runner(
            max_iterations=int(spec.get("max_iterations", 30)),
            timeout=spec.get("model_timeout"),
        )

        # Panelists run concurrently, so the progress callback fires from worker
        # threads — serialise the append + file write.
        import threading

        progress_lock = threading.Lock()

        def on_progress(stage: str, detail: str) -> None:
            with progress_lock:
                _append_progress(job, stage, detail)

        result = run_quorum(
            question_title=question.title,
            resolution_criteria=question.resolution_criteria,
            context_packet=context,
            models=models,
            runner=runner,
            question_id=question.id,
            evidence_cutoff=evidence_cutoff,
            judge_model=judge_model,
            pool_method=spec.get("pool_method", "trimmed_geomean_odds"),
            trim=int(spec.get("trim", 1)),
            self_fusion=self_fusion,
            on_progress=on_progress,
        )

        # Persist the quorum as a sibling panel run. The spread_summary already
        # carries the disagreement scalar (see panel.aggregate_panel_estimates).
        _append_progress(job, "record", "recording quorum panel run")
        panel_run = ledger.record_panel_run(
            question_id=question.id,
            estimates=result.panel_estimates(),
            aggregation_method=result.pool_method,
            trim=result.trim,
            snapshot_id=spec.get("attach_snapshot"),
            triggered_by=spec.get("triggered_by") or "quorum",
            judge=result.judge.to_dict() if result.judge else None,
        )
        job["panel_run_id"] = panel_run["id"]
        job["result"] = result.to_dict()
        job["status"] = "done"
        write_job(job)
    except Exception as exc:  # noqa: BLE001 — a background worker must record, not crash
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        write_job(job)
    return job


if __name__ == "__main__":  # detached worker entrypoint
    if len(sys.argv) != 2:
        print("usage: python -m forecasting.quorum_jobs <run_id>", file=sys.stderr)
        raise SystemExit(2)
    execute_job(sys.argv[1])
