"""Resolution domain (resolutions + corrections + postmortems).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns three closely-related outcome-side
table families:

* RESOLUTIONS: ``resolve_question`` (the gated commit that closes a question) +
  the resolution readers/serializers (``get_resolution`` / ``get_latest_resolution``
  / ``_row_to_resolution`` / ``_resolution_to_dict`` / ``latest_resolution_by_question``),
  the resolution-rule + proposal surface (``set_resolution_rule`` /
  ``propose_resolution`` / ``propose_due_resolutions``), and the trusted-resolver
  policy CRUD (``create_trusted_resolver_policy`` / ``get_`` / ``list_``);
* CORRECTIONS: ``create_correction`` (+ ``get_``/``list_``) and the learning-record
  invalidation cascade (``_affected_records_for_correction`` /
  ``_invalidate_learning_records_for_correction`` / ``_corrections_for_question``);
* POSTMORTEMS: ``create_postmortem`` / ``create_continuous_miss_postmortem_stubs``
  (+ ``get_``/``list_``) and the auto-postmortem derivations (``_predictive_central``
  / ``_auto_postmortem_lesson`` / ``_auto_postmortem_adjustment`` /
  ``_auto_postmortem_error_tags``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. Gated writes reach the shared
write-gate via ``forecasting.ledger.gate``; core-owned constants (``FAILURE_CLASSES``
lives in models) are imported from their origin. Every cross-domain read
(``get_question`` / ``get_current_snapshot`` / scoring / lesson helpers) resolves
through the ``ledger`` INSTANCE, so no core-defined method is imported here."""

from __future__ import annotations

import logging
from typing import Any
from forecasting.models import EvidenceItem
from forecasting.models import FAILURE_CLASSES
from forecasting.models import ForecastQuestion
from forecasting.models import ForecastSnapshot
from forecasting.models import LedgerNotFoundError
from pathlib import Path
from forecasting.models import RESOLUTION_STATUSES
from forecasting.models import Resolution
from forecasting.models import ScoreRecord
from forecasting.models import ValidationError
from forecasting.ledger.watches import WATCH_SOURCE_ROLES
from forecasting.models import json_dumps
from forecasting.models import json_loads
import math
import sqlite3
import time
from forecasting.models import utc_now_iso
import uuid

logger = logging.getLogger(__name__)


