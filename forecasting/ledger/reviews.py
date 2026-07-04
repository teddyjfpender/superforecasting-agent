"""Scheduled-review domain (D6 carve — cadence, schedules, and the review sweep).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade: the review QUEUE builder (``review_questions``), the
scheduled-review CRUD + lifecycle (``schedule_review`` / ``get_scheduled_review``
/ ``list_scheduled_reviews`` / ``next_review_by_question`` /
``count_due_scheduled_reviews`` / ``next_scheduled_review_at`` /
``mark_question_review_due`` / ``dedupe_scheduled_reviews`` /
``list_scheduled_review_runs``), the DETERMINISTIC review SWEEP
(``run_due_scheduled_reviews`` + its ``_refresh_due_question`` self-refresh and
``_record_scheduled_review_run`` recorder), the cadence-resolution helpers
(``_advance_cadence`` / ``_clamp_cadence_to_deadline`` / ``_cadence_due`` /
``_cadence_delta``), the auto-review-eligibility gate (``_is_auto_review_eligible``),
the priority ranker (``_review_priority``), and the review-run serializer
(``_row_to_scheduled_review_run``). Each function takes the ``ForecastLedger``
instance first; ``core`` keeps a one-line delegate per method so no caller changed.

Dependency direction (no cycle, per the D1 finding): this leaf owns its own
review constants and imports only ``forecasting.models`` + stdlib + the ``gate``
leaf at load time. ``_refresh_due_question`` reaches ``allow_ledger_writes``
straight from :mod:`forecasting.ledger.gate`. Everything else the moved bodies
need is reached through the ``ledger`` INSTANCE at call time — the big
``self_check`` alert engine, ``refresh_forecast``, ``get_question`` /
``get_current_snapshot`` / ``list_watched_sources`` / ``list_assumptions`` /
``list_reference_classes``, the shared validators (``_validate_confidence_filters``
/ ``_validate_probability_threshold`` / ``_horizon_matches`` /
``_latest_forecast_delta``), and ``_is_learning_alert_reason`` (an alert-reason
classifier deliberately LEFT in core for the D7 alerts slice even though its only
caller is here). So the leaf has no load-time dependency on ``core``.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from forecasting.ledger.gate import allow_ledger_writes
from forecasting.models import (
    AlertEvent,
    LedgerNotFoundError,
    ValidationError,
    json_dumps,
    json_loads,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)

# ---------------------------------------------------------------------------
# Leaf-owned review constants (D1 "constants to the leaf" — ``core`` imports NONE
# of these back; they are referenced only by the moved review methods).

# Auto-review eligibility — default-weekly-review gate for create_question.
#
# A LIVE organic forecast question created without an explicit review cadence
# should DEFAULT to a weekly scheduled review so it is auto-re-forecast and shows
# a "NEXT" column on the desk. But two classes of question are forecast-once-then-
# scored and must STAY cadence-less:
#   - market_nightly: foreknowledge-proof live benchmark snapshots — re-forecasting
#     them later would break the foreknowledge lock (the agent must not revisit a
#     question after the market it was pinned against has moved).
#   - forecastbench: historical replay / closed-book backtest cases — re-forecasting
#     them with today's information would contaminate the replay.
# Membership is checked against the lowercased domain OR any lowercased tag.
_AUTO_REVIEW_INELIGIBLE_DOMAINS = frozenset({"forecastbench", "market_nightly"})
_AUTO_REVIEW_INELIGIBLE_TAGS = frozenset({"bench", "forecastbench", "market_nightly"})

# Valid ``scope_type`` values for schedule_review. Re-exported on the package
# surface via ``__init__`` (``forecasting.ledger.SCHEDULE_SCOPE_TYPES``) for
# byte-for-byte parity with the pre-carve single module.
SCHEDULE_SCOPE_TYPES = {"question", "domain", "topic", "domain_topic", "portfolio", "horizon"}


def _is_auto_review_eligible(
    ledger,
    domain: str | None,
    tags: list[str] | None,
) -> bool:
    """Whether a newly-created question should DEFAULT to a weekly review.

    INELIGIBLE (returns False — must stay cadence-less) when the question is a
    forecast-once-then-scored benchmark/foreknowledge-proof case, identified by
    a benchmark domain OR a benchmark tag (case-insensitive). See
    ``_AUTO_REVIEW_INELIGIBLE_DOMAINS`` / ``_AUTO_REVIEW_INELIGIBLE_TAGS``.
    Everything else is eligible.
    """
    if (domain or "").strip().lower() in _AUTO_REVIEW_INELIGIBLE_DOMAINS:
        return False
    for tag in tags or []:
        if str(tag).strip().lower() in _AUTO_REVIEW_INELIGIBLE_TAGS:
            return False
    return True


def review_questions(
    ledger,
    *,
    stale: bool = False,
    last_days: int | None = None,
    domain: str | None = None,
    topic: str | None = None,
    horizon: str | None = None,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
    large_delta_threshold: float | None = None,
    now: str | None = None,
) -> list[dict[str, Any]]:
    ledger._validate_confidence_filters(
        confidence_below=confidence_below,
        confidence_above=confidence_above,
    )
    ledger._validate_probability_threshold(
        large_delta_threshold,
        field_name="large_delta_threshold",
    )
    questions = ledger.list_questions(status="active", domain=domain)
    if topic:
        questions = [question for question in questions if topic in question.topics]
    now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
    assert now_dt is not None
    rows: list[dict[str, Any]] = []
    for question in questions:
        snapshot = ledger.get_current_snapshot(question.id)
        if horizon and (
            snapshot is None
            or not ledger._horizon_matches(snapshot.forecast_horizon_days, horizon)
        ):
            continue
        if confidence_below is not None or confidence_above is not None:
            if snapshot is None or snapshot.confidence is None:
                continue
            if confidence_below is not None and snapshot.confidence >= confidence_below:
                continue
            if confidence_above is not None and snapshot.confidence <= confidence_above:
                continue
        reasons: list[str] = []
        evidence_items = ledger.list_evidence(question.id)
        if snapshot is None:
            reasons.append("no_forecast_snapshot")
        else:
            snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
            for item in evidence_items:
                available_dt = timestamp_to_datetime(item.available_at)
                if snapshot_as_of and available_dt and available_dt > snapshot_as_of:
                    reasons.append(f"new_evidence:{item.id}")
        if question.next_review_at:
            next_review = timestamp_to_datetime(question.next_review_at)
            if next_review and next_review <= now_dt:
                reasons.append("review_due")
        if question.close_time:
            close_time = timestamp_to_datetime(question.close_time)
            if close_time and close_time <= now_dt:
                reasons.append("close_time_passed")
            elif stale and last_days is not None and close_time and close_time <= now_dt + timedelta(days=last_days):
                reasons.append(f"close_time_within_{last_days}d")
        if question.resolution_time:
            resolution_time = timestamp_to_datetime(question.resolution_time)
            if resolution_time and resolution_time <= now_dt:
                reasons.append("resolution_check_due")
        if stale and snapshot is not None and last_days is not None:
            as_of = timestamp_to_datetime(snapshot.as_of)
            if as_of and (now_dt - as_of).days >= last_days:
                reasons.append(f"last_update_{last_days}d_plus")
            if not evidence_items:
                reasons.append("no_evidence")
            else:
                latest_available = max(
                    (
                        timestamp_to_datetime(item.available_at)
                        for item in evidence_items
                        if timestamp_to_datetime(item.available_at) is not None
                    ),
                    default=None,
                )
                if latest_available and (now_dt - latest_available).days >= last_days:
                    reasons.append(f"evidence_stale_{last_days}d_plus")
        for assumption in ledger.list_assumptions(question.id):
            if assumption["status"] == "invalidated":
                reasons.append(f"assumption_invalidated:{assumption['id']}")
            elif assumption["status"] == "stale":
                reasons.append(f"assumption_stale:{assumption['id']}")
            elif ledger._cadence_due(
                assumption.get("last_checked_at") or assumption.get("created_at"),
                assumption.get("check_cadence"),
                now_dt,
            ):
                reasons.append(f"assumption_check_due:{assumption['id']}")
        for reference_class in ledger.list_reference_classes(question.id):
            if reference_class["status"] == "invalidated":
                reasons.append(f"reference_class_invalidated:{reference_class['id']}")
            elif reference_class["status"] in {"stale", "superseded"}:
                reasons.append(f"reference_class_stale:{reference_class['id']}")
            elif ledger._cadence_due(
                reference_class.get("last_checked_at") or reference_class.get("created_at"),
                reference_class.get("check_cadence"),
                now_dt,
            ):
                reasons.append(f"reference_class_check_due:{reference_class['id']}")
        if large_delta_threshold is not None:
            delta = ledger._latest_forecast_delta(question.id)
            if delta is not None and abs(delta) >= large_delta_threshold:
                reasons.append(f"large_forecast_delta:{delta:+.3f}")
        if reasons or not stale:
            rows.append(
                {
                    "question": question,
                    "current_snapshot": snapshot,
                    "reasons": reasons,
                    "priority": ledger._review_priority(reasons),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["priority"],
            row["question"].close_time or row["question"].resolution_time or "9999-12-31T00:00:00Z",
            row["question"].title.lower(),
        ),
    )


def schedule_review(
    ledger,
    *,
    scope_type: str,
    scope_ref: str | None,
    cadence: str,
    next_run_at: str | None = None,
    trigger_reason: str = "scheduled",
    enabled: bool = True,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    stale_days: int = 7,
    confidence_below: float | None = None,
    confidence_above: float | None = None,
    large_delta_threshold: float | None = None,
) -> dict[str, Any]:
    if scope_type not in SCHEDULE_SCOPE_TYPES:
        raise ValidationError(
            "scope_type must be question, domain, topic, domain_topic, portfolio, or horizon"
        )
    if scope_type == "horizon":
        if not scope_ref:
            raise ValidationError("horizon scheduled reviews require scope_ref")
        ledger._horizon_matches(0.0, scope_ref)
    if not cadence.strip():
        raise ValidationError("cadence is required")
    if stale_days < 0:
        raise ValidationError("stale_days must be non-negative")
    ledger._validate_confidence_filters(
        confidence_below=confidence_below,
        confidence_above=confidence_above,
    )
    ledger._validate_probability_threshold(
        large_delta_threshold,
        field_name="large_delta_threshold",
    )
    review_id = f"sr_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        # Idempotent by (scope_type, scope_ref, cadence, trigger_reason): a
        # schedule for the same scope + cadence + reason already covers this, so
        # re-scheduling re-activates the existing row instead of spawning a
        # duplicate. Without this, a lazy prompter (or the agent re-running an
        # onboarding step) silently accumulates duplicate weekly reviews that
        # each fire independently. scope_ref may be NULL, so match it explicitly.
        existing = conn.execute(
            """
            SELECT id FROM scheduled_reviews
            WHERE scope_type = ? AND cadence = ? AND trigger_reason = ?
              AND ((scope_ref IS NULL AND ? IS NULL) OR scope_ref = ?)
            ORDER BY enabled DESC, next_run_at ASC
            LIMIT 1
            """,
            (scope_type, cadence, trigger_reason, scope_ref, scope_ref),
        ).fetchone()
        if existing is not None:
            # Idempotent UPSERT: a re-schedule for the same scope+cadence+reason
            # must APPLY its new settings (stale_days, auto_*, filters), not be
            # silently dropped — only the duplicate ROW is avoided. next_run_at is
            # reset only when the caller passed one explicitly, so a plain
            # re-schedule preserves the existing cadence position (no re-trigger).
            set_clauses = [
                "enabled = ?",
                "stale_days = ?",
                "auto_score = ?",
                "auto_postmortem = ?",
                "confidence_below = ?",
                "confidence_above = ?",
                "large_delta_threshold = ?",
            ]
            params: list[Any] = [
                1 if enabled else 0,
                int(stale_days),
                1 if auto_score else 0,
                1 if auto_postmortem else 0,
                confidence_below,
                confidence_above,
                large_delta_threshold,
            ]
            if next_run_at is not None:
                set_clauses.append("next_run_at = ?")
                params.append(parse_timestamp(next_run_at, field_name="next_run_at") or utc_now_iso())
            params.append(existing["id"])
            conn.execute(f"UPDATE scheduled_reviews SET {', '.join(set_clauses)} WHERE id = ?", params)
            # Return the upserted row's id and read it AFTER this `with` commits:
            # get_scheduled_review opens its own connection, so reading it inside
            # this still-open transaction would return the pre-UPDATE row (the
            # upserted auto_*/stale_days/filters would be invisible).
            result_id = existing["id"]
        else:
            conn.execute(
                """
                INSERT INTO scheduled_reviews (
                    id, scope_type, scope_ref, cadence, stale_days, next_run_at,
                    trigger_reason, enabled, auto_score, auto_postmortem,
                    confidence_below, confidence_above, large_delta_threshold
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    scope_type,
                    scope_ref,
                    cadence,
                    int(stale_days),
                    parse_timestamp(next_run_at, field_name="next_run_at") or utc_now_iso(),
                    trigger_reason,
                    1 if enabled else 0,
                    1 if auto_score else 0,
                    1 if auto_postmortem else 0,
                    confidence_below,
                    confidence_above,
                    large_delta_threshold,
                ),
            )
            result_id = review_id
    return ledger.get_scheduled_review(result_id)


