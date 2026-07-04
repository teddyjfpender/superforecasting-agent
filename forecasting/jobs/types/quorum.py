"""The QUORUM job type: the multi-model Delphi forecast on the one detached-job
runtime (Arc B3).

A quorum dispatches several models (each researching with web search) plus a judge
synthesis pass — minutes of wall-clock, far past the TUI's 45s slash timeout. So a
quorum runs as a **detached background job** (ONE question per job): the CLI / tool
enqueues it (returning a run-id immediately) and a separate process executes it,
streaming progress into the persisted record. ``forecast quorum status <run-id>``
and the ``forecast.quorum.status`` RPC read that record.

:func:`execute` is a faithful lift of the old ``quorum_jobs.execute_job`` (the
multi-model Delphi run): resolve the question + panel, build each panelist runner
(foreknowledge-gated on the evidence cutoff), optionally derive the terminal Platt
slope, wire the live supervisor fresh-search loop, weight panelists by track
record, run the quorum + judge synthesis, and persist the aggregate as a sibling
panel run through the ledger write gate. NOTHING here weakens a gate; the committed
number is the P0.3-resolved, terminally-calibrated value.

Detach is a CHILD PROCESS (``python -m forecasting.jobs run <job_id>``, fresh
contextvars, ``start_new_session=True``) for the same reason the legacy runner was:
the one-shot CLI/RPC that enqueues exits as soon as it has the id, so a thread would
be killed. The fresh worker discovers plugins (search/extract providers) before it
runs — handled once in :mod:`forecasting.jobs.__main__`.

New jobs persist as :class:`~forecasting.jobs.model.JobRecord` files under
``{home}/jobs/`` (``job_`` ids) via the shared :class:`~forecasting.jobs.store.JobStore`.
The legacy ``qr_*`` job files under ``{home}/quorum_runs/`` stay readable through the
compat read-shim here, so a status/active query answers for a run that was in flight
across the migration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # forecasting/jobs/types/quorum.py → repo root is three parents up.
    return Path(__file__).resolve().parents[3]


# ── legacy qr_ store (read-shim + test/back-compat seeding) ───────────────────
#
# NEW runs live on the shared JobStore (``{home}/jobs/``); these helpers keep the
# OLD ``{home}/quorum_runs/`` dir readable/writable so a ``qr_`` record that
# predates the migration still answers a status/active query verbatim.


def jobs_dir() -> Path:
    path = get_hermes_home() / "quorum_runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_path(run_id: str) -> Path:
    if not run_id or "/" in run_id or "\\" in run_id or run_id.startswith("."):
        raise ValueError(f"invalid quorum run id: {run_id!r}")
    return jobs_dir() / f"{run_id}.json"


def write_job(job: dict[str, Any]) -> None:
    """Atomically persist a legacy-shape quorum job record (temp file + os.replace)
    into the ``quorum_runs`` dir. Kept for back-compat + test seeding; live runs go
    through :func:`start_job` (the JobStore)."""

    job["updated_at"] = _now_iso()
    path = _legacy_path(job["run_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _to_legacy(record: Any) -> dict[str, Any]:
    """Project a JobRecord onto the legacy quorum job dict shape (``run_id``,
    ``question_id``, ``panel_run_id``, ``result`` as the aggregate QuorumResult dict,
    ``progress`` as the ordered ``{stage, detail, at}`` steps) the desk + CLI + the
    ``forecast.quorum.status`` RPC already speak. The QuorumResult dict and the
    ``panel_run_id`` are carried on the terminal ``result`` (with the running
    ``annotations`` as the mid-flight fallback), so a mid-run poll and a done poll
    both read honestly."""

    result = record.result or {}
    ann = record.annotations or {}
    quorum_result = result.get("quorum_result")
    if quorum_result is None:
        quorum_result = ann.get("quorum_result") or {}
    panel_run_id = result.get("panel_run_id")
    if panel_run_id is None:
        panel_run_id = ann.get("panel_run_id")
    return {
        "run_id": record.job_id,
        "question_id": (record.spec or {}).get("question_id"),
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "spec": record.spec,
        "progress": record.progress,
        "panel_run_id": panel_run_id,
        "result": quorum_result,
        "error": record.error,
    }


def read_job(run_id: str) -> dict[str, Any]:
    """Legacy-shape read for a quorum run — the JobStore first (new ``job_`` records,
    projected via :func:`_to_legacy`), then the legacy ``quorum_runs`` dir (a ``qr_``
    file that predates the migration, returned verbatim). Raises ``FileNotFoundError``
    when neither has it."""

    store = JobStore()
    try:
        return _to_legacy(store.read(run_id))
    except (FileNotFoundError, ValueError):
        pass
    path = jobs_dir() / f"{run_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no quorum run '{run_id}' (looked in {jobs_dir()})")


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """Legacy-shape list of quorum runs — the JobStore's ``quorum`` records merged
    with any surviving legacy ``qr_`` files, newest first."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for record in JobStore().list(limit=max(limit * 4, 200)):
            if record.type == "quorum":
                rows.append(_to_legacy(record))
                seen.add(record.job_id)
    except Exception:  # noqa: BLE001 — a store hiccup never blanks the legacy view
        pass
    for path in jobs_dir().glob("qr_*.json"):
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
    """question_id -> {run_id, status, created_at} for the MOST RECENT still-in-flight
    quorum job (``queued`` | ``running``) per question.

    A single scan (no per-question I/O) so the desk workspace payload can badge a
    "quorum running" chip on the row whose auto-quorum just started, then poll
    ``forecast.quorum.status`` by the surfaced run_id. Only live jobs — a
    ``done``/``error`` job is terminal and never chipped. This is ALSO the seam the
    REFORECAST type diffs before/after the chain to attribute a quorum THIS run
    started, so it must answer over the shared JobStore's quorum records."""

    out: dict[str, dict[str, Any]] = {}
    # list_jobs already returns newest-first, so the first live job seen per
    # question is the most recent one.
    for job in list_jobs(limit=limit):
        qid = job.get("question_id")
        if not qid or qid in out:
            continue
        if job.get("status") not in ("queued", "running"):
            continue
        out[str(qid)] = {
            "run_id": job.get("run_id"),
            "status": job.get("status"),
            "created_at": job.get("created_at"),
        }
    return out


