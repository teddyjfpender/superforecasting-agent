"""Autopilot + forecast-update-proposal domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the autonomous-reforecast lifecycle:

* AUTOPILOT POLICY: ``autopilot_readiness`` / ``enable_autopilot`` /
  ``disable_autopilot`` / ``get_autopilot_policy`` / ``get_active_autopilot_policy``
  / ``list_autopilot_policies`` / ``_row_to_autopilot_policy``;
* AUTOPILOT RUN: ``run_autopilot`` and its guardrails/recording
  (``_autopilot_recheck_without_policy`` / ``_autopilot_material_change`` /
  ``_default_autopilot_rationale`` / ``_autopilot_guardrail_violations`` /
  ``_record_autopilot_run`` / ``list_autopilot_runs`` / ``_row_to_autopilot_run``);
* UPDATE PROPOSALS: ``list_forecast_update_proposals`` /
  ``create_forecast_update_proposal`` / ``get_`` / ``approve_`` / ``reject_`` /
  ``_row_to_forecast_update_proposal``.

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed (``run_autopilot`` stays
monkeypatchable on the ledger INSTANCE). ``refresh_forecast`` /
``check_update_triggers`` and every cross-domain read resolve through the
``ledger`` INSTANCE; the ``AUTOPILOT_MODES`` / ``AUTOPILOT_PROPOSAL_STATUSES`` /
``FORECASTING_PROTOCOL_VERSION`` core constants are reached via the ``_core.``
call-time hop."""

from __future__ import annotations

from datetime import timedelta

from forecasting.ledger import core as _core
from forecasting.models import AlertEvent
from typing import Any
from forecasting.models import ForecastSnapshot
from forecasting.models import LedgerNotFoundError
from forecasting.models import ValidationError
from forecasting.ledger.watches import WATCH_SOURCE_TYPES
from forecasting.models import json_dumps
from forecasting.models import json_loads
from forecasting.models import parse_timestamp
from forecasting.models import timestamp_to_datetime
import sqlite3
from forecasting.models import utc_now_iso
import uuid


def autopilot_readiness(
    ledger,
    question_id: str,
    *,
    sources: list[str] | None = None,
    allow_missing_resolution_source: bool = False,
) -> dict[str, Any]:
    question = ledger.get_question(question_id)
    hard_blockers: list[str] = []
    warnings: list[str] = []
    if question.status != "active":
        hard_blockers.append("question is not active")
    if not question.resolution_criteria.strip():
        hard_blockers.append("missing resolution criteria")
    if not question.resolution_source and not allow_missing_resolution_source:
        hard_blockers.append("missing resolution source")
    if question.outcome_space.type not in {"binary", "categorical", "numeric", "distribution"}:
        hard_blockers.append(f"unsupported outcome type: {question.outcome_space.type}")
    if ledger.get_current_snapshot(question_id) is None:
        hard_blockers.append("no baseline forecast snapshot")
    if sources is not None and not sources:
        hard_blockers.append("at least one watched source is required")
    for source in sources or []:
        source_type = ledger._infer_watch_source_type(source.strip())
        if source_type == "manual_note":
            source_type = "manual"
        if source_type not in WATCH_SOURCE_TYPES:
            hard_blockers.append(f"no source adapter available for {source!r}")
        elif source_type == "manual":
            hard_blockers.append(f"no pollable source adapter available for {source!r}")
    if not ledger.list_reference_classes(question_id):
        warnings.append("no reference class recorded")
    if not ledger.list_scores():
        warnings.append("no calibration or scoring history")
    stale_assumptions = [
        row["id"]
        for row in ledger.list_assumptions(question_id)
        if row.get("status") in {"stale", "invalidated"}
    ]
    if stale_assumptions:
        warnings.append("stale assumptions: " + ", ".join(stale_assumptions))
    return {
        "question_id": question_id,
        "ready": not hard_blockers,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
    }