def get_scheduled_review(ledger, review_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM scheduled_reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"scheduled review not found: {review_id}")
    return dict(row)


def list_scheduled_reviews(ledger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_reviews ORDER BY next_run_at ASC",
        ).fetchall()
    return [dict(row) for row in rows]


def next_review_by_question(ledger) -> dict[str, dict[str, Any]]:
    """question_id -> {next_run_at, cadence} from the SOONEST enabled per-question
    scheduled review (the live, self-advancing schedule, not the stale question
    column). One batched query for the desk's "next update" column."""
    out: dict[str, dict[str, Any]] = {}
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT scope_ref, next_run_at, cadence FROM scheduled_reviews "
            "WHERE scope_type = 'question' AND enabled = 1 AND next_run_at IS NOT NULL "
            "ORDER BY next_run_at ASC",
        ).fetchall()
    for row in rows:
        ref = row["scope_ref"]
        # ORDER BY next_run_at ASC → the first row per question is the soonest.
        if ref and ref not in out:
            out[ref] = {"cadence": row["cadence"], "next_run_at": row["next_run_at"]}
    return out


def count_due_scheduled_reviews(ledger, *, now: str | None = None) -> int:
    """Cheap COUNT of enabled scheduled-review rows already DUE (next_run_at <= now).

    The gateway due-sweeper reads this every tick to decide whether to run the
    deterministic sweep at all — one indexed COUNT, no row materialization, so
    the common "nothing due" case is nearly free."""
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM scheduled_reviews "
            "WHERE enabled = 1 AND next_run_at <= ?",
            (now_ts,),
        ).fetchone()
    return int(row["n"]) if row else 0


