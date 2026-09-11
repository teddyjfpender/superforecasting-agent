"""Gateway RPCs for the ``forecast.*`` family — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a) — the biggest and hottest RPC family. Every
``forecast.*`` handler (dashboard, warnings.*, workspace, theses, bench,
quorum.status, question.readiness, triage.*, schedule.status, reviews.next,
onboard_*, calibration, hooks.*, command, reforecast, config[.set], question)
moved here VERBATIM, along with the calibration-breakdown helpers used only by
``forecast.calibration``. The local ``rpc_validated`` decorator captures the
handlers into ``_REGISTRARS``; ``server.py`` calls :func:`register` (at load AND
on ``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract), which replays
them through the REAL ``server.rpc_validated`` so the registration lands in the
same ``tui_gateway.server._methods`` dispatch dict — the wire stays
byte-identical.

Note: ``forecast.warnings.automode.*`` / ``jobs.*`` / ``events.replay`` are NOT
here — they are registered by ``jobs_rpc`` / ``event_log`` (Arc B), whose
registration blocks stay in core.

Only three core names are monkeypatched by the test suite and so are reached via
the ``_core.`` call-time hop (all in ``forecast.reviews.next``):
``_nightly_self_check_job`` and the mutable ``_review_sweep_next_tick_at`` /
``_review_sweep_running`` sweep-state globals. ``_ok`` / ``_err`` / ``logger``
are not patched — imported bare from core.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys

import tui_gateway.server as _core
from tui_gateway.server import _err, _ok, logger

# Handlers captured at import; replayed into the gateway by register() so they
# survive a server module reload (the re-entrant sibling seam).
_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved forecast.* handler into ``server._methods``."""
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]


@rpc_validated("forecast.dashboard")
def _(rid, params: dict) -> dict:
    try:
        from forecasting.dashboard import build_dashboard_summary, render_dashboard_text

        limit = int(params.get("limit") or 20)
        fast = bool(params.get("fast") or params.get("summary_only"))
        summary = build_dashboard_summary(limit=limit, fast=fast)
        return _ok(rid, {"summary": summary, "output": render_dashboard_text(summary)})
    except Exception as e:
        return _err(rid, 5008, str(e))


# ── Warning resolution (open alert_events backlog) ────────────────────────────
# The desk's "drain the open warnings" surface. `list` is read-only; `resolve`
# resolves ONE alert through the gated dispatcher.
#
# `automode.run` / `automode.cancel` are no longer defined here: they moved to the
# ONE detached-job runtime (Arc B) and are registered as thin ALIASES over it by
# `tui_gateway/jobs_rpc.py` (see the registration below). The hand-written
# per-warning throttle + daemon-thread body that used to live here are gone — the
# coalescing (the 1,300-event storm guard) is now structural in JobContext.


@rpc_validated("forecast.warnings.list")
def _(rid, params: dict) -> dict:
    """Group the open warning backlog by reason (counts + priority + recommended
    action). Read-only — mirrors `forecast warnings list`."""
    try:
        from forecasting import warnings as fwarn
        from forecasting.ledger import ForecastLedger

        scope = params.get("scope") or None
        reason = params.get("reason") or None
        limit = params.get("limit")
        summary = fwarn.summarize_open_warnings(
            ForecastLedger(),
            scope=scope,
            reason=reason,
            limit=int(limit) if limit is not None else None,
        )
        return _ok(rid, summary)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.warnings.aggregate")
def _(rid, params: dict) -> dict:
    """Fold the FULL open warning backlog into the 4 operator tiers (free / agent /
    manual + the agent-tier ``stale`` sub-bucket) with per-tier + per-reason totals
    and a ``headline`` ``{total, free, agent, manual}``. Read-only; counts are
    server-side UNTRUNCATED (no ``limit`` — the dashboard headline must reflect the
    whole backlog). Mirrors `forecast.warnings.list` scope/reason filtering."""
    try:
        from forecasting import warnings as fwarn
        from forecasting.ledger import ForecastLedger

        scope = params.get("scope") or None
        reason = params.get("reason") or None
        aggregate = fwarn.aggregate_open_warnings(
            ForecastLedger(),
            scope=scope,
            reason=reason,
        )
        return _ok(rid, aggregate)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.warnings.resolve")
