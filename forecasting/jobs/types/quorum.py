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

Detach is a CHILD PROCESS (``python -m superforecasting_agent.worker run <job_id>``, fresh
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
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from superforecasting_agent.constants import get_agent_home

from forecasting.jobs.detached import spawn_detached_job
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import JobType, register


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── legacy qr_ store (read-shim + test/back-compat seeding) ───────────────────
#
# NEW runs live on the shared JobStore (``{home}/jobs/``); these helpers keep the
# OLD ``{home}/quorum_runs/`` dir readable/writable so a ``qr_`` record that
# predates the migration still answers a status/active query verbatim.


def jobs_dir() -> Path:
    path = get_agent_home() / "quorum_runs"
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
    # UPGRADE 2 — surface the deviation bet id (like panel_run_id) so the desk/CLI
    # can see a named-edge bet the run just recorded (None when no bet fired).
    deviation_bet_id = result.get("deviation_bet_id")
    if deviation_bet_id is None:
        deviation_bet_id = ann.get("deviation_bet_id")
    return {
        "run_id": record.job_id,
        "question_id": (record.spec or {}).get("question_id"),
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "spec": record.spec,
        "progress": record.progress,
        "panel_run_id": panel_run_id,
        "deviation_bet_id": deviation_bet_id,
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
        # include_legacy=False: the store's generic read-shim would drop the rich
        # legacy fields (progress/panel_run_id/result); this alias reads a surviving
        # qr_ file VERBATIM below to preserve them byte-for-byte.
        return _to_legacy(store.read(run_id, include_legacy=False))
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
        # include_legacy=False: only the NEW job_ records here; the qr_ glob below
        # supplies surviving legacy runs VERBATIM (rich legacy shape preserved).
        for record in JobStore().list(limit=max(limit * 4, 200), include_legacy=False):
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

    Detach is a CHILD PROCESS (``python -m superforecasting_agent.worker run <job_id>``, fresh
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

    spawn_detached_job(job_id)
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

    DEFAULT ON (the audit's finding #1: the proven edge had fired 0/223 times while
    this was default-OFF). The per-run spec ``supervisor_search`` wins (set by
    ``forecast quorum --supervisor-search``/``--no-supervisor-search``); otherwise
    the fleet-wide config flag ``quorum.supervisor_search`` (default True) governs,
    and a missing key / config-load failure ALSO defaults ON — so a bare
    programmatic enqueue still gets the edge.

    This ON default is LIVE-only-safe by construction: enabling it here only
    CONSTRUCTS a search_runner; :func:`execute` still gates the actual fresh search
    behind :func:`_cutoff_is_live`, so a historical evidence_cutoff
    (backtest/replay) disables it and no post-cutoff information can leak. It governs
    ONLY the run_quorum/execute path; the market-nightly path uses an injected
    agent_forecaster seam and is unaffected.
    """

    if "supervisor_search" in spec:
        return _truthy(spec.get("supervisor_search"))
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration().get("quorum", {})
    except Exception:  # noqa: BLE001 — config optional; harmless default ON
        return True
    if not isinstance(cfg, dict) or "supervisor_search" not in cfg:
        return True
    return _truthy(cfg.get("supervisor_search"))


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
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration().get("quorum", {})
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
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration().get("quorum", {})
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
        from superforecasting_agent.storage.configuration import read_configuration

        cal = (read_configuration().get("forecasting", {}) or {}).get("calibration", {})
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


# ── FIX B: market-anchor discipline config + extraction ───────────────────────


def _market_anchor_enabled(spec: dict[str, Any]) -> bool:
    """Whether to inject the current market price as the outside-view anchor.

    DEFAULT ON. The per-run spec ``market_anchor`` wins; otherwise the fleet-wide
    ``quorum.market_anchor`` config (default True) governs. Any config/import
    failure defaults ON — the market-as-prior doctrine is the safe default.
    """

    if "market_anchor" in spec:
        return _truthy(spec.get("market_anchor"))
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration().get("quorum", {})
    except Exception:  # noqa: BLE001 — config optional; doctrine default ON
        return True
    if not isinstance(cfg, dict) or "market_anchor" not in cfg:
        return True
    return _truthy(cfg.get("market_anchor"))


def _market_anchor_threshold_pp(spec: dict[str, Any]) -> float:
    """The unjustified-deviation threshold in percentage points (default 10pp).

    Per-run spec ``market_anchor_deviation_pp`` wins, else the fleet-wide
    ``quorum.market_anchor_deviation_pp``. Fails safe to 10.0 on any parse error.
    """

    if "market_anchor_deviation_pp" in spec:
        try:
            return max(0.0, float(spec.get("market_anchor_deviation_pp")))
        except (TypeError, ValueError):
            return 10.0
    try:
        from superforecasting_agent.storage.configuration import read_configuration

        cfg = read_configuration().get("quorum", {})
        if isinstance(cfg, dict) and "market_anchor_deviation_pp" in cfg:
            return max(0.0, float(cfg.get("market_anchor_deviation_pp")))
    except Exception:  # noqa: BLE001 — config optional
        pass
    return 10.0


_MARKET_SOURCE_PREFIXES = ("polymarket", "kalshi", "manifold", "metaculus", "market")


def extract_market_anchor(ledger: Any, question: Any, snapshot: Any) -> float | None:
    """Pull the current de-vigged market price for a market-linked BINARY question.

    Prefers a market-typed component on the current snapshot's
    ``ensemble_components`` (source slug like ``polymarket:…``); falls back to the
    first market-typed ``baseline_comparison`` (de-vigged through the same helper
    :mod:`forecasting.market_ensemble` uses). Returns ``None`` when the question is
    not binary or carries no market data — so a non-market question keeps the pre-FIX
    behaviour exactly (no anchor, no pull).
    """

    try:
        if getattr(question.outcome_space, "type", None) != "binary":
            return None
    except Exception:  # noqa: BLE001 — a malformed question carries no anchor
        return None

    from forecasting.market_ensemble import _coerce_prob, _devig_market_baseline

    # 1) A market/crowd component on the current snapshot.
    components = getattr(snapshot, "ensemble_components", None) if snapshot else None
    if isinstance(components, dict) and components:
        try:
            from forecasting.ensembles import _component_rows

            for row in _component_rows(components):
                source = str(row.get("source") or "").strip().lower()
                if any(source.startswith(pfx) for pfx in _MARKET_SOURCE_PREFIXES):
                    prob = _coerce_prob(row.get("probability"))
                    if prob is not None:
                        return prob
        except Exception:  # noqa: BLE001 — component read is best-effort
            pass

    # 2) First market-typed baseline comparison (de-vigged).
    try:
        from forecasting import bayes_toolkit

        market_types = {"market_price", "market", "imported_market"}
        for baseline in ledger.list_baseline_comparisons(question.id):
            if str(baseline.get("baseline_type") or "").lower() not in market_types:
                continue
            raw = ledger._baseline_probability_value(baseline)
            devigged = _devig_market_baseline(raw, baseline, bayes_toolkit)
            if devigged is not None:
                return devigged
    except Exception:  # noqa: BLE001 — baseline read is best-effort
        pass
    return None


def extract_outside_view_prior(ledger: Any, question: Any) -> float | None:
    """The recorded outside-view PRIOR used as the A3 shrink anchor when a question
    carries NO live market.

    BLF A3's anchor is the market price where linked, ELSE this recorded prior — so a
    contested NON-market panel still shrinks toward the outside view rather than
    running free. Pulls the first ``base_rate`` baseline comparison (a reference-class
    / status-quo rate the desk recorded) and returns its probability in ``(0, 1)``;
    ``None`` when the question carries no such prior, so A3 stays a no-op there.
    """

    try:
        for baseline in ledger.list_baseline_comparisons(question.id):
            if str(baseline.get("baseline_type") or "").lower() != "base_rate":
                continue
            raw = ledger._baseline_probability_value(baseline)
            if raw is None:
                continue
            prob = float(raw)
            if 0.0 < prob < 1.0:
                return prob
    except Exception:  # noqa: BLE001 — best-effort; no prior on any read failure
        return None
    return None


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
    from forecasting.jobs.policy import ActionClass
    from forecasting.ledger import ForecastLedger
    from forecasting.protocol import build_context_packet
    from forecasting.quorum import (
        DEFAULT_JUDGE_MODEL,
        make_aiagent_runner,
        resolve_connected_panel,
        resolve_models,
        resolve_trial_count,
        run_quorum,
    )

    # Arc-9 approval gate: a quorum SPENDS (several panelists each researching + a
    # judge synthesis) and WRITES a sibling panel run through the ledger gate. It
    # authorizes both ONCE up front — before resolving the panel — so an ask/never
    # cell parks or refuses before any model is dispatched. AUTO under every default
    # (llm_spend in ``cycle``/``cron`` is auto-but-BOUNDED by ``cap_preset_by_calls``).
    ctx.authorize(ActionClass.LLM_SPEND, "multi-model Delphi panel + judge synthesis")
    ctx.authorize(ActionClass.LEDGER_WRITES, "record the quorum as a sibling panel run")

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

    # FIX A — resolve a multi-provider preset to the user's ACTUALLY-authed providers.
    # The built-in presets name OpenRouter-format ids; on a host with no OpenRouter
    # key every panelist would fail ("agent protocol response is empty"). Rebuild the
    # panel from connected providers (their native default models, routed via the
    # provider:model split) or fall back to an honestly-labeled self-fusion. Only runs
    # for a preset-shaped run (no explicit --models, not already self-fusion); an
    # unknown provider picture fails open and keeps the preset verbatim.
    panel_resolution_note: str | None = None
    a_preset = spec.get("preset")

    # OPERATOR-PINNED PANEL (QUORUM_PANEL_MODELS) — precedence over BOTH the preset
    # expansion and the connected-provider rebuild. The CLI already resolves this into
    # spec["models"]; this covers the non-CLI callers (gateway / autorun) whose spec did
    # not. A non-callable entry raises ValidationError, which the runtime turns into an
    # honest whole-job error rather than a silent drop.
    panel_pinned = False
    if not spec.get("models"):
        from forecasting.quorum import resolve_configured_panel

        configured = resolve_configured_panel()
        if configured:
            models = configured["models"]
            if configured.get("judge") and not spec.get("judge"):
                judge_model = configured["judge"]
            self_fusion = False
            panel_pinned = True
            panel_resolution_note = "QUORUM_PANEL_MODELS -> " + ", ".join(models)
            emit("panel_resolution", panel_resolution_note)

    if not spec.get("models") and not panel_pinned and a_preset not in (None, "self") and not self_fusion:
        panel = resolve_connected_panel(
            a_preset,
            active_model=spec.get("active_model"),
            active_provider=spec.get("active_provider"),
            samples=int(spec.get("samples", 3) or 3),
        )
        if panel.get("rebuilt"):
            models = panel["models"]
            # Only override the judge when the caller did not pin one — a rebuilt
            # panel's native/self judge is callable where the OpenRouter default is not.
            if not spec.get("judge") and panel.get("judge"):
                judge_model = panel["judge"]
            self_fusion = bool(panel.get("self_fusion")) or self_fusion
            panel_resolution_note = panel.get("label")
            emit("panel_resolution", panel_resolution_note or "")

    # Delphi v1 — optional single anonymous revision round. Resolved to a plain int
    # here and threaded into run_quorum (which validates {0, 1}). ``0`` is the DEFAULT
    # and keeps this path byte-identical: no extra model calls, empty delphi_audit.
    delphi_rounds = int(spec.get("delphi_rounds") or 0)

    # Multi-trial per panelist (BLF A2). The spec ``trials`` (already cost-capped by
    # the dispatch layer) wins; absent it, resolve K from the question's impact
    # (high-impact → 3, else 1). ``1`` is the DEFAULT and keeps this path byte-
    # identical — one draw per seat, no pooling. The extra spend rides the SAME
    # LLM_SPEND authorize (above) + cost caps the panel width does.
    if spec.get("trials"):
        trials = max(1, int(spec.get("trials")))
    else:
        trials, trials_reason = resolve_trial_count(question)
        if trials > 1:
            emit("trials", f"{trials} trials/panelist — {trials_reason}")

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

    # DETERMINISTIC SPECIALISTS (BLF A5). For a CONTINUOUS question with a derivable
    # numeric threshold, register climatology-KNN / seasonal-naive / living-model
    # panelists under stable ``model:*`` ids and wrap the runner so those seats
    # dispatch to deterministic estimators. It ADDS seats; the S7.5 track-record
    # weighting (threaded below) weighs their votes empirically. A strict no-op for
    # binary/categorical questions — every current quorum question — so the LLM-only
    # panel stays byte-identical. Any seat whose series is unreachable DECLINES
    # (recorded as a labeled, excluded panelist). Fail-open: any wiring error
    # degrades to the LLM-only panel and never blocks the run.
    try:
        from forecasting.specialists import attach_specialists, specialist_seats_for

        if specialist_seats_for(question):
            as_of_date = None
            if evidence_cutoff:
                try:
                    as_of_date = datetime.fromisoformat(
                        str(evidence_cutoff).replace("Z", "")
                    ).date()
                except ValueError:
                    as_of_date = None
            before = len(models)
            models, runner = attach_specialists(models, runner, question, as_of=as_of_date)
            added = [m for m in models[before:] if m.startswith("model:")]
            if added:
                emit("specialists", "registered deterministic specialists: " + ", ".join(added))
    except Exception as exc:  # noqa: BLE001 — specialists are additive; never block the panel
        emit("specialists", f"skipped (non-fatal): {type(exc).__name__}: {exc}")

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

    # MARKET-ANCHOR DISCIPLINE (FIX B). For a market-linked binary question pull the
    # current de-vigged price in as the outside-view anchor: shown to panelists, the
    # judge must justify deviating more than the threshold, and an unjustified
    # over-deviation is pulled back toward the market. DEFAULT ON; a non-market
    # question yields None and the path is byte-identical to before.
    market_anchor: float | None = None
    market_anchor_threshold = _market_anchor_threshold_pp(spec)
    if _market_anchor_enabled(spec):
        market_anchor = extract_market_anchor(ledger, question, snapshot)
        if market_anchor is not None:
            emit(
                "market_anchor",
                f"outside-view anchor {market_anchor:.3f} "
                f"(deviation discipline >{market_anchor_threshold:.0f}pp needs justification)",
            )

    # BLF A3 anchor fallback: with no live market, the variance-adaptive pool shrink
    # anchors on the recorded outside-view prior (a base-rate baseline) instead, so a
    # contested non-market panel still leans on the outside view. No prior → None → A3
    # is a no-op, byte-identical to before.
    outside_view_prior: float | None = None
    if market_anchor is None:
        outside_view_prior = extract_outside_view_prior(ledger, question)
        if outside_view_prior is not None:
            emit(
                "outside_view_prior",
                f"A3 shrink anchor {outside_view_prior:.3f} "
                "(recorded base rate; no live market)",
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
        market_anchor=market_anchor,
        market_anchor_threshold_pp=market_anchor_threshold,
        outside_view_prior=outside_view_prior,
        trials=trials,
    )

    # Persist the quorum as a sibling panel run. The spread_summary already carries
    # the disagreement scalar. We pass the ALREADY-resolved committed number + its
    # source so the persisted aggregate is the P0.3-resolved, terminally-calibrated
    # value — not a divergent re-pool.
    emit("record", "recording quorum panel run")
    from forecasting.ledger import allow_ledger_writes

    # ARTIFACT STAMPING: carry the run's process provenance (research/delphi rounds,
    # whether supervisor search was wired), the market-anchor outcome, the self-fusion
    # caveat, and the connected-provider panel label into the persisted panel run so
    # the artifact the desk reads is honest — not just the raw columns.
    market_anchor_record: dict[str, Any] | None = None
    if result.market_price is not None:
        market_anchor_record = {
            "market_price": round(float(result.market_price), 6),
            "threshold_pp": round(float(market_anchor_threshold), 3),
            "deviation_pp": (
                round(float(result.market_deviation_pp), 3)
                if result.market_deviation_pp is not None
                else None
            ),
            "justification": result.market_justification,
            "pull_applied": bool(result.market_pull_applied),
        }
    # UPGRADE 2 — the deviation ledger. Create a bet ONLY on a LIVE run (never a
    # backtest: foreknowledge-gated by the SAME _cutoff_is_live predicate the
    # supervisor search uses, so a resolved-question replay can never fabricate an
    # edge) when the reconciled verdict deviates from the market anchor past the
    # threshold WITH a named edge that was NOT pulled back to the price — a genuine
    # conviction bet against the market. A within-threshold verdict, or one whose
    # unjustified deviation was pulled toward the market, is deliberately NOT a bet.
    live_run = _cutoff_is_live(evidence_cutoff)
    make_bet = (
        live_run
        and result.market_price is not None
        and result.market_deviation_pp is not None
        and result.market_deviation_pp > market_anchor_threshold
        and not result.market_pull_applied
        and bool((result.market_justification or "").strip())
    )
    # BLF A5 — the specialist-seat summary. result.forecasts KEEPS declined/errored
    # seats (panel_estimates() drops them before persistence), so this is the only place
    # a SpecialistDeclined seat is captured for the gate. Absent (None) when the panel
    # offered no specialist seats, so a non-specialist run stays byte-compatible.
    from forecasting.specialists import SPECIALIST_IDS as _SPECIALIST_IDS

    _spec_ran = [f.model for f in result.forecasts if f.model in _SPECIALIST_IDS and f.error is None]
    _spec_declined = [
        {"seat": f.model, "reason": f.error}
        for f in result.forecasts
        if f.model in _SPECIALIST_IDS and f.error is not None
    ]
    specialist_summary = (
        {"ran": _spec_ran, "declined": _spec_declined} if (_spec_ran or _spec_declined) else None
    )
    deviation_bet_id: str | None = None
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
            supervisor_search_enabled=search_runner is not None,
            market_anchor=market_anchor_record,
            pseudo_diversity_caveat=result.pseudo_diversity_caveat,
            panel_resolution_note=panel_resolution_note,
            blind_pool=result.blind_pool,
            reconciled_pool=result.reconciled_pool,
            pool_shrinkage=result.pool_shrinkage,
            specialist_summary=specialist_summary,
        )
        if make_bet:
            bet = ledger.record_deviation_bet(
                question_id=question.id,
                panel_run_id=panel_run["id"],
                market_price=float(result.market_price),
                blind_pool=result.blind_pool,
                reconciled_verdict=float(result.committed_probability),
                deviation_pp=float(result.market_deviation_pp),
                named_edge=result.market_justification,
                threshold_pp=float(market_anchor_threshold),
                forecast_origin="live",
            )
            deviation_bet_id = bet["id"]
            emit(
                "deviation_bet",
                f"named-edge bet vs market {float(result.market_price):.3f}: verdict "
                f"{float(result.committed_probability):.3f} "
                f"({float(result.market_deviation_pp):.1f}pp, blind_pool "
                f"{result.blind_pool if result.blind_pool is None else round(result.blind_pool, 3)})",
            )

    # Carry the panel_run_id + aggregate on the record's annotations too, so a
    # mid-flight read (before the runtime writes the terminal result) is still honest.
    ctx.annotate("panel_run_id", panel_run["id"])
    if deviation_bet_id:
        ctx.annotate("deviation_bet_id", deviation_bet_id)
    return {
        "quorum_result": result.to_dict(),
        "panel_run_id": panel_run["id"],
        "deviation_bet_id": deviation_bet_id,
    }


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
    "_truthy",
    "_supervisor_search_enabled",
    "_track_record_weights_enabled",
    "_track_record_min_sample",
    "_has_explicit_alpha_override",
    "_derive_alpha_enabled",
    "_cutoff_is_live",
]