def next_scheduled_review_at(ledger) -> str | None:
    """The SOONEST enabled scheduled-review ``next_run_at`` (a past value means
    already due; a future value is the next time something becomes due), or
    None when nothing is scheduled. Backs the TUI review-sweep countdown."""
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT MIN(next_run_at) AS soonest FROM scheduled_reviews "
            "WHERE enabled = 1 AND next_run_at IS NOT NULL",
        ).fetchone()
    return (row["soonest"] if row else None) or None


def mark_question_review_due(ledger, question_id: str, *, now: str | None = None) -> dict[str, Any]:
    """Re-arm a question's review to fire on the next cron tick — the desk's
    "run update" shortcut. Sets the enabled per-question schedule's next_run_at
    to now; if no schedule row exists, creates one at the question's cadence
    (default weekly). The autonomous cycle then reforecasts it on its next tick."""
    when = now or utc_now_iso()
    with ledger._connect() as conn:
        cur = conn.execute(
            "UPDATE scheduled_reviews SET next_run_at = ? "
            "WHERE scope_type = 'question' AND scope_ref = ? AND enabled = 1",
            (when, question_id),
        )
        rearmed = cur.rowcount
    if rearmed:
        return {"next_run_at": when, "queued": True, "scheduled": "rearmed"}
    cadence = "weekly"
    try:
        question = ledger.get_question(question_id)
        cadence = question.review_cadence or "weekly"
    except Exception:
        pass
    ledger.schedule_review(
        scope_type="question", scope_ref=question_id, cadence=cadence,
        next_run_at=when, trigger_reason="manual",
    )
    return {"next_run_at": when, "queued": True, "scheduled": "created"}