def _(rid, params: dict) -> dict:
    """Resolve ONE open alert through the gated dispatcher and ack ONLY on real
    work. ``alert_id`` may be an ``al_*`` id (resolve that one) or a scope ref
    (resolve every open alert for it, worst/oldest first)."""
    try:
        from forecasting import warnings as fwarn
        from forecasting.cron_runner import build_warning_runners
        from forecasting.ledger import ForecastLedger, allow_ledger_writes

        target = str(params.get("alert_id") or "").strip()
        if not target:
            return _err(rid, 5008, "alert_id is required")
        ledger = ForecastLedger()
        now = params.get("now")
        open_alerts = ledger.list_alerts(unresolved_only=True)
        if target.startswith("al_"):
            selected = [a for a in open_alerts if a.id == target]
        else:
            selected = [w.alert for w in fwarn.iter_warnings(ledger, scope=target)]
        if not selected:
            return _err(rid, 5008, f"no open alert for {target}")

        # No LLM reforecast runner in the synchronous RPC path (opt-in only) — the
        # autopilot + score runners are the gated, non-LLM real work.
        runners = build_warning_runners(ledger, now=now)
        results = []
        with allow_ledger_writes(reason="forecast_warnings_resolve"):
            for alert in selected:
                results.append(fwarn.resolve_alert(ledger, alert, runners=runners, now=now))
        return _ok(rid, {"results": results, "count": len(results)})
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.warnings.dismiss")
def _(rid, params: dict) -> dict:
    """DISMISS (silence) a matching group of OPEN alerts — a RECORDED human silence,
    NOT a resolution.

    Selects the open backlog matching ``scope`` / ``reason`` (substring) / ``kind``
    (a ResolutionKind or list) — or an explicit ``alert_id`` / ``alert_ids`` — and
    bulk-sets ``acknowledged_at`` WITHOUT invoking any runner or moving any forecast.
    It stamps a dismissal audit trail (note + actor + ``dismissed_at`` +
    ``dismiss_reason`` + TTL) so the silence is auditable and visibly distinct from a
    runner-resolution. A non-empty ``note`` and ``actor`` are REQUIRED (no silent
    mass-dismiss). The silence is bounded: the group RE-SURFACES after ``ttl_days``
    (default 7) if the condition still holds."""
    try:
        from forecasting import warnings as fwarn
        from forecasting.ledger import ForecastLedger, allow_ledger_writes

        note = str(params.get("note") or "").strip()
        if not note:
            return _err(rid, 5008, "note is required to dismiss alerts (no silent mass-dismiss)")
        actor = str(params.get("actor") or "").strip()
        if not actor:
            return _err(rid, 5008, "actor is required to dismiss alerts")

        ledger = ForecastLedger()
        now = params.get("now")
        ttl_days = params.get("ttl_days")

        explicit = params.get("alert_ids") or ([params["alert_id"]] if params.get("alert_id") else None)
        scope = params.get("scope") or None
        reason = params.get("reason") or None
        kind = params.get("kind") or params.get("kinds") or None
        kinds = None
        if kind is not None:
            kinds = kind if isinstance(kind, (list, tuple)) else [kind]

        if explicit:
            open_alerts = {a.id: a for a in ledger.list_alerts(unresolved_only=True)}
            selected_ids = [aid for aid in explicit if aid in open_alerts]
            label = "alert_ids=" + ",".join(str(a) for a in explicit)
        else:
            if scope is None and reason is None and kinds is None:
                return _err(
                    rid, 5008,
                    "a selection (scope, reason, kind, or alert_id) is required to dismiss",
                )
            # Validate the kind filter loudly (a typo must not silently match nothing).
            try:
                warnings = fwarn.select_open_warnings(
                    ledger, scope=scope, reason=reason, kinds=kinds
                )
            except ValueError as ve:
                return _err(rid, 5008, str(ve))
            selected_ids = [w.id for w in warnings]
            parts = []
            if scope:
                parts.append(f"scope={scope}")
            if reason:
                parts.append(f"reason={reason}")
            if kinds:
                parts.append("kind=" + ",".join(str(k) for k in kinds))
            label = "; ".join(parts)

        if not selected_ids:
            return _ok(rid, {"dismissed": [], "count": 0, "matched": 0})

        with allow_ledger_writes(reason="forecast_warnings_dismiss"):
            dismissed = ledger.dismiss_alerts(
                selected_ids,
                note=note,
                actor=actor,
                dismiss_reason=label,
                ttl_days=int(ttl_days) if ttl_days is not None else None,
                now=now,
            )
        return _ok(rid, {
            "dismissed": [
                {
                    "alert_id": a.id,
                    "reason": a.reason,
                    "scope_ref": a.scope_ref,
                    "dismissed_at": a.dismissed_at,
                    "dismiss_note": a.dismiss_note,
                    "dismiss_actor": a.dismiss_actor,
                    "dismiss_reason": a.dismiss_reason,
                    "dismiss_ttl_days": a.dismiss_ttl_days,
                }
                for a in dismissed
            ],
            "count": len(dismissed),
            "matched": len(selected_ids),
        })
    except ValueError as e:
        return _err(rid, 5008, str(e))
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.workspace")
def _(rid, params: dict) -> dict:
    try:
        from forecasting.dashboard import build_workspace_payload

        # Default high so the desk loads the full active book (the client filters
        # locally; a small cap silently hides the oldest forecasts).
        limit = int(params.get("limit") or 1000)
        # The navigable LIST + skinny panel never render `related` or
        # `relevant_lessons` (only the detail modal does, and it re-fetches
        # forecast.question per selection), so skip those per-question N^2/N+1
        # walks here — the bulk of the desk's load time. History only needs to
        # cover the sparkline + the 1MO window delta, so 40 points is plenty.
        payload = build_workspace_payload(
            limit=limit,
            include_related=False,
            include_lessons=False,
            history_limit=40,
        )
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.theses")
def _(rid, params: dict) -> dict:
    # Standalone thesis master list (health / score / delta / coverage / members) for a
    # dedicated thesis dashboard — without shipping the whole forecast workspace.
    try:
        from forecasting.application.aggregate_summaries import build_factor_summary, build_thesis_summary
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()  # one ledger for both scans (avoid a double schema-init)
        return _ok(rid, {"theses": build_thesis_summary(ledger=ledger), "factors": build_factor_summary(ledger=ledger)})
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.bench")
def _(rid, params: dict) -> dict:
    # READ-ONLY ForecastBench backtest scoreboard: per-question agent vs de-vigged
    # market-freeze Brier + the paired aggregate. Never mutates the ledger; backs
    # the desk's separate "Bench" lens (it is NOT the live organic-forecast desk).
    try:
        from forecasting.dashboard import build_bench_scoreboard

        limit = params.get("limit")
        payload = build_bench_scoreboard(limit=int(limit) if limit is not None else None)
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.quorum.status")
def _(rid, params: dict) -> dict:
    """READ-ONLY status/progress for a detached quorum background job.

    Given a ``run_id``, returns the job's ``status`` (queued|running|done|error),
    the ordered ``progress`` steps, the ``panel_run_id`` once recorded, and the
    ``result`` summary (aggregate/committed probability, disagreement, per-model
    forecasts, degraded flag). Reuses :func:`forecasting.jobs.types.quorum.read_job`
    (the JobStore record + the legacy ``qr_`` read-shim); never runs a quorum or
    mutates the ledger. Backs a later TUI surface.
    """
    try:
        from forecasting.jobs.types.quorum import read_job

        run_id = str(params.get("run_id") or "").strip()
        if not run_id:
            return _err(rid, 5008, "forecast.quorum.status requires a run_id")
        try:
            job = read_job(run_id)
        except FileNotFoundError as exc:
            return _err(rid, 5008, str(exc))
        result = job.get("result") or {}
        return _ok(
            rid,
            {
                "run_id": job.get("run_id"),
                "status": job.get("status"),
                "question_id": job.get("question_id"),
                "panel_run_id": job.get("panel_run_id"),
                "progress": job.get("progress") or [],
                "error": job.get("error"),
                "result": result,
                "degraded": bool(result.get("degraded")),
            },
        )
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.question.readiness")
def _(rid, params: dict) -> dict:
    """READ-ONLY machine-readiness composite for ONE question (the settings modal).

    Returns ``{question_id, title, score (0-100), src_count, gaps:[{key, label,
    fix_hint}]}`` — the hidden per-question workability parameters (watched sources,
    structured components, reference classes, executable triggers, an enabled review
    schedule, close_time/impact/resolution rule) and the EXACT operator fix for each
    unmet one. Never mutates the ledger."""
    try:
        from forecasting.ledger import ForecastLedger
        from forecasting.readiness_lens import build_question_readiness

        qid = str(params.get("question_id") or "").strip()
        if not qid:
            return _err(rid, 5008, "forecast.question.readiness requires a question_id")
        ledger = ForecastLedger()
        try:
            payload = build_question_readiness(ledger, qid)
        except Exception as exc:  # noqa: BLE001 — unknown id / read failure
            return _err(rid, 5008, str(exc))
        return _ok(rid, payload)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.triage.contested")