# ── enqueue (runtime store + detached worker) ─────────────────────────────────


def start_job(spec: dict[str, Any], *, wait: bool = False) -> str:
    """Create a queued ``quorum`` JobRecord and execute it (inline if ``wait`` else
    detached).

    ``spec`` keys: ``question_id`` (required), ``db``, ``preset``, ``models``,
    ``judge``, ``pool_method``, ``trim``, ``self_fusion``, ``samples``,
    ``triggered_by``, ``attach_snapshot``, ``active_model``, ``delphi_rounds``,
    ``supervisor_search``, ``max_iterations``, ``model_timeout``.

    Detach is a CHILD PROCESS (``python -m forecasting.jobs run <job_id>``, fresh
    contextvars, ``start_new_session=True``) — the enqueuing CLI/RPC exits as soon as
    it has the id, so a thread would be killed."""

    from forecasting.jobs.model import JobRecord

    store = JobStore()
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="quorum", spec=dict(spec)))

    if wait:
        from forecasting.jobs import runtime

        runtime.run(job_id, store=store)
        return job_id

    env = dict(os.environ)
    # Propagate the agent-home override so the child writes to the same place.
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


# ── per-run gate helpers (verbatim from the legacy runner) ────────────────────


def _truthy(value: Any) -> bool:
    """Tolerant on/off parse for the supervisor-search gate.

    Accepts a real bool, the common string tokens, or a number; anything
    missing/garbage collapses to ``False`` — the DEFAULT-OFF state, so the live
    default stays byte-identical (no search_runner, research_rounds 0).
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == value and value != 0  # NaN-safe
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "on"}
    return False


def _supervisor_search_enabled(spec: dict[str, Any]) -> bool:
    """Whether to wire the live fresh-search supervisor loop for this run.

    OPT-IN, DEFAULT OFF. Turned on by the per-run spec ``supervisor_search`` (set by
    ``forecast quorum --supervisor-search``), which the CLI already resolves from the
    fleet-wide config flag ``quorum.supervisor_search`` at enqueue time. This
    config fallback is the safety net for a spec that omits the key entirely (e.g. a
    programmatic enqueue). It governs ONLY the run_quorum/execute path; the
    market-nightly path uses an injected agent_forecaster seam and is unaffected.
    """

    if "supervisor_search" in spec:
        return _truthy(spec.get("supervisor_search"))
    try:
        from hermes_cli.config import load_config

        cfg = load_config().get("quorum", {})
    except Exception:  # noqa: BLE001 — config is optional; default OFF without it
        return False
    return _truthy(cfg.get("supervisor_search")) if isinstance(cfg, dict) else False


def _track_record_weights_enabled(spec: dict[str, Any]) -> bool:
    """Whether to weight panelists by their measured track record for this run.

    DEFAULT ON but HARMLESS-BY-CONSTRUCTION on cold start: a model must clear the
    resolved-sample gate before its weight moves off 1.0, so with no history every
    panelist is equal-weighted and the committed number is byte-identical to the
    unweighted pool. The per-run spec ``track_record_weights`` wins; otherwise the
    fleet-wide config flag ``quorum.track_record_weights`` (default True) governs.
    Any config/import failure defaults ON (the harmless-on-cold-start behaviour)."""

    if "track_record_weights" in spec:
        return _truthy(spec.get("track_record_weights"))
    try:
        from hermes_cli.config import load_config

        cfg = load_config().get("quorum", {})
    except Exception:  # noqa: BLE001 — config optional; harmless default ON
        return True
    if not isinstance(cfg, dict) or "track_record_weights" not in cfg:
        return True
    return _truthy(cfg.get("track_record_weights"))


def _track_record_min_sample(spec: dict[str, Any]) -> int:
    """Resolved-binary sample gate for panelist weighting: per-run spec wins, else
    the fleet-wide ``quorum.track_record_min_sample`` (default 10). Fails safe to
    10 on any config/parse error."""

    if "track_record_min_sample" in spec:
        try:
            return max(1, int(spec.get("track_record_min_sample")))
        except (TypeError, ValueError):
            return 10
    try:
        from hermes_cli.config import load_config

        cfg = load_config().get("quorum", {})
        if isinstance(cfg, dict) and "track_record_min_sample" in cfg:
            return max(1, int(cfg.get("track_record_min_sample")))
    except Exception:  # noqa: BLE001 — config optional
        pass
    return 10


def _has_explicit_alpha_override(metadata: Any) -> bool:
    """True when a question carries an EXPLICIT ``alpha_extremize`` threshold.

    The evidence-gated derivation (item 6) must NEVER override a hand-set slope, so
    this checks ``metadata['forecast_hooks']['thresholds']['alpha_extremize']``
    directly. A missing/garbage structure ⇒ ``False`` (no explicit override → the
    derivation may run when enabled)."""

    if not isinstance(metadata, dict):
        return False
    fh = metadata.get("forecast_hooks")
    thresholds = fh.get("thresholds") if isinstance(fh, dict) else None
    return isinstance(thresholds, dict) and "alpha_extremize" in thresholds


def _derive_alpha_enabled() -> bool:
    """Whether evidence-gated terminal-Platt derivation is turned on (DEFAULT OFF).

    Reads ``forecasting.calibration.derive_alpha``. Any config/import failure ⇒
    ``False`` (the fail-safe: never derive without an explicit opt-in)."""

    try:
        from hermes_cli.config import load_config

        cal = (load_config().get("forecasting", {}) or {}).get("calibration", {})
    except Exception:  # noqa: BLE001 — config optional; default OFF without it
        return False
    return _truthy(cal.get("derive_alpha")) if isinstance(cal, dict) else False


def _cutoff_is_live(evidence_cutoff: Any, *, tolerance_hours: float = 48.0) -> bool:
    """True when fresh web search is admissible — i.e. the forecast is LIVE.

    Fresh search returns present-day content, so it is only safe when there is no
    historical cutoff to pin to. ``None`` (no cutoff) or a cutoff within
    ``tolerance_hours`` of now is treated as live; an older cutoff (a backtest /
    replay snapshot) disables the supervisor search so now-known information cannot
    be folded into a past-pinned forecast. An unparseable cutoff fails SAFE (no search).
    """

    if not evidence_cutoff:
        return True
    try:
        from datetime import datetime, timedelta, timezone

        from forecasting.models import parse_timestamp, timestamp_to_datetime

        cutoff_dt = timestamp_to_datetime(
            parse_timestamp(str(evidence_cutoff), field_name="evidence_cutoff")
        )
        if cutoff_dt is None:
            return False
        if cutoff_dt.tzinfo is None:
            cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
        return cutoff_dt >= datetime.now(timezone.utc) - timedelta(hours=tolerance_hours)
    except Exception:  # noqa: BLE001 — any parse/clock failure fails safe (no search)
        return False


# ── the QUORUM type: one multi-model Delphi run per job ───────────────────────


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run the quorum for one question to completion, streaming progress into the
    record and persisting the aggregate as a sibling panel run.

    A faithful lift of the old ``quorum_jobs.execute_job`` body: the runtime owns the
    ``running``/``done``/``error`` transitions (so any raise here becomes a whole-job
    ``error`` with the same ``{type}: {exc}`` message), and this function only does
    the work + reports progress. Progress events keep the legacy ``{stage, detail,
    at}`` shape the desk/CLI/RPC read; the QUORUM type's ``min_interval_s=0.0`` means
    every one lands (the audit trail is coarse, not a storm)."""

    from forecasting.hooks.thresholds import resolve_alpha_extremize
    from forecasting.ledger import ForecastLedger
    from forecasting.protocol import build_context_packet
    from forecasting.quorum import (
        DEFAULT_JUDGE_MODEL,
        make_aiagent_runner,
        resolve_models,
        run_quorum,
    )

    # Panelists run concurrently, so run_quorum's on_progress fires from worker
    # threads — serialise the coalescer's append + file write behind one lock. The
    # manual (main-thread) emits share it harmlessly.
    progress_lock = threading.Lock()

    def emit(stage: str, detail: str) -> None:
        with progress_lock:
            ctx.progress({"stage": stage, "detail": detail, "at": _now_iso()})

    emit("start", "resolving question and panel")

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
    # The judge synthesis is the core of a quorum (a model paired with itself still
    # gains from it), so it always runs: explicit judge → preset judge → global
    # default.
    judge_model = spec.get("judge") or preset_judge or DEFAULT_JUDGE_MODEL
    self_fusion = bool(spec.get("self_fusion")) or spec.get("preset") == "self"

    # Delphi v1 — optional single anonymous revision round. Resolved to a plain int
    # here and threaded into run_quorum (which validates {0, 1}). ``0`` is the DEFAULT
    # and keeps this path byte-identical: no extra model calls, empty delphi_audit.
    delphi_rounds = int(spec.get("delphi_rounds") or 0)

    # FOREKNOWLEDGE GUARD (mirrors the supervisor-search guard below): gate the
    # PANELIST toolset on the SAME _cutoff_is_live(evidence_cutoff) predicate. A
    # HISTORICAL cutoff (backtest/replay snapshot) builds each panelist closed-book
    # (EMPTY toolset — NO web, NO forecast_ledger.import_source_evidence). A LIVE
    # cutoff gives panelists web research only (still NO ledger-write surface — the
    # quorum job, not the panelist, aggregates + records the forecast).
    runner = make_aiagent_runner(
        max_iterations=int(spec.get("max_iterations", 30)),
        timeout=spec.get("model_timeout"),
        evidence_cutoff=evidence_cutoff,
    )

    def on_progress(stage: str, detail: str) -> None:
        emit(stage, detail)

    # Terminal Platt calibration (AIA P0.1): resolve the per-question slope ONCE here
    # and thread it through run_quorum so the in-memory QuorumResult is already
    # calibrated. record_panel_run then persists the SAME resolved number (it does
    # NOT re-pool), so the in-memory result and the durable panel_run can never
    # diverge.
    metadata = question.metadata if isinstance(question.metadata, dict) else None
    alpha_extremize = resolve_alpha_extremize(metadata)
    # EVIDENCE-GATED EXTREMIZATION (item 6, config-gated DEFAULT OFF). When no
    # EXPLICIT per-question alpha_extremize override is set AND
    # forecasting.calibration.derive_alpha is enabled, derive the terminal Platt slope
    # from the domain's RESOLVED calibration via the validated extremization gate
    # (sqrt(3) permitted only where measurably under-confident; 1.0 otherwise —
    # fail-safe cold start). The explicit metadata override always wins.
    if not _has_explicit_alpha_override(metadata) and _derive_alpha_enabled():
        derived = ledger.derive_extremize_alpha(question)
        if derived and derived != 1.0:
            alpha_extremize = float(derived)
            emit(
                "derived_alpha",
                f"terminal Platt slope {derived:.3f} from resolved calibration",
            )

    # GATE 2 (AIA P1.1, live) — wire the agentic-supervisor fresh-search loop. The
    # judge can flag an unresolved crux (information_gap + clarifying_queries) and the
    # supervisor runs FRESH web/news search to fold in information the market has not
    # yet priced. OPT-IN and DEFAULT OFF: only when the spec (or the quorum config)
    # turns it on do we construct a search_runner and allow one research round. With
    # it off, search_runner stays None so run_quorum is byte-identical to before.
    search_runner = None
    max_research_rounds = 0
    if _supervisor_search_enabled(spec):
        # LEAKAGE GUARD (enforced in code, not convention): a fresh web search returns
        # PRESENT-DAY content, which cannot be pinned to a historical evidence_cutoff.
        # So the supervisor search only runs when the forecast is effectively LIVE (no
        # cutoff, or a cutoff within tolerance of now). A historical cutoff — e.g. a
        # backtest/replay snapshot — disables it, so now-known information can never be
        # folded into a past-pinned forecast.
        if _cutoff_is_live(evidence_cutoff):
            from forecasting.supervisor_search import build_supervisor_search_runner

            # Clamp the per-run bounds: each round re-runs the FULL panel+judge, so cap
            # rounds at 3 regardless of an arbitrary spec value.
            max_research_rounds = max(1, min(3, int(spec.get("max_research_rounds", 1))))
            search_runner = build_supervisor_search_runner(
                max_queries=int(spec.get("supervisor_max_queries", 3)),
                max_results_per_query=int(spec.get("supervisor_results_per_query", 5)),
            )
            emit("supervisor_search", f"enabled (max {max_research_rounds} round)")
        else:
            emit(
                "supervisor_search",
                f"DISABLED — historical evidence_cutoff ({evidence_cutoff}); "
                "fresh search would leak post-cutoff information",
            )

    # TRACK-RECORD WEIGHTING (S7). DEFAULT ON but harmless-by-construction: a model
    # must clear the resolved-sample gate before its weight leaves 1.0, so a
    # cold-start desk is equal-weighted and byte-identical to before. Best-effort — a
    # measurement hiccup degrades to equal weights, never blocks.
    model_weights: dict[str, float] = {}
    if _track_record_weights_enabled(spec):
        try:
            model_weights = ledger.recommended_model_weights(
                min_sample=_track_record_min_sample(spec)
            )
        except Exception:  # noqa: BLE001 — degrade to equal weights, never crash
            model_weights = {}
        if model_weights:
            emit(
                "track_record_weights",
                "weighted by track record: "
                + ", ".join(f"{m}={w:.2f}" for m, w in sorted(model_weights.items())),
            )

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
        alpha_extremize=alpha_extremize,
        self_fusion=self_fusion,
        on_progress=on_progress,
        search_runner=search_runner,
        max_research_rounds=max_research_rounds or 1,
        delphi_rounds=delphi_rounds,
        model_weights=model_weights or None,
    )

    # Persist the quorum as a sibling panel run. The spread_summary already carries
    # the disagreement scalar. We pass the ALREADY-resolved committed number + its
    # source so the persisted aggregate is the P0.3-resolved, terminally-calibrated
    # value — not a divergent re-pool.
    emit("record", "recording quorum panel run")
    from forecasting.ledger import allow_ledger_writes

    with allow_ledger_writes(reason="quorum_jobs.execute_job"):
        panel_run = ledger.record_panel_run(
            question_id=question.id,
            estimates=result.panel_estimates(),
            aggregation_method=result.pool_method,
            trim=result.trim,
            snapshot_id=spec.get("attach_snapshot"),
            triggered_by=spec.get("triggered_by") or "quorum",
            judge=result.judge.to_dict() if result.judge else None,
            final_probability=result.committed_probability,
            final_source=result.final_source,
            research_rounds=result.research_rounds,
            supervisor_evidence=result.supervisor_evidence,
            delphi_rounds=result.delphi_rounds,
            delphi_audit=result.delphi_audit,
        )

    # Carry the panel_run_id + aggregate on the record's annotations too, so a
    # mid-flight read (before the runtime writes the terminal result) is still honest.
    ctx.annotate("panel_run_id", panel_run["id"])
    return {"quorum_result": result.to_dict(), "panel_run_id": panel_run["id"]}


QUORUM = JobType(
    name="quorum",
    execute=execute,
    # Coarse progress (a panelist/judge/record handful — an audit trail, not a
    # storm). 0.0 means nothing is throttled, so every stage lands exactly as the old
    # per-append write did — the legacy consumers assert specific stages are present.
    min_interval_s=0.0,
    # READ-ONLY status is served by the ``forecast.quorum.status`` alias in
    # tui_gateway; the quorum has no gateway-thread progress/complete event family to
    # mirror, so no alias_namespace.
    alias_namespace=None,
    # A multi-model research + judge run: real model spend.
    spend_class="agent",
)

register(QUORUM)

__all__ = [
    "QUORUM",
    "execute",
    "start_job",
    "read_job",
    "write_job",
    "list_jobs",
    "active_jobs_by_question",
    "jobs_dir",
    "_now_iso",
    "_repo_root",
    "_truthy",
    "_supervisor_search_enabled",
    "_track_record_weights_enabled",
    "_track_record_min_sample",
    "_has_explicit_alpha_override",
    "_derive_alpha_enabled",
    "_cutoff_is_live",
]