def dedupe_scheduled_reviews(ledger) -> dict[str, Any]:
    """Collapse pre-existing duplicate ENABLED schedules that share
    (scope_type, scope_ref, cadence, trigger_reason). Keeps the most-established
    one — the one that has run most recently, else the soonest next_run_at —
    and disables the rest (so its run history is preserved, not deleted).
    Idempotent: a deduped ledger is a no-op. Pairs with the idempotency guard
    in schedule_review() which prevents NEW duplicates."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for review in ledger.list_scheduled_reviews():
        if not review.get("enabled"):
            continue
        key = (review["scope_type"], review["scope_ref"], review["cadence"], review["trigger_reason"])
        groups.setdefault(key, []).append(review)

    disabled: list[str] = []
    kept: list[str] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ran = [m for m in members if m.get("last_run_at")]
        keep = (
            max(ran, key=lambda m: (m["last_run_at"], m["id"]))
            if ran
            else min(members, key=lambda m: (m.get("next_run_at") or "", m["id"]))
        )
        kept.append(keep["id"])
        with ledger._connect() as conn:
            for member in members:
                if member["id"] != keep["id"]:
                    conn.execute("UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?", (member["id"],))
                    disabled.append(member["id"])

    return {
        "groups_collapsed": len(kept),
        "kept": kept,
        "disabled": disabled,
        "disabled_count": len(disabled),
    }


def list_scheduled_review_runs(
    ledger,
    *,
    scheduled_review_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(int(limit), 1)
    clauses: list[str] = []
    params: list[Any] = []
    if scheduled_review_id:
        clauses.append("scheduled_review_id = ?")
        params.append(scheduled_review_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM scheduled_review_runs
            {where}
            ORDER BY run_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [ledger._row_to_scheduled_review_run(row) for row in rows]


def run_due_scheduled_reviews(
    ledger,
    *,
    now: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    refresh_fetcher: Any = None,
) -> list[dict[str, Any]]:
    """Run every due scheduled-review row, advancing each row's cadence.

    ``refresh_fetcher`` (injected by the cron layer — the ledger never imports
    the tool/adapter layer) turns the sweep into a DETERMINISTIC self-refresh:
    for each due QUESTION-scoped review that is refreshable (has a baseline
    snapshot with structured ensemble_components AND active watched sources) we
    re-pull the sources, re-pool, and auto-commit a fresh snapshot — no LLM.
    Fail-open per question: one broken source records an error in the row's
    result and never aborts the sweep. The cadence is also DEADLINE-AWARE — a
    question's next run is escalated (never slowed) as its close/resolution/
    decision deadline nears."""
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scheduled_reviews
            WHERE enabled = 1 AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now_ts,),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        review = dict(row)
        scope_type = review["scope_type"]
        scope_ref = review["scope_ref"]
        stale_days = int(review.get("stale_days") or 7)
        confidence_below = review.get("confidence_below")
        confidence_above = review.get("confidence_above")
        large_delta_threshold = review.get("large_delta_threshold")
        refresh_result: dict[str, Any] | None = None
        refresh_error: str | None = None
        deadlines: list[str | None] | None = None
        if scope_type == "question":
            alerts = ledger.self_check(
                question_id=scope_ref,
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
            # Deadline-aware cadence input: read the question's live deadlines so
            # the next run can be escalated as close/resolution/decision nears.
            try:
                question = ledger.get_question(scope_ref)
                deadlines = [
                    getattr(question, "close_time", None),
                    getattr(question, "resolution_time", None),
                    getattr(question, "decision_deadline", None),
                ]
            except Exception:
                deadlines = None
            # Deterministic self-refresh (no LLM) for a refreshable question.
            if refresh_fetcher is not None:
                try:
                    refresh_result = ledger._refresh_due_question(
                        scope_ref, fetcher=refresh_fetcher, now=now_ts
                    )
                except Exception as exc:  # never abort the sweep on one question
                    refresh_error = str(exc)
        elif scope_type == "domain":
            alerts = ledger.self_check(
                domain=scope_ref,
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
        elif scope_type == "topic":
            alerts = ledger.self_check(
                topic=scope_ref,
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
        elif scope_type == "domain_topic":
            scope_filter = json_loads(scope_ref, {})
            alerts = ledger.self_check(
                domain=scope_filter.get("domain"),
                topic=scope_filter.get("topic"),
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
        elif scope_type == "portfolio":
            alerts = ledger.self_check(
                portfolio=scope_ref,
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
        else:
            alerts = ledger.self_check(
                horizon=scope_ref,
                stale_days=stale_days,
                now=now_ts,
                auto_score=auto_score or bool(review.get("auto_score")),
                auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                confidence_below=confidence_below,
                confidence_above=confidence_above,
                large_delta_threshold=large_delta_threshold,
            )
        next_run_at = ledger._advance_cadence(
            now_ts, review["cadence"], deadlines=deadlines
        )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE scheduled_reviews
                SET last_run_at = ?, next_run_at = ?
                WHERE id = ?
                """,
                (now_ts, next_run_at, review["id"]),
            )
        run = ledger._record_scheduled_review_run(
            review=review,
            run_at=now_ts,
            next_run_at=next_run_at,
            alerts=alerts,
        )
        results.append(
            {
                "review": ledger.get_scheduled_review(review["id"]),
                "run": run,
                "alerts": alerts,
                "refresh": refresh_result,
                "refresh_error": refresh_error,
            }
        )
    return results


