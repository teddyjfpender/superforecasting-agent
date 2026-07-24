"""Alerts domain (D7 carve — the desk's health engine + alert_events lifecycle).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the whole ALERTS surface:

* the ``alert_events`` CRUD + lifecycle — ``create_alert`` / ``get_alert`` /
  ``list_alerts`` / ``acknowledge_alert`` / ``record_alert_attempt`` (backoff) /
  ``dismiss_alerts`` + ``active_dismissal_keys`` (the TTL silence window) and the
  ``_row_to_alert`` serializer;
* the fold/dedupe/recenter reconciler ``reconcile_alerts`` (score-clears consumed
  alerts, deduped by reason+scope);
* the under-saturation WARN cluster — ``enqueue_saturation_alert`` /
  ``sweep_saturation_alerts`` / ``_has_open_alert``;
* the DOCTOR engine ``self_check`` (returns ``list[AlertEvent]``) with its
  exclusive scope/severity helpers ``_question_in_portfolio`` /
  ``_question_matches_confidence`` / ``_is_high_impact_question`` /
  ``_recommended_action``;
* the alert PRODUCERS deferred by earlier slices — ``_domain_error_profile_alerts``
  (+ its ``_active_questions_for_error_profile`` / ``_error_profile_question_action``
  formatting helpers), ``_calibration_lesson_review_alerts``,
  ``_benchmark_evidence_alerts`` (D3 left it), and ``_is_learning_alert_reason``
  (a ``@staticmethod``, D6 left it).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed.

Dependency direction (no cycle, per the D1 finding): this leaf owns its two
leaf-exclusive alert constants and imports only ``forecasting.models`` + stdlib
at load time — it has NO load-time dependency on ``core`` and needs NO ``_core.``
hop. Everything the moved bodies read is reached through the ``ledger`` INSTANCE
at call time: the write path uses ``create_alert``'s own ``_connect`` /
``allow_ledger_writes``-free INSERT (``alert_events`` is not a GATED table); the
cross-domain reads (``get_question`` / ``list_questions`` / ``review_questions``
(reviews leaf) / ``check_watched_sources`` (watches leaf) / ``snapshots_by_question``
(snapshots leaf) / ``list_calibration_lessons`` / ``list_domain_error_profiles`` /
``list_scores`` / ``list_postmortems`` / ``list_backtest_runs`` / the shared
validators ``_validate_confidence_filters`` / ``_validate_probability_threshold`` /
``_horizon_matches`` and the auto-postmortem writers ``_auto_postmortem_*``) all
stay in core / their own leaves and resolve through the class delegate.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import Any, Iterable

from forecasting.models import (
    AlertEvent,
    ForecastQuestion,
    ForecastingError,
    LedgerNotFoundError,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)

# ---------------------------------------------------------------------------
# Leaf-owned alert constants (D1 "constants to the leaf" — ``core`` imports NONE
# of these back; both are PRIVATE / never on the package surface and are
# referenced only by the moved alert methods).

# Under-saturation WARN alert reason. The observe-mode saturation score is
# recorded on every snapshot but changes no behaviour; the scheduled cron sweep
# raises a deduped WARN alert for each active LIVE forecast below the bar, and a
# programmatic commit (refresh / aggregate / autopilot) escalates the SAME alert
# the moment it commits under the bar. The alert routes to the REFORECAST
# resolution kind, so ``reconcile_alerts`` auto-clears it once a fresh snapshot
# lands and the next sweep re-raises only if it is still under-saturated. Never a
# bare-ack; deduped by reason+scope.
_SATURATION_ALERT_REASON = "under_saturated"

# G5 · cadence-overdue WARN alert reason. The sweep-side update_cadence_honored rule
# fires read-only (event="lint") for a live forecast past its review cadence × the
# grace multiple with no recorded stale_evidence_reason; this raises a deduped WARN
# alert that folds through create_alert (touch, never re-row) and ages up the P1
# escalation ladder (7d elevated / 14d high). It auto-closes on a fresh snapshot.
_CADENCE_ALERT_REASON = "cadence_overdue"

# Default re-surface window for a dismissed group (the design's TTL). A dismissal
# silences a group for this many days; once the window elapses the group
# re-surfaces (``self_check`` re-emits the alert IF the condition still holds). A
# dismissal is NEVER an indefinite silence.
DISMISS_TTL_DAYS_DEFAULT = 7

# Severity ladder (most-severe first). Mirrors the warnings dispatcher's rank so the
# desk, the dedup "severity max", and the age-escalation all agree on ordering.
_SEVERITY_ORDER = ("info", "warning", "high")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(_SEVERITY_ORDER)}


def _more_severe(a: str | None, b: str | None) -> str:
    """Return whichever of two severities is MORE severe (info < warning < high).
    An unknown severity is treated as the least severe so it never wins the max."""
    ra = _SEVERITY_RANK.get((a or "").strip().lower(), -1)
    rb = _SEVERITY_RANK.get((b or "").strip().lower(), -1)
    return (a or "info") if ra >= rb else (b or "info")


# Age-escalation thresholds (Fix 4). An OPEN alert that ages past these floors has
# its severity escalated so a genuinely-neglected item sorts UP the desk instead of
# drowning in the backlog. The escalation only ever RAISES severity (never a
# downgrade) and keys off ``created_at`` (the oldest/first emission, preserved by the
# enqueue dedup) — so the clock is real neglect, not the last re-fire. "elevated"
# maps onto the existing ``warning`` tier (there is no separate tier in the ladder).
ESCALATE_ELEVATED_DAYS = 7
ESCALATE_HIGH_DAYS = 14

# Canonical reason prefix for a resolution PROPOSAL alert (guide-and-make-visible,
# never an auto-resolution). Both the metric-threshold resolver
# (``propose_due_resolutions``) and the auto-resolution DETECTOR
# (``forecasting.resolution_detector``) raise this SAME reason so their proposals
# dedupe outcome-aware against each other and surface / reconcile identically — a
# question never carries two competing proposal alerts for the same outcome. The
# reason falls through ``classify_warning`` to NO_AUTO (surfaced for the human,
# never auto-reconciled), so the proposal stays OPEN until the operator confirms
# via the EXISTING ``forecast resolve`` flow (which auto-scores + synthesizes the
# lesson) or dismisses it.
_RESOLUTION_PROPOSAL_REASON_PREFIX = "resolution proposed:"


def resolution_proposal_outcome(reason: str | None) -> str | None:
    """Parse the proposed outcome token out of a ``resolution proposed:`` reason
    (the first word after the prefix, lower-cased) — the outcome-aware dedup key.
    Returns None for any non-proposal reason. Mirrors the inline parse in
    :meth:`propose_due_resolutions` so both proposal producers dedupe on the SAME
    key space."""
    text = (reason or "").strip().lower()
    if _RESOLUTION_PROPOSAL_REASON_PREFIX not in text:
        return None
    tail = text.split(_RESOLUTION_PROPOSAL_REASON_PREFIX, 1)[1].strip()
    if not tail:
        return None
    token = tail.split()[0].strip().strip("—-").strip()
    return token or None


def normalized_alert_key(
    reason: str | None,
    *,
    prior_forecast_id: str | None = None,
) -> str:
    """Return a stable condition key while preserving ``reason`` as display text."""
    text = " ".join(str(reason or "").strip().split())
    if text.startswith("new_evidence:"):
        return f"new_evidence_batch:{prior_forecast_id or 'unforecasted'}"
    if text.startswith("learned_error_update_required:"):
        # The run/profile suffix is evidence for the review, not a new operator
        # condition. Scope already separates questions, so keep one open review
        # family per question instead of manufacturing a task for every run.
        return "learned_error_update_required"
    if text.startswith("forecast_estimation_required:"):
        return "forecast_estimation_required"
    if text.startswith("autopilot_estimation_required:"):
        return "autopilot_estimation_required"
    outcome = resolution_proposal_outcome(text)
    if outcome:
        return f"resolution_proposed:{outcome}"
    approval_class = approval_request_action_class(text)
    if approval_class:
        return f"approval_required:{approval_class}"
    return text.lower()


def enqueue_resolution_proposal(
    ledger,
    *,
    question_id: str,
    outcome: Any,
    rationale: str,
    confirm_command: str | None = None,
) -> AlertEvent:
    """Raise the canonical confirm-me PROPOSAL alert for a detected/derived
    resolution. Propose-only: this writes an ``alert_events`` row, NEVER a
    resolution. The ``recommended_action`` is the exact one-key confirm path
    through the EXISTING resolve flow (``forecast resolve <id> --outcome <o>``),
    which auto-scores + synthesizes the lesson. Callers own dedup (outcome-aware,
    via :func:`resolution_proposal_outcome`) — this always writes."""
    outcome_label = str(outcome).strip()
    reason = f"{_RESOLUTION_PROPOSAL_REASON_PREFIX} {outcome_label.upper()} — {rationale}"
    action = confirm_command or (
        f"confirm with: forecast resolve {question_id} --outcome {outcome_label}"
    )
    return ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question_id,
        reason=reason,
        recommended_action=action,
    )


# Canonical reason prefix for a job APPROVAL request (Arc-9 approval/spend matrix).
# A background job whose ``policy.<mode>.<class>`` cell resolved to ``ask`` parks and
# raises this alert — the SAME guide-and-make-visible seam a resolution PROPOSAL rides.
# There is no metadata column on ``alert_events``, so the job_id rides ``scope_ref``,
# the action class rides the ``reason`` (after this prefix), and the operator
# how-to + the parked detail ride ``recommended_action`` — exactly as a proposal's
# outcome rides its reason. It surfaces in the open backlog until the operator
# approves (``forecast jobs approve <id>`` — a documented follow-up surface) or loosens
# the policy key, at which point the parked job resumes.
_APPROVAL_REQUEST_REASON_PREFIX = "approval required:"


def approval_request_action_class(reason: str | None) -> str | None:
    """Parse the action-class token out of an ``approval required:`` reason (the first
    word after the prefix). Returns None for any non-approval reason — the dedup key
    space, mirroring :func:`resolution_proposal_outcome`."""
    text = (reason or "").strip().lower()
    if _APPROVAL_REQUEST_REASON_PREFIX not in text:
        return None
    tail = text.split(_APPROVAL_REQUEST_REASON_PREFIX, 1)[1].strip()
    if not tail:
        return None
    token = tail.split()[0].strip()
    return token or None


def enqueue_approval_request(
    ledger,
    *,
    job_id: str,
    job_type: str,
    action_class: str,
    detail: str,
    run_mode: str,
    confirm_command: str | None = None,
) -> AlertEvent:
    """Raise (or reuse) the confirm-me APPROVAL alert for a job parked by an ``ask``
    policy cell. Propose-only: writes an ``alert_events`` row, never authorizes the
    action. Deduped against an already-open request for the SAME ``(job, class)`` (the
    reason encodes both), so a re-run before approval never stacks a duplicate — it
    returns the existing alert."""
    reason = f"{_APPROVAL_REQUEST_REASON_PREFIX} {action_class} for {job_type} job {job_id}"
    for alert in ledger.list_alerts(unresolved_only=True):
        if (
            alert.reason == reason
            and alert.scope_type == "job"
            and alert.scope_ref == job_id
        ):
            return alert  # dedup: the request is already open
    action = confirm_command or (
        f"approve with: forecast jobs approve {job_id}  "
        f"(or loosen policy.{run_mode}.{action_class} — set "
        f"FORECAST_POLICY_{run_mode.upper()}_{action_class.upper()}=auto). "
        f"Parked action: {detail}"
    )
    return ledger.create_alert(
        severity="warning",
        scope_type="job",
        scope_ref=job_id,
        reason=reason,
        recommended_action=action,
    )


def _has_open_alert(ledger, *, reason: str, scope_type: str, scope_ref: str) -> bool:
    """True when an unacknowledged alert with the SAME reason+scope already
    exists — so a re-transition does not stack a duplicate row (mirrors the
    dedup in :meth:`propose_due_resolutions`)."""
    for alert in ledger.list_alerts(unresolved_only=True):
        if (
            alert.reason == reason
            and alert.scope_type == scope_type
            and alert.scope_ref == scope_ref
        ):
            return True
    return False


def enqueue_saturation_alert(
    ledger,
    question_id: str,
    saturation: Any,
    *,
    threshold: float | None = None,
) -> "AlertEvent | None":
    """Open a deduped WARN under-saturation alert for a forecast whose STORED
    saturation report (``snapshot_metadata['saturation']``, passed in — no
    recompute) scores below ``threshold`` (config
    ``forecasting.hooks.sweep_alert_threshold``, default 60). The
    ``recommended_action`` carries the failing rule ids + remediation hints.
    Deduped against an already-open alert of the same reason+scope (mirrors the
    triage-graduation + resolver-proposal kinds — never stacks a duplicate).
    Returns the new AlertEvent, or None (no report / at-or-above the bar /
    already open). Fail-open callers should still wrap this."""
    from forecasting.hooks import saturation_summary, sweep_alert_threshold

    summary = saturation_summary(saturation)
    if summary is None:
        return None
    score = summary.get("score")
    if not isinstance(score, (int, float)):
        return None
    bar = threshold if threshold is not None else sweep_alert_threshold()
    if score >= bar:
        return None
    if ledger._has_open_alert(
        reason=_SATURATION_ALERT_REASON,
        scope_type="question",
        scope_ref=question_id,
    ):
        return None
    advisories = summary.get("advisories") or []
    rule_ids = [str(a.get("rule_id")) for a in advisories if a.get("rule_id")]
    hints = sorted({str(a.get("remediation")) for a in advisories if a.get("remediation")})
    action = f"forecast saturation {float(score):.0f}/100 is below the {float(bar):.0f} bar — under-saturated. "
    if rule_ids:
        action += f"Failing checks: {', '.join(rule_ids)}. "
    if hints:
        action += f"Remediate: {', '.join(hints)}. "
    action += (
        "Re-run the forecast (collect fresh evidence / run the panel / decompose / "
        "tag reasoning) to raise saturation, then re-commit."
    )
    return ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question_id,
        reason=_SATURATION_ALERT_REASON,
        recommended_action=action,
    )


def sweep_saturation_alerts(
    ledger,
    *,
    threshold: float | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Scan active LIVE forecasts and open a deduped WARN alert for each whose
    STORED saturation score is below the bar. Read-only over the observe report
    already on each current snapshot — no hook recompute. Batched
    (``snapshots_by_question``) to avoid a per-question query. Returns
    ``{checked, under_saturated, alerted:[question_id]}``."""
    from forecasting.hooks import saturation_summary, sweep_alert_threshold

    bar = threshold if threshold is not None else sweep_alert_threshold()
    questions = [
        q for q in ledger.list_questions(status="active", limit=limit)
        if q.outcome_space.type != "thesis"
    ]
    snapshots_by_q = ledger.snapshots_by_question([q.id for q in questions])
    checked = 0
    under = 0
    alerted: list[str] = []
    for question in questions:
        snaps = snapshots_by_q.get(question.id) or []
        current = snaps[-1] if snaps else None
        if current is None or getattr(current, "forecast_origin", None) != "live":
            continue
        metadata = getattr(current, "metadata", None)
        saturation = metadata.get("saturation") if isinstance(metadata, dict) else None
        summary = saturation_summary(saturation)
        if summary is None or not isinstance(summary.get("score"), (int, float)):
            continue
        checked += 1
        if summary["score"] >= bar:
            continue
        under += 1
        alert = ledger.enqueue_saturation_alert(question.id, saturation, threshold=bar)
        if alert is not None:
            alerted.append(question.id)
    return {"checked": checked, "under_saturated": under, "alerted": alerted}