def enable_autopilot(
    ledger,
    *,
    question_id: str,
    sources: list[str],
    cadence: str,
    mode: str = "propose",
    materiality_policy: dict[str, Any] | None = None,
    guardrail_policy: dict[str, Any] | None = None,
    notification_policy: dict[str, Any] | None = None,
    required_sources: list[str] | None = None,
    next_run_at: str | None = None,
    created_by: str | None = None,
    allow_missing_resolution_source: bool = False,
) -> dict[str, Any]:
    mode = mode.replace("-", "_")
    if mode not in _core.AUTOPILOT_MODES:
        raise ValidationError("autopilot mode must be propose, auto-commit, or alert-only")
    sources = list(dict.fromkeys(source.strip() for source in sources if source.strip()))
    required_sources = list(
        dict.fromkeys(source.strip() for source in (required_sources or []) if source.strip())
    )
    for source in required_sources:
        if source not in sources:
            sources.append(source)
    required_source_set = set(required_sources)
    readiness = ledger.autopilot_readiness(
        question_id,
        sources=sources,
        allow_missing_resolution_source=allow_missing_resolution_source,
    )
    if readiness["hard_blockers"]:
        raise ValidationError("autopilot readiness failed: " + "; ".join(readiness["hard_blockers"]))
    if not cadence.strip():
        raise ValidationError("autopilot cadence is required")
    policy_id = f"ap_{uuid.uuid4().hex[:12]}"
    now = utc_now_iso()
    schedule = ledger.schedule_review(
        scope_type="question",
        scope_ref=question_id,
        cadence=cadence,
        next_run_at=next_run_at,
        trigger_reason="autopilot",
    )
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM autopilot_policies WHERE question_id = ? AND enabled = 1",
            (question_id,),
        ).fetchone()
        if existing:
            policy_id = existing["id"]
            conn.execute(
                """
                UPDATE autopilot_policies
                SET mode = ?, cadence = ?, scheduled_review_id = ?,
                    materiality_policy = ?, guardrail_policy = ?,
                    notification_policy = ?, updated_at = ?,
                    created_by = COALESCE(?, created_by)
                WHERE id = ?
                """,
                (
                    mode,
                    cadence,
                    schedule["id"],
                    json_dumps(materiality_policy or {}),
                    json_dumps(guardrail_policy or {}),
                    json_dumps(notification_policy or {}),
                    now,
                    created_by,
                    policy_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO autopilot_policies (
                    id, question_id, enabled, mode, cadence, scheduled_review_id,
                    materiality_policy, guardrail_policy, notification_policy,
                    created_at, updated_at, created_by
                )
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    question_id,
                    mode,
                    cadence,
                    schedule["id"],
                    json_dumps(materiality_policy or {}),
                    json_dumps(guardrail_policy or {}),
                    json_dumps(notification_policy or {}),
                    now,
                    now,
                    created_by,
                ),
            )
    watches = [
        ledger.add_watched_source(
            scope_type="question",
            scope_ref=question_id,
            source=source,
            metadata={
                "autopilot_policy_id": policy_id,
                "required": source in required_source_set,
            },
        )
        for source in sources
    ]
    alert = ledger.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=question_id,
        reason=f"autopilot_enabled:{policy_id}",
        recommended_action=f"Run `forecast autopilot status {question_id}` to inspect the maintenance policy.",
    )
    return {
        "policy": ledger.get_autopilot_policy(policy_id),
        "scheduled_review": schedule,
        "watched_sources": watches,
        "readiness": readiness,
        "audit_alert": alert,
    }


def disable_autopilot(ledger, question_id: str) -> dict[str, Any]:
    policy = ledger.get_active_autopilot_policy(question_id)
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE autopilot_policies SET enabled = 0, updated_at = ? WHERE id = ?",
            (now, policy["id"]),
        )
        if policy.get("scheduled_review_id"):
            conn.execute(
                "UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?",
                (policy["scheduled_review_id"],),
            )
    return ledger.get_autopilot_policy(policy["id"])


