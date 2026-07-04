"""The REFORECAST job type: the operator's Desk "mass LLM re-run" on the one
detached-job runtime (Arc B2).

The operator multi-selects Desk questions and wants the FULL formal forecast flow
PER question — fresh evidence searched/imported/triaged, a VOI research-adequacy
audit, a base rate, a quorum where indicated, and a GATED LLM commit — NOT the
deterministic re-pool. That chain already exists: :func:`forecasting.cli.run_forecast_chain`
drives research → base_rate → (model) → update through the same gated
``_run_update_agent`` every manual ``forecast agent --stage S`` run uses, and the
tool commit hook applies lessons, records the saturation score, and auto-runs a
quorum on high-impact commits.

:func:`execute` is a faithful lift of the old ``reforecast_jobs.execute_job`` loop:
it runs the chain PER QUESTION SEQUENTIALLY (one LLM session at a time — spend
sanity), fail-open per question (one bad question never kills the batch), and
recovers saturation + auto-quorum from the REAL artifacts the commit produced —
never fabricated. NOTHING here weakens a gate: every question commits through the
exact same gated ``run_forecast_chain`` → ``_run_update_agent`` path, so the panel
gate, analyst brief, saturation score, and auto-quorum fire unchanged.

Write-path preservation (the plan's named risk): the chain opens the ledger write
gate itself (``_run_update_agent`` wraps every commit in
``allow_ledger_writes(reason="forecast_cli")``), and :func:`execute` runs in the
detached worker's MAIN thread (``python -m forecasting.jobs run <job_id>`` or an
inline ``wait=True``) — a fresh process, default contextvars — so the exact
allow-writes environment a manual chain run uses is preserved verbatim. Heavy work
is detached as a CHILD PROCESS (not a thread) for the same reason the legacy runner
was: the one-shot CLI/RPC that enqueues exits as soon as it has the id.

New jobs persist as :class:`~forecasting.jobs.model.JobRecord` files under
``{home}/jobs/`` (``job_`` ids) via the shared :class:`~forecasting.jobs.store.JobStore`.
The legacy ``rf_*`` job files under ``{home}/reforecast_runs/`` stay readable
through the compat read-shim here, so a status/active query answers for a run that
was in flight across the migration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register

# Default per-batch cap (config ``forecasting.reforecast.max_batch`` overrides).
# A mass re-run is N multi-minute LLM sessions of real spend, so the batch is
# bounded before anything is enqueued.
DEFAULT_MAX_BATCH = 25

# Bound each question's agent session (config/spec override). Mirrors the
# run_forecast_chain default so a bare enqueue behaves like a manual chain run.
DEFAULT_MAX_ITERATIONS = 12


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # forecasting/jobs/types/reforecast.py → repo root is three parents up.
    return Path(__file__).resolve().parents[3]


# ── legacy rf_ store (read-shim + test/back-compat seeding) ───────────────────
#
# NEW runs live on the shared JobStore (``{home}/jobs/``); these helpers keep the
# OLD ``{home}/reforecast_runs/`` dir readable/writable so an ``rf_`` record that
# predates the migration still answers a status/active query verbatim.


def jobs_dir() -> Path:
    path = get_hermes_home() / "reforecast_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_path(run_id: str) -> Path:
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise ValueError(f"invalid reforecast run id: {run_id!r}")
    return jobs_dir() / f"{run_id}.json"


def write_job(job: dict[str, Any]) -> None:
    """Atomically persist a legacy-shape job record (temp file + os.replace) into
    the ``reforecast_runs`` dir. Kept for back-compat + test seeding; live runs go
    through :func:`start_job` (the JobStore)."""

    job["updated_at"] = _now_iso()
    path = _legacy_path(job["run_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _to_legacy(record: Any) -> dict[str, Any]:
    """Project a JobRecord onto the legacy reforecast/task job dict shape (``run_id``,
    ``results``/``current`` as the desk + CLI + aliases expect). The per-question
    ``results`` list and the dict ``current`` pointer are carried on the record's
    ``annotations`` (persisted unconditionally as the run progresses) with the
    terminal ``result`` as the fallback — so a mid-run poll and a done poll both read
    honestly."""

    ann = record.annotations or {}
    result = record.result or {}
    results = ann.get("results")
    if results is None:
        results = result.get("results") or []
    legacy: dict[str, Any] = {
        "run_id": record.job_id,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "spec": record.spec,
        "total": record.total,
        "done_count": record.done_count,
        "current": ann.get("current"),
        "results": results,
        "error": record.error,
    }
    # Task-mode extras (harmless on a reforecast record — simply absent).
    progress = ann.get("progress")
    if progress is not None:
        legacy["progress"] = progress
    summary = ann.get("task_summary")
    if summary is None:
        summary = result.get("task_summary")
    if summary is not None:
        legacy["task_summary"] = summary
    task_result = ann.get("task_result")
    if task_result is None:
        task_result = result.get("task_result")
    if task_result is not None:
        legacy["task_result"] = task_result
    return legacy


def read_job(run_id: str) -> dict[str, Any]:
    """Legacy-shape read for a reforecast/task run — the JobStore first (new
    ``job_`` records, projected via :func:`_to_legacy`), then the legacy
    ``reforecast_runs`` dir (an ``rf_`` file that predates the migration, returned
    verbatim). Raises ``FileNotFoundError`` when neither has it."""

    store = JobStore()
    try:
        return _to_legacy(store.read(run_id))
    except (FileNotFoundError, ValueError):
        pass
    path = jobs_dir() / f"{run_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no reforecast run '{run_id}' (looked in {jobs_dir()})")


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """Legacy-shape list of reforecast/task runs — the JobStore's reforecast/task
    records merged with any surviving legacy ``rf_`` files, newest first."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for record in JobStore().list(limit=max(limit * 4, 200)):
            if record.type in ("reforecast", "task"):
                rows.append(_to_legacy(record))
                seen.add(record.job_id)
    except Exception:  # noqa: BLE001 — a store hiccup never blanks the legacy view
        pass
    for path in jobs_dir().glob("rf_*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if row.get("run_id") in seen:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]


def active_jobs_by_question(limit: int = 40) -> dict[str, dict[str, Any]]:
    """question_id -> {run_id, status, created_at, done_count, total} for the MOST
    RECENT still-in-flight reforecast job (``queued`` | ``running``) that INCLUDES
    that question. One scan (no per-question I/O) so the desk can badge every row
    caught in a live mass re-run, then poll by the surfaced run_id."""

    out: dict[str, dict[str, Any]] = {}
    for job in list_jobs(limit=limit):
        if job.get("status") not in ("queued", "running"):
            continue
        for qid in (job.get("spec") or {}).get("question_ids") or []:
            qid = str(qid)
            if qid in out:
                continue
            out[qid] = {
                "run_id": job.get("run_id"),
                "status": job.get("status"),
                "created_at": job.get("created_at"),
                "done_count": job.get("done_count"),
                "total": job.get("total"),
            }
    return out


# ── shared enqueue validator ──────────────────────────────────────────────────


def validate_reforecast_ids(
    ledger: Any, question_ids: Any, *, max_batch: int = DEFAULT_MAX_BATCH
) -> tuple[list[str], list[str]]:
    """Dedupe + verify each id exists and is an ACTIVE question, and enforce the
    batch cap. The SHARED validator for both enqueue surfaces (the CLI and the
    ``forecast.reforecast.start`` RPC) so they refuse identically.

    Returns ``(accepted, errors)``. ``accepted`` preserves input order, deduped.
    ``errors`` is a list of human-readable refusals — an unknown id, an inactive
    id, or an over-cap batch. When ANY refusal is present the caller should refuse
    the WHOLE batch (never silently drop a selected question); over-cap clears
    ``accepted`` so a too-large selection can never start."""

    seen: set[str] = set()
    accepted: list[str] = []
    errors: list[str] = []
    for raw in question_ids or []:
        qid = str(raw).strip()
        if not qid or qid in seen:
            continue
        seen.add(qid)
        try:
            question = ledger.get_question(qid)
        except Exception:  # noqa: BLE001 — any lookup failure is an unknown id
            errors.append(f"{qid}: no such question")
            continue
        if getattr(question, "status", None) != "active":
            errors.append(
                f"{qid}: not active (status={getattr(question, 'status', None)})"
            )
            continue
        accepted.append(qid)
    if len(accepted) > max_batch:
        errors.append(
            f"batch of {len(accepted)} exceeds the reforecast cap of {max_batch}; "
            f"select {max_batch} or fewer"
        )
        accepted = []
    return accepted, errors


# ── enqueue (runtime store + detached worker) ─────────────────────────────────


def start_job(spec: dict[str, Any], *, wait: bool = False) -> str:
    """Create a queued JobRecord and execute it (inline if ``wait`` else detached).

    ``spec`` keys: ``question_ids`` (required list), ``db``, ``model``,
    ``provider``, ``max_iterations``, ``triggered_by`` — and ``mode='task'`` +
    ``instruction`` for a Desk task run. ``spec.mode`` selects the registered TYPE
    (``task`` vs ``reforecast``); the runtime resolves it. Validation (ids exist +
    active + batch cap) is the enqueue surface's job — see
    :func:`validate_reforecast_ids`; ``start_job`` trusts the spec so the type's
    ``execute`` stays fail-open per question regardless.

    Detach is a CHILD PROCESS (``python -m forecasting.jobs run <job_id>``, fresh
    contextvars, ``start_new_session=True``) — the enqueuing CLI/RPC exits as soon
    as it has the id, so a thread would be killed."""

    job_type = "task" if (spec.get("mode") or "").strip() == "task" else "reforecast"
    question_ids = [
        str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()
    ]

    from forecasting.jobs.model import JobRecord

    store = JobStore()
    job_id = store.new_id()
    store.write(
        JobRecord(
            job_id=job_id,
            type=job_type,
            spec=dict(spec),
            total=len(question_ids),
        )
    )

    if wait:
        from forecasting.jobs import runtime

        runtime.run(job_id, store=store)
        return job_id

    env = dict(os.environ)
    popen_kwargs: dict[str, Any] = {}
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "forecasting.jobs", "run", job_id],
        cwd=str(_repo_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **popen_kwargs,
    )
    return job_id


