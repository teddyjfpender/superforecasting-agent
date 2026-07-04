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

# Default re-surface window for a dismissed group (the design's TTL). A dismissal
# silences a group for this many days; once the window elapses the group
# re-surfaces (``self_check`` re-emits the alert IF the condition still holds). A
# dismissal is NEVER an indefinite silence.
DISMISS_TTL_DAYS_DEFAULT = 7


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
) -> AlertEvent:
    alert_id = f"al_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO alert_events (
                id, created_at, severity, scope_type, scope_ref, reason,
                recommended_action
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                utc_now_iso(),
                severity,
                scope_type,
                scope_ref,
                reason,
                recommended_action,
            ),
        )
    return ledger.get_alert(alert_id)


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
            f"SELECT * FROM alert_events {where} ORDER BY created_at DESC"
        ).fetchall()
    return [ledger._row_to_alert(row) for row in rows]


def acknowledge_alert(ledger, alert_id: str, *, acknowledged_at: str | None = None) -> AlertEvent:
    ledger.get_alert(alert_id)
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE alert_events SET acknowledged_at = ? WHERE id = ?",
            (parse_timestamp(acknowledged_at, field_name="acknowledged_at") or utc_now_iso(), alert_id),
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
                       dismiss_ttl_days = ?
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
    """Close the loop: source-changed -> evidence-imported -> forecast-updated
    -> acknowledged. A question-scoped alert that fired BEFORE both fresh
    evidence was imported AND a new forecast snapshot was committed has already
    been consumed by the operator/agent — leaving it open is just alert fatigue,
    so acknowledge it. Alerts still missing evidence or an update stay open with
    an explicit reason. dry_run reports what WOULD be acknowledged without
    mutating (so a cautious caller can preview). Idempotent.

    Acking liberally (any fresh evidence + any forecast update after the alert,
    not necessarily from the alert's exact source) is intentional + safe for
    source-driven alerts: it clears the backlog the operator already worked
    past, and if the underlying source is still dirty the next self_check
    re-raises a fresh alert — so a genuinely-open signal is never lost.

    EXCEPTION — the MANUAL classes (NO_AUTO: domain-error profiles, assumption /
    reference-class checks, central-in-band, calibration-lesson review; and
    CONTESTED_LABEL: a triage auto-label the verifier disputes) are explicitly
    EXCLUDED from auto-ack. These are human-judgment alerts the warning
    dispatcher deliberately *surfaces* and never auto-resolves, and a new
    forecast + fresh evidence does NOT address them (an invalidated assumption
    is still invalidated; a band is still off-centre; a contested label is
    closed only when the operator records a real expert label via
    relabel_route). Reconciling one on unrelated forecast activity would
    silently close a still-valid signal the operator must act on — the same
    bare-ack the dispatcher forbids — so they always stay OPEN here."""
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    # Local import keeps reconcile_alerts free of any module import-order
    # coupling with the (model-only) warnings dispatcher.
    from forecasting.warnings import ResolutionKind, classify_warning

    reconciled: list[dict[str, Any]] = []
    still_open: list[dict[str, Any]] = []

    for alert in ledger.list_alerts(unresolved_only=True):
        if alert.scope_type != "question":
            still_open.append(
                {"id": alert.id, "reason": alert.reason, "open_because": "scope is not a single question"}
            )
            continue

        if classify_warning(alert.reason) in (
            ResolutionKind.NO_AUTO,
            ResolutionKind.CONTESTED_LABEL,
        ):
            still_open.append(
                {
                    "id": alert.id,
                    "reason": alert.reason,
                    "open_because": "manual class (no-auto / contested-label) — surfaced for human review, never auto-reconciled",
                }
            )
            continue

        question_id = alert.scope_ref

        # under_saturated is a SCORE-based signal, not an evidence-based one: it
        # clears when the current snapshot's STORED saturation score is back
        # at/above the bar, regardless of whether new evidence was imported. A
        # non-evidence re-saturation (added reasoning tags, a re-run panel, a
        # fuller decomposition) is a legitimate fix; the score on an immutable
        # snapshot only rises via a fresh commit, so a current score >= bar
        # already implies a re-forecast landed. Evidence-gated reconcile would
        # leave an evidence-free re-saturation stuck open forever (alert fatigue,
        # since the deduped sweep won't re-raise it).
        if alert.reason == _SATURATION_ALERT_REASON:
            _sat_score: float | None = None
            _sat_bar: float | None = None
            try:
                from forecasting.hooks import saturation_summary, sweep_alert_threshold

                _snap = ledger.get_current_snapshot(question_id)
                _meta = getattr(_snap, "metadata", None) if _snap is not None else None
                _summary = saturation_summary(_meta.get("saturation") if isinstance(_meta, dict) else None)
                _raw = _summary.get("score") if _summary else None
                _sat_score = float(_raw) if isinstance(_raw, (int, float)) else None
                _sat_bar = float(sweep_alert_threshold())
            except Exception:
                _sat_score, _sat_bar = None, None
            if _sat_score is not None and _sat_bar is not None and _sat_score >= _sat_bar:
                if not dry_run:
                    ledger.acknowledge_alert(alert.id, acknowledged_at=now_ts)
                reconciled.append({"id": alert.id, "reason": alert.reason, "scope_ref": question_id})
            else:
                still_open.append({
                    "id": alert.id,
                    "reason": alert.reason,
                    "open_because": (
                        "saturation still below the bar"
                        if _sat_score is not None
                        else "no saturation score on the current snapshot"
                    ),
                })
            continue

        try:
            evidence_after = any(
                (getattr(item, "captured_at", None) or getattr(item, "available_at", None) or "") > alert.created_at
                for item in ledger.list_evidence(question_id)
            )
        except Exception:
            evidence_after = False

        snapshot = None
        try:
            snapshot = ledger.get_current_snapshot(question_id)
        except Exception:
            snapshot = None
        snapshot_ts = (getattr(snapshot, "created_at", None) or getattr(snapshot, "as_of", None) or "") if snapshot else ""
        update_after = bool(snapshot_ts and snapshot_ts > alert.created_at)

        if evidence_after and update_after:
            if not dry_run:
                ledger.acknowledge_alert(alert.id, acknowledged_at=now_ts)
            reconciled.append({"id": alert.id, "reason": alert.reason, "scope_ref": question_id})
        else:
            missing = []
            if not evidence_after:
                missing.append("no fresh evidence imported since the alert")
            if not update_after:
                missing.append("no forecast update committed since the alert")
            still_open.append({"id": alert.id, "reason": alert.reason, "open_because": "; ".join(missing)})

    return {
        "reconciled": reconciled,
        "reconciled_count": len(reconciled),
        "still_open": still_open,
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
        stale=True,
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
                latest_score = scores[0]
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
    )