def get_autopilot_policy(ledger, policy_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM autopilot_policies WHERE id = ?", (policy_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"autopilot policy not found: {policy_id}")
    return ledger._row_to_autopilot_policy(row)


def get_active_autopilot_policy(ledger, question_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM autopilot_policies
            WHERE question_id = ? AND enabled = 1
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (question_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"active autopilot policy not found for {question_id}")
    return ledger._row_to_autopilot_policy(row)


def list_autopilot_policies(
    ledger,
    *,
    question_id: str | None = None,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if enabled_only:
        clauses.append("enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM autopilot_policies {where} ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
    return [ledger._row_to_autopilot_policy(row) for row in rows]


def list_autopilot_runs(
    ledger,
    *,
    question_id: str | None = None,
    policy_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if policy_id:
        clauses.append("policy_id = ?")
        params.append(policy_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit), 1))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM autopilot_runs
            {where}
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [ledger._row_to_autopilot_run(row) for row in rows]


def run_autopilot(
    ledger,
    question_id: str,
    *,
    now: str | None = None,
    trigger_reason: str = "manual",
    proposed_probability_or_distribution: Any | None = None,
    rationale: str | None = None,
    require_policy: bool = True,
) -> dict[str, Any]:
    # The autopilot POLICY governs only the MATERIALITY threshold and the
    # auto-commit MODE (whether a watched-source change becomes a proposal /
    # auto-commit). Watched sources + update-triggers are attached to a question
    # at spec/import time WITHOUT the operator ever enabling autopilot (autopilot
    # is a deliberate per-question opt-in), yet they still emit
    # `watched_source_changed` alerts that land in the FREE resolution tier. So a
    # missing policy must NOT hard-fail the free-tier drain: with
    # ``require_policy=False`` we degrade to a conservative, zero-spend,
    # deterministic source RE-CHECK (record a source-snapshot audit row, propose
    # /commit nothing). The explicit `forecast autopilot run` path keeps the
    # default ``require_policy=True`` so an operator asking to autopilot a
    # policy-less question still gets a loud, actionable error.
    try:
        policy = ledger.get_active_autopilot_policy(question_id)
    except LedgerNotFoundError:
        if require_policy:
            raise
        return ledger._autopilot_recheck_without_policy(
            question_id, now=now, trigger_reason=trigger_reason
        )
    current = ledger.get_current_snapshot(question_id)
    if current is None:
        raise ValidationError("autopilot requires a baseline forecast snapshot")
    run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
    ledger.expire_forecast_update_proposals(now=run_at, question_id=question_id)
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
    source_snapshots: list[dict[str, Any]] = []
    source_change_events: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    required_source_failures: list[str] = []
    rate_limited_sources: list[dict[str, Any]] = []
    alerts: list[AlertEvent] = []
    for watch in watches:
        handoff = None
        from forecasting.ledger.workflow import acquire_watch_source_token

        rate_limit = acquire_watch_source_token(ledger, watch, now=run_at)
        if not rate_limit["granted"]:
            rate_limited_sources.append(
                {
                    "watched_source_id": watch["id"],
                    "source_type": watch["source_type"],
                    "retry_after_seconds": rate_limit["retry_after_seconds"],
                }
            )
            continue
        previous_signature = watch.get("last_seen_signature")
        from forecasting.ledger.source_signatures import (
            begin_source_observation_capture,
            take_source_observation,
        )

        begin_source_observation_capture()
        current_signature = ledger._source_signature(
            watch["source"],
            watch["source_type"],
            metadata=watch.get("metadata"),
        )
        observed_content = take_source_observation()
        status = "success"
        error_message = None
        if current_signature is None or str(current_signature).startswith("missing:"):
            status = "failed"
            error_message = str(current_signature or "source unavailable")
        did_change = (
            status == "success"
            and previous_signature is not None
            and current_signature is not None
            and current_signature != previous_signature
        )
        source_snapshot = ledger._record_source_snapshot(
            question_id=question_id,
            watch=watch,
            retrieved_at=run_at,
            signature=current_signature,
            previous_signature=previous_signature,
            changed=did_change,
            status=status,
            error_message=error_message,
            observed_content=observed_content,
        )
        source_snapshots.append(source_snapshot)
        if current_signature != previous_signature and current_signature is not None:
            from forecasting.ledger.workflow import (
                pending_source_change,
                record_source_change_event,
            )

            handoff = pending_source_change(
                ledger,
                watched_source_id=watch["id"],
                current_signature=current_signature,
            )
            if handoff is None:
                handoff = record_source_change_event(
                    ledger,
                    question_id=question_id,
                    watch=watch,
                    source_snapshot=source_snapshot,
                    previous_signature=previous_signature,
                    current_signature=current_signature,
                    detected_at=run_at,
                )
            source_change_events.append(handoff["event"])
        if did_change:
            changed.append(source_snapshot)
        if status == "failed":
            is_required = bool((watch.get("metadata") or {}).get("required"))
            if is_required:
                required_source_failures.append(source_snapshot["id"])
            source_alert = ledger.create_alert(
                    severity="high" if is_required else "warning",
                    scope_type="question",
                    scope_ref=question_id,
                    reason=(
                        f"autopilot_required_source_failed:{watch['id']}"
                        if is_required
                        else f"autopilot_source_failed:{watch['id']}"
                    ),
                    recommended_action=(
                        "Required autopilot source failed; forecast refresh is blocked until it recovers. "
                        f"Inspect the source and rerun `forecast autopilot run {question_id}`."
                        if is_required
                        else (
                            "Inspect the watched source and rerun "
                            f"`forecast autopilot run {question_id}` after the adapter recovers."
                        )
                    ),
                )
            alerts.append(source_alert)
            if current_signature != previous_signature and current_signature is not None:
                from forecasting.ledger.workflow import link_source_change_alert

                link_source_change_alert(ledger, handoff["event"]["id"], source_alert.id)
        with ledger._connect() as conn:
            if handoff is None:
                conn.execute(
                    """
                    UPDATE watched_sources
                    SET last_checked_at = ?, last_seen_signature = ?
                    WHERE id = ?
                    """,
                    (run_at, current_signature, watch["id"]),
                )
            else:
                conn.execute(
                    "UPDATE watched_sources SET last_checked_at = ? WHERE id = ?",
                    (run_at, watch["id"]),
                )
    blocked_by_required_source_failure = bool(required_source_failures)
    material_changes = 0
    if not blocked_by_required_source_failure and ledger._autopilot_material_change(policy, changed):
        material_changes = len(changed)
    proposal: dict[str, Any] | None = None
    snapshot: ForecastSnapshot | None = None
    model_run: dict[str, Any] | None = None
    source_failures = [row["id"] for row in source_snapshots if row["status"] == "failed"]
    if blocked_by_required_source_failure:
        status = "failed"
    elif source_failures or rate_limited_sources:
        status = "partial"
    else:
        status = "skipped" if material_changes == 0 else "success"
    diagnostics: dict[str, Any] = {
        "mode": policy["mode"],
        "source_snapshot_ids": [row["id"] for row in source_snapshots],
        "changed_source_snapshot_ids": [row["id"] for row in changed],
        "source_failures": source_failures,
        "required_source_failures": required_source_failures,
        "rate_limited_sources": rate_limited_sources,
        "forecast_refresh_blocked": blocked_by_required_source_failure,
        "materiality_policy": policy["materiality_policy"],
        "guardrail_policy": policy["guardrail_policy"],
        "source_change_event_ids": [row["id"] for row in source_change_events],
    }
    estimation_required = bool(
        material_changes and proposed_probability_or_distribution is None
    )
    if estimation_required:
        status = "needs_estimation"
        diagnostics["estimation_status"] = "required"
        alerts.append(
            ledger.create_alert(
                severity="warning",
                scope_type="question",
                scope_ref=question_id,
                reason=f"autopilot_estimation_required:{policy['id']}",
                recommended_action=(
                    "A material source change was captured, but no estimator produced a revised "
                    "distribution. Run the reforecast worker before proposing or committing."
                ),
            )
        )
    elif material_changes:
        proposed_payload = proposed_probability_or_distribution
        proposal_rationale = rationale or ledger._default_autopilot_rationale(
            changed=changed,
            current=current,
        )
        prior_probability = ledger._numeric_probability(current.probability_or_distribution)
        proposed_probability = ledger._numeric_probability(proposed_payload)
        probability_delta = (
            proposed_probability - prior_probability
            if prior_probability is not None and proposed_probability is not None
            else None
        )
        guardrail_violations = ledger._autopilot_guardrail_violations(
            policy=policy,
            prior_payload=current.probability_or_distribution,
            proposed_payload=proposed_payload,
            source_snapshots=source_snapshots,
        )
        estimation_artifact = {
            "prior_probability": prior_probability,
            "evidence_updates": [
                {
                    "event_id": event["id"],
                    "source_snapshot_id": event["new_source_snapshot_id"],
                    "likelihood_ratio": None,
                    "correlation_cluster": (event.get("metadata") or {}).get("source_type"),
                    "reliability_weight": None,
                }
                for event in source_change_events
            ],
            "raw_posterior": proposed_probability,
            "ensemble_components": {},
            "panel_result": {},
            "proposed_probability": proposed_probability,
            "probability_delta": probability_delta,
            "materiality": (
                "unknown"
                if probability_delta is None
                else "high"
                if abs(probability_delta) >= 0.15
                else "medium"
                if abs(probability_delta) >= 0.05
                else "low"
            ),
            "evidence_cutoff": run_at,
            "change_my_mind": [],
            "guardrail_results": {
                "passed": not guardrail_violations,
                "violations": guardrail_violations,
            },
            "estimator_provenance": "explicit_run_input",
        }
        model_run = ledger.record_model_run(
            question_id=question_id,
            model_type="autopilot_estimation",
            inputs={
                "trigger_reason": trigger_reason,
                "prior_forecast_id": current.forecast_id,
                "source_snapshot_refs": [row["id"] for row in source_snapshots],
            },
            parameters={
                "materiality_policy": policy["materiality_policy"],
                "guardrail_policy": policy["guardrail_policy"],
            },
            output={
                "proposed_probability_or_distribution": proposed_payload,
                "rationale": proposal_rationale,
                "estimation_artifact": estimation_artifact,
            },
            diagnostics=diagnostics,
            model_version=_core.FORECASTING_PROTOCOL_VERSION,
            evidence_cutoff=run_at,
        )
        from forecasting.warnings import MATERIAL_MOVE_THRESHOLD, is_material_move

        minimum_delta = float(
            (policy.get("materiality_policy") or {}).get(
                "min_probability_delta", MATERIAL_MOVE_THRESHOLD
            )
        )
        if not is_material_move(
            current.probability_or_distribution,
            proposed_payload,
            threshold=max(minimum_delta, 0.0),
        ):
            status = "reviewed_immaterial"
            diagnostics["estimation_status"] = "reviewed_immaterial"
            diagnostics["minimum_probability_delta"] = minimum_delta
        else:
            proposal = ledger.create_forecast_update_proposal(
                question_id=question_id,
                run_id=None,
                prior_forecast_id=current.forecast_id,
                proposed_probability_or_distribution=proposed_payload,
                rationale=proposal_rationale,
                source_snapshot_refs=[row["id"] for row in source_snapshots],
                model_run_refs=[model_run["id"]],
            )
            if policy["mode"] == "alert_only":
                alerts.append(
                    ledger.create_alert(
                        severity="warning",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_material_change:{policy['id']}",
                        recommended_action=f"Review proposal {proposal['id']} before updating the forecast.",
                    )
                )
            elif policy["mode"] == "auto_commit":
                violations = guardrail_violations
                diagnostics["guardrail_violations"] = violations
                if violations:
                    alerts.append(
                        ledger.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question_id,
                            reason=f"autopilot_guardrail_review:{policy['id']}",
                            recommended_action=(
                                "Autopilot update requires review: "
                                + "; ".join(violations)
                                + f". Approve manually with `forecast autopilot approve {proposal['id']}`."
                            ),
                        )
                    )
                else:
                    snapshot = ledger.approve_forecast_update_proposal(
                        proposal["id"],
                        status="auto_committed",
                    )
            else:
                alerts.append(
                    ledger.create_alert(
                        severity="info",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_update_proposed:{proposal['id']}",
                        recommended_action=f"Review with `forecast autopilot approve {proposal['id']}` or reject it.",
                    )
                )
    run = ledger._record_autopilot_run(
        policy_id=policy["id"],
        question_id=question_id,
        started_at=run_at,
        finished_at=utc_now_iso(),
        status=status,
        trigger_reason=trigger_reason,
        sources_checked=len(watches),
        sources_changed=len(changed),
        material_changes=material_changes,
        proposal_id=proposal["id"] if proposal else None,
        forecast_snapshot_id=snapshot.forecast_id if snapshot else None,
        alerts_created=len(alerts),
        diagnostics=diagnostics,
    )
    if proposal and proposal.get("run_id") is None:
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE forecast_update_proposals SET run_id = ? WHERE id = ?",
                (run["id"], proposal["id"]),
            )
        proposal = ledger.get_forecast_update_proposal(proposal["id"])
    from forecasting.ledger.workflow import (
        complete_source_change_events,
        defer_source_change_events_for_estimation,
    )

    if estimation_required:
        defer_source_change_events_for_estimation(
            ledger,
            question_id=question_id,
            event_ids=[event["id"] for event in source_change_events],
            now=run_at,
        )
    elif snapshot is not None:
        event_disposition = "auto_committed"
    elif proposal is not None:
        event_disposition = "proposed"
    elif blocked_by_required_source_failure:
        event_disposition = "required_source_failure"
    elif source_failures:
        event_disposition = "partial_source_failure"
    elif status == "reviewed_immaterial":
        event_disposition = "reviewed_immaterial"
    else:
        event_disposition = "no_material_change"
    if not estimation_required:
        complete_source_change_events(
            ledger,
            question_id=question_id,
            event_ids=[event["id"] for event in source_change_events],
            status="failed" if blocked_by_required_source_failure else "processed",
            disposition=event_disposition,
            proposal_id=proposal["id"] if proposal else None,
            forecast_snapshot_id=snapshot.forecast_id if snapshot else None,
            error=(
                "required source refresh failed: " + ", ".join(required_source_failures)
                if blocked_by_required_source_failure
                else None
            ),
            now=run_at,
        )
    return {
        "policy": policy,
        "run": run,
        "source_snapshots": source_snapshots,
        "proposal": proposal,
        "forecast_snapshot": snapshot,
        "model_run": model_run,
        "alerts": alerts,
    }


def _autopilot_recheck_without_policy(
    ledger,
    question_id: str,
    *,
    now: str | None = None,
    trigger_reason: str = "manual",
) -> dict[str, Any]:
    """Deterministic, zero-spend watched-source re-check for a question with NO
    active autopilot policy. This remains a compatibility diagnostic for explicit
    callers; source-backed warning alerts are owned by the immutable event queue.
    Re-reads every active watched source, records a source-snapshot audit row
    (so the drift is captured in the ledger) and updates ``last_seen_signature``.
    It proposes / commits NOTHING, records NO ``autopilot_run``, and never changes
    or completes an existing source-change event. The shape mirrors the
    policy-backed :meth:`run_autopilot` result (with ``policy=None``,
    ``run=None``) so existing consumers stay total.
    """
    run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
    watches = ledger.list_watched_sources(
        scope_type="question", scope_ref=question_id, status="active"
    )
    source_snapshots: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for watch in watches:
        previous_signature = watch.get("last_seen_signature")
        from forecasting.ledger.source_signatures import (
            begin_source_observation_capture,
            take_source_observation,
        )

        begin_source_observation_capture()
        current_signature = ledger._source_signature(
            watch["source"], watch["source_type"], metadata=watch.get("metadata"),
        )
        observed_content = take_source_observation()
        status = "success"
        error_message = None
        if current_signature is None or str(current_signature).startswith("missing:"):
            status = "failed"
            error_message = str(current_signature or "source unavailable")
        did_change = (
            status == "success"
            and previous_signature is not None
            and current_signature is not None
            and current_signature != previous_signature
        )
        source_snapshot = ledger._record_source_snapshot(
            question_id=question_id,
            watch=watch,
            retrieved_at=run_at,
            signature=current_signature,
            previous_signature=previous_signature,
            changed=did_change,
            status=status,
            error_message=error_message,
            observed_content=observed_content,
        )
        source_snapshots.append(source_snapshot)
        if did_change:
            changed.append(source_snapshot)
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE watched_sources SET last_checked_at = ? WHERE id = ?",
                (run_at, watch["id"]),
            )
    source_failures = [row["id"] for row in source_snapshots if row["status"] == "failed"]
    if not source_snapshots:
        run_status = "skipped"
    elif source_failures:
        run_status = "partial"
    else:
        run_status = "success"
    return {
        "policy": None,
        "policy_source": "none",
        "run": None,
        "status": run_status,
        "recheck_only": True,
        "trigger_reason": trigger_reason,
        "source_snapshots": source_snapshots,
        "changed_source_snapshots": changed,
        "proposal": None,
        "forecast_snapshot": None,
        "model_run": None,
        "alerts": [],
    }


