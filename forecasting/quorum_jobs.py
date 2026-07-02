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


def active_jobs_by_question(limit: int = 40) -> dict[str, dict[str, Any]]:
    """question_id -> {run_id, status, created_at} for the MOST RECENT still-in-flight
    quorum job (``queued`` | ``running``) per question.

    A single jobs-dir scan (no per-question I/O) so the desk workspace payload can
    badge a "quorum running" chip on the row whose auto-quorum just started, then
    poll ``forecast.quorum.status`` by the surfaced run_id. Only live jobs — a
    ``done``/``error`` job is terminal and never chipped."""
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


def new_run_id() -> str:
    return f"qr_{uuid.uuid4().hex[:12]}"


def start_job(spec: dict[str, Any], *, wait: bool = False) -> str:
    """Create a queued job and execute it (inline if ``wait`` else detached).

    ``spec`` keys: ``question_id`` (required), ``db``, ``preset``, ``models``,
    ``judge``, ``pool_method``, ``trim``, ``self_fusion``, ``samples``,
    ``triggered_by``, ``attach_snapshot``, ``active_model``, ``delphi_rounds``.
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


def resolve_active_model_id(model_cfg: Any) -> str | None:
    """Extract the active model-id STRING from the config ``model`` value.

    Since the codex auth overhaul ``config["model"]`` is a structured dict
    ({base_url, default, provider}); the canonical id is ``default`` (or legacy
    ``model``), as fallback_cmd/dump/doctor resolve it. A legacy bare string is
    tolerated. Returns None when unset. (Passing the raw dict downstream made the
    quorum's `self`/judge model a dict and blew up the panelist with
    ``'dict' object has no attribute 'lower'`` — a silent, total quorum failure.)
    """

    if isinstance(model_cfg, dict):
        return (model_cfg.get("default") or model_cfg.get("model") or "").strip() or None
    if model_cfg:
        return str(model_cfg).strip() or None
    return None


def maybe_autorun_quorum(
    ledger: Any,
    question_id: str,
    *,
    snapshot: Any,
    has_panel: bool,
    has_prior_snapshot: bool,
    forecast_origin: str | None,
    notify: Any = None,
) -> dict[str, Any] | None:
    """AUTO-RUN a quorum (detached) when one is auto-indicated but none attached.

    THE shared seam for every commit surface — the CLI ``forecast update`` verb
    AND the agent tool's ``update_forecast`` (which is what ``full_forecast``,
    the chained pipeline, and ``cycle run --agent`` commit through) — so the
    autonomous paths get the same multi-model fusion a hand-typed update does.
    The panel shape is resolved by :func:`forecasting.quorum.resolve_quorum_defaults`
    (impact/type-aware, with the single-key reality guard) and cost-bounded by
    ``quorum.max_calls`` before we spend anything.

    STRICTLY BOUNDED + FAIL-OPEN: the commit already happened, so ANY failure
    here (config, resolution, job spawn) is reported via ``notify`` and never
    blocks or corrupts it. Only fires for LIVE forecasts with no panel already
    attached, and only when ``quorum.default_enabled`` + the scope gate say so.

    ``notify`` (optional callable) receives human-readable progress lines — the
    CLI passes ``print``; the tool collects them into its result. Returns a
    structured record ``{run_id, preset, delphi_rounds, estimated_calls, reason,
    cap_note}`` when a job was started, else ``None``.
    """

    def _say(message: str) -> None:
        if notify is not None:
            notify(message)

    if has_panel or (forecast_origin or "live") != "live":
        return None
    try:
        from hermes_cli.config import load_config
        from forecasting.panel import should_run_panel
        from forecasting.quorum import (
            available_provider_slugs,
            cap_preset_by_calls,
            quorum_auto_indicated,
            resolve_quorum_defaults,
        )

        full_cfg = load_config()
        cfg = full_cfg.get("quorum", {}) or {}
        if not cfg.get("default_enabled"):
            return None
        question = ledger.get_question(question_id)
        panel_indicated = should_run_panel(
            impact=getattr(question, "impact", None),
            has_prior_snapshot=has_prior_snapshot,
        )
        if not quorum_auto_indicated(
            cfg, panel_indicated=panel_indicated, has_prior_snapshot=has_prior_snapshot
        ):
            return None

        active_model = resolve_active_model_id(full_cfg.get("model"))
        samples = 3
        defaults = resolve_quorum_defaults(
            question,
            available_providers=available_provider_slugs(),
            active_model=active_model,
            samples=samples,
        )
        preset = defaults["preset"]
        delphi_rounds = int(defaults["delphi_rounds"])
        trim = int(defaults["trim"])
        max_calls = int(cfg.get("max_calls", 12) or 12)
        preset, delphi_rounds, samples, est_calls, cap_note = cap_preset_by_calls(
            preset, delphi_rounds, max_calls=max_calls, samples=samples
        )

        judge = cfg.get("judge") or None
        self_fusion = preset == "self"
        models = None
        preset_for_spec: str | None = preset
        if self_fusion:
            if not active_model:
                _say(
                    "↳ quorum auto-run skipped: self-fusion needs a default model "
                    "(set one with `superforecasting-agent model`)."
                )
                return None
            models = [active_model] * samples
            judge = judge or active_model
            preset_for_spec = None  # models now explicit

        spec = {
            "question_id": question_id,
            # str() — the spec is JSON-persisted by write_job; a Path is not
            # serializable. ForecastLedger accepts the str form.
            "db": (str(ledger.db_path) if getattr(ledger, "db_path", None) else None),
            "preset": preset_for_spec,
            "models": models,
            "judge": judge,
            "pool_method": cfg.get("pool_method") or "trimmed_geomean_odds",
            "trim": trim,
            "self_fusion": self_fusion,
            "samples": samples,
            "attach_snapshot": getattr(snapshot, "forecast_id", None),
            "triggered_by": "auto_quorum",
            "active_model": active_model,
            "max_iterations": int(cfg.get("max_iterations", 30)),
            "model_timeout": int(cfg.get("model_timeout", 300)),
            "supervisor_search": bool(cfg.get("supervisor_search")),
            "delphi_rounds": delphi_rounds,
        }
        run_id = start_job(spec, wait=False)
        _say(
            f"↳ quorum auto-run started: {run_id} "
            f"(preset={preset}, delphi={delphi_rounds}, ~{est_calls} model calls) — "
            f"{defaults['reason']}."
        )
        if cap_note:
            _say(f"  cost cap: {cap_note}")
        _say(f"  poll with:  forecast quorum status {run_id}")
        return {
            "run_id": run_id,
            "preset": preset,
            "delphi_rounds": delphi_rounds,
            "estimated_calls": est_calls,
            "reason": defaults["reason"],
            "cap_note": cap_note,
        }
    except Exception as exc:  # noqa: BLE001 — auto-run is fail-open; the commit stands
        # The commit already happened; ANY failure here (config, resolution, job
        # spawn) degrades to a one-line note and never blocks or corrupts it.
        _say(f"↳ quorum auto-run skipped (non-fatal): {type(exc).__name__}: {exc}")
        return None


def _append_progress(job: dict[str, Any], stage: str, detail: str) -> None:
    job["progress"].append({"stage": stage, "detail": detail, "at": _now_iso()})
    write_job(job)


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
    programmatic enqueue). It governs ONLY the run_quorum/execute_job path; the
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


def execute_job(run_id: str) -> dict[str, Any]:
    """Run the quorum for ``run_id`` to completion, persisting state as it goes."""

    from forecasting.hooks.thresholds import resolve_alpha_extremize
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

        # Delphi v1 — optional single anonymous revision round. Resolved to a plain
        # int here and threaded into run_quorum (which validates {0, 1} and raises
        # ValidationError otherwise). ``0`` is the DEFAULT and keeps this path
        # byte-identical: no extra model calls, no revision round, empty delphi_audit.
        # When ``1`` fires, run_quorum emits the "delphi_start"/"delphi_done"
        # progress events through ``on_progress`` below, so they land in job progress.
        delphi_rounds = int(spec.get("delphi_rounds") or 0)

        # FOREKNOWLEDGE GUARD (mirrors the supervisor-search guard below): gate the
        # PANELIST toolset on the SAME _cutoff_is_live(evidence_cutoff) predicate.
        # A HISTORICAL cutoff (backtest/replay snapshot) builds each panelist
        # closed-book (EMPTY toolset — NO web, NO forecast_ledger.import_source_evidence,
        # which would otherwise fetch the LIVE / now-known source value). A LIVE cutoff
        # gives panelists web research only (still NO ledger-write surface — the quorum
        # job, not the panelist, aggregates + records the forecast).
        runner = make_aiagent_runner(
            max_iterations=int(spec.get("max_iterations", 30)),
            timeout=spec.get("model_timeout"),
            evidence_cutoff=evidence_cutoff,
        )

        # Panelists run concurrently, so the progress callback fires from worker
        # threads — serialise the append + file write.
        import threading

        progress_lock = threading.Lock()

        def on_progress(stage: str, detail: str) -> None:
            with progress_lock:
                _append_progress(job, stage, detail)

        # Terminal Platt calibration (AIA P0.1): resolve the per-question slope
        # ONCE here and thread it through run_quorum so the in-memory
        # QuorumResult is already calibrated. record_panel_run then persists the
        # SAME resolved number (it does NOT re-pool), so the in-memory result and
        # the durable panel_run can never diverge.
        metadata = question.metadata if isinstance(question.metadata, dict) else None
        alpha_extremize = resolve_alpha_extremize(metadata)
        # EVIDENCE-GATED EXTREMIZATION (item 6, config-gated DEFAULT OFF). When no
        # EXPLICIT per-question alpha_extremize override is set AND
        # forecasting.calibration.derive_alpha is enabled, derive the terminal Platt
        # slope from the domain's RESOLVED calibration via the validated
        # extremization gate (sqrt(3) permitted only where measurably
        # under-confident; 1.0 otherwise — fail-safe cold start). The explicit
        # metadata override always wins and is never overridden by derivation.
        if not _has_explicit_alpha_override(metadata) and _derive_alpha_enabled():
            derived = ledger.derive_extremize_alpha(question)
            if derived and derived != 1.0:
                alpha_extremize = float(derived)
                _append_progress(
                    job,
                    "derived_alpha",
                    f"terminal Platt slope {derived:.3f} from resolved calibration",
                )

        # GATE 2 (AIA P1.1, live) — wire the agentic-supervisor fresh-search loop.
        # The judge can flag an unresolved crux (information_gap +
        # clarifying_queries) and the supervisor runs FRESH web/news search to fold
        # in information the market has not yet priced — the only path to BEATING
        # the market (the closed-book LLM has no intrinsic edge). This is OPT-IN and
        # DEFAULT OFF: only when the spec (or the quorum config) turns it on do we
        # construct a search_runner and allow one research round. With it off,
        # search_runner stays None so run_quorum is byte-identical to before
        # (research_rounds 0, supervisor_evidence empty).
        search_runner = None
        max_research_rounds = 0
        if _supervisor_search_enabled(spec):
            # LEAKAGE GUARD (enforced in code, not convention): a fresh web search
            # returns PRESENT-DAY content, which cannot be pinned to a historical
            # evidence_cutoff. So the supervisor search only runs when the forecast
            # is effectively LIVE (no cutoff, or a cutoff within tolerance of now).
            # A historical cutoff — e.g. a backtest/replay snapshot — disables it,
            # so now-known information can never be folded into a past-pinned forecast.
            if _cutoff_is_live(evidence_cutoff):
                from forecasting.supervisor_search import build_supervisor_search_runner

                # Clamp the per-run bounds: each round re-runs the FULL panel+judge,
                # so cap rounds at 3 regardless of an arbitrary spec value.
                max_research_rounds = max(1, min(3, int(spec.get("max_research_rounds", 1))))
                search_runner = build_supervisor_search_runner(
                    max_queries=int(spec.get("supervisor_max_queries", 3)),
                    max_results_per_query=int(spec.get("supervisor_results_per_query", 5)),
                )
                _append_progress(
                    job, "supervisor_search", f"enabled (max {max_research_rounds} round)"
                )
            else:
                _append_progress(
                    job, "supervisor_search",
                    f"DISABLED — historical evidence_cutoff ({evidence_cutoff}); "
                    "fresh search would leak post-cutoff information",
                )

        # TRACK-RECORD WEIGHTING (S7). DEFAULT ON but harmless-by-construction: a
        # model must clear the resolved-sample gate before its weight leaves 1.0, so
        # a cold-start desk is equal-weighted and byte-identical to before. Best-
        # effort — a measurement hiccup degrades to equal weights, never blocks.
        model_weights: dict[str, float] = {}
        if _track_record_weights_enabled(spec):
            try:
                model_weights = ledger.recommended_model_weights(
                    min_sample=_track_record_min_sample(spec)
                )
            except Exception:  # noqa: BLE001 — degrade to equal weights, never crash
                model_weights = {}
            if model_weights:
                _append_progress(
                    job,
                    "track_record_weights",
                    "weighted by track record: "
                    + ", ".join(
                        f"{m}={w:.2f}" for m, w in sorted(model_weights.items())
                    ),
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

        # Persist the quorum as a sibling panel run. The spread_summary already
        # carries the disagreement scalar (see panel.aggregate_panel_estimates).
        # We pass the ALREADY-resolved committed number + its source so the
        # persisted aggregate is the P0.3-resolved, terminally-calibrated value
        # — not a divergent re-pool.
        _append_progress(job, "record", "recording quorum panel run")
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
    # A detached worker is a fresh process: discover plugins so the panelists'
    # web search AND the supervisor fresh-search runner have their providers
    # (ddgs/brave-free/tavily/…) registered — exactly as gateway.py / oneshot.py
    # do at boot. Without this the live supervisor search silently finds nothing.
    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:  # noqa: BLE001 — search/extract degrade gracefully if discovery fails
        pass
    execute_job(sys.argv[1])