def _refresh_due_question(
    ledger, question_id: str, *, fetcher: Any, now: str | None
) -> dict[str, Any] | None:
    """Deterministically self-refresh a due question when it is refreshable.

    Refreshable = a baseline snapshot with structured ensemble_components AND
    at least one active watched source. Returns ``None`` (skipped) otherwise,
    so a bare/no-source question is quietly left for the agent-tier re-reason.
    Opens its own write context so the commit is permitted even when the caller
    did not (e.g. the tool's direct ``run_scheduled_reviews``)."""
    current = ledger.get_current_snapshot(question_id)
    if current is None:
        return None
    components = current.ensemble_components
    if not isinstance(components, dict) or not components:
        return None
    watches = ledger.list_watched_sources(
        scope_type="question", scope_ref=question_id, status="active"
    )
    if not watches:
        return None
    with allow_ledger_writes(reason="scheduled_refresh"):
        return ledger.refresh_forecast(
            question_id,
            fetcher=fetcher,
            now=now,
            trigger_reason="scheduled_refresh",
        )


def _record_scheduled_review_run(
    ledger,
    *,
    review: dict[str, Any],
    run_at: str,
    next_run_at: str,
    alerts: list[AlertEvent],
) -> dict[str, Any]:
    score_count = sum(1 for alert in alerts if alert.reason.startswith("score_created:"))
    postmortem_count = sum(1 for alert in alerts if alert.reason.startswith("postmortem_created:"))
    learning_review_count = sum(1 for alert in alerts if ledger._is_learning_alert_reason(alert.reason))
    run_id = f"srr_{uuid.uuid4().hex[:12]}"
    metadata = {
        "scope_type": review.get("scope_type"),
        "scope_ref": review.get("scope_ref"),
        "cadence": review.get("cadence"),
        "trigger_reason": review.get("trigger_reason"),
        "auto_score": bool(review.get("auto_score")),
        "auto_postmortem": bool(review.get("auto_postmortem")),
        "alert_reasons": [alert.reason for alert in alerts],
        "alert_ids": [alert.id for alert in alerts],
    }
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_review_runs (
                id, scheduled_review_id, run_at, next_run_at, alert_count,
                score_count, postmortem_count, learning_review_count,
                status, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                review["id"],
                run_at,
                next_run_at,
                len(alerts),
                score_count,
                postmortem_count,
                learning_review_count,
                "completed",
                json_dumps(metadata),
            ),
        )
    return ledger.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=1)[0]