def resolve_question(
    ledger,
    *,
    question_id: str,
    outcome: Any,
    resolution_source: str | None = None,
    resolution_source_snapshot_ref: str | None = None,
    resolver_type: str = "manual",
    resolution_status: str = "confirmed",
    criteria_satisfied: bool = True,
    confidence: float | None = None,
    confirmed_by: str | None = None,
    resolver_notes: str | None = None,
    correction_ref: str | None = None,
    trusted_policy_id: str | None = None,
    scoreable: bool = True,
    auto_score: bool = True,
) -> Resolution:
    resolved_question = ledger.get_question(question_id)
    # Validate before changing question/scheduler state. Auto-scoring is best
    # effort, so relying on it to reject an invalid outcome closes an unscoreable
    # question and silently skips the feedback loop.
    if resolution_status == "confirmed" and criteria_satisfied and scoreable:
        space = resolved_question.outcome_space
        if space.type == "binary":
            ledger._probability_for_outcome(0.5, outcome, space)
        elif space.type == "categorical":
            ledger._probability_for_outcome({choice: 0.0 for choice in space.choices}, outcome, space)
    if resolution_status not in RESOLUTION_STATUSES:
        raise ValidationError(
            f"resolution_status must be one of {', '.join(sorted(RESOLUTION_STATUSES))}"
        )
    if confidence is not None and not (0 <= confidence <= 1):
        raise ValidationError("resolution confidence must be between 0 and 1")
    if resolution_status == "corrected" and not correction_ref:
        raise ValidationError("corrected resolutions require correction_ref")
    if trusted_policy_id:
        policy = ledger.get_trusted_resolver_policy(trusted_policy_id)
        if not policy["enabled"]:
            raise ValidationError("trusted resolver policy is disabled")
    now = utc_now_iso()
    resolution_id = f"rs_{uuid.uuid4().hex[:12]}"
    if resolution_source and resolution_source_snapshot_ref is None:
        source_path = Path(resolution_source).expanduser()
        if source_path.is_file():
            resolution_source_snapshot_ref = ledger._archive_resolution_source_snapshot(
                question_id=question_id,
                resolution_id=resolution_id,
                source_file_path=source_path,
            )
    confirmed_at = now if resolution_status == "confirmed" and criteria_satisfied else None
    disputed_at = now if resolution_status == "disputed" else None
    from forecasting.ledger.workflow import calculate_task_utility

    resolution_utility = calculate_task_utility(
        ledger,
        question_id=question_id,
        task_type="finalize_resolution",
        now=now,
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO resolutions (
                id, question_id, resolved_at, outcome, resolution_source,
                resolution_source_snapshot_ref, resolver_type, resolution_status,
                criteria_satisfied, confidence, confirmed_at, confirmed_by,
                resolver_notes, disputed_at, correction_ref, scoreable,
                trusted_policy_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolution_id,
                question_id,
                now,
                json_dumps(outcome),
                resolution_source,
                resolution_source_snapshot_ref,
                resolver_type,
                resolution_status,
                1 if criteria_satisfied else 0,
                confidence,
                confirmed_at,
                confirmed_by,
                resolver_notes,
                disputed_at,
                correction_ref,
                1 if scoreable else 0,
                trusted_policy_id,
            ),
        )
        if resolution_status == "confirmed" and criteria_satisfied:
            conn.execute(
                "UPDATE forecast_questions SET status = 'resolved' WHERE id = ?",
                (question_id,),
            )
            # A confirmed resolution is also the transactional stop signal for
            # every producer attached to this question. Keeping teardown in the
            # SAME transaction prevents a scheduler/watch worker from observing
            # `resolved` while still finding executable work for the question.
            conn.execute(
                "UPDATE watched_sources SET status = 'inactive' "
                "WHERE scope_type = 'question' AND scope_ref = ? AND status = 'active'",
                (question_id,),
            )
            conn.execute(
                "UPDATE scheduled_reviews SET enabled = 0 "
                "WHERE scope_type = 'question' AND scope_ref = ? AND enabled = 1",
                (question_id,),
            )
            conn.execute(
                "UPDATE autopilot_policies SET enabled = 0, updated_at = ? "
                "WHERE question_id = ? AND enabled = 1",
                (now, question_id),
            )
            conn.execute(
                "UPDATE forecast_update_proposals "
                "SET status = 'rejected', reviewed_at = ?, "
                "    reviewed_by = COALESCE(reviewed_by, 'lifecycle:resolved') "
                "WHERE question_id = ? AND status = 'pending'",
                (now, question_id),
            )
            conn.execute(
                "UPDATE alert_events "
                "SET acknowledged_at = ?, "
                "    ack_note = COALESCE(ack_note, 'auto_close:question_resolved'), "
                "    disposition = COALESCE(disposition, 'resolved_by_resolution') "
                "WHERE scope_type = 'question' AND scope_ref = ? "
                "  AND acknowledged_at IS NULL "
                "  AND reason NOT IN ('score_due', 'high_impact_score_due', "
                "                     'postmortem_due', 'high_impact_postmortem_due')",
                (now, question_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO operational_tasks (
                    id, task_type, lane, question_id, status, priority,
                    utility_score, utility_components, available_at,
                    idempotency_key, created_at, updated_at
                ) VALUES (?, 'finalize_resolution', 'deterministic_critical', ?,
                          'pending', 100, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"ot_{uuid.uuid4().hex[:12]}",
                    question_id,
                    resolution_utility["score"],
                    json_dumps(resolution_utility["components"]),
                    now,
                    f"finalize-resolution:{resolution_id}",
                    now,
                    now,
                ),
            )
        elif resolution_status == "proposed":
            conn.execute(
                "UPDATE forecast_questions SET status = 'closed' WHERE id = ? AND status = 'active'",
                (question_id,),
            )
        if trusted_policy_id and resolution_status == "confirmed":
            conn.execute(
                "UPDATE trusted_resolver_policies SET last_used_at = ? WHERE id = ?",
                (now, trusted_policy_id),
            )
    # Auto-score on a confirmed, criteria-satisfied, scoreable resolution so
    # a forecast cannot resolve without a Brier/log score — closing the
    # feedback loop (calibration, postmortems, lessons) automatically. Only
    # scores a committed forecast (origin != "exploratory"); exploratory
    # scratchpad snapshots are never scored. Best-effort: a scoring hiccup
    # must never break the resolution itself, and score_snapshot is
    # idempotent so a later explicit `score` is a no-op.
    if auto_score and resolution_status == "confirmed" and criteria_satisfied and scoreable:
        try:
            snapshot = ledger.get_current_snapshot(question_id)
            if snapshot is not None and snapshot.forecast_origin != "exploratory":
                ledger.score_snapshot(snapshot.forecast_id)
                # Close the learning loop: a fresh LIVE score can shift the signed-
                # bias picture, so re-synthesise the corrective calibration lesson
                # for this question's scope family. synthesize_bias_lessons is
                # internally FDR/ESS-gated — it emits nothing on thin/noisy data —
                # so this is safe to fire on a live resolution. Gated on
                # forecast_origin == "live" for BOTH correctness and cost: the
                # synthesis measures the LIVE stratum only (forecast_origin="live"),
                # so firing it on a backtest/imported resolution would rescan the
                # same live data for no new signal — pure waste (and the per-resolve
                # scan is O(live-scores), so a bulk backtest must not trigger it).
                # Scoped to the resolved question's domain (or global when it has
                # none) to bound cost to a single domain target, not the full "all"
                # sweep. Best-effort: a synthesis hiccup must never break the
                # resolution — a broken step degrades to today's behaviour.
                # Cheap pre-gate (spend bound): the signed-bias estimator emits
                # NOTHING until a scope clears its ESS floor (12 domain / 20
                # global), and each synthesis is O(live-scores) — so a single
                # COUNT skips the whole scan whenever the scope is still obviously
                # too thin. This makes an ordinary small desk (and a bulk cohort
                # below the floor) pay nothing, and only mature scopes run the
                # full synthesis. Count is a necessary condition (ESS <= count),
                # so skipping below it can never suppress a lesson that would fire.
                synth_scope = resolved_question.domain or "global"
                _floor = 12 if resolved_question.domain else 20
                _now_mono = time.monotonic()
                _last = ledger._bias_synth_last.get(synth_scope)
                _debounced = _last is not None and (_now_mono - _last) < ledger._BIAS_SYNTH_DEBOUNCE_SECONDS
                if (
                    snapshot.forecast_origin == "live"
                    and not _debounced
                    and ledger._live_score_count(resolved_question.domain) >= _floor
                ):
                    ledger._bias_synth_last[synth_scope] = _now_mono
                    try:
                        synthesized = ledger.synthesize_bias_lessons(scope=synth_scope, now=now)
                        fired = [
                            r for r in synthesized
                            if isinstance(r, dict) and (r.get("action") or {}).get("written")
                        ]
                        if fired:
                            logger.debug(
                                "auto bias-lesson synthesis on resolution of %s wrote %d lesson(s)",
                                question_id,
                                len(fired),
                            )
                    except Exception:
                        logger.debug(
                            "auto bias-lesson synthesis on resolution failed for %s",
                            question_id,
                            exc_info=True,
                        )
        except Exception:
            logger.debug("auto-score on resolution failed for %s", question_id, exc_info=True)
    # Operator practice loop (R2): score the OPERATOR's own estimates for
    # this question against the confirmed outcome — fail-open, exactly like
    # auto-score, and independent of the system-scoreable flag (the operator's
    # practice number is scored against the same realized outcome). A hiccup
    # here must never break the resolution itself.
    if resolution_status == "confirmed" and criteria_satisfied:
        try:
            ledger.score_operator_estimates(question_id, outcome, now=now)
        except Exception:
            logger.debug(
                "operator-estimate scoring on resolution failed for %s",
                question_id,
                exc_info=True,
            )
    # R4 Living Models: score this question's model_runs against the confirmed
    # outcome so a model's skill accrues (model_skill reads these on-read).
    # Fail-open + gated on scoreable exactly like auto-score — a scoring hiccup
    # must never break the resolution itself.
    if resolution_status == "confirmed" and criteria_satisfied and scoreable:
        try:
            ledger.score_model_runs(question_id, outcome, now=now)
        except Exception:
            logger.debug(
                "model-run scoring on resolution failed for %s",
                question_id,
                exc_info=True,
            )
    # UPGRADE 2 — deviation-bet resolution hook: score any OPEN named-edge bet
    # for this question (Brier-ours-vs-Brier-market on the realized outcome).
    # Fail-open + gated on scoreable exactly like auto-score; a scoring hiccup
    # must never break the resolution, and the scorer is idempotent (an already-
    # scored bet is skipped) so a re-resolve is a no-op.
    if resolution_status == "confirmed" and criteria_satisfied and scoreable:
        try:
            ledger.score_deviation_bets(
                question_id, outcome, resolution_id=resolution_id, now=now
            )
        except Exception:
            logger.debug(
                "deviation-bet scoring on resolution failed for %s",
                question_id,
                exc_info=True,
            )
    return ledger.get_resolution(resolution_id)


def get_resolution(ledger, resolution_id: str) -> Resolution:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM resolutions WHERE id = ?", (resolution_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"resolution not found: {resolution_id}")
    return ledger._row_to_resolution(row)


def get_latest_resolution(
    ledger,
    question_id: str,
    *,
    confirmed_only: bool = False,
) -> Resolution | None:
    clauses = ["question_id = ?"]
    params: list[Any] = [question_id]
    if confirmed_only:
        clauses.extend(["resolution_status = 'confirmed'", "criteria_satisfied = 1", "scoreable = 1"])
    with ledger._connect() as conn:
        row = conn.execute(
            f"""
            SELECT * FROM resolutions
            WHERE {' AND '.join(clauses)}
            ORDER BY resolved_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    return ledger._row_to_resolution(row) if row else None


def set_resolution_rule(
    ledger,
    question_id: str,
    *,
    field: str,
    comparator: str,
    threshold: float,
    resolver: str = "metric_threshold",
    source_role: str = "resolver",
) -> dict[str, Any]:
    """Attach a structured resolution rule so the desk can PROPOSE a resolution
    from ingested source data instead of resolving by hand (feedback #9). The
    rule is the generic shape behind the earnings/benchmark/infrastructure
    resolvers: read ``field`` from a watched source in role ``source_role`` and
    compare it to ``threshold``. Validated up front so a bad rule is refused."""
    from forecasting.resolvers import RESOLVER_TYPES, validate_metric_threshold_rule
    question = ledger.get_question(question_id)
    if resolver not in RESOLVER_TYPES:
        raise ValidationError("resolver must be one of: " + ", ".join(sorted(RESOLVER_TYPES)))
    if source_role not in WATCH_SOURCE_ROLES:
        raise ValidationError("source_role must be one of: " + ", ".join(sorted(WATCH_SOURCE_ROLES)))
    rule = {
        "resolver": resolver,
        "field": str(field).strip(),
        "comparator": comparator,
        "threshold": float(threshold),
        "source_role": source_role,
    }
    issues = validate_metric_threshold_rule(rule)
    if issues:
        raise ValidationError("; ".join(issues))
    meta = dict(question.metadata) if isinstance(question.metadata, dict) else {}
    meta["resolution_rule"] = rule
    with ledger._connect() as conn:
        conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), question_id))
    return rule


def propose_resolution(ledger, question_id: str) -> dict[str, Any] | None:
    """Run the question's resolution rule against the latest ingested source
    value and return a PROPOSED resolution (never committed — the user confirms
    with ``forecast resolve``). None when the question has no rule. An
    undetermined proposal (no observed value yet) is returned, never fabricated."""
    from forecasting.resolvers import propose_metric_threshold
    question = ledger.get_question(question_id)
    meta = question.metadata if isinstance(question.metadata, dict) else {}
    rule = meta.get("resolution_rule")
    if not isinstance(rule, dict):
        return None
    if rule.get("resolver") != "metric_threshold":
        return None
    field = str(rule.get("field") or "")
    source_role = rule.get("source_role") or "resolver"
    observed: float | None = None
    source_ref: str | None = None
    watched = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    for source in watched:
        if source.get("role") != source_role:
            continue
        snaps = ledger.list_source_snapshots(watched_source_id=source["id"], limit=1)
        if not snaps:
            continue
        parsed = snaps[0].get("parsed_values") or {}
        value = parsed.get(field)
        if isinstance(value, (int, float)):
            observed = float(value)
            source_ref = source["id"]
            break
    return propose_metric_threshold(
        question_id=question_id, rule=rule, observed_value=observed, source_ref=source_ref,
    ).to_dict()


def propose_due_resolutions(ledger, *, dry_run: bool = False) -> list[dict[str, Any]]:
    """Autonomy layer for the resolver framework: run every ACTIVE question's
    resolution rule and raise a confirm-me alert for each that now yields a
    DETERMINABLE proposal — so the desk surfaces "this is ready to resolve, YES"
    on its own instead of waiting for the operator to check. Propose-only (the
    user confirms with ``forecast resolve``). Deduped against an existing open
    proposal alert per question so it never re-alerts every cycle. ``dry_run``
    previews without raising alerts."""
    open_alerts = ledger.list_alerts(unresolved_only=True)
    # Dedup is OUTCOME-AWARE: an open alert suppresses re-alerting only for the
    # SAME proposed outcome. If the data flips the proposal (e.g. NO -> YES) the
    # operator must see the new one, so (scope_ref, outcome) is the key, not the
    # question alone.
    already: set[tuple[str, str]] = set()
    for alert in open_alerts:
        reason = (alert.reason or "").lower()
        if alert.scope_type == "question" and "resolution proposed:" in reason:
            tail = reason.split("resolution proposed:", 1)[1].strip()
            outcome = "yes" if tail.startswith("yes") else ("no" if tail.startswith("no") else "")
            already.add((alert.scope_ref, outcome))
    results: list[dict[str, Any]] = []
    for question in ledger.list_questions(status="active"):
        meta = question.metadata if isinstance(question.metadata, dict) else {}
        if not isinstance(meta.get("resolution_rule"), dict):
            continue
        proposal = ledger.propose_resolution(question.id)
        if not proposal or not proposal.get("determinable"):
            continue
        if (question.id, proposal["outcome"]) in already:
            results.append({"question_id": question.id, "outcome": proposal["outcome"], "alerted": False, "skipped": "open_alert"})
            continue
        alert_id = None
        if not dry_run:
            alert = ledger.create_alert(
                severity="warning",
                scope_type="question",
                scope_ref=question.id,
                reason=f"resolution proposed: {str(proposal['outcome']).upper()} — {proposal['rationale']}",
                recommended_action=f"confirm with: forecast resolve {question.id} --outcome {proposal['outcome']}",
            )
            alert_id = alert.id
        results.append({"question_id": question.id, "outcome": proposal["outcome"], "alerted": not dry_run, "alert_id": alert_id})
    return results


def _row_to_resolution(ledger, row: sqlite3.Row) -> Resolution:
    return Resolution(
        id=row["id"],
        question_id=row["question_id"],
        resolved_at=row["resolved_at"],
        outcome=json_loads(row["outcome"], row["outcome"]),
        resolution_source=row["resolution_source"],
        resolution_source_snapshot_ref=row["resolution_source_snapshot_ref"],
        resolver_type=row["resolver_type"],
        resolution_status=row["resolution_status"],
        criteria_satisfied=bool(row["criteria_satisfied"]),
        confidence=row["confidence"],
        confirmed_at=row["confirmed_at"],
        confirmed_by=row["confirmed_by"],
        resolver_notes=row["resolver_notes"],
        disputed_at=row["disputed_at"],
        correction_ref=row["correction_ref"],
        scoreable=bool(row["scoreable"]),
        trusted_policy_id=row["trusted_policy_id"],
    )


def _resolution_to_dict(ledger, resolution: Resolution) -> dict[str, Any]:
    return resolution.__dict__.copy()


def latest_resolution_by_question(ledger, question_ids: list[str]) -> dict[str, Resolution]:
    """question_id -> latest resolution by resolved_at (mirrors
    get_latest_resolution with confirmed_only=False); absent when none."""
    out: dict[str, Resolution] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM resolutions WHERE question_id IN ({placeholders}) "
                "ORDER BY question_id ASC, resolved_at DESC",
                chunk,
            ).fetchall()
        for row in rows:
            qid = row["question_id"]
            if qid not in out:  # first row per question = latest resolved_at
                out[qid] = ledger._row_to_resolution(row)
    return out


def create_trusted_resolver_policy(
    ledger,
    *,
    resolver_plugin: str,
    plugin_version: str | None,
    scope_type: str,
    scope_ref: str | None = None,
    enabled: bool = False,
    approved_by: str | None = None,
    audit_log_ref: str | None = None,
) -> dict[str, Any]:
    if not resolver_plugin.strip():
        raise ValidationError("resolver_plugin is required")
    if scope_type not in {"domain", "topic", "source", "question_type", "global"}:
        raise ValidationError("resolver policy scope_type must be domain, topic, source, question_type, or global")
    policy_id = f"trp_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO trusted_resolver_policies (
                id, resolver_plugin, plugin_version, scope_type, scope_ref,
                enabled, created_at, approved_by, audit_log_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id,
                resolver_plugin.strip(),
                plugin_version,
                scope_type,
                scope_ref,
                1 if enabled else 0,
                utc_now_iso(),
                approved_by,
                audit_log_ref,
            ),
        )
    return ledger.get_trusted_resolver_policy(policy_id)


def get_trusted_resolver_policy(ledger, policy_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM trusted_resolver_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"trusted resolver policy not found: {policy_id}")
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    return data


def list_trusted_resolver_policies(
    ledger,
    *,
    resolver_plugin: str | None = None,
    scope_type: str | None = None,
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if resolver_plugin:
        clauses.append("resolver_plugin = ?")
        params.append(resolver_plugin)
    if scope_type:
        clauses.append("scope_type = ?")
        params.append(scope_type)
    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(1 if enabled else 0)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM trusted_resolver_policies {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        result.append(data)
    return result


def create_correction(
    ledger,
    *,
    target_type: str,
    target_id: str,
    reason: str,
    created_by: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    patch: dict[str, Any] | None = None,
    status: str = "proposed",
) -> dict[str, Any]:
    allowed = {
        "forecast_snapshot",
        "evidence_item",
        "assumption",
        "reference_class",
        "resolution",
        "score_record",
        "postmortem",
        "calibration_lesson",
    }
    if target_type not in allowed:
        raise ValidationError(f"target_type must be one of {', '.join(sorted(allowed))}")
    if status not in {"proposed", "applied", "rejected"}:
        raise ValidationError("correction status must be proposed, applied, or rejected")
    if not reason.strip():
        raise ValidationError("correction reason is required")
    correction_id = f"fc_{uuid.uuid4().hex[:12]}"
    affected_scores, affected_postmortems, affected_lessons = ledger._affected_records_for_correction(
        target_type,
        target_id,
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO forecast_corrections (
                id, target_type, target_id, created_at, created_by, reason,
                old_value, new_value, patch, affected_score_record_refs,
                affected_postmortem_refs, affected_calibration_lesson_refs,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                correction_id,
                target_type,
                target_id,
                utc_now_iso(),
                created_by,
                reason.strip(),
                json_dumps(old_value),
                json_dumps(new_value),
                json_dumps(patch or {}),
                json_dumps(affected_scores),
                json_dumps(affected_postmortems),
                json_dumps(affected_lessons),
                status,
            ),
        )
        if status == "applied":
            ledger._invalidate_learning_records_for_correction(
                conn,
                correction_id=correction_id,
                score_refs=affected_scores,
                postmortem_refs=affected_postmortems,
                lesson_refs=affected_lessons,
            )
    if affected_scores or affected_postmortems or affected_lessons:
        ledger.create_alert(
            severity="high",
            scope_type=target_type,
            scope_ref=target_id,
            reason="correction_affects_learning_records",
            recommended_action="Review affected scores, postmortems, and calibration lessons before relying on them.",
        )
    return ledger.get_correction(correction_id)


def get_correction(ledger, correction_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM forecast_corrections WHERE id = ?",
            (correction_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"correction not found: {correction_id}")
    data = dict(row)
    for field in (
        "old_value",
        "new_value",
        "patch",
        "affected_score_record_refs",
        "affected_postmortem_refs",
        "affected_calibration_lesson_refs",
    ):
        data[field] = json_loads(data[field], {} if field in {"old_value", "new_value", "patch"} else [])
    return data


def list_corrections(
    ledger,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if target_type:
        clauses.append("target_type = ?")
        params.append(target_type)
    if target_id:
        clauses.append("target_id = ?")
        params.append(target_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT id FROM forecast_corrections {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [ledger.get_correction(row["id"]) for row in rows]


def apply_correction(
    ledger, correction_id: str, *, applied_by: str | None = None
) -> dict[str, Any]:
    """Apply a proposed correction and invalidate every derived learning row."""
    correction = ledger.get_correction(correction_id)
    if correction["status"] == "applied":
        return correction
    if correction["status"] != "proposed":
        raise ValidationError("only proposed corrections can be applied")
    patch: dict[str, Any] = {}
    if isinstance(correction.get("new_value"), dict):
        patch.update(correction["new_value"])
    if isinstance(correction.get("patch"), dict):
        patch.update(correction["patch"])
    with ledger._connect() as conn:
        if correction["target_type"] == "score_record":
            allowed = {"calibration_eligible", "calibration_weight", "notes"}
            unknown = set(patch) - allowed - {"reason"}
            if unknown:
                raise ValidationError(
                    "unsupported score correction fields: " + ", ".join(sorted(unknown))
                )
            assignments: list[str] = []
            params: list[Any] = []
            if "calibration_eligible" in patch:
                assignments.append("calibration_eligible = ?")
                params.append(1 if patch["calibration_eligible"] else 0)
            if "calibration_weight" in patch:
                weight = float(patch["calibration_weight"])
                if weight < 0:
                    raise ValidationError("calibration_weight must be non-negative")
                assignments.append("calibration_weight = ?")
                params.append(weight)
            if "notes" in patch:
                assignments.append("notes = ?")
                params.append(str(patch["notes"]))
            if assignments:
                params.append(correction["target_id"])
                conn.execute(
                    f"UPDATE score_records SET {', '.join(assignments)} WHERE id = ?",
                    params,
                )
        ledger._invalidate_learning_records_for_correction(
            conn,
            correction_id=correction_id,
            score_refs=correction["affected_score_record_refs"],
            postmortem_refs=correction["affected_postmortem_refs"],
            lesson_refs=correction["affected_calibration_lesson_refs"],
        )
        conn.execute(
            "UPDATE forecast_corrections SET status = 'applied', "
            "created_by = COALESCE(?, created_by) WHERE id = ? AND status = 'proposed'",
            (applied_by, correction_id),
        )
        conn.execute(
            """
            UPDATE forecast_corrections SET status = 'rejected'
            WHERE target_type = ? AND target_id = ? AND id != ? AND status = 'proposed'
            """,
            (correction["target_type"], correction["target_id"], correction_id),
        )
        conn.execute(
            """
            UPDATE alert_events
            SET acknowledged_at = ?, disposition = 'correction_applied',
                ack_note = COALESCE(ack_note, 'auto_close:correction_applied')
            WHERE scope_type = ? AND scope_ref = ? AND acknowledged_at IS NULL
              AND reason = 'correction_affects_learning_records'
            """,
            (utc_now_iso(), correction["target_type"], correction["target_id"]),
        )
    return ledger.get_correction(correction_id)


def _corrections_for_question(
    ledger,
    *,
    question_id: str,
    snapshots: list[ForecastSnapshot],
    evidence: list[EvidenceItem],
    assumptions: list[dict[str, Any]],
    reference_classes: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
    resolution: Resolution | None,
    scores: list[ScoreRecord],
    postmortems: list[dict[str, Any]],
    calibration_lessons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    del model_runs
    ids_by_type = {
        "forecast_snapshot": {snapshot.forecast_id for snapshot in snapshots},
        "evidence_item": {item.id for item in evidence},
        "assumption": {item["id"] for item in assumptions},
        "reference_class": {item["id"] for item in reference_classes},
        "resolution": {resolution.id} if resolution else set(),
        "score_record": {score.id for score in scores},
        "postmortem": {item["id"] for item in postmortems},
        "calibration_lesson": {item["id"] for item in calibration_lessons},
    }
    corrections = []
    for correction in ledger.list_corrections():
        if correction["target_type"] in ids_by_type and correction["target_id"] in ids_by_type[correction["target_type"]]:
            corrections.append(correction)
    return corrections


def _affected_records_for_correction(
    ledger,
    target_type: str,
    target_id: str,
) -> tuple[list[str], list[str], list[str]]:
    score_refs: list[str] = []
    postmortem_refs: list[str] = []
    lesson_refs: list[str] = []
    with ledger._connect() as conn:
        if target_type == "resolution":
            score_refs = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM score_records WHERE resolution_id = ?",
                    (target_id,),
                ).fetchall()
            ]
            postmortem_refs = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM postmortems WHERE resolution_id = ?",
                    (target_id,),
                ).fetchall()
            ]
        elif target_type == "score_record":
            score_refs = [target_id]
            postmortem_refs = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM postmortems WHERE score_record_id = ?",
                    (target_id,),
                ).fetchall()
            ]
        elif target_type == "postmortem":
            postmortem_refs = [target_id]
        elif target_type == "calibration_lesson":
            lesson_refs = [target_id]
        if postmortem_refs:
            all_lessons = conn.execute("SELECT id, source_postmortem_refs FROM calibration_lessons").fetchall()
            postmortem_set = set(postmortem_refs)
            for row in all_lessons:
                refs = set(json_loads(row["source_postmortem_refs"], []))
                if refs & postmortem_set:
                    lesson_refs.append(row["id"])
        if score_refs:
            all_lessons = conn.execute("SELECT id, source_score_record_refs FROM calibration_lessons").fetchall()
            score_set = set(score_refs)
            for row in all_lessons:
                refs = set(json_loads(row["source_score_record_refs"], []))
                if refs & score_set:
                    lesson_refs.append(row["id"])
    return sorted(set(score_refs)), sorted(set(postmortem_refs)), sorted(set(lesson_refs))


def _invalidate_learning_records_for_correction(
    ledger,
    conn: sqlite3.Connection,
    *,
    correction_id: str,
    score_refs: list[str],
    postmortem_refs: list[str],
    lesson_refs: list[str],
) -> None:
    if score_refs:
        conn.executemany(
            "UPDATE score_records SET invalidated_by_correction_id = ? WHERE id = ?",
            [(correction_id, score_id) for score_id in score_refs],
        )
    if postmortem_refs:
        conn.executemany(
            "UPDATE postmortems SET invalidated_by_correction_id = ? WHERE id = ?",
            [(correction_id, postmortem_id) for postmortem_id in postmortem_refs],
        )
    if lesson_refs:
        conn.executemany(
            """
            UPDATE calibration_lessons
            SET invalidated_by_correction_id = ?, status = 'superseded', updated_at = ?
            WHERE id = ?
            """,
            [(correction_id, utc_now_iso(), lesson_id) for lesson_id in lesson_refs],
        )


def create_postmortem(
    ledger,
    *,
    question_id: str,
    summary: str = "",
    what_happened: str = "",
    what_was_expected: str = "",
    missed_evidence: str = "",
    overweighted_evidence: str = "",
    base_rate_error: str = "",
    inside_view_error: str = "",
    resolution_error: str = "",
    lesson: str = "",
    calibration_adjustment: dict[str, Any] | None = None,
    failure_class: str | None = None,
) -> dict[str, Any]:
    question = ledger.get_question(question_id)
    if failure_class is not None:
        failure_class = failure_class.strip().lower() or None
        if failure_class and failure_class not in FAILURE_CLASSES:
            raise ValidationError(
                f"failure_class must be one of {', '.join(sorted(FAILURE_CLASSES))}"
            )
    score = ledger.score_question(question_id)
    snapshot = ledger.get_snapshot(score.forecast_id)
    resolution = ledger.get_resolution(score.resolution_id)
    with ledger._connect() as conn:
        existing = conn.execute(
            """
            SELECT id FROM postmortems
            WHERE score_record_id = ? AND invalidated_by_correction_id IS NULL
            ORDER BY created_at ASC, id ASC LIMIT 1
            """,
            (score.id,),
        ).fetchone()
    if existing is not None:
        return ledger.get_postmortem(existing["id"])
    postmortem_id = f"pm_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO postmortems (
                id, question_id, forecast_id, resolution_id, score_record_id,
                forecast_origin, calibration_eligible, created_at, summary,
                what_happened, what_was_expected, missed_evidence,
                overweighted_evidence, base_rate_error, inside_view_error,
                resolution_error, lesson, calibration_adjustment, failure_class
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                postmortem_id,
                question_id,
                snapshot.forecast_id,
                resolution.id,
                score.id,
                score.forecast_origin,
                1 if score.calibration_eligible else 0,
                utc_now_iso(),
                summary or f"Resolved outcome was {resolution.outcome!r}.",
                what_happened or f"Resolution recorded outcome {resolution.outcome!r}.",
                what_was_expected or f"Forecast probability was {snapshot.probability_or_distribution!r}.",
                missed_evidence,
                overweighted_evidence,
                base_rate_error,
                inside_view_error,
                resolution_error,
                lesson,
                json_dumps(calibration_adjustment or {}),
                failure_class,
            ),
        )
    postmortem = ledger.get_postmortem(postmortem_id)
    if lesson and score.calibration_eligible:
        ledger.create_calibration_lesson(
            scope_type="domain" if question.domain else "global",
            scope_ref=question.domain,
            lesson=lesson,
            confidence=0.5,
            recommended_adjustment=calibration_adjustment or {},
            source_postmortem_refs=[postmortem_id],
            source_score_record_refs=[score.id],
            status="tentative",
        )
    ledger.update_domain_error_profile(question)
    return postmortem


def _predictive_central(ledger, payload: Any) -> float | None:
    """A robust central estimate of a predictive distribution payload —
    prefer an explicit central moment, else the midpoint of the narrowest
    central interval, else a bare numeric. Used ONLY to state the direction
    of a continuous miss (forecast central vs realized outcome); None when
    no central can be read (never a fabricated number)."""
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return float(payload)
    if not isinstance(payload, dict):
        return None
    for key in ("median", "mean", "expected", "point", "value"):
        v = payload.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return float(v)
    for width in ("50", "80", "90"):
        lo = payload.get(f"interval_{width}_low")
        hi = payload.get(f"interval_{width}_high")
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, hi)):
            return (float(lo) + float(hi)) / 2.0
    return None


def create_continuous_miss_postmortem_stubs(
    ledger,
    *,
    question_ids: list[str] | None = None,
    dry_run: bool = True,
    min_crps: float = 0.0,
) -> dict[str, Any]:
    """Generate postmortem STUBS for resolved continuous (CRPS-scored) misses
    — the direction (forecast central above/below the realized outcome) and
    magnitude (CRPS + the raw gap) pre-filled from the score, surfaced as a
    REVIEW ITEM for the operator and never auto-concluded (no ``lesson`` is
    written, so no calibration lesson is spawned).
    Read-only when ``dry_run`` (the default): returns the proposal. When
    ``dry_run`` is False, a stub is created for each candidate that does not
    already have a postmortem. Idempotent — questions already carrying a
    postmortem are skipped."""
    if question_ids is None:
        candidates = [
            q.id
            for q in ledger.list_questions()
            if q.outcome_space.type in {"distribution", "numeric"}
        ]
    else:
        candidates = list(question_ids)
    proposed: list[dict[str, Any]] = []
    for qid in candidates:
        score = ledger.get_current_score(qid)
        if score is None or not str(score.score_rule or "").startswith("crps"):
            continue
        if score.proper_score is None or float(score.proper_score) < min_crps:
            continue
        if ledger.list_postmortems(question_id=qid):
            continue  # never duplicate a postmortem.
        snapshot = ledger.get_snapshot(score.forecast_id)
        resolution = ledger.get_resolution(score.resolution_id)
        central = ledger._predictive_central(snapshot.probability_or_distribution)
        try:
            outcome_value = ledger._numeric_outcome(resolution.outcome)
        except Exception:
            outcome_value = None
        direction = "unknown"
        gap: float | None = None
        if central is not None and outcome_value is not None:
            gap = central - outcome_value
            direction = "high" if gap > 0 else "low" if gap < 0 else "on_target"
        proposed.append(
            {
                "question_id": qid,
                "score_id": score.id,
                "direction": direction,
                "forecast_central": central,
                "outcome": outcome_value,
                "gap": gap,
                "crps": float(score.proper_score),
            }
        )
    created = 0
    if not dry_run:
        for item in proposed:
            gap_txt = (
                f" by {abs(item['gap']):.4g} (forecast central {item['forecast_central']:.4g} "
                f"vs outcome {item['outcome']:.4g})"
                if item["gap"] is not None
                else ""
            )
            ledger.create_postmortem(
                question_id=item["question_id"],
                summary=(
                    f"STUB (review): continuous miss — forecast ran {item['direction']}"
                    f"{gap_txt}; CRPS {item['crps']:.4g}."
                ),
                what_happened=(
                    f"Realized outcome {item['outcome']!r}; the forecast central estimate "
                    f"was {item['forecast_central']!r} — i.e. the forecast ran {item['direction']}."
                ),
                what_was_expected=(
                    f"Predictive distribution centered near {item['forecast_central']!r}; "
                    f"CRPS against the confirmed outcome was {item['crps']:.4g}."
                ),
                # No lesson / failure_class: a STUB is a review item, never an
                # auto-concluded diagnosis. The operator fills these in.
                failure_class=None,
            )
            created += 1
    return {"dry_run": dry_run, "created": created, "proposed": proposed}


def get_postmortem(ledger, postmortem_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM postmortems WHERE id = ?", (postmortem_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"postmortem not found: {postmortem_id}")
    data = dict(row)
    data["calibration_eligible"] = bool(data["calibration_eligible"])
    data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
    data.setdefault("failure_class", None)
    return data


def list_postmortems(
    ledger,
    question_id: str | None = None,
    *,
    include_invalidated: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if not include_invalidated:
        clauses.append("invalidated_by_correction_id IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM postmortems {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["calibration_eligible"] = bool(data["calibration_eligible"])
        data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
        data.setdefault("failure_class", None)
        result.append(data)
    return result


def _auto_postmortem_lesson(ledger, question: ForecastQuestion, score: ScoreRecord) -> str:
    if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
        return ""
    if score.brier_score is None or score.brier_score < 0.25:
        return ""
    scope = question.domain or "global"
    origin_prefix = (
        "Recent"
        if score.forecast_origin == "live"
        else f"Eligible {score.forecast_origin} replay"
    )
    tags = ledger._auto_postmortem_error_tags(score)
    if "overconfidence" in tags:
        return (
            f"{origin_prefix} high-confidence miss in {scope}; require explicit base-rate, "
            "counterevidence, and assumption-staleness checks before similar extreme probabilities."
        )
    return (
        f"{origin_prefix} high-Brier resolved forecast in {scope}; check base rates, "
        "missed evidence, and confidence before similar updates."
    )


def _auto_postmortem_adjustment(ledger, question: ForecastQuestion, score: ScoreRecord) -> dict[str, Any]:
    if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
        return {}
    tags = ledger._auto_postmortem_error_tags(score)
    if not tags:
        return {}
    checklist = [
        "Compare against a current reference class before changing probability.",
        "Look for counterevidence from at least one independent source class.",
        "Re-check active assumptions and evidence freshness before the next update.",
    ]
    return {
        "error_tags": tags,
        "forecast_origin": score.forecast_origin,
        "requires_review_before_live_use": score.forecast_origin != "live",
        "review_checklist": checklist,
        "scope": question.domain or "global",
    }


def _auto_postmortem_error_tags(ledger, score: ScoreRecord) -> list[str]:
    if score.brier_score is None or score.brier_score < 0.25:
        return []
    tags = ["high_brier_miss"]
    try:
        snapshot = ledger.get_snapshot(score.forecast_id)
    except LedgerNotFoundError:
        return tags
    sharpness = ledger._sharpness(snapshot.probability_or_distribution)
    if sharpness is not None and sharpness >= 0.6:
        tags.insert(0, "overconfidence")
    return tags
