"""Background job runner for the operator's Desk "mass LLM re-run".

The operator multi-selects Desk questions and wants the FULL formal forecast flow
PER question — fresh evidence searched/imported/triaged, a VOI research-adequacy
audit, a base rate, a quorum where indicated, and a GATED LLM commit — NOT the
deterministic re-pool. That chain already exists:
:func:`forecasting.cli.run_forecast_chain` drives research → base_rate → (model) →
update through the same gated ``_run_update_agent`` every manual
``forecast agent --stage S`` run uses, and the tool commit hook applies lessons,
records the saturation score, and auto-runs a quorum on high-impact commits.

What this module adds is the detached ORCHESTRATION for a BATCH of explicit
question ids: a TUI keypress enqueues one job (returning an ``rf_`` run-id
immediately) and a separate process runs the chain PER QUESTION SEQUENTIALLY —
one LLM session at a time (spend sanity) — streaming per-question progress into a
per-run JSON file under the agent home. ``forecast rerun status <run-id>`` (or the
``forecast.reforecast.status`` RPC) reads that file.

A detached child process (not a thread) is used deliberately — the same reasoning
as :mod:`forecasting.quorum_jobs`: the one-shot CLI/RPC that enqueues the job exits
as soon as it has the run-id, so a thread would be killed; a child with
``start_new_session=True`` survives. NOTHING here weakens a gate — each question
commits through the exact same gated ``run_forecast_chain`` → ``_run_update_agent``
path, so the panel gate, analyst brief, saturation score, and auto-quorum fire
unchanged; this module only SCOPES the run to explicit ids, detaches it, and
reports the outcome honestly.

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

# Default per-batch cap (config ``forecasting.reforecast.max_batch`` overrides).
# A mass re-run is N multi-minute LLM sessions of real spend, so the batch is
# bounded before anything is enqueued.
DEFAULT_MAX_BATCH = 25

# Bound each question's agent session (config/spec override). Mirrors the
# run_forecast_chain default so a bare enqueue behaves like a manual chain run.
DEFAULT_MAX_ITERATIONS = 12

# Bound the ONE agent session a 'task' job runs (spec override). A batch chore
# ("add watched sources to these five", "set executable triggers") sweeps several
# questions in a single session, so it gets a larger default than the per-question
# reforecast leg.
DEFAULT_TASK_MAX_ITERATIONS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def jobs_dir() -> Path:
    path = get_hermes_home() / "reforecast_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(run_id: str) -> Path:
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise ValueError(f"invalid reforecast run id: {run_id!r}")
    return jobs_dir() / f"{run_id}.json"


def write_job(job: dict[str, Any]) -> None:
    """Atomically persist a job record (temp file + os.replace)."""

    job["updated_at"] = _now_iso()
    path = _job_path(job["run_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_job(run_id: str) -> dict[str, Any]:
    path = _job_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"no reforecast run '{run_id}' (looked in {jobs_dir()})")
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in jobs_dir().glob("rf_*.json"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]


def active_jobs_by_question(limit: int = 40) -> dict[str, dict[str, Any]]:
    """question_id -> {run_id, status, created_at, done_count, total} for the MOST
    RECENT still-in-flight reforecast job (``queued`` | ``running``) that INCLUDES
    that question.

    A single jobs-dir scan (no per-question I/O) so the desk workspace payload can
    badge a "reforecasting" chip on every row caught in a live mass re-run, then
    poll ``forecast.reforecast.status`` by the surfaced run_id. Unlike a quorum job
    (one question per job) a reforecast job carries MANY question_ids, so each id in
    a live job's spec maps to that job. Only live jobs — a ``done``/``error`` job is
    terminal and never chipped."""

    out: dict[str, dict[str, Any]] = {}
    # list_jobs returns newest-first, so the first live job seen per question is the
    # most recent one.
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


def new_run_id() -> str:
    return f"rf_{uuid.uuid4().hex[:12]}"


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


def start_job(spec: dict[str, Any], *, wait: bool = False) -> str:
    """Create a queued job and execute it (inline if ``wait`` else detached).

    ``spec`` keys: ``question_ids`` (required list), ``db``, ``model``,
    ``provider``, ``max_iterations``, ``triggered_by``. Validation (ids exist +
    active + batch cap) is the enqueue surface's job — see
    :func:`validate_reforecast_ids`; ``start_job`` trusts the spec so
    :func:`execute_job` stays fail-open per question regardless."""

    run_id = new_run_id()
    question_ids = [str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()]
    job = {
        "run_id": run_id,
        "status": "queued",
        "created_at": _now_iso(),
        "spec": spec,
        "total": len(question_ids),
        "done_count": 0,
        "current": None,
        "results": [],
        "error": None,
    }
    write_job(job)

    if wait:
        execute_job(run_id)
        return run_id

    env = dict(os.environ)
    popen_kwargs: dict[str, Any] = {}
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "forecasting.reforecast_jobs", run_id],
        cwd=str(_repo_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **popen_kwargs,
    )
    return run_id


def execute_job(run_id: str) -> dict[str, Any]:
    """Run the full forecast chain for every question in ``run_id`` SEQUENTIALLY,
    persisting per-question progress + honest results as it goes.

    Fail-open PER QUESTION: any failure on one question is recorded in that
    question's result and the batch CONTINUES — one bad question never kills the
    job. The chain commits through the exact same gated path a manual run uses, so
    saturation + auto-quorum are recovered from the REAL artifacts the commit
    produced (the snapshot metadata and the detached quorum job file) — never
    fabricated."""

    # Imported lazily: the detached worker is a fresh process and cli/run_agent are
    # heavy; keeping the import here also avoids any import cycle (cli imports this
    # module lazily too).
    from forecasting.cli import run_forecast_chain
    from forecasting.hooks.sweep import saturation_summary
    from forecasting.ledger import ForecastLedger

    job = read_job(run_id)
    spec = job.get("spec") or {}
    # A 'task' job is a DIFFERENT shape: one operator free-text session over the whole
    # batch (not the per-question reforecast chain), so it forks to its own runner.
    # Both modes share this job store + the forecast.reforecast.status contract; the
    # spec.mode field is what distinguishes them for readers.
    if (spec.get("mode") or "").strip() == "task":
        return _execute_task_job(run_id)
    job["status"] = "running"
    write_job(job)

    question_ids = [str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()]
    model = spec.get("model") or None
    provider = spec.get("provider") or None
    try:
        max_iterations = int(spec.get("max_iterations") or DEFAULT_MAX_ITERATIONS)
    except (TypeError, ValueError):
        max_iterations = DEFAULT_MAX_ITERATIONS

    try:
        ledger = ForecastLedger(spec.get("db"))
    except Exception as exc:  # noqa: BLE001 — a bad db is a whole-job failure
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        write_job(job)
        return job

    # Detect a NEWLY-started auto-quorum per question: a high-impact live commit
    # detaches a quorum via the tool hook, keyed by question_id in quorum_jobs. We
    # diff the live quorum run-id for the question before vs after the chain so we
    # only attribute a quorum THIS chain started (not a pre-existing one).
    try:
        from forecasting.quorum_jobs import active_jobs_by_question as _quorum_active
    except Exception:  # noqa: BLE001 — quorum surfacing is best-effort
        _quorum_active = None

    def _live_quorum_run_id(qid: str) -> str | None:
        if _quorum_active is None:
            return None
        try:
            return (_quorum_active().get(qid) or {}).get("run_id")
        except Exception:  # noqa: BLE001
            return None

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
            job["current"] = {"question_id": qid, "title": title, "stage": "start"}
            write_job(job)

            pre_quorum = _live_quorum_run_id(qid)

            def _on_stage(stage: str, _outcome: dict[str, Any], _qid: str = qid, _title=title) -> None:
                job["current"] = {"question_id": _qid, "title": _title, "stage": stage}
                write_job(job)

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
                current = ledger.get_current_snapshot(qid)
                meta = getattr(current, "metadata", None) or {}
                entry["saturation"] = saturation_summary(meta.get("saturation"))
            except Exception:  # noqa: BLE001
                entry["saturation"] = None

            # Auto-quorum — surface the NEW detached quorum this commit started (a
            # high-impact live commit with no panel). The TUI toast counts these to
            # report "N quorums started" and can poll each via forecast.quorum.status.
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

        job["results"].append(entry)
        job["done_count"] = len(job["results"])
        job["current"] = None
        write_job(job)

    job["status"] = "done"
    job["current"] = None
    write_job(job)
    return job


# ── Desk task jobs (the operator's free-text fix loop) ────────────────────────
#
# A 'task' job is the visibility arc's other half: the readiness composite SHOWS
# the operator what a question is missing (no watched sources, no executable
# trigger, ...), and a task job is how they FIX it — a free-text instruction over a
# batch of questions, run as ONE gated agent session. The session works the SAME
# gated forecast_ledger_tool every commit path uses; this module only scopes it to
# the instruction + the question list (each carrying its readiness gaps so the agent
# sees WHAT is missing) and reports progress honestly. NOTHING here opens a new
# write path.


def _append_progress(job: dict[str, Any], stage: str, detail: str) -> None:
    """Stage a human-readable progress note into the job file (started/working/done).
    Tolerant of a job record without a ``progress`` key (reforecast-mode jobs never
    set one)."""
    job.setdefault("progress", []).append(
        {"stage": stage, "detail": detail, "at": _now_iso()}
    )
    write_job(job)


def _run_task_agent(
    user_message: str,
    *,
    system_message: str,
    model: str | None,
    provider: str | None,
    max_iterations: int,
) -> dict[str, Any]:
    """Run ONE gated agent session for a Desk task job — the SAME seam
    :func:`forecasting.cli._run_update_agent` uses (the ``forecasting`` toolset
    through ``run_agent.AIAgent``), so every write still goes through the gated
    ``forecast_ledger_tool``; this only scopes the session to the composed
    instruction. Returns ``run_conversation``'s result dict. A module-level function
    so tests can stub it exactly as they stub ``cli._run_update_agent``."""
    from run_agent import AIAgent

    agent = AIAgent(
        model=model or "",
        provider=provider,
        max_iterations=max_iterations,
        # The forecasting toolset is the gated write path; file+web let the chore
        # do real research (import a source, add a reference class) when the
        # instruction calls for it — the same toolset a research/base_rate stage uses.
        enabled_toolsets=["forecasting", "file", "web"],
        platform="cli",
    )
    return agent.run_conversation(user_message, system_message=system_message)


def _compose_task_prompt(
    ledger: Any, instruction: str, question_ids: list[str]
) -> tuple[str, str]:
    """Build ``(system, user)`` for a task session: the forecasting-desk system
    prompt + the operator's instruction followed by the scoped question list, each
    line carrying id + title + the machine-readiness GAPS the desk is missing, so the
    agent sees exactly WHAT to fix. Read-only assembly."""
    from forecasting.protocol import SYSTEM_PROMPT
    from forecasting.readiness_lens import build_question_readiness

    lines: list[str] = []
    for qid in question_ids:
        try:
            composite = build_question_readiness(ledger, qid)
        except Exception:  # noqa: BLE001 — a bad id never aborts the compose
            lines.append(f"- {qid}")
            continue
        header = f"- {qid}"
        if composite.get("title"):
            header += f" — {composite['title']}"
        score = composite.get("score")
        if score is not None:
            header += f"  (machine-readiness {score}/100)"
        lines.append(header)
        gaps = composite.get("gaps") or []
        if not gaps:
            lines.append("    · machine-ready — no missing inputs")
        for gap in gaps:
            lines.append(f"    · MISSING {gap['label']}: {gap['fix_hint']}")

    user = (
        "## Operator task\n"
        f"{instruction.strip()}\n\n"
        "## Questions in scope\n"
        "Work through these questions. Each line lists the question id, title, and the "
        "machine-readiness gaps the autonomous desk is currently missing (watched "
        "sources, structured components, reference classes, an executable update "
        "trigger, an enabled review schedule, close_time / impact / resolution rule). "
        "Use the forecasting tools to close the gaps the instruction calls for, "
        "committing every change through the gated tool. When finished, summarise what "
        "you changed per question.\n\n" + "\n".join(lines)
    )
    return SYSTEM_PROMPT.strip(), user


def _execute_task_job(run_id: str) -> dict[str, Any]:
    """Run a 'task' job: ONE gated agent session over the whole batch, staging
    started/working/done progress notes + a final summary of what the agent reported.

    Honest completion: the job is ``done`` only when the session returns; any failure
    (bad db, empty instruction, agent raise) lands ``error`` with the reason. The
    summary is the agent's own ``final_response`` — never fabricated."""
    from forecasting.ledger import ForecastLedger

    job = read_job(run_id)
    spec = job.get("spec") or {}
    job["status"] = "running"
    job.setdefault("progress", [])
    write_job(job)

    instruction = str(spec.get("instruction") or "").strip()
    question_ids = [
        str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()
    ]
    model = spec.get("model") or None
    provider = spec.get("provider") or None
    try:
        max_iterations = int(spec.get("max_iterations") or DEFAULT_TASK_MAX_ITERATIONS)
    except (TypeError, ValueError):
        max_iterations = DEFAULT_TASK_MAX_ITERATIONS

    if not instruction:
        _append_progress(job, "error", "task job requires a non-empty instruction")
        job["status"] = "error"
        job["error"] = "task job requires a non-empty instruction"
        write_job(job)
        return job

    _append_progress(
        job, "start", f"composing task over {len(question_ids)} question(s)"
    )

    try:
        ledger = ForecastLedger(spec.get("db"))
    except Exception as exc:  # noqa: BLE001 — a bad db is a whole-job failure
        _append_progress(job, "error", f"{type(exc).__name__}: {exc}")
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        write_job(job)
        return job

    try:
        system_message, user_message = _compose_task_prompt(
            ledger, instruction, question_ids
        )
    except Exception as exc:  # noqa: BLE001
        _append_progress(job, "error", f"compose failed: {type(exc).__name__}: {exc}")
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        write_job(job)
        return job

    job["current"] = {"stage": "agent", "question_ids": question_ids}
    _append_progress(
        job, "working", f"running one agent session (max_iterations={max_iterations})"
    )

    try:
        result = _run_task_agent(
            user_message,
            system_message=system_message,
            model=model,
            provider=provider,
            max_iterations=max_iterations,
        )
    except Exception as exc:  # noqa: BLE001 — the session raising is a job error
        _append_progress(job, "error", f"agent session failed: {type(exc).__name__}: {exc}")
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["current"] = None
        write_job(job)
        return job

    result = result or {}
    summary = str(result.get("final_response") or "").strip()
    job["task_summary"] = summary
    job["task_result"] = {
        "final_response": summary,
        "api_calls": result.get("api_calls"),
        "completed": result.get("completed"),
        "failed": bool(result.get("failed")),
    }
    _append_progress(
        job, "done", summary[:500] if summary else "agent session complete (no summary)"
    )
    job["done_count"] = len(question_ids)
    job["current"] = None
    job["status"] = "done"
    write_job(job)
    return job


if __name__ == "__main__":  # detached worker entrypoint
    if len(sys.argv) != 2:
        print("usage: python -m forecasting.reforecast_jobs <run_id>", file=sys.stderr)
        raise SystemExit(2)
    # A detached worker is a fresh process: discover plugins so the per-question
    # research stage's web search + import_source_evidence have their providers
    # registered — exactly as gateway.py / oneshot.py / quorum_jobs do at boot.
    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:  # noqa: BLE001 — search/extract degrade gracefully if discovery fails
        pass
    execute_job(sys.argv[1])