def _autopilot_material_change(policy: dict[str, Any], changed: list[dict[str, Any]]) -> bool:
    minimum = int((policy.get("materiality_policy") or {}).get("min_source_changes") or 1)
    return len(changed) >= max(minimum, 1)


def _default_autopilot_rationale(
    *,
    changed: list[dict[str, Any]],
    current: ForecastSnapshot,
) -> str:
    drivers = ", ".join(
        f"{row['source_type']}:{row['watched_source_id']}"
        for row in changed[:3]
    )
    return (
        "Autopilot detected material watched-source changes "
        f"({drivers or 'source change'}) after prior forecast {current.forecast_id}. "
        "The proposal records the explicit estimator output supplied for this run."
    )


def _autopilot_guardrail_violations(
    ledger,
    *,
    policy: dict[str, Any],
    prior_payload: Any,
    proposed_payload: Any,
    source_snapshots: list[dict[str, Any]],
) -> list[str]:
    guardrails = policy.get("guardrail_policy") or {}
    violations: list[str] = []
    if guardrails.get("require_no_critical_source_failures", True):
        failures = [row["id"] for row in source_snapshots if row.get("status") == "failed"]
        if failures:
            violations.append("critical source failures: " + ", ".join(failures))
    required_sources = int(guardrails.get("min_independent_sources_for_auto_commit") or 0)
    successful_sources = len([row for row in source_snapshots if row.get("status") == "success"])
    if required_sources and successful_sources < required_sources:
        violations.append(
            f"successful sources {successful_sources} below required {required_sources}"
        )
    max_delta = guardrails.get("max_single_run_probability_delta")
    if max_delta is None:
        max_delta = guardrails.get("max_auto_delta")
    if max_delta is not None:
        prior_probability = ledger._numeric_probability(prior_payload)
        proposed_probability = ledger._numeric_probability(proposed_payload)
        if prior_probability is not None and proposed_probability is not None:
            delta = abs(proposed_probability - prior_probability)
            if delta > float(max_delta):
                violations.append(
                    f"proposed probability delta {delta:.3f} exceeds max {float(max_delta):.3f}"
                )
    return violations