def _(rid, params: dict) -> dict:
    """READ-ONLY list of CONTESTED triage staging rows awaiting an operator label.

    These are the auto-labeler calls the contested-routing loop disputed (near the
    decision boundary, or a verifier disagreed): each carries its question ref, the
    auto label, the model's rationale, and the linked alert id. Un-adjudicated only
    (``expert_label`` still unset) so the list is exactly the open hand-label work —
    the same rows the CLI ``forecast triage contested`` surfaces. Adjudicate via
    ``forecast.triage.relabel`` (which records the expert label AND acks the alert).
    """
    try:
        from forecasting.ledger import ForecastLedger

        try:
            limit = int(params.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        ledger = ForecastLedger()
        question_id = params.get("question_id") or params.get("question") or None
        rows = ledger.list_triage_labels(
            question_id=str(question_id) if question_id else None,
            contested=True,
            adjudicated=False,
            limit=max(1, min(limit, 500)),
        )
        contested = [
            {
                "id": row.get("id"),
                "question_id": row.get("question_id"),
                "candidate_ref": row.get("candidate_ref"),
                "title": row.get("title") or "",
                "summary": row.get("summary") or "",
                "url": row.get("url"),
                "source": row.get("source"),
                "auto_label": row.get("auto_label"),
                "materiality": row.get("materiality"),
                "relevance": row.get("relevance"),
                "rationale": row.get("rationale") or "",
                "alert_id": row.get("alert_id"),
                "created_at": row.get("created_at"),
            }
            for row in rows
        ]
        return _ok(rid, {"contested": contested, "count": len(contested)})
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.triage.relabel")
def _(rid, params: dict) -> dict:
    """Record an operator expert label for a contested triage row + ACK its alert.

    Routes through the SAME ``relabel_route`` tool action the CLI + agent use (one
    place owns the triage logic): sets ``expert_label``/``triage_label`` +
    ``label_source='expert'``, clears ``contested``, and acknowledges the linked
    contested_label alert because the real adjudication work was done (never a bare
    ack). ``label`` must be one of relevant_interesting | relevant_uninteresting |
    irrelevant. Accepts a single ``{label_id, label}`` or bulk ``adjudications``.
    """
    label_id = params.get("label_id")
    label = params.get("label")
    adjudications = params.get("adjudications")
    if not (isinstance(adjudications, list) and adjudications):
        if not (label_id and label):
            return _err(rid, 4003, "forecast.triage.relabel requires label_id + label (or adjudications)")
    try:
        from tools.forecasting_tool import forecast_ledger_tool

        payload: dict = {"action": "relabel_route"}
        if isinstance(adjudications, list) and adjudications:
            payload["adjudications"] = adjudications
        else:
            payload["label_id"] = label_id
            payload["label"] = label
        result = json.loads(forecast_ledger_tool(payload))
        if result.get("error") or result.get("success") is False:
            return _err(rid, 5008, str(result.get("error") or "relabel failed"))
        return _ok(rid, result)
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.schedule.status")
def _(rid, params: dict) -> dict:
    """READ-ONLY schedule health: the forecast cron jobs' liveness joined with the
    per-question scheduled reviews (the live, self-advancing schedule).

    Reuses :func:`forecasting.scheduler.forecast_cron_health` (last-fired / errored /
    missed + next-run per installed forecast cron job) and the ledger's
    ``list_scheduled_reviews`` — so the TUI can show a compact green/red schedule
    strip (last-fired ok vs last-error, next-run) without re-deriving cron state.
    Never installs, pauses, or runs anything.
    """
    try:
        from forecasting.scheduler import forecast_cron_health

        cron = forecast_cron_health()
    except Exception:
        logger.exception("forecast.schedule.status cron health failed")
        cron = {"installed": 0, "jobs": [], "errored": [], "missed": [], "healthy": True}

    reviews: list[dict] = []
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        try:
            review_limit = int(params.get("limit") or 12)
        except (TypeError, ValueError):
            review_limit = 12
        enabled = [r for r in ledger.list_scheduled_reviews() if r.get("enabled")]
        for row in enabled[: max(1, min(review_limit, 100))]:
            reviews.append(
                {
                    "id": row.get("id"),
                    "scope_type": row.get("scope_type"),
                    "scope_ref": row.get("scope_ref"),
                    "cadence": row.get("cadence"),
                    "next_run_at": row.get("next_run_at"),
                    "last_run_at": row.get("last_run_at"),
                    "trigger_reason": row.get("trigger_reason"),
                }
            )
    except Exception:
        logger.exception("forecast.schedule.status scheduled-review listing failed")

    return _ok(
        rid,
        {
            "cron": cron,
            "healthy": bool(cron.get("healthy", True)),
            "scheduled_reviews": reviews,
            "scheduled_review_count": len(reviews),
        },
    )


@rpc_validated("forecast.reviews.next")
def _(rid, params: dict) -> dict:
    """READ-ONLY: everything the TUI needs to render the review-sweep countdown +
    a running indicator, without re-deriving scheduler state.

    Returns the soonest DUE scheduled review (``next_due_at`` — a past value means
    already overdue), how many are due right now (``due_count``), the gateway
    sweeper's live state (``sweeper``: enabled / interval / next-eligible-tick /
    running), and the nightly self-check cron's next/last run (``nightly``). The
    TUI combines these with the ``review.sweep`` event stream to show "runs in 4m"
    and a spinner while a sweep is in flight. Never runs or installs anything.
    """
    from forecasting.cron_runner import resolve_review_sweep_interval_minutes

    interval = resolve_review_sweep_interval_minutes()
    next_due_at: str | None = None
    due_count = 0
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        next_due_at = ledger.next_scheduled_review_at()
        due_count = ledger.count_due_scheduled_reviews()
    except Exception:
        logger.exception("forecast.reviews.next scheduled-review read failed")

    nightly = {"installed": False, "next_run_at": None, "last_run_at": None}
    try:
        job = _core._nightly_self_check_job()
        if job:
            nightly = {
                "installed": True,
                "next_run_at": job.get("next_run_at"),
                "last_run_at": job.get("last_run_at"),
            }
    except Exception:
        logger.exception("forecast.reviews.next nightly read failed")

    return _ok(
        rid,
        {
            "next_due_at": next_due_at,
            "due_count": int(due_count),
            "sweeper": {
                "enabled": interval > 0,
                "interval_minutes": interval,
                "next_tick_at": _core._review_sweep_next_tick_at,
                "running": _core._review_sweep_running,
            },
            "nightly": nightly,
        },
    )


@rpc_validated("forecast.onboard_propose")
def _(rid, params: dict) -> dict:
    """Validate a draft QuestionSpec and return issues + the clarifications to ask.

    Backs the TUI onboarding modal: the client sends whatever fields it has so
    far (or just a prompt) and gets back the normalized spec, its error/gap/warn
    issues, and the ordered, recommended-marked clarifications to surface next.
    Deterministic — no model call.
    """
    try:
        from forecasting.question_spec import recommended_clarifications, spec_from_dict

        raw = dict(params.get("spec") or {})
        if not raw.get("title") and params.get("prompt"):
            raw["title"] = str(params.get("prompt"))
        spec = spec_from_dict(raw)
        issues = [issue.to_dict() for issue in spec.validate()]
        return _ok(
            rid,
            {
                "spec": spec.to_dict(),
                "issues": issues,
                "errors": [i for i in issues if i["severity"] == "error"],
                "readiness_gaps": [i for i in issues if i["severity"] == "gap"],
                "recommended_clarifications": recommended_clarifications(spec),
                "committable": spec.is_committable(),
            },
        )
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.onboard_commit")
def _(rid, params: dict) -> dict:
    """Validate a finalized QuestionSpec and commit the full fan-out.

    Refuses on error-severity issues (returns committed=false + the issues,
    writing nothing); otherwise creates the question + watched sources +
    reference classes + decision card via QuestionSpec.commit.
    """
    try:
        from forecasting.ledger import ForecastLedger
        from forecasting.question_spec import spec_from_dict

        spec = spec_from_dict(params.get("spec") or {})
        errs = [issue.to_dict() for issue in spec.errors()]
        if errs:
            return _ok(rid, {"committed": False, "issues": errs})
        result = spec.commit(ForecastLedger())
        return _ok(rid, {"committed": True, **result})
    except Exception as e:
        return _err(rid, 5008, str(e))


# ── forecast.calibration ─────────────────────────────────────────────
# Structured calibration analytics for the TUI's native calibration view.
# `forecast.command` already exposes the same numbers as CLI text; this RPC
# returns the raw ledger payloads (reliability curve, ECE/MCE, signed bias)
# so the client can chart them instead of re-parsing prose.

# The compact per-scope row used by the domain/origin breakdowns. Headline
# metrics only — the full curve/buckets ship once, for the global summary.
_CALIBRATION_BREAKDOWN_FIELDS = (
    "count",
    "mean_brier",
    "expected_calibration_error",
    "calibration_curve_sample_count",
    "mean_predicted",
    "observed_frequency",
)


def _calibration_breakdown_row(summary: dict) -> dict:
    return {field: summary.get(field) for field in _CALIBRATION_BREAKDOWN_FIELDS}


def _calibration_bias_or_none(ledger, *, domain: str | None = None):
    """Signed-bias report, or None when the loop can't run (legacy ledgers,
    import errors). The report itself already degrades to
    ``insufficient_evidence`` on thin data — only true failures become None."""

    try:
        return ledger.calibration_bias(domain=domain)
    except Exception:
        logger.exception("forecast.calibration bias assessment failed")
        return None


@rpc_validated("forecast.calibration")
def _(rid, params: dict) -> dict:
    domain = params.get("domain") or None
    origin = params.get("origin") or None
    if domain is not None and not isinstance(domain, str):
        return _err(rid, 4003, "domain must be a string")
    if origin is not None and not isinstance(origin, str):
        return _err(rid, 4003, "origin must be a string")

    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        summary = ledger.calibration_summary(
            domain=domain,
            forecast_origin=origin,
            calibration_eligible=True,
        )
        bias = _calibration_bias_or_none(ledger, domain=domain)

        # Lessons-correcting-this (S7): the active calibration lessons adjusting
        # forecasts in this scope, each with its recommended_adjustment + measured
        # coverage + dormant flag — the honest "which learning is biting?" read.
        try:
            lessons = ledger.calibration_correcting_lessons(domain=domain)
        except Exception:
            logger.exception("forecast.calibration correcting-lessons lookup failed")
            lessons = []

        # Operator practice loop (R2): the human's own calibration, when they
        # have recorded + scored any practice/drill estimates. Best-effort — a
        # legacy ledger with no operator_estimates simply returns n=0. Payload
        # only here (TUI render is a later slice).
        try:
            operator = ledger.operator_calibration_summary()
        except Exception:
            logger.exception("forecast.calibration operator summary failed")
            operator = None

        # Measurement honesty: the by-cohort scoreboard (live calibration-
        # eligible kept apart from the market-visible baselines + a SEPARATE
        # continuous scorecard + a labelled pooled diagnostic). Global view only.
        cohort_scoreboard = None
        if domain is None and origin is None:
            try:
                cohort_scoreboard = ledger.cohort_scoreboard()
            except Exception:
                logger.exception("forecast.calibration cohort scoreboard failed")

        # Per-domain / per-origin breakdowns only make sense on the unfiltered
        # view; a filtered request already IS one row of that breakdown.
        domains: list[dict] = []
        origins: list[dict] = []
        if domain is None and origin is None:
            scores = ledger.list_scores(calibration_eligible=True)
            domain_names = sorted({s.domain for s in scores if s.domain})
            origin_names = sorted({s.forecast_origin for s in scores if s.forecast_origin})
            for name in domain_names:
                row = _calibration_breakdown_row(
                    ledger.calibration_summary(domain=name, calibration_eligible=True)
                )
                row["domain"] = name
                row["bias"] = _calibration_bias_or_none(ledger, domain=name)
                domains.append(row)
            for name in origin_names:
                row = _calibration_breakdown_row(
                    ledger.calibration_summary(
                        forecast_origin=name, calibration_eligible=True
                    )
                )
                row["origin"] = name
                origins.append(row)

        return _ok(
            rid,
            {
                "summary": summary,
                "bias": bias,
                "lessons": lessons,
                "operator": operator,
                "cohort_scoreboard": cohort_scoreboard,
                "domains": domains,
                "origins": origins,
                "domain": domain,
                "origin": origin,
            },
        )
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.hooks")
def _(rid, params: dict) -> dict:
    """Forecast saturation/style hooks summary for the TUI Hooks view: the
    resolved rule severities, the signal glossary, the curated profiles, and the
    lint status of any user-defined rules."""
    try:
        from forecasting.hooks import HOOK_PROFILES, resolve_severities
        from forecasting.hooks.builtins import builtin_rule_meta
        from forecasting.hooks.dsl import RuleSpec, signal_glossary, validate_rule
        from forecasting.hooks.engine import load_hook_config
        from forecasting.hooks.loader import load_user_rule_specs
        from forecasting.hooks.reasoning import REASONING_METHODS
        from forecasting.ledger import ForecastLedger

        qid = params.get("question_id") or None
        question = ForecastLedger().get_question(qid) if qid else None
        sev = resolve_severities(question, forecast_origin="live")
        cfg = load_hook_config()
        overrides = cfg.get("overrides") or {}

        known: set = set()
        user_rules = []
        user_by_id: dict = {}
        for raw in load_user_rule_specs(cfg):
            spec = RuleSpec.from_dict(raw)
            issues = validate_rule(spec, known_ids=known)
            known.add(spec.id)
            entry = {
                "id": spec.id or "(no id)",
                "category": spec.category,
                "severity": spec.severity,
                "description": spec.description,
                "check": spec.check,
                "remediation": spec.remediation_hint,
                "applies_to": spec.applies_to,
                "valid": not any(i.severity == "error" for i in issues),
                "issues": [{"field": i.field, "severity": i.severity, "message": i.message, "fix": i.fix} for i in issues],
            }
            user_rules.append(entry)
            user_by_id[spec.id] = entry

        # Unified rule list for the manager: resolved severity + WHY (override /
        # profile / user) + static metadata (category, default, doc, remediation).
        rules = []
        for rule_id, sev_obj in sev.items():
            is_user = rule_id in user_by_id
            entry = {
                "id": rule_id,
                "severity": sev_obj.value,
                "is_user": is_user,
                "source": "override" if rule_id in overrides else ("user" if is_user else "profile"),
                "blocks": sev_obj.value == "error",
            }
            meta = builtin_rule_meta(rule_id)
            if meta:
                entry.update(meta)  # category, default, remediation, doc
            if is_user:
                u = user_by_id[rule_id]
                entry.update({"category": u["category"], "doc": u["description"],
                              "remediation": u["remediation"], "check": u["check"],
                              "valid": u["valid"], "issues": u["issues"]})
            rules.append(entry)

        return _ok(rid, {
            "enabled": bool(cfg.get("enabled", True)),
            "profile": cfg.get("profile", "standard"),
            "resolved": {k: v.value for k, v in sev.items()},
            "overrides": dict(overrides),
            "rules": rules,
            "glossary": [{"name": n, "kind": k, "doc": d} for n, k, d in signal_glossary()],
            "operators": ["==", "!=", ">", ">=", "<", "<=", "in", "not_in", "is_true", "is_false"],
            "profiles": list(HOOK_PROFILES.keys()),
            "reasoning_methods": [{"name": n, "doc": d} for n, d in REASONING_METHODS.items()],
            "user_rules": user_rules,
        })
    except Exception as e:
        return _err(rid, 4003, str(e))


@rpc_validated("forecast.hooks.set")
def _(rid, params: dict) -> dict:
    """Write a hook policy change: target=profile|enabled|severity|enable|disable."""
    try:
        from forecasting.hooks import store

        target = (params.get("target") or "").strip()
        if target == "profile":
            return _ok(rid, store.set_profile(str(params.get("value"))))
        if target == "enabled":
            return _ok(rid, store.set_enabled(bool(params.get("value"))))
        if target == "severity":
            return _ok(rid, store.set_severity(str(params.get("rule_id")), str(params.get("value"))))
        if target == "enable":
            return _ok(rid, store.enable(str(params.get("rule_id"))))
        if target == "disable":
            return _ok(rid, store.disable(str(params.get("rule_id"))))
        return _err(rid, 4004, f"unknown target {target!r}")
    except Exception as e:
        return _err(rid, 4004, str(e))


@rpc_validated("forecast.hooks.save_rule")
def _(rid, params: dict) -> dict:
    """Validate + save a user rule. params.rule is the spec; params.edit_id edits
    an existing rule instead of adding. Returns issues on a validation refusal."""
    try:
        from forecasting.hooks import store
        from forecasting.hooks.store import HookWriteError

        rule = params.get("rule") or {}
        edit_id = params.get("edit_id")
        try:
            res = store.edit_rule(str(edit_id), rule) if edit_id else store.save_rule(rule)
            return _ok(rid, res)
        except HookWriteError as e:
            return _ok(rid, {"ok": False, "error": str(e),
                             "issues": [{"field": i.field, "severity": i.severity, "message": i.message, "fix": i.fix} for i in e.issues]})
    except Exception as e:
        return _err(rid, 4005, str(e))


@rpc_validated("forecast.hooks.remove_rule")
def _(rid, params: dict) -> dict:
    try:
        from forecasting.hooks import store

        return _ok(rid, store.remove_rule(str(params.get("id"))))
    except Exception as e:
        return _err(rid, 4006, str(e))


@rpc_validated("forecast.hooks.preview")
def _(rid, params: dict) -> dict:
    """Dry-run a candidate rule spec against the active questions: how many it
    applies to, how many it would block, and a few failing ids. Validates first."""
    try:
        from forecasting.hooks.dsl import RuleSpec, compile_rule, validate_rule
        from forecasting.hooks.signals import build_context_from_ledger
        from forecasting.ledger import ForecastLedger

        rule = params.get("rule") or {}
        spec = RuleSpec.from_dict(rule)
        issues = validate_rule(spec, known_ids=set())
        errs = [{"field": i.field, "severity": i.severity, "message": i.message, "fix": i.fix} for i in issues if i.severity == "error"]
        if errs:
            return _ok(rid, {"valid": False, "issues": errs})
        compiled = compile_rule(spec)
        ledger = ForecastLedger()
        applies = would_block = 0
        failing: list = []
        questions = ledger.list_questions(status="active")
        # Batch the current-snapshot fetch (one query) instead of the previous
        # per-question ``get_current_snapshot`` (which cost 2 queries each — one
        # here, one again inside ``build_context_from_ledger``). We resolve the
        # SAME snapshot the old code did — the one referenced by the question's
        # ``current_forecast_id`` (not merely the newest by created_at) — from the
        # batched map, skip questions with no committed forecast BEFORE the
        # expensive context build, and thread the snapshot into the context
        # builder so it does not re-run the lookup.
        snaps_by_q = ledger.snapshots_by_question([q.id for q in questions])
        # Optional safety cap for pathological ledgers; ``None`` (default) scans
        # every question so the reported counts stay exact.
        raw_cap = params.get("max_scan")
        max_scan = int(raw_cap) if isinstance(raw_cap, (int, float)) and raw_cap else None
        scanned = 0
        capped = False
        for q in questions:
            current_id = getattr(q, "current_forecast_id", None)
            if not current_id:
                continue  # no committed forecast → nothing to lint
            current_snap = next(
                (s for s in (snaps_by_q.get(q.id) or []) if s.forecast_id == current_id),
                None,
            )
            if current_snap is None:
                continue
            if max_scan is not None and scanned >= max_scan:
                capped = True
                break
            scanned += 1
            try:
                ctx = build_context_from_ledger(ledger, q.id, event="lint", snapshot=current_snap)
            except Exception:
                continue
            if not compiled.applies(ctx):
                continue
            applies += 1
            verdict = compiled.evaluate(ctx, compiled.default_severity)
            if not verdict.passed:
                would_block += 1
                if len(failing) < 8:
                    failing.append(q.id)
        result = {"valid": True, "applies": applies, "would_block": would_block, "failing": failing}
        if capped:
            result["capped_at"] = max_scan
        return _ok(rid, result)
    except Exception as e:
        return _err(rid, 4007, str(e))


@rpc_validated("forecast.command")
def _(rid, params: dict) -> dict:
    raw_arg = params.get("arg", "")
    if not isinstance(raw_arg, str):
        return _err(rid, 4003, "arg must be a string")

    argv_param = params.get("argv")
    if argv_param is not None:
        if not isinstance(argv_param, list) or not all(isinstance(item, str) for item in argv_param):
            return _err(rid, 4003, "argv must be a list of strings")
        argv = list(argv_param)
    else:
        try:
            from forecasting.argv import split_forecast_cli_args

            argv = split_forecast_cli_args(raw_arg)
        except ValueError as exc:
            return _err(rid, 4003, f"forecast command parse failed: {exc}")

    try:
        from forecasting.cli import main as forecast_main

        code = 0
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                forecast_main(argv)
            except SystemExit as exc:
                if isinstance(exc.code, int):
                    code = exc.code
                elif exc.code is None:
                    code = 0
                else:
                    code = 1
                    print(str(exc.code), file=sys.stderr)

        text = output.getvalue().strip() or "(no output)"
        return _ok(rid, {"code": code, "output": text[:48_000]})
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.reforecast")
def _(rid, params: dict) -> dict:
    # The desk's "run update" shortcut: re-arm the question's review to fire on the
    # next cron tick (the in-process autonomous cycle then reforecasts it). Returns
    # immediately — non-blocking — and the desk's NEXT column flips to "now".
    question_id = params.get("id", "")
    if not isinstance(question_id, str) or not question_id.strip():
        return _err(rid, 4003, "id must be a non-empty string")
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        return _ok(rid, ledger.mark_question_review_due(question_id.strip()))
    except Exception as e:
        return _err(rid, 5008, str(e))


@rpc_validated("forecast.config")
def _(rid, params: dict) -> dict:
    """Resolve the full per-forecast settings for the Desk settings modal: review
    cadence + the live next-run, the decision card, every hook gate (severity +
    source), and every tunable minimum-requirement threshold (value + default +
    looser flag). Read-only."""
    question_id = params.get("id") or params.get("question_id") or ""
    if not isinstance(question_id, str) or not question_id.strip():
        return _err(rid, 4003, "id must be a non-empty string")
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        return _ok(rid, ledger.resolve_question_config(question_id.strip()))
    except Exception as e:
        return _err(rid, 5009, str(e))


@rpc_validated("forecast.config.set")
def _(rid, params: dict) -> dict:
    """Write the per-forecast settings the modal owns, atomically: review_cadence
    (re-arms the live schedule), decision card fields, and hook gates/thresholds.
    Returns the freshly-resolved config so the modal + the Desk NEXT column refresh."""
    question_id = params.get("id") or params.get("question_id") or ""
    if not isinstance(question_id, str) or not question_id.strip():
        return _err(rid, 4003, "id must be a non-empty string")
    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        qid = question_id.strip()
        kwargs: dict = {}
        if "review_cadence" in params and params["review_cadence"] is not None:
            kwargs["review_cadence"] = str(params["review_cadence"])
        if isinstance(params.get("decision"), dict):
            kwargs["decision"] = params["decision"]
        if isinstance(params.get("hooks"), dict):
            kwargs["hooks"] = params["hooks"]
        ledger.update_question_config(qid, **kwargs)
        return _ok(rid, ledger.resolve_question_config(qid))
    except Exception as e:
        return _err(rid, 5009, str(e))


@rpc_validated("forecast.question")
def _(rid, params: dict) -> dict:
    question_id = params.get("id", "")
    if not isinstance(question_id, str) or not question_id.strip():
        return _err(rid, 4003, "id must be a non-empty string")

    try:
        from forecasting.ledger import ForecastLedger

        ledger = ForecastLedger()
        qid = question_id.strip()
        packet = json.loads(ledger.export_question(qid, fmt="json"))

        # Cross-pollination + scope-matched lessons for the detail modal. These are
        # gated OUT of forecast.workspace (the list) for speed, so the per-selection
        # detail RPC carries them — computed for this ONE question only (cheap).
        related = None
        relevant_lessons: list = []
        try:
            from forecasting.dashboard import _workspace_related

            question = ledger.get_question(qid)
            current = ledger.get_current_snapshot(qid)
            related = _workspace_related(ledger, question, current)
            from forecasting.learning import active_lessons_for_question

            relevant_lessons = [
                {
                    "id": lesson["id"],
                    "lesson": (lesson.get("lesson") or "")[:200],
                    "scope_type": lesson.get("scope_type"),
                    "scope_ref": lesson.get("scope_ref"),
                    "confidence": lesson.get("confidence"),
                }
                for lesson in active_lessons_for_question(ledger, question)
            ]
        except Exception:
            related, relevant_lessons = None, []

        return _ok(rid, {"packet": packet, "related": related, "relevant_lessons": relevant_lessons})
    except Exception as e:
        return _err(rid, 5008, str(e))