def _review_priority(ledger, reasons: list[str]) -> int:
    if any(reason.startswith("new_evidence:") for reason in reasons):
        return 0
    if any(
        reason in {"resolution_check_due", "close_time_passed"}
        or reason.startswith("close_time_within_")
        for reason in reasons
    ):
        return 1
    if any(reason.startswith(("assumption_invalidated:", "reference_class_invalidated:")) for reason in reasons):
        return 2
    if any(
        reason in {"review_due", "no_forecast_snapshot", "no_evidence"}
        or reason.startswith(("large_forecast_delta:", "assumption_check_due:", "reference_class_check_due:", "assumption_stale:", "reference_class_stale:"))
        for reason in reasons
    ):
        return 3
    if any(reason.startswith(("last_update_", "evidence_stale_")) for reason in reasons):
        return 4
    return 9


def _advance_cadence(
    ledger, now_ts: str, cadence: str, *, deadlines: list[str | None] | None = None
) -> str:
    now_dt = timestamp_to_datetime(now_ts)
    assert now_dt is not None
    delta = ledger._cadence_delta(cadence)
    delta = ledger._clamp_cadence_to_deadline(now_dt, delta, deadlines)
    return (now_dt + delta).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp_cadence_to_deadline(
    ledger, now_dt, delta: timedelta, deadlines: list[str | None] | None
) -> timedelta:
    """Escalate (never slow) the cadence as the nearest deadline nears.

    Within 7 days of the nearest of close/resolution/decision deadline -> at
    most daily; within 48h -> at most twice-daily. Only SHORTENS the interval
    (``min`` with the base cadence), so a slow base cadence still speeds up near
    the wire but a fast one is never slowed. Past deadlines are ignored."""
    if not deadlines:
        return delta
    nearest = None
    for ts in deadlines:
        dt = timestamp_to_datetime(ts) if ts else None
        if dt is None or dt <= now_dt:
            continue
        if nearest is None or dt < nearest:
            nearest = dt
    if nearest is None:
        return delta
    horizon = nearest - now_dt
    if horizon <= timedelta(hours=48):
        cap = timedelta(hours=12)
    elif horizon <= timedelta(days=7):
        cap = timedelta(days=1)
    else:
        return delta
    return min(delta, cap)