def _record_autopilot_run(
    ledger,
    *,
    policy_id: str,
    question_id: str,
    started_at: str,
    finished_at: str,
    status: str,
    trigger_reason: str,
    sources_checked: int,
    sources_changed: int,
    material_changes: int,
    proposal_id: str | None,
    forecast_snapshot_id: str | None,
    alerts_created: int,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    run_id = f"apr_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO autopilot_runs (
                id, policy_id, question_id, started_at, finished_at, status,
                trigger_reason, sources_checked, sources_changed,
                material_changes, proposal_id, forecast_snapshot_id,
                alerts_created, diagnostics
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                policy_id,
                question_id,
                started_at,
                finished_at,
                status,
                trigger_reason,
                sources_checked,
                sources_changed,
                material_changes,
                proposal_id,
                forecast_snapshot_id,
                alerts_created,
                json_dumps(diagnostics),
            ),
        )
    return ledger.list_autopilot_runs(policy_id=policy_id, limit=1)[0]


def _row_to_autopilot_policy(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["materiality_policy"] = json_loads(data["materiality_policy"], {})
    data["guardrail_policy"] = json_loads(data["guardrail_policy"], {})
    data["notification_policy"] = json_loads(data["notification_policy"], {})
    return data


def _row_to_autopilot_run(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["diagnostics"] = json_loads(data["diagnostics"], {})
    return data


def list_forecast_update_proposals(
    ledger,
    *,
    question_id: str | None = None,
    status: str | None = "pending",
    limit: int = 20,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit), 1))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM forecast_update_proposals
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [ledger._row_to_forecast_update_proposal(row) for row in rows]