def sweep_cadence_alerts(
    ledger,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """G5 · scan active LIVE forecasts and open a deduped ``cadence_overdue`` WARN alert
    for each whose current snapshot has out-lived its review cadence past the grace
    multiple with no recorded stale_evidence_reason. Fires the sweep-side
    update_cadence_honored hook rule READ-ONLY (event="lint"); the alert folds through
    ``create_alert`` (touch, never re-row) and ages up the P1 escalation ladder
    (7d elevated / 14d high). Best-effort. Returns ``{checked, overdue, alerted}``."""
    from forecasting.hooks import lint_forecast

    questions = [
        q for q in ledger.list_questions(status="active", limit=limit)
        if q.outcome_space.type != "thesis"
    ]
    checked = 0
    overdue = 0
    alerted: list[str] = []
    for question in questions:
        try:
            report = lint_forecast(ledger, question.id, event="lint")
        except Exception:
            report = None
        if report is None:
            continue
        checked += 1
        verdict = next(
            (v for v in report.verdicts if v.rule_id == "update_cadence_honored" and not v.passed),
            None,
        )
        if verdict is None:
            continue
        overdue += 1
        already = ledger._has_open_alert(
            reason=_CADENCE_ALERT_REASON, scope_type="question", scope_ref=question.id
        )
        action = verdict.message or (
            "This forecast is past its review cadence — run `forecast refresh <id>` or record "
            "stale_evidence_reason."
        )
        # refresh_action keeps the (changing) overdue-ratio detail current on a touch.
        ledger.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=question.id,
            reason=_CADENCE_ALERT_REASON,
            recommended_action=action,
            refresh_action=True,
        )
        if not already:
            alerted.append(question.id)
    return {"checked": checked, "overdue": overdue, "alerted": alerted}