def _cadence_due(ledger, last_checked_at: str | None, cadence: str | None, now_dt) -> bool:
    if not last_checked_at or not cadence:
        return False
    last_dt = timestamp_to_datetime(last_checked_at)
    if last_dt is None:
        return False
    return last_dt + ledger._cadence_delta(cadence) <= now_dt


def _cadence_delta(ledger, cadence: str) -> timedelta:
    raw = re.sub(r"\s+", " ", cadence.strip().lower())
    if raw.startswith("every "):
        raw = raw[len("every "):].strip()
    if raw in {"daily", "1d"}:
        return timedelta(days=1)
    elif raw in {"weekly", "1w"}:
        return timedelta(days=7)
    elif raw == "hourly":
        return timedelta(hours=1)
    elif raw == "minutely":
        return timedelta(minutes=1)

    match = re.fullmatch(
        r"(?P<count>\d*)\s*(?P<unit>w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes)",
        raw,
    )
    if match:
        count = max(int(match.group("count") or "1"), 1)
        unit = match.group("unit")
        if unit in {"w", "week", "weeks"}:
            return timedelta(days=count * 7)
        if unit in {"d", "day", "days"}:
            return timedelta(days=count)
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return timedelta(hours=count)
        return timedelta(minutes=count)
    return timedelta(days=1)


def _row_to_scheduled_review_run(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = json_loads(data["metadata"], {})
    return data