def create_forecast_update_proposal(
    ledger,
    *,
    question_id: str,
    run_id: str | None,
    prior_forecast_id: str | None,
    proposed_probability_or_distribution: Any,
    rationale: str,
    evidence_refs: list[str] | None = None,
    source_snapshot_refs: list[str] | None = None,
    model_run_refs: list[str] | None = None,
    assumption_refs: list[str] | None = None,
    reference_class_refs: list[str] | None = None,
    status: str = "pending",
    expires_at: str | None = None,
) -> dict[str, Any]:
    question = ledger.get_question(question_id)
    if status not in _core.AUTOPILOT_PROPOSAL_STATUSES:
        raise ValidationError("proposal status is invalid")
    payload = ledger._validate_probability_payload(
        proposed_probability_or_distribution,
        question.outcome_space,
    )
    if not rationale.strip():
        raise ValidationError("proposal rationale is required")
    proposal_id = f"fup_{uuid.uuid4().hex[:12]}"
    created_at = utc_now_iso()
    if expires_at is None:
        created_dt = timestamp_to_datetime(created_at)
        assert created_dt is not None
        expires_at = (created_dt + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    else:
        expires_at = parse_timestamp(expires_at, field_name="expires_at")
        if expires_at <= created_at:
            raise ValidationError("proposal expires_at must be in the future")
    with ledger._connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO forecast_update_proposals (
                id, question_id, run_id, prior_forecast_id,
                proposed_probability_or_distribution, rationale, evidence_refs,
                source_snapshot_refs, model_run_refs, assumption_refs,
                reference_class_refs, status, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                question_id,
                run_id,
                prior_forecast_id,
                json_dumps(payload),
                rationale.strip(),
                json_dumps(evidence_refs or []),
                json_dumps(source_snapshot_refs or []),
                json_dumps(model_run_refs or []),
                json_dumps(assumption_refs or []),
                json_dumps(reference_class_refs or []),
                status,
                created_at,
                expires_at,
            ),
        )
        if not cursor.rowcount and status in {"pending", "committing"}:
            row = conn.execute(
                """
                SELECT id FROM forecast_update_proposals
                WHERE question_id = ?
                  AND ((prior_forecast_id IS NULL AND ? IS NULL) OR prior_forecast_id = ?)
                  AND status IN ('pending', 'committing')
                ORDER BY created_at ASC LIMIT 1
                """,
                (question_id, prior_forecast_id, prior_forecast_id),
            ).fetchone()
            proposal_id = row["id"]
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    _ensure_proposal_review_task(ledger, proposal)
    return proposal