def _is_learning_alert_reason(reason: str | None) -> bool:
    text = str(reason or "")
    return text in {"calibration_lesson_review", "domain_error_profile_review"} or text.startswith(
        "domain_error_profile_applies:"
    )


def create_alert(
    ledger,
    *,
    severity: str,
    scope_type: str,
    scope_ref: str,
    reason: str,
    recommended_action: str,
    refresh_action: bool = False,
    now: str | None = None,
) -> AlertEvent:
    """Open an alert, or — the UNIVERSAL enqueue dedup (Fix 1) — TOUCH the existing
    OPEN alert with the same ``(scope_type, scope_ref, reason)`` instead of writing a
    second row. This is the single chokepoint every producer flows through, so the
    dedup covers the paths that previously bypassed it (``self_check``'s staleness
    loop, the learning-review producers, benchmark gaps) and floods the ledger no
    more: a re-fired condition bumps ``seen_count`` + ``last_seen_at`` and raises
    ``severity`` to the max, but ``created_at`` (the first emission) and the row id
    are preserved so age-escalation and downstream refs stay stable.

    ``refresh_action=True`` also refreshes ``recommended_action`` on a touch — used by
    digest producers (the domain-error-profile review) whose action text summarises a
    changing set (matching forecasts); the default leaves a stable action untouched.
    A dedup only ever folds into an OPEN row (``acknowledged_at IS NULL``): once an
    alert is acked/dismissed a recurrence opens a fresh row, as it should.
    """
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    target_id = f"al_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        prior_forecast_id = None
        if scope_type == "question" and str(reason).startswith("new_evidence:"):
            question = conn.execute(
                "SELECT current_forecast_id FROM forecast_questions WHERE id = ?",
                (scope_ref,),
            ).fetchone()
            prior_forecast_id = question["current_forecast_id"] if question else None
        alert_key = normalized_alert_key(reason, prior_forecast_id=prior_forecast_id)
        conn.execute(
            """
            INSERT INTO alert_events (
                id, created_at, severity, scope_type, scope_ref, reason,
                recommended_action, alert_key, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_type, scope_ref, alert_key)
                WHERE acknowledged_at IS NULL
            DO UPDATE SET
                severity = CASE
                    WHEN excluded.severity = 'high' THEN 'high'
                    WHEN alert_events.severity = 'high' THEN 'high'
                    WHEN excluded.severity = 'warning' THEN 'warning'
                    WHEN alert_events.severity = 'warning' THEN 'warning'
                    ELSE excluded.severity
                END,
                seen_count = COALESCE(alert_events.seen_count, 1) + 1,
                last_seen_at = excluded.created_at,
                reason = excluded.reason,
                recommended_action = CASE
                    WHEN ? THEN excluded.recommended_action
                    ELSE alert_events.recommended_action
                END
            """,
            (
                target_id,
                stamp,
                severity,
                scope_type,
                scope_ref,
                reason,
                recommended_action,
                alert_key,
                stamp,
                1 if refresh_action else 0,
            ),
        )
        row = conn.execute(
            "SELECT id FROM alert_events WHERE scope_type = ? AND scope_ref = ? "
            "AND alert_key = ? AND acknowledged_at IS NULL",
            (scope_type, scope_ref, alert_key),
        ).fetchone()
        target_id = row["id"]
    # Re-read AFTER the write transaction commits so the returned object reflects the
    # persisted touch/insert (get_alert opens its own connection — it would not see an
    # uncommitted transaction's rows).
    alert = ledger.get_alert(target_id)
    if alert.severity in {"critical", "high"}:
        from forecasting.ledger.workflow import enqueue_alert_operational_task

        enqueue_alert_operational_task(
            ledger, alert, lane="urgent_forecast", now=stamp
        )
    return alert


def get_alert(ledger, alert_id: str) -> AlertEvent:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM alert_events WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"alert not found: {alert_id}")
    return ledger._row_to_alert(row)


def list_alerts(ledger, *, unresolved_only: bool = True) -> list[AlertEvent]:
    where = "WHERE acknowledged_at IS NULL" if unresolved_only else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM alert_events {where} ORDER BY created_at DESC, rowid ASC"
        ).fetchall()
    return [ledger._row_to_alert(row) for row in rows]


def acknowledge_alert(
    ledger,
    alert_id: str,
    *,
    acknowledged_at: str | None = None,
    ack_note: str | None = None,
    disposition: str | None = None,
) -> AlertEvent:
    """Acknowledge (close) an alert. ``ack_note`` records WHY for an AUTOMATIC close
    (reconciliation / collapse) — it makes the close auditable and visibly distinct
    from an operator ack (leaves ``ack_note`` NULL) and a human dismissal (which also
    stamps ``dismissed_at`` / ``dismiss_*``). An operator ack passes no note."""
    ledger.get_alert(alert_id)
    stamped = parse_timestamp(acknowledged_at, field_name="acknowledged_at") or utc_now_iso()
    if disposition is None:
        note = ack_note or ""
        if "collapsed:" in note:
            disposition = "duplicate"
        elif "resolution" in note:
            disposition = "resolved_by_resolution"
        elif "source_recovery" in note:
            disposition = "resolved_by_source_recovery"
        elif ack_note:
            disposition = "not_actionable"
        else:
            disposition = "operator_acknowledged"
    with ledger._connect() as conn:
        if ack_note is not None:
            conn.execute(
                "UPDATE alert_events SET acknowledged_at = COALESCE(acknowledged_at, ?), "
                "ack_note = COALESCE(ack_note, ?), disposition = COALESCE(disposition, ?) WHERE id = ?",
                (stamped, ack_note, disposition, alert_id),
            )
        else:
            conn.execute(
                "UPDATE alert_events SET acknowledged_at = COALESCE(acknowledged_at, ?), "
                "disposition = COALESCE(disposition, ?) WHERE id = ?",
                (stamped, disposition, alert_id),
            )
    return ledger.get_alert(alert_id)


def record_alert_attempt(ledger, alert_id: str, *, now: str | None = None) -> AlertEvent:
    """Record a FAILED paid-tier resolution attempt: stamp ``last_attempted_at``
    and increment ``attempt_count`` so the per-alert exponential backoff window
    opens.

    This is the *opposite* of an acknowledgement — it NEVER sets
    ``acknowledged_at``. The alert stays OPEN (the underlying condition still
    holds, so it must re-surface) but is now COOLED DOWN: the continuous paid
    (LLM) tier will not re-attempt it until the backoff window elapses, so an
    unattended loop cannot re-spend on the same gated/failing alert every cycle.
    Each repeated failure (after the window passes and it is retried) bumps
    ``attempt_count`` again, doubling the next window. Idempotency is NOT a goal
    here — every real spend that failed should advance the count.
    """
    ledger.get_alert(alert_id)  # raises LedgerNotFoundError on an unknown id
    stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE alert_events "
            "SET last_attempted_at = ?, attempt_count = COALESCE(attempt_count, 0) + 1 "
            "WHERE id = ?",
            (stamped, alert_id),
        )
    return ledger.get_alert(alert_id)


