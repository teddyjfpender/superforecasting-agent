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
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
    source_snapshots: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    required_source_failures: list[str] = []
    alerts: list[AlertEvent] = []
    for watch in watches:
        previous_signature = watch.get("last_seen_signature")
        current_signature = ledger._source_signature(
            watch["source"],
            watch["source_type"],
            metadata=watch.get("metadata"),
        )
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
        )
        source_snapshots.append(source_snapshot)
        if did_change:
            changed.append(source_snapshot)
        if status == "failed":
            is_required = bool((watch.get("metadata") or {}).get("required"))
            if is_required:
                required_source_failures.append(source_snapshot["id"])
            alerts.append(
                ledger.create_alert(
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
            )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE watched_sources
                SET last_checked_at = ?, last_seen_signature = ?
                WHERE id = ?
                """,
                (run_at, current_signature, watch["id"]),
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
    elif source_failures:
        status = "partial"
    else:
        status = "skipped" if material_changes == 0 else "success"
    diagnostics: dict[str, Any] = {
        "mode": policy["mode"],
        "source_snapshot_ids": [row["id"] for row in source_snapshots],
        "changed_source_snapshot_ids": [row["id"] for row in changed],
        "source_failures": source_failures,
        "required_source_failures": required_source_failures,
        "forecast_refresh_blocked": blocked_by_required_source_failure,
        "materiality_policy": policy["materiality_policy"],
        "guardrail_policy": policy["guardrail_policy"],
    }
    if material_changes:
        proposed_payload = (
            proposed_probability_or_distribution
            if proposed_probability_or_distribution is not None
            else current.probability_or_distribution
        )
        proposal_rationale = rationale or ledger._default_autopilot_rationale(
            changed=changed,
            current=current,
        )
        model_run = ledger.record_model_run(
            question_id=question_id,
            model_type="autopilot_refresh",
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
            },
            diagnostics=diagnostics,
            model_version=_core.FORECASTING_PROTOCOL_VERSION,
            evidence_cutoff=run_at,
        )
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
            violations = ledger._autopilot_guardrail_violations(
                policy=policy,
                prior_payload=current.probability_or_distribution,
                proposed_payload=proposed_payload,
                source_snapshots=source_snapshots,
            )
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
    active autopilot policy — the conservative default the free-tier drain uses
    so a `watched_source_changed` alert can resolve WITHOUT an opt-in policy.
    Re-reads every active watched source, records a source-snapshot audit row
    (so the drift is captured in the ledger) and updates ``last_seen_signature``.
    It proposes / commits NOTHING and records NO ``autopilot_run`` (there is no
    policy to attribute one to). This is genuine gated work (a persisted
    source_snapshot), so the dispatcher MAY ack — but it is never a bare ack: a
    question whose watched source has been removed records no snapshot and the
    returned result carries an empty ``source_snapshots``, which the free-drain
    runner treats as falsy (the alert stays OPEN). The shape mirrors the
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
        current_signature = ledger._source_signature(
            watch["source"], watch["source_type"], metadata=watch.get("metadata"),
        )
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
        )
        source_snapshots.append(source_snapshot)
        if did_change:
            changed.append(source_snapshot)
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE watched_sources
                SET last_checked_at = ?, last_seen_signature = ?
                WHERE id = ?
                """,
                (run_at, current_signature, watch["id"]),
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
        "This proposal preserves the previous probability until an explicit model or operator "
        "adjustment supplies a different distribution."
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
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO forecast_update_proposals (
                id, question_id, run_id, prior_forecast_id,
                proposed_probability_or_distribution, rationale, evidence_refs,
                source_snapshot_refs, model_run_refs, assumption_refs,
                reference_class_refs, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                utc_now_iso(),
            ),
        )
    return ledger.get_forecast_update_proposal(proposal_id)


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
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] != "pending" and status != "auto_committed":
        raise ValidationError("only pending proposals can be approved")
    snapshot = ledger.create_snapshot(
        question_id=proposal["question_id"],
        probability_or_distribution=proposal["proposed_probability_or_distribution"],
        rationale=proposal["rationale"],
        method="autopilot",
        style_autofix=True,  # autopilot auto-commit: no agent to rewrite, clean prose mechanically
        distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
        evidence_refs=proposal["evidence_refs"],
        source_snapshot_refs=proposal["source_snapshot_refs"],
        model_run_refs=proposal["model_run_refs"],
        assumption_refs=proposal["assumption_refs"],
        reference_class_refs=proposal["reference_class_refs"],
        require_citations=True,
        metadata={"autopilot_proposal_id": proposal_id},
    )
    reviewed_at = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = ?, reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (status, reviewed_at, reviewed_by, proposal_id),
        )
        if proposal.get("run_id"):
            conn.execute(
                "UPDATE autopilot_runs SET forecast_snapshot_id = ? WHERE id = ?",
                (snapshot.forecast_id, proposal["run_id"]),
            )
    return snapshot


def reject_forecast_update_proposal(
    ledger,
    proposal_id: str,
    *,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    proposal = ledger.get_forecast_update_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise ValidationError("only pending proposals can be rejected")
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (utc_now_iso(), reviewed_by, proposal_id),
        )
    return ledger.get_forecast_update_proposal(proposal_id)


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