def _ensure_proposal_review_task(ledger, proposal: dict[str, Any]) -> None:
    if proposal.get("status") != "pending":
        return
    question = ledger.get_question(proposal["question_id"])
    owner = getattr(question, "owner", None) or "human:forecast-duty"
    created_at = proposal["created_at"]
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO operational_tasks (
                id, task_type, lane, question_id, status, priority,
                utility_score, utility_components, available_at, due_at,
                escalation_owner, escalated_at, idempotency_key, disposition,
                result, created_at, updated_at
            ) VALUES (?, 'review_forecast_proposal', 'human_review', ?,
                      'awaiting_human', 90, 0, '{}', ?, ?, ?, ?, ?,
                      'proposal_review_required', ?, ?, ?)
            """,
            (
                f"ot_proposal_{proposal['id'][4:]}",
                proposal["question_id"],
                created_at,
                proposal.get("expires_at"),
                owner,
                created_at,
                f"proposal-review:{proposal['id']}",
                json_dumps({"proposal_id": proposal["id"], "review_sla_at": proposal.get("expires_at")}),
                created_at,
                created_at,
            ),
        )


def _close_proposal_review_task(
    ledger, proposal_id: str, *, disposition: str, now: str
) -> None:
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE operational_tasks
            SET status = 'completed', disposition = ?, completed_at = ?, updated_at = ?,
                lease_owner = NULL, lease_expires_at = NULL
            WHERE idempotency_key = ? AND status = 'awaiting_human'
            """,
            (disposition, now, now, f"proposal-review:{proposal_id}"),
        )


def get_forecast_update_proposal(ledger, proposal_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM forecast_update_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"forecast update proposal not found: {proposal_id}")
    return ledger._row_to_forecast_update_proposal(row)