def dismiss_alerts(
    ledger,
    alert_ids: "Iterable[str]",
    *,
    note: str,
    actor: str,
    dismiss_reason: str | None = None,
    ttl_days: int | None = None,
    now: str | None = None,
) -> list[AlertEvent]:
    """Explicitly DISMISS (silence) a set of OPEN alerts — a RECORDED human
    silence, NOT a resolution.

    This is the bulk "ignore-this-group" path. It bulk-sets ``acknowledged_at``
    on every still-OPEN alert in ``alert_ids`` (so the group drops out of the
    open backlog) WITHOUT invoking any runner and WITHOUT doing any gated
    forecast work. Crucially it ALSO stamps the dismissal audit trail
    (``dismissed_at`` / ``dismiss_note`` / ``dismiss_actor`` / ``dismiss_reason``
    / ``dismiss_ttl_days``), which is what makes a dismissal auditable and
    visibly distinct from a runner-resolution (the latter leaves
    ``dismissed_at`` NULL). The silence is bounded: after ``ttl_days`` the group
    re-surfaces (``self_check`` respects an active dismissal and re-emits once
    the window elapses — see :meth:`active_dismissal_keys`).

    A non-empty ``note`` is REQUIRED: a mass-dismiss must always carry a human
    rationale (no silent bare-ack). Already-acknowledged alerts are skipped (a
    dismissal never overwrites a real resolution). Returns the alerts that were
    actually dismissed.
    """
    if not (note or "").strip():
        raise ValueError("dismiss_alerts requires a non-empty note (no silent mass-dismiss)")
    if not (actor or "").strip():
        raise ValueError("dismiss_alerts requires a non-empty actor")
    ttl = DISMISS_TTL_DAYS_DEFAULT if ttl_days is None else int(ttl_days)
    if ttl <= 0:
        raise ValueError("dismiss_alerts ttl_days must be a positive number of days")
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    note_text = note.strip()
    actor_text = actor.strip()
    reason_text = (dismiss_reason or "").strip() or None

    dismissed_ids: list[str] = []
    seen: set[str] = set()
    with ledger._connect() as conn:
        for alert_id in alert_ids:
            if not alert_id or alert_id in seen:
                continue
            seen.add(alert_id)
            row = conn.execute(
                "SELECT acknowledged_at FROM alert_events WHERE id = ?", (alert_id,)
            ).fetchone()
            if row is None:
                continue
            if row["acknowledged_at"] is not None:
                # Already resolved/dismissed — never clobber a real resolution.
                continue
            conn.execute(
                """
                UPDATE alert_events
                   SET acknowledged_at = ?,
                       dismissed_at = ?,
                       dismiss_note = ?,
                       dismiss_actor = ?,
                       dismiss_reason = ?,
                       dismiss_ttl_days = ?,
                       disposition = 'dismissed_by_policy'
                 WHERE id = ? AND acknowledged_at IS NULL
                """,
                (now_ts, now_ts, note_text, actor_text, reason_text, ttl, alert_id),
            )
            dismissed_ids.append(alert_id)
    # Re-read AFTER the write transaction has committed so the returned objects
    # reflect the persisted dismissal trail (get_alert opens its own connection,
    # which would not see the still-open transaction's uncommitted rows).
    return [ledger.get_alert(alert_id) for alert_id in dismissed_ids]


def active_dismissal_keys(ledger, *, now: str | None = None) -> "set[tuple[str, str]]":
    """The ``(scope_ref, reason)`` pairs currently inside an UNEXPIRED dismissal
    window — the silences ``self_check`` must respect so a dismissed group is
    not immediately re-emitted.

    A dismissal is active while ``dismissed_at + dismiss_ttl_days >= now``. Once
    the window elapses the pair drops out of this set, so the very next
    ``self_check`` re-creates the alert IF the underlying condition still holds —
    i.e. the group RE-SURFACES after the TTL rather than being silenced forever.
    """
    now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
    active: set[tuple[str, str]] = set()
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT scope_ref, reason, dismissed_at, dismiss_ttl_days "
            "FROM alert_events WHERE dismissed_at IS NOT NULL"
        ).fetchall()
    for row in rows:
        dismissed_dt = timestamp_to_datetime(row["dismissed_at"])
        if dismissed_dt is None:
            continue
        ttl = row["dismiss_ttl_days"]
        ttl_days = int(ttl) if ttl is not None else DISMISS_TTL_DAYS_DEFAULT
        if dismissed_dt + timedelta(days=ttl_days) >= now_dt:
            active.add((row["scope_ref"], row["reason"]))
    return active