# ── the REFORECAST type: the per-question chain loop ──────────────────────────


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run the full forecast chain for every question in ``spec`` SEQUENTIALLY,
    persisting per-question progress + honest results as it goes.

    Fail-open PER QUESTION: any failure on one question is recorded in that
    question's result and the batch CONTINUES — one bad question never kills the
    job. The chain commits through the exact same gated path a manual run uses, so
    saturation + auto-quorum are recovered from the REAL artifacts the commit
    produced (the snapshot metadata and the detached quorum job file) — never
    fabricated. A bad db raises out to the runtime (whole-job ``error``)."""

    # Imported lazily: the detached worker is a fresh process and cli/run_agent are
    # heavy; keeping the import here also avoids any import cycle (cli imports the
    # jobs package lazily too).
    from forecasting.cli import run_forecast_chain
    from forecasting.hooks.sweep import saturation_summary
    from forecasting.ledger import ForecastLedger

    question_ids = [
        str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()
    ]
    model = spec.get("model") or None
    provider = spec.get("provider") or None
    try:
        max_iterations = int(spec.get("max_iterations") or DEFAULT_MAX_ITERATIONS)
    except (TypeError, ValueError):
        max_iterations = DEFAULT_MAX_ITERATIONS
    total = len(question_ids)

    ledger = ForecastLedger(spec.get("db"))  # a bad db → runtime marks the job error

    # Detect a NEWLY-started auto-quorum per question: a high-impact live commit
    # detaches a quorum via the tool hook, keyed by question_id in the QUORUM type's
    # store query. We diff the live quorum run-id before vs after the chain so we only
    # attribute a quorum THIS chain started (not a pre-existing one).
    try:
        from forecasting.jobs.types.quorum import active_jobs_by_question as _quorum_active
    except Exception:  # noqa: BLE001 — quorum surfacing is best-effort
        _quorum_active = None

    def _live_quorum_run_id(qid: str) -> str | None:
        if _quorum_active is None:
            return None
        try:
            return (_quorum_active().get(qid) or {}).get("run_id")
        except Exception:  # noqa: BLE001
            return None

    results: list[dict[str, Any]] = []

    def _save(current: dict[str, Any] | None) -> None:
        """Persist the running results list + current pointer + accounting onto the
        record UNCONDITIONALLY (annotate writes the whole record — no coalescing),
        so a mid-run status poll always reads honestly."""
        ctx.record.total = total
        ctx.record.done_count = len(results)
        ctx.record.annotations["results"] = results
        ctx.annotate("current", current)

    for qid in question_ids:
        entry: dict[str, Any] = {
            "question_id": qid,
            "title": None,
            "committed": False,
            "forecast_id": None,
            "stages": [],
            "research_audit_rounds": 0,
            "update_ready": None,
            "update_blockers": [],
            "saturation": None,
            "quorum_autorun": None,
            "error": None,
        }
        try:
            try:
                title = ledger.get_question(qid).title
            except Exception:  # noqa: BLE001 — a missing title never blocks the run
                title = None
            entry["title"] = title
            _save({"question_id": qid, "title": title, "stage": "start"})
            ctx.progress(phase="start", done=len(results), total=total, current=qid)

            pre_quorum = _live_quorum_run_id(qid)

            def _on_stage(stage: str, _outcome: dict[str, Any], _qid: str = qid, _title=title) -> None:
                _save({"question_id": _qid, "title": _title, "stage": stage})
                ctx.progress(phase=stage, done=len(results), total=total, current=_qid)

            # The full formal flow — research (+ VOI audit re-runs) → base_rate →
            # (model) → update — through the SAME gated agent. run_forecast_chain
            # captures per-stage errors internally (never re-raises for a flaky
            # stage); it only raises if the question itself vanished, which the
            # outer per-question try isolates.
            chain = run_forecast_chain(
                ledger,
                qid,
                model=model,
                provider=provider,
                max_iterations=max_iterations,
                on_stage=_on_stage,
            )
            entry["stages"] = chain.get("stages") or []
            entry["committed"] = bool(chain.get("committed"))
            entry["update_ready"] = chain.get("update_ready")
            entry["update_blockers"] = chain.get("update_blockers") or []
            entry["research_audit_rounds"] = int(chain.get("research_audit_rounds") or 0)
            snap = chain.get("snapshot") or {}
            entry["forecast_id"] = snap.get("forecast_id")

            # Saturation — read straight off the just-committed snapshot's metadata
            # (the SAME value the tool commit path surfaces); absent when no report
            # was recorded. Never fabricated.
            try:
                current_snap = ledger.get_current_snapshot(qid)
                meta = getattr(current_snap, "metadata", None) or {}
                entry["saturation"] = saturation_summary(meta.get("saturation"))
            except Exception:  # noqa: BLE001
                entry["saturation"] = None

            # Auto-quorum — surface the NEW detached quorum this commit started (a
            # high-impact live commit with no panel). The TUI toast counts these.
            post_quorum = _live_quorum_run_id(qid)
            if post_quorum and post_quorum != pre_quorum and _quorum_active is not None:
                try:
                    info = _quorum_active().get(qid) or {}
                except Exception:  # noqa: BLE001
                    info = {}
                entry["quorum_autorun"] = {
                    "run_id": post_quorum,
                    "status": info.get("status"),
                    "created_at": info.get("created_at"),
                }
        except Exception as exc:  # noqa: BLE001 — one bad question must never kill the batch
            entry["error"] = f"{type(exc).__name__}: {exc}"

        results.append(entry)
        _save(None)
        ctx.progress(phase="question", done=len(results), total=total)

    return {"results": results, "total": total, "done_count": len(results)}


REFORECAST = JobType(
    name="reforecast",
    execute=execute,
    # Coarse progress (per stage per question — a few dozen events, not a storm).
    min_interval_s=0.0,
    # The legacy event family the aliased RPCs still speak (the desk polls status).
    alias_namespace="forecast.reforecast",
    spend_class="agent",
)

register(REFORECAST)

__all__ = [
    "DEFAULT_MAX_BATCH",
    "DEFAULT_MAX_ITERATIONS",
    "REFORECAST",
    "execute",
    "start_job",
    "validate_reforecast_ids",
    "read_job",
    "write_job",
    "list_jobs",
    "active_jobs_by_question",
    "jobs_dir",
    "_now_iso",
    "_repo_root",
]