def approve_forecast_update_proposal(
    ledger,
    proposal_id: str,
    *,
    reviewed_by: str | None = None,
    status: str = "approved",
) -> ForecastSnapshot:
    if status not in {"approved", "auto_committed"}:
        raise ValidationError("approved proposal status must be approved or auto_committed")
    ledger.expire_forecast_update_proposals()
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] in {"approved", "auto_committed"} and proposal.get(
        "resulting_forecast_id"
    ):
        return ledger.get_snapshot(proposal["resulting_forecast_id"])
    reviewed_at = utc_now_iso()
    with ledger._connect() as conn:
        claimed = conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = 'committing', reviewed_at = ?, reviewed_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (reviewed_at, reviewed_by, proposal_id),
        )
        if claimed.rowcount != 1:
            raise ValidationError("proposal is already claimed or no longer pending")
    try:
        snapshot = ledger.create_snapshot(
            question_id=proposal["question_id"],
            probability_or_distribution=proposal["proposed_probability_or_distribution"],
            rationale=proposal["rationale"],
            method="autopilot",
            style_autofix=True,
            distribution_autofix=True,
            evidence_refs=proposal["evidence_refs"],
            source_snapshot_refs=proposal["source_snapshot_refs"],
            model_run_refs=proposal["model_run_refs"],
            assumption_refs=proposal["assumption_refs"],
            reference_class_refs=proposal["reference_class_refs"],
            require_citations=True,
            metadata={"autopilot_proposal_id": proposal_id},
        )
    except Exception:
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE forecast_update_proposals SET status = 'pending' "
                "WHERE id = ? AND status = 'committing'",
                (proposal_id,),
            )
        raise
    with ledger._connect() as conn:
        finalized = conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = ?, reviewed_at = ?, reviewed_by = ?, resulting_forecast_id = ?
            WHERE id = ? AND status = 'committing'
            """,
            (status, reviewed_at, reviewed_by, snapshot.forecast_id, proposal_id),
        )
        if finalized.rowcount != 1:
            raise ValidationError("proposal commit claim was lost")
        if proposal.get("run_id"):
            conn.execute(
                "UPDATE autopilot_runs SET forecast_snapshot_id = ? WHERE id = ?",
                (snapshot.forecast_id, proposal["run_id"]),
            )
    _close_proposal_review_task(
        ledger, proposal_id, disposition=status, now=reviewed_at
    )
    from forecasting.ledger.workflow import reconcile_source_events_for_proposal

    reconcile_source_events_for_proposal(
        ledger,
        proposal_id,
        outcome="committed",
        actor=reviewed_by or "proposal-review",
        forecast_snapshot_id=snapshot.forecast_id,
    )
    return snapshot


def expire_forecast_update_proposals(
    ledger,
    *,
    now: str | None = None,
    question_id: str | None = None,
) -> list[dict[str, Any]]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    pending = ledger.list_forecast_update_proposals(status="pending", limit=10_000)
    for proposal in pending:
        _ensure_proposal_review_task(ledger, proposal)
    # A proposal against an older committed forecast is no longer reviewable as
    # written. Close it explicitly instead of leaving it pending until expiry.
    for proposal in pending:
        current = ledger.get_current_snapshot(proposal["question_id"])
        prior_id = proposal.get("prior_forecast_id")
        if current is None or not prior_id or current.forecast_id == prior_id:
            continue
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = 'superseded', reviewed_at = ?,
                    reviewed_by = 'lifecycle:newer_forecast'
                WHERE id = ? AND status = 'pending'
                """,
                (stamp, proposal["id"]),
            )
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, 'superseded'),
                    ack_note = COALESCE(ack_note, 'auto_close:proposal_superseded')
                WHERE scope_type = 'question' AND scope_ref = ?
                  AND reason IN (?, ?) AND acknowledged_at IS NULL
                """,
                (
                    stamp,
                    proposal["question_id"],
                    f"autopilot_update_proposed:{proposal['id']}",
                    f"forecast_update_proposal_expiring:{proposal['id']}",
                ),
            )
        _close_proposal_review_task(
            ledger, proposal["id"], disposition="superseded", now=stamp
        )
        from forecasting.ledger.workflow import reconcile_source_events_for_proposal

        reconcile_source_events_for_proposal(
            ledger,
            proposal["id"],
            outcome="rejected",
            actor="lifecycle:newer_forecast",
        )

    warning_cutoff = (
        timestamp_to_datetime(stamp) + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    for proposal in ledger.list_forecast_update_proposals(status="pending", limit=10_000):
        expires_at = proposal.get("expires_at")
        if not expires_at or not (stamp < expires_at <= warning_cutoff):
            continue
        reason = f"forecast_update_proposal_expiring:{proposal['id']}"
        with ledger._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM alert_events WHERE reason = ? LIMIT 1", (reason,)
            ).fetchone()
        if exists is None:
            ledger.create_alert(
                severity="warning",
                scope_type="question",
                scope_ref=proposal["question_id"],
                reason=reason,
                recommended_action=(
                    f"Approve, reject, or defer proposal {proposal['id']} before "
                    f"it expires at {expires_at}."
                ),
                now=stamp,
            )
    clauses = ["status = 'pending'", "expires_at IS NOT NULL", "expires_at <= ?"]
    params: list[Any] = [stamp]
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT id, question_id FROM forecast_update_proposals WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        ids = [row["id"] for row in rows]
        for row in rows:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = 'expired', reviewed_at = ?, reviewed_by = 'lifecycle:expired'
                WHERE id = ? AND status = 'pending'
                """,
                (stamp, row["id"]),
            )
    expired = [ledger.get_forecast_update_proposal(proposal_id) for proposal_id in ids]
    for proposal in expired:
        _close_proposal_review_task(
            ledger, proposal["id"], disposition="expired", now=stamp
        )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, 'expired'),
                    ack_note = COALESCE(ack_note, 'auto_close:proposal_expired')
                WHERE scope_type = 'question' AND scope_ref = ?
                  AND reason IN (?, ?) AND acknowledged_at IS NULL
                """,
                (
                    stamp,
                    proposal["question_id"],
                    f"autopilot_update_proposed:{proposal['id']}",
                    f"forecast_update_proposal_expiring:{proposal['id']}",
                ),
            )
        from forecasting.ledger.workflow import reconcile_source_events_for_proposal

        reconcile_source_events_for_proposal(
            ledger,
            proposal["id"],
            outcome="rejected",
            actor="lifecycle:expired",
        )
        ledger.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=proposal["question_id"],
            reason=f"forecast_update_proposal_expired:{proposal['id']}",
            recommended_action="Refresh the estimate before creating a replacement proposal.",
            now=stamp,
        )
    return expired


def reject_forecast_update_proposal(
    ledger,
    proposal_id: str,
    *,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValidationError("only pending proposals can be rejected")
    reviewed_at = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (reviewed_at, reviewed_by, proposal_id),
        )
        conn.execute(
            """
            UPDATE alert_events
            SET acknowledged_at = COALESCE(acknowledged_at, ?),
                disposition = COALESCE(disposition, 'rejected'),
                ack_note = COALESCE(ack_note, 'auto_close:proposal_rejected')
            WHERE scope_type = 'question' AND scope_ref = ?
              AND reason IN (?, ?) AND acknowledged_at IS NULL
            """,
            (
                reviewed_at,
                proposal["question_id"],
                f"autopilot_update_proposed:{proposal_id}",
                f"autopilot_guardrail_review:{proposal_id}",
            ),
        )
    _close_proposal_review_task(
        ledger, proposal_id, disposition="rejected", now=reviewed_at
    )
    from forecasting.ledger.workflow import reconcile_source_events_for_proposal

    reconcile_source_events_for_proposal(
        ledger,
        proposal_id,
        outcome="rejected",
        actor=reviewed_by or "proposal-review",
    )
    return ledger.get_forecast_update_proposal(proposal_id)


def reject_unsupported_source_proposals(
    ledger, *, reviewed_by: str = "lifecycle:insufficient_source_content"
) -> list[dict[str, Any]]:
    """Reject legacy signature-only proposals that cannot support review."""
    rejected: list[dict[str, Any]] = []
    for proposal in ledger.list_forecast_update_proposals(status="pending", limit=10_000):
        refs = proposal.get("source_snapshot_refs") or []
        if not refs or proposal.get("evidence_refs"):
            continue
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT parsed_values FROM source_snapshots WHERE id IN ({','.join('?' for _ in refs)})",
                refs,
            ).fetchall()
        if len(rows) != len(refs) or any(
            bool(json_loads(row["parsed_values"], {}).get("content_available"))
            for row in rows
        ):
            continue
        rejected.append(
            reject_forecast_update_proposal(
                ledger, proposal["id"], reviewed_by=reviewed_by
            )
        )
    return rejected


def _row_to_forecast_update_proposal(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["proposed_probability_or_distribution"] = json_loads(
        data["proposed_probability_or_distribution"],
        None,
    )
    for field in (
        "evidence_refs",
        "source_snapshot_refs",
        "model_run_refs",
        "assumption_refs",
        "reference_class_refs",
    ):
        data[field] = json_loads(data[field], [])
    return data