def reconcile_alerts(ledger, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """AUTO-CLOSE every open question-scoped alert whose condition NO LONGER HOLDS,
    per-condition — so a satisfied alert is not immortal (the live "superseded alerts
    never die" pathology). Each closer keys off the *specific* condition, not a blanket
    evidence+update heuristic:

    * ``last_update_*`` / ``new_evidence:*`` close on a FRESH forecast snapshot;
    * ``evidence_stale_*`` / ``no_evidence`` close on FRESH / landed evidence;
    * ``no_forecast_snapshot`` closes once a snapshot exists;
    * ``close_time_within_*`` is SUPERSEDED by ``close_time_passed`` (the former closes
      when the close date has passed / its passed-alert is open);
    * ``resolution_check_due`` closes on a confirmed resolution OR an open proposal;
    * ``close_time_passed`` closes once the question is closed/resolved;
    * ``under_saturated`` clears on a score-based re-saturation;
    * generic watched-source / trigger material-change alerts close when BOTH fresh
      evidence was imported AND a forecast committed since.

    A close sets ``acknowledged_at`` WITH an ``ack_note`` (``auto_close:<condition>``),
    which makes it auditable and visibly distinct from an operator ack (no note) and a
    human dismissal (``dismissed_at`` set). ``dry_run`` previews without mutating.
    Idempotent, and if the underlying condition still holds the next self_check
    re-raises a fresh alert, so a genuinely-open signal is never lost.

    EXCEPTION — the MANUAL classes (NO_AUTO: domain-error profiles, assumption /
    reference-class checks, central-in-band, calibration-lesson review; and
    CONTESTED_LABEL: a disputed triage label) are EXCLUDED from auto-close: a new
    forecast + fresh evidence does NOT address an invalidated assumption or a disputed
    label, so they always stay OPEN (surfaced for a human)."""
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(now_ts)
    # Local import keeps reconcile_alerts free of any module import-order
    # coupling with the (model-only) warnings dispatcher.
    from forecasting.warnings import ResolutionKind, classify_warning

    reconciled: list[dict[str, Any]] = []
    still_open: list[dict[str, Any]] = []

    open_alerts = ledger.list_alerts(unresolved_only=True)
    # Cross-alert supersession sets, computed once: a question carrying an OPEN
    # ``close_time_passed`` alert supersedes its ``close_time_within_*`` alert, and a
    # question carrying an OPEN resolution PROPOSAL has had its ``resolution_check_due``
    # actioned into the confirm flow.
    close_passed_qs = {
        a.scope_ref for a in open_alerts
        if a.scope_type == "question" and a.reason == "close_time_passed"
    }
    proposal_qs = {
        a.scope_ref for a in open_alerts
        if a.scope_type == "question"
        and (a.reason or "").strip().lower().startswith(_RESOLUTION_PROPOSAL_REASON_PREFIX)
    }

    def _close(alert, note: str) -> None:
        # Closure = acknowledged_at WITH an auto note: auditable + visibly distinct
        # from an operator ack (no note) and a human dismissal (dismissed_at set).
        if not dry_run:
            ledger.acknowledge_alert(alert.id, acknowledged_at=now_ts, ack_note=f"auto_close:{note}")
        reconciled.append({"id": alert.id, "reason": alert.reason, "scope_ref": alert.scope_ref})

    def _keep(alert, because: str) -> None:
        still_open.append({"id": alert.id, "reason": alert.reason, "open_because": because})

    for alert in open_alerts:
        if alert.scope_type != "question":
            _keep(alert, "scope is not a single question")
            continue

        question_id = alert.scope_ref
        reason = alert.reason or ""

        def _snapshot():
            try:
                return ledger.get_current_snapshot(question_id)
            except Exception:
                return None

        def _snapshot_after() -> bool:
            snap = _snapshot()
            ts = (getattr(snap, "created_at", None) or getattr(snap, "as_of", None) or "") if snap else ""
            return bool(ts and ts > alert.created_at)

        def _evidence_after() -> bool:
            try:
                return any(
                    (getattr(item, "captured_at", None) or getattr(item, "available_at", None) or "") > alert.created_at
                    for item in ledger.list_evidence(question_id)
                )
            except Exception:
                return False

        def _question():
            try:
                return ledger.get_question(question_id)
            except Exception:
                return None

        def _confirmed_resolution() -> bool:
            try:
                return ledger.get_latest_resolution(question_id, confirmed_only=True) is not None
            except Exception:
                return False

        # --- CONDITION-SPECIFIC auto-close (Fix 3) ---
        # These run BEFORE the generic NO_AUTO skip because ``resolution_check_due``
        # and ``close_time_passed`` fall through classify_warning to NO_AUTO; without
        # an explicit carve-out they were immortal (the live "superseded alerts never
        # die" pathology). Each closes ONLY on the precise condition clearing.

        # close_time_within_* is SUPERSEDED once close_time_passed holds.
        if reason.startswith("close_time_within_"):
            q = _question()
            close_dt = timestamp_to_datetime(getattr(q, "close_time", None)) if q else None
            passed = question_id in close_passed_qs or (
                close_dt is not None and now_dt is not None and close_dt <= now_dt
            )
            if passed:
                _close(alert, "superseded_by_close_time_passed")
            else:
                _keep(alert, "close time has not yet passed")
            continue

        # resolution_check_due closes on a confirmed resolution OR an open proposal.
        if reason == "resolution_check_due":
            if _confirmed_resolution() or question_id in proposal_qs:
                _close(alert, "resolution_confirmed_or_proposed")
            else:
                _keep(alert, "no confirmed resolution or open proposal yet")
            continue

        # close_time_passed closes once the question is actually closed/resolved.
        if reason == "close_time_passed":
            q = _question()
            inactive = q is not None and getattr(q, "status", None) != "active"
            if inactive or _confirmed_resolution():
                _close(alert, "question_closed_or_resolved")
            else:
                _keep(alert, "question still active — needs close/resolution")
            continue

        # G5 · cadence_overdue closes on a FRESH snapshot (the forecast was refreshed
        # on cadence). Handled before the NO_AUTO skip so an unknown reason doesn't
        # leave it immortal.
        if reason == _CADENCE_ALERT_REASON:
            if _snapshot_after():
                _close(alert, "fresh_snapshot")
            else:
                _keep(alert, "no forecast update committed since the cadence alert")
            continue

        # A refresh-generated estimation request is done when a newer forecast lands
        # or the dedicated source estimator records a judgment (including an
        # immaterial result or a reviewable proposal).
        if reason.startswith("forecast_estimation_required:"):
            estimated = False
            try:
                with ledger._connect() as conn:
                    estimated = (
                        conn.execute(
                            """
                            SELECT 1 FROM model_runs
                            WHERE question_id = ?
                              AND model_type = 'source_change_estimation'
                              AND created_at > ?
                            LIMIT 1
                            """,
                            (question_id, alert.created_at),
                        ).fetchone()
                        is not None
                    )
            except Exception:
                estimated = False
            if _snapshot_after() or estimated:
                _close(alert, "estimation_completed")
            else:
                _keep(alert, "no estimator judgment or forecast update since the alert")
            continue

        # Genuine human-judgment classes (domain-error profiles, assumption /
        # reference-class checks, central-in-band, calibration-lesson review,
        # contested labels) are NEVER auto-reconciled — a new forecast + fresh
        # evidence does not address an invalidated assumption or a disputed label.
        if classify_warning(reason) in (ResolutionKind.NO_AUTO, ResolutionKind.CONTESTED_LABEL):
            _keep(alert, "manual class (no-auto / contested-label) — surfaced for human review, never auto-reconciled")
            continue

        # under_saturated is a SCORE-based signal: it clears when the current
        # snapshot's STORED saturation score is back at/above the bar, regardless of
        # whether new evidence was imported (a non-evidence re-saturation is a
        # legitimate fix; the score on an immutable snapshot only rises via a commit).
        if reason == _SATURATION_ALERT_REASON:
            _sat_score: float | None = None
            _sat_bar: float | None = None
            try:
                from forecasting.hooks import saturation_summary, sweep_alert_threshold

                _snap = _snapshot()
                _meta = getattr(_snap, "metadata", None) if _snap is not None else None
                _summary = saturation_summary(_meta.get("saturation") if isinstance(_meta, dict) else None)
                _raw = _summary.get("score") if _summary else None
                _sat_score = float(_raw) if isinstance(_raw, (int, float)) else None
                _sat_bar = float(sweep_alert_threshold())
            except Exception:
                _sat_score, _sat_bar = None, None
            if _sat_score is not None and _sat_bar is not None and _sat_score >= _sat_bar:
                _close(alert, "re_saturated")
            else:
                _keep(alert, "saturation still below the bar" if _sat_score is not None
                      else "no saturation score on the current snapshot")
            continue

        # last_update_* — a stale forecast; closes when a FRESH snapshot exists.
        if reason.startswith("last_update_"):
            if _snapshot_after():
                _close(alert, "fresh_snapshot")
            else:
                _keep(alert, "no forecast update committed since the alert")
            continue

        # evidence_stale_* — closes on FRESH evidence.
        if reason.startswith("evidence_stale_"):
            if _evidence_after():
                _close(alert, "fresh_evidence")
            else:
                _keep(alert, "no fresh evidence imported since the alert")
            continue

        # no_evidence — closes when evidence LANDS.
        if reason == "no_evidence":
            if _evidence_after():
                _close(alert, "evidence_landed")
            else:
                _keep(alert, "still no evidence imported")
            continue

        # no_forecast_snapshot — closes when a snapshot now EXISTS.
        if reason == "no_forecast_snapshot":
            if _snapshot() is not None:
                _close(alert, "snapshot_created")
            else:
                _keep(alert, "still no forecast snapshot")
            continue

        # new_evidence:* — the operator reviewed it into a fresh forecast update.
        if reason.startswith("new_evidence:"):
            if _snapshot_after():
                _close(alert, "reviewed_via_update")
            else:
                _keep(alert, "no forecast update committed since the alert")
            continue

        # Generic (watched-source / trigger material change): the loop closed only
        # when BOTH fresh evidence was imported AND a forecast committed since.
        ev = _evidence_after()
        up = _snapshot_after()
        if ev and up:
            _close(alert, "source_change_consumed")
        else:
            missing = []
            if not ev:
                missing.append("no fresh evidence imported since the alert")
            if not up:
                missing.append("no forecast update committed since the alert")
            _keep(alert, "; ".join(missing))

    return {
        "reconciled": reconciled,
        "reconciled_count": len(reconciled),
        "still_open": still_open,
        "dry_run": dry_run,
    }


def escalate_aged_alerts(ledger, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """AGE-ESCALATE open alerts (Fix 4): an alert that has stayed open past a
    threshold has its severity RAISED so a genuinely-neglected item sorts UP the desk
    (and the VOI ``alert_pressure`` input reflects real neglect) instead of drowning
    in the flood. Thresholds (:data:`ESCALATE_ELEVATED_DAYS` / :data:`ESCALATE_HIGH_DAYS`):
    at 7d the severity floor is ``warning`` (elevated), at 14d it is ``high``.

    Age is measured from ``created_at`` — the FIRST emission, preserved by the enqueue
    dedup — so the clock is genuine neglect, not the last re-fire. Escalation only ever
    RAISES severity (never a downgrade) and touches only OPEN alerts, so it is
    idempotent: a second pass over an already-escalated backlog is a no-op. ``dry_run``
    previews without mutating."""
    now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
    escalated: list[dict[str, Any]] = []
    for alert in ledger.list_alerts(unresolved_only=True):
        created_dt = timestamp_to_datetime(alert.created_at)
        if created_dt is None or now_dt is None:
            continue
        age_days = (now_dt - created_dt).total_seconds() / 86400.0
        if age_days >= ESCALATE_HIGH_DAYS:
            floor = "high"
        elif age_days >= ESCALATE_ELEVATED_DAYS:
            floor = "warning"
        else:
            continue
        target = _more_severe(alert.severity, floor)
        if target == (alert.severity or ""):
            continue  # already at/above the age floor — never a downgrade
        if not dry_run:
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE alert_events SET severity = ? WHERE id = ? AND acknowledged_at IS NULL",
                    (target, alert.id),
                )
            if target in {"critical", "high"}:
                from forecasting.ledger.workflow import enqueue_alert_operational_task

                enqueue_alert_operational_task(
                    ledger,
                    ledger.get_alert(alert.id),
                    lane="urgent_forecast",
                    now=now_dt.isoformat() if now_dt else None,
                )
        escalated.append({
            "id": alert.id,
            "reason": alert.reason,
            "scope_ref": alert.scope_ref,
            "from": alert.severity,
            "to": target,
            "age_days": round(age_days, 1),
        })
    task_escalation = {"escalated": [], "escalated_count": 0}
    if not dry_run:
        task_escalation = ledger.escalate_overdue_high_severity_tasks(
            now=now_dt.isoformat() if now_dt else None
        )
    return {
        "escalated": escalated,
        "escalated_count": len(escalated),
        "task_escalation": task_escalation,
        "dry_run": dry_run,
    }


def collapse_duplicate_alerts(ledger, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """ONE-TIME migration (Fix 1b): fold the EXISTING duplicate open-alert backlog
    that accumulated before enqueue dedup existed. For every ``(scope_type, scope_ref,
    reason)`` group with more than one OPEN row it KEEPS THE OLDEST row (smallest
    ``created_at`` — so age-escalation and downstream refs stay stable) and FOLDS the
    surplus into it: the kept row's ``seen_count`` becomes the group total and its
    ``severity`` becomes the most-severe in the group, while each surplus row is closed
    with ``acknowledged_at`` + ``ack_note = collapsed:<kept_id>`` (auditable, distinct
    from an operator ack / dismissal).

    ``dry_run`` reports what WOULD collapse without mutating. Idempotent: once run, no
    group has more than one open row, so a second pass folds nothing."""
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    open_alerts = ledger.list_alerts(unresolved_only=True)

    def collapse_key(alert: AlertEvent) -> str:
        if alert.reason.startswith(
            (
                "learned_error_update_required:",
                "forecast_estimation_required:",
                "autopilot_estimation_required:",
            )
        ):
            return normalized_alert_key(alert.reason)
        return alert.alert_key or normalized_alert_key(alert.reason)

    groups: dict[tuple[str, str, str], list[AlertEvent]] = {}
    for alert in open_alerts:
        groups.setdefault(
            (
                alert.scope_type,
                alert.scope_ref,
                collapse_key(alert),
            ),
            [],
        ).append(alert)

    groups_collapsed = 0
    rows_folded = 0
    folded_ids: list[str] = []
    for members in groups.values():
        if len(members) < 2:
            if not dry_run:
                only = members[0]
                with ledger._connect() as conn:
                    conn.execute(
                        "UPDATE alert_events SET alert_key = ? WHERE id = ?",
                        (collapse_key(only), only.id),
                    )
            continue
        groups_collapsed += 1
        ordered = sorted(members, key=lambda a: (a.created_at or "", a.id))
        kept = ordered[0]
        surplus = ordered[1:]
        rows_folded += len(surplus)
        total_seen = sum(int(getattr(m, "seen_count", 1) or 1) for m in members)
        max_severity = kept.severity
        for m in members:
            max_severity = _more_severe(max_severity, m.severity)
        latest_seen = max(
            [s for s in (m.last_seen_at or m.created_at for m in members) if s],
            default=kept.last_seen_at,
        )
        if dry_run:
            folded_ids.extend(m.id for m in surplus)
            continue
        with ledger._connect() as conn:
            for m in surplus:
                conn.execute(
                    "UPDATE alert_events SET acknowledged_at = ?, ack_note = ? "
                    "WHERE id = ? AND acknowledged_at IS NULL",
                    (now_ts, f"collapsed:{kept.id}", m.id),
                )
                folded_ids.append(m.id)
            conn.execute(
                """
                UPDATE alert_events
                SET seen_count = ?, severity = ?, last_seen_at = ?, alert_key = ?
                WHERE id = ?
                """,
                (
                    total_seen,
                    max_severity,
                    latest_seen,
                    collapse_key(kept),
                    kept.id,
                ),
            )
    return {
        "groups_collapsed": groups_collapsed,
        "rows_folded": rows_folded,
        "folded_ids": folded_ids,
        "dry_run": dry_run,
    }


def self_check(
    ledger,
    *,
    question_id: str | None = None,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    portfolio: str | None = None,
    stale_days: int = 7,
    stale: bool = True,
    now: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
    large_delta_threshold: float | None = None,
) -> list[AlertEvent]:
    ledger._validate_confidence_filters(
        confidence_below=confidence_below,
        confidence_above=confidence_above,
    )
    ledger._validate_probability_threshold(
        large_delta_threshold,
        field_name="large_delta_threshold",
    )
    if question_id:
        questions = [ledger.get_question(question_id)]
    else:
        questions = ledger.list_questions(domain=domain)
        if topic:
            questions = [q for q in questions if topic in q.topics]
        if horizon:
            questions = [
                q
                for q in questions
                if (snapshot := ledger.get_current_snapshot(q.id)) is not None
                and ledger._horizon_matches(snapshot.forecast_horizon_days, horizon)
            ]
        if portfolio:
            questions = [q for q in questions if ledger._question_in_portfolio(q, portfolio)]
    if confidence_below is not None or confidence_above is not None:
        questions = [
            q
            for q in questions
            if ledger._question_matches_confidence(
                q.id,
                confidence_below=confidence_below,
                confidence_above=confidence_above,
            )
        ]

    # Respect any UNEXPIRED dismissal (Slice 5): a group an operator explicitly
    # silenced must NOT be re-emitted while its TTL window is live. Once the
    # window elapses the (scope_ref, reason) pair drops out of this set and the
    # alert is re-created below — i.e. the group RE-SURFACES after the TTL.
    active_dismissals = ledger.active_dismissal_keys(now=now)

    alerts: list[AlertEvent] = []
    for row in ledger.review_questions(
        stale=stale,
        last_days=stale_days,
        domain=domain,
        topic=topic,
        horizon=horizon,
        confidence_below=confidence_below,
        confidence_above=confidence_above,
        large_delta_threshold=large_delta_threshold,
        now=now,
    ):
        question = row["question"]
        if question_id and question.id != question_id:
            continue
        if portfolio and not ledger._question_in_portfolio(question, portfolio):
            continue
        for reason in row["reasons"]:
            if (question.id, reason) in active_dismissals:
                continue  # silenced by an active dismissal — re-surfaces after TTL
            action = ledger._recommended_action(reason)
            alerts.append(
                ledger.create_alert(
                    severity="warning" if reason != "resolution_check_due" else "high",
                    scope_type="question",
                    scope_ref=question.id,
                    reason=reason,
                    recommended_action=action,
                )
            )
    # Dedupe guard (mirrors check_update_triggers' open_reasons set): re-running
    # self_check before reconcile must NOT accumulate duplicate postmortem_due
    # alerts for the same question. One open postmortem alert per question until
    # it is acknowledged. Both severity variants (postmortem_due /
    # high_impact_postmortem_due) count as "already surfaced" for this question.
    open_postmortem_questions = {
        alert.scope_ref
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.scope_type == "question"
        and alert.reason in ("postmortem_due", "high_impact_postmortem_due")
    }
    for question in questions:
        if question.status != "resolved":
            continue
        if ledger.get_latest_resolution(question.id, confirmed_only=True) is None:
            continue
        current = ledger.get_current_snapshot(question.id)
        scores = [score for score in ledger.list_scores() if score.question_id == question.id]
        if current is not None and not scores:
            if auto_score:
                try:
                    score = ledger.score_question(question.id)
                except ForecastingError as exc:
                    alerts.append(
                        ledger.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question.id,
                            reason="score_blocked",
                            recommended_action=f"Inspect resolution and scoring setup: {exc}",
                        )
                    )
                    continue
                alerts.append(
                    ledger.create_alert(
                        severity="info",
                        scope_type="question",
                        scope_ref=question.id,
                        reason=f"score_created:{score.id}",
                        recommended_action="Run `forecast postmortem` so the score can update calibration memory.",
                    )
                )
                scores = [score]
            else:
                high_impact = ledger._is_high_impact_question(question)
                alerts.append(
                    ledger.create_alert(
                        severity="high",
                        scope_type="question",
                        scope_ref=question.id,
                        reason="high_impact_score_due" if high_impact else "score_due",
                        recommended_action=(
                            "Prioritize scoring this high-impact confirmed resolution before updating calibration memory."
                            if high_impact
                            else "Run `forecast score` for the confirmed resolution."
                        ),
                    )
                )
                continue
        if scores and not ledger.list_postmortems(question.id):
            if auto_postmortem:
                # Derive the auto-postmortem from the CURRENT snapshot's score —
                # the desk's own resolved forecast — not an arbitrary scores[0].
                # list_scores orders by scored_at DESC ONLY, so scores[0] can be a
                # non-eligible imported_baseline score (backtests write a 0.5
                # baseline score AFTER the desk score) whenever the wall clock
                # ticks a second between the two inserts on a slow CI worker.
                # create_postmortem re-scores the current snapshot, so selecting
                # that same score here keeps the lesson text consistent with the
                # postmortem's calibration_eligible gate (else a real eligible miss
                # silently synthesizes no calibration lesson).
                latest_score = next(
                    (
                        score
                        for score in scores
                        if current is not None and score.forecast_id == current.forecast_id
                    ),
                    scores[0],
                )
                postmortem = ledger.create_postmortem(
                    question_id=question.id,
                    summary="Auto-created by forecast self-check after confirmed resolution and scoring.",
                    what_happened="The forecast resolved and was scored during a scheduled or manual self-check.",
                    what_was_expected="See the linked forecast snapshot and score record for the prior probability.",
                    lesson=ledger._auto_postmortem_lesson(question, latest_score),
                    calibration_adjustment=ledger._auto_postmortem_adjustment(question, latest_score),
                )
                alerts.append(
                    ledger.create_alert(
                        severity="info",
                        scope_type="question",
                        scope_ref=question.id,
                        reason=f"postmortem_created:{postmortem['id']}",
                        recommended_action=(
                            "Review the auto-created postmortem and any tentative calibration lesson "
                            "before relying on it for future updates."
                        ),
                    )
                )
                continue
            if question.id in open_postmortem_questions:
                continue  # one open postmortem_due alert per question until acked
            high_impact = ledger._is_high_impact_question(question)
            alerts.append(
                ledger.create_alert(
                    severity="high" if high_impact else "warning",
                    scope_type="question",
                    scope_ref=question.id,
                    reason="high_impact_postmortem_due" if high_impact else "postmortem_due",
                    recommended_action=(
                        "Prioritize a postmortem for this high-impact resolution before reusing the lesson."
                        if high_impact
                        else "Run `forecast postmortem` so the resolved forecast can update learning artifacts."
                    ),
                )
            )
            open_postmortem_questions.add(question.id)
    alerts.extend(ledger._domain_error_profile_alerts(domain=domain, topic=topic, questions=questions))
    alerts.extend(
        ledger._calibration_lesson_review_alerts(
            domain=domain,
            topic=topic,
            questions=questions,
        )
    )
    if not any([question_id, domain, topic, horizon, portfolio]):
        alerts.extend(ledger._benchmark_evidence_alerts())
    watch_scope_type, watch_scope_ref = ledger._self_check_watch_scope(
        question_id=question_id,
        domain=domain,
        topic=topic,
        portfolio=portfolio,
    )
    alerts.extend(
        ledger.check_watched_sources(
            scope_type=watch_scope_type,
            scope_ref=watch_scope_ref,
            now=now,
        )
    )
    # Fire executable update_triggers for in-scope questions against their
    # latest imported values (idempotent — one open alert per source).
    for question in questions:
        if any(trigger.get("operator") for trigger in question.update_triggers):
            alerts.extend(ledger.check_update_triggers(question_id=question.id, now=now))
    return alerts


def _recommended_action(ledger, reason: str) -> str:
    if reason.startswith("assumption_invalidated:"):
        return "Update the forecast or replace the invalidated assumption."
    if reason.startswith("assumption_stale:") or reason.startswith("assumption_check_due:"):
        return "Re-check the assumption and record fresh evidence or mark it resolved/invalidated."
    if reason.startswith("reference_class_invalidated:"):
        return "Replace the reference class or rerun the base-rate estimate before updating probability."
    if reason.startswith("reference_class_stale:") or reason.startswith("reference_class_check_due:"):
        return "Refresh the reference class and base-rate evidence."
    if reason == "no_evidence":
        return "Run `forecast research` or add evidence before trusting the current probability."
    if reason.startswith("new_evidence:"):
        return "Review the new evidence and append a forecast update if it changes the probability."
    if reason.startswith("evidence_stale_"):
        return "Refresh evidence and decide whether a new forecast snapshot is warranted."
    if reason.startswith("large_forecast_delta:"):
        return "Review the large probability move; record what changed and whether assumptions or calibration lessons need updates."
    if reason.startswith("close_time_within_"):
        return "Review evidence and prepare for close/resolution before the question closes."
    return {
        "no_forecast_snapshot": "Run `forecast update` to create an explicit probability.",
        "review_due": "Run a research pass or update the forecast rationale.",
        "close_time_passed": "Check whether the question should be closed or resolved.",
        "resolution_check_due": "Confirm resolution criteria and score if resolved.",
    }.get(reason, "Review the forecast and decide whether a new snapshot is warranted.")


def _question_in_portfolio(ledger, question: ForecastQuestion, portfolio: str) -> bool:
    portfolio = portfolio.strip()
    if not portfolio:
        return True
    expected_tags = {portfolio, f"portfolio:{portfolio}", f"portfolio={portfolio}"}
    if any(tag in expected_tags for tag in question.tags):
        return True
    metadata_portfolio = question.metadata.get("portfolio")
    if isinstance(metadata_portfolio, str) and metadata_portfolio == portfolio:
        return True
    metadata_portfolios = question.metadata.get("portfolios")
    if isinstance(metadata_portfolios, list) and portfolio in metadata_portfolios:
        return True
    return False


def _question_matches_confidence(
    ledger,
    question_id: str,
    *,
    confidence_below: float | None,
    confidence_above: float | None,
) -> bool:
    if confidence_below is None and confidence_above is None:
        return True
    snapshot = ledger.get_current_snapshot(question_id)
    if snapshot is None or snapshot.confidence is None:
        return False
    if confidence_below is not None and snapshot.confidence >= confidence_below:
        return False
    if confidence_above is not None and snapshot.confidence <= confidence_above:
        return False
    return True


def _is_high_impact_question(question: ForecastQuestion) -> bool:
    return (question.impact or "").strip().lower() in {"high", "critical", "material"}


def _domain_error_profile_alerts(
    ledger,
    *,
    domain: str | None,
    topic: str | None,
    questions: list[ForecastQuestion],
) -> list[AlertEvent]:
    profile_filters: set[tuple[str | None, str | None]] = set()
    if domain or topic:
        profile_filters.add((domain, topic))
    for question in questions:
        if question.domain:
            profile_filters.add((question.domain, None))
            for question_topic in question.topics:
                profile_filters.add((question.domain, question_topic))
    alerts: list[AlertEvent] = []
    seen_profiles: set[str] = set()
    for profile_domain, profile_topic in profile_filters:
        for profile in ledger.list_domain_error_profiles(domain=profile_domain, topic=profile_topic):
            if profile["id"] in seen_profiles:
                continue
            if not profile["recurring_errors"] and not profile["recommended_adjustments"]:
                continue
            seen_profiles.add(profile["id"])
            matching_questions = ledger._active_questions_for_error_profile(profile, questions)
            matching_ids = [question.id for question in matching_questions[:5]]
            matching_summary = (
                f" Active matching forecasts: {', '.join(matching_ids)}."
                if matching_ids
                else ""
            )
            alerts.append(
                ledger.create_alert(
                    severity="info",
                    scope_type="domain_error_profile",
                    scope_ref=profile["id"],
                    reason="domain_error_profile_review",
                    recommended_action=(
                        "Review active forecasts in this scope against recurring errors: "
                        + ", ".join(profile["recurring_errors"] or profile["recommended_adjustments"])
                        + "."
                        + matching_summary
                    ),
                    # ONE alert per profile (scope_ref == profile id): the enqueue dedup
                    # touches an already-open review instead of re-emitting a new row
                    # every self_check (the live 1,899-rows-for-15-profiles flood).
                    # refresh_action keeps the digest — the changing set of matching
                    # forecasts in the action text — current on each touch. The
                    # question-scoped ``domain_error_profile_applies:*`` alerts below are
                    # the actionable, per-forecast items; this profile row is the
                    # per-profile reminder, deduped and refreshed, never stacked.
                    refresh_action=True,
                )
            )
            for question in matching_questions:
                alerts.append(
                    ledger.create_alert(
                        severity="warning",
                        scope_type="question",
                        scope_ref=question.id,
                        reason=f"domain_error_profile_applies:{profile['id']}",
                        recommended_action=ledger._error_profile_question_action(profile, question),
                    )
                )
    return alerts


def _active_questions_for_error_profile(
    ledger,
    profile: dict[str, Any],
    questions: list[ForecastQuestion],
) -> list[ForecastQuestion]:
    profile_domain = profile.get("domain")
    profile_topic = profile.get("topic")
    profile_question_type = profile.get("question_type")
    result: list[ForecastQuestion] = []
    seen: set[str] = set()
    for question in questions:
        if question.id in seen or question.status != "active":
            continue
        if profile_domain and question.domain != profile_domain:
            continue
        if profile_topic and profile_topic not in question.topics:
            continue
        if profile_question_type and question.outcome_space.type != profile_question_type:
            continue
        result.append(question)
        seen.add(question.id)
    return result


def _error_profile_question_action(
    ledger,
    profile: dict[str, Any],
    question: ForecastQuestion,
) -> str:
    recurring = list(profile.get("recurring_errors") or profile.get("recommended_adjustments") or [])
    patterns = ", ".join(str(item) for item in recurring[:4]) or "recent misses"
    return (
        "Review this active forecast against learned error patterns "
        f"({patterns}). Inspect `forecast show {question.id}`, refresh evidence, "
        "and save any probability change explicitly with `forecast update`."
    )


def _calibration_lesson_review_alerts(
    ledger,
    *,
    domain: str | None,
    topic: str | None,
    questions: list[ForecastQuestion],
) -> list[AlertEvent]:
    candidates: dict[str, dict[str, Any]] = {}

    def add_lesson(lesson: dict[str, Any]) -> None:
        if lesson.get("status") != "tentative":
            return
        if lesson.get("invalidated_by_correction_id"):
            return
        candidates[lesson["id"]] = lesson

    if domain:
        for lesson in ledger.list_calibration_lessons(scope_type="domain", scope_ref=domain):
            add_lesson(lesson)
    if topic:
        for lesson in ledger.list_calibration_lessons(scope_type="topic", scope_ref=topic):
            add_lesson(lesson)

    all_scores = ledger.list_scores()
    for question in questions:
        if question.domain:
            for lesson in ledger.list_calibration_lessons(scope_type="domain", scope_ref=question.domain):
                add_lesson(lesson)
        for question_topic in question.topics:
            for lesson in ledger.list_calibration_lessons(scope_type="topic", scope_ref=question_topic):
                add_lesson(lesson)
        question_scores = [score for score in all_scores if score.question_id == question.id]
        postmortems = ledger.list_postmortems(question.id)
        for lesson in ledger._calibration_lessons_for_question(question_scores, postmortems):
            add_lesson(lesson)

    if not any([domain, topic, questions]):
        for lesson in ledger.list_calibration_lessons(scope_type="global", scope_ref=None):
            add_lesson(lesson)

    alerts: list[AlertEvent] = []
    for lesson in sorted(candidates.values(), key=lambda item: item["updated_at"], reverse=True):
        alerts.append(
            ledger.create_alert(
                severity="info",
                scope_type="calibration_lesson",
                scope_ref=lesson["id"],
                reason="calibration_lesson_review",
                recommended_action=(
                    f"Review tentative lesson {lesson['id']} with `forecast lesson status {lesson['id']} "
                    "--status active` or reject/supersede it before relying on it for future updates."
                ),
            )
        )
    return alerts


def _benchmark_evidence_alerts(ledger) -> list[AlertEvent]:
    from forecasting.backtesting import (
        build_backtest_performance_summaries,
        build_forecasting_evidence_status,
    )

    rows = ledger.list_backtest_runs()[:20]
    status = build_forecasting_evidence_status(
        ledger,
        build_backtest_performance_summaries(ledger, rows),
    )
    gaps = list(status.get("gaps") or [])
    if not gaps:
        return []
    command_hints = [
        commands[0]
        for action in list(status.get("next_actions") or [])[:3]
        if (commands := list(action.get("commands") or []))
    ]
    command_hint = (
        f" Suggested commands: {'; '.join(command_hints)}."
        if command_hints
        else ""
    )
    return [
        ledger.create_alert(
            severity="warning",
            scope_type="global",
            scope_ref="benchmark_evidence",
            reason="benchmark_evidence_gaps",
            recommended_action=(
                "Run `forecast performance --json` and close evidence gaps: "
                f"{', '.join(gaps[:5])}. Collect live scored forecasts and "
                "agent-protocol held-out runs, and include external resolved-question "
                "corpora from at least two source families before claiming live "
                f"superiority.{command_hint}"
            ),
        )
    ]


def _row_to_alert(ledger, row: sqlite3.Row) -> AlertEvent:
    keys = set(row.keys())
    ttl = row["dismiss_ttl_days"] if "dismiss_ttl_days" in keys else None
    attempts = row["attempt_count"] if "attempt_count" in keys else 0
    seen = row["seen_count"] if "seen_count" in keys else 1
    return AlertEvent(
        id=row["id"],
        created_at=row["created_at"],
        severity=row["severity"],
        scope_type=row["scope_type"],
        scope_ref=row["scope_ref"],
        reason=row["reason"],
        recommended_action=row["recommended_action"],
        acknowledged_at=row["acknowledged_at"],
        dismissed_at=row["dismissed_at"] if "dismissed_at" in keys else None,
        dismiss_note=row["dismiss_note"] if "dismiss_note" in keys else None,
        dismiss_actor=row["dismiss_actor"] if "dismiss_actor" in keys else None,
        dismiss_reason=row["dismiss_reason"] if "dismiss_reason" in keys else None,
        dismiss_ttl_days=int(ttl) if ttl is not None else None,
        last_attempted_at=row["last_attempted_at"] if "last_attempted_at" in keys else None,
        attempt_count=int(attempts) if attempts is not None else 0,
        seen_count=int(seen) if seen is not None else 1,
        last_seen_at=row["last_seen_at"] if "last_seen_at" in keys else None,
        ack_note=row["ack_note"] if "ack_note" in keys else None,
        alert_key=row["alert_key"] if "alert_key" in keys else normalized_alert_key(row["reason"]),
        disposition=row["disposition"] if "disposition" in keys else None,
    )
