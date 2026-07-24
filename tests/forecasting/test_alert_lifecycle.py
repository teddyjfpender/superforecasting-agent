"""Warnings-lifecycle: enqueue dedup, the domain-error flood, condition-based
auto-close reconciliation, age escalation, and the one-time collapse migration.

These reproduce the live pathology (2,773 open alerts; ~1,900 of them a single
re-emitted `domain_error_profile_review`; 192 duplicate (scope, reason) groups;
superseded/consumed alerts immortal because nothing reconciled the satisfied
condition) against a seeded ledger, then pin the fixes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from datetime import timedelta

from forecasting.ledger import ForecastLedger
from forecasting.models import parse_timestamp, timestamp_to_datetime, utc_now_iso

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "alerts.db"))
    lg.initialize_schema()
    return lg


def _age_alert(lg: ForecastLedger, alert_id: str, created_at: str) -> None:
    """Backdate an alert's created_at (simulate an alert that fired earlier)."""
    with lg._connect() as conn:
        conn.execute(
            "UPDATE alert_events SET created_at = ? WHERE id = ?", (created_at, alert_id)
        )


def _days_ago(days: float) -> str:
    dt = timestamp_to_datetime(utc_now_iso()) - timedelta(days=days)
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Fix 1 — DEDUPE AT ENQUEUE (universal)
# ---------------------------------------------------------------------------


def test_enqueue_dedupes_same_scope_reason_and_touches(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will it cross the line?", resolution_criteria=CRIT)

    first = lg.create_alert(
        severity="info", scope_type="question", scope_ref=q.id,
        reason="last_update_7d_plus", recommended_action="reforecast",
    )
    second = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="last_update_7d_plus", recommended_action="reforecast again",
    )

    # Same row (never a second), touched: seen_count grows, severity escalates to max.
    assert second.id == first.id
    assert len(lg.list_alerts(unresolved_only=False)) == 1
    touched = lg.get_alert(first.id)
    assert touched.seen_count == 2
    assert touched.severity == "warning"  # max(info, warning)
    assert touched.last_seen_at is not None


def test_enqueue_distinct_reason_or_scope_is_a_new_row(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Distinct?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="last_update_7d_plus", recommended_action="x")
    b = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="evidence_stale_7d_plus", recommended_action="y")
    assert a.id != b.id
    assert len(lg.list_alerts()) == 2


def test_enqueue_does_not_touch_a_closed_alert(tmp_path):
    """A dedup only folds into an OPEN row; once acked, a fresh transition re-opens
    a new row (the condition recurred after the operator cleared it)."""
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Recur?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="no_evidence", recommended_action="x")
    lg.acknowledge_alert(a.id)
    b = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="no_evidence", recommended_action="x")
    assert b.id != a.id
    assert len(lg.list_alerts(unresolved_only=True)) == 1


def test_repeated_self_check_does_not_stack_duplicate_alerts(tmp_path):
    """The live flood: nightly self_check re-emitting the same open alert every run.
    With enqueue dedup, N runs over an unchanged ledger yield ONE row per condition."""
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the metric report on time?", resolution_criteria=CRIT,
        domain="macro", next_review_at="2020-01-01T00:00:00Z",
    )
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5,
                       rationale="baseline", as_of="2020-01-02T00:00:00Z")
    for _ in range(5):
        lg.self_check(question_id=q.id, stale_days=1)
    groups: dict[tuple[str, str, str], int] = {}
    for alert in lg.list_alerts(unresolved_only=True):
        key = (alert.scope_type, alert.scope_ref, alert.reason)
        groups[key] = groups.get(key, 0) + 1
    assert groups, "self_check should have produced at least one alert"
    assert max(groups.values()) == 1, f"duplicate open rows: {groups}"


# ---------------------------------------------------------------------------
# Fix 2 — the domain_error_profile_review flood
# ---------------------------------------------------------------------------


def _seed_error_profile(lg: ForecastLedger):
    resolved = lg.create_question(
        title="Will a resolved macro miss create a reusable error profile?",
        resolution_criteria="Resolved no if the profile should warn active macro forecasts.",
        domain="macro", topics=["inflation"],
    )
    active = lg.create_question(
        title="Will the active macro forecast get learned-error review?",
        resolution_criteria="Resolved yes if learned profile alerts apply to active matching forecasts.",
        domain="macro", topics=["inflation"],
    )
    lg.create_snapshot(question_id=resolved.id, probability_or_distribution=0.9,
                       rationale="overconfident miss")
    lg.create_snapshot(question_id=active.id, probability_or_distribution=0.65,
                       rationale="active standing forecast")
    lg.resolve_question(question_id=resolved.id, outcome="no")
    lg.self_check(question_id=resolved.id, auto_score=True, auto_postmortem=True)
    return active


def test_domain_error_profile_review_touches_never_re_emits(tmp_path):
    lg = _ledger(tmp_path)
    _seed_error_profile(lg)
    for _ in range(6):
        lg.self_check(domain="macro", topic="inflation")
    reviews = [a for a in lg.list_alerts(unresolved_only=True)
               if a.reason == "domain_error_profile_review"]
    # One alert per profile (scope_ref == profile id), never a re-emitted stack.
    per_profile: dict[str, int] = {}
    for a in reviews:
        per_profile[a.scope_ref] = per_profile.get(a.scope_ref, 0) + 1
    assert per_profile, "expected a profile-review alert"
    assert max(per_profile.values()) == 1
    assert all(r.seen_count >= 1 for r in reviews)
    # scope_ref is the profile id (contract other code relies on)
    profile = lg.list_domain_error_profiles(domain="macro", topic="inflation")[0]
    assert profile["id"] in per_profile


# ---------------------------------------------------------------------------
# Fix 3 — RECONCILIATION: auto-close when the condition no longer holds
# ---------------------------------------------------------------------------


def test_reconcile_last_update_closes_on_fresh_snapshot(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Stale update?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="last_update_7d_plus", recommended_action="reforecast")
    _age_alert(lg, a.id, _days_ago(10))

    # No fresh snapshot yet -> stays open.
    assert lg.reconcile_alerts()["reconciled_count"] == 0

    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="re-forecast")
    result = lg.reconcile_alerts()
    assert [e["id"] for e in result["reconciled"]] == [a.id]
    closed = lg.get_alert(a.id)
    assert closed.acknowledged_at is not None
    assert closed.ack_note and "fresh_snapshot" in closed.ack_note
    assert closed.dismissed_at is None  # distinct from an operator dismissal


def test_reconcile_evidence_stale_closes_on_fresh_evidence(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Stale evidence?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="evidence_stale_7d_plus", recommended_action="refresh")
    _age_alert(lg, a.id, _days_ago(10))
    assert lg.reconcile_alerts()["reconciled_count"] == 0
    lg.add_evidence(question_id=q.id, source_or_note="fresh read", claim="value moved")
    assert [e["id"] for e in lg.reconcile_alerts()["reconciled"]] == [a.id]


def test_reconcile_no_evidence_closes_when_evidence_lands(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="No evidence?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="no_evidence", recommended_action="research")
    _age_alert(lg, a.id, _days_ago(3))
    assert lg.reconcile_alerts()["reconciled_count"] == 0
    lg.add_evidence(question_id=q.id, source_or_note="first read", claim="a data point")
    assert [e["id"] for e in lg.reconcile_alerts()["reconciled"]] == [a.id]


def test_reconcile_no_forecast_snapshot_closes_when_snapshot_exists(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="No snapshot?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="no_forecast_snapshot", recommended_action="forecast update")
    _age_alert(lg, a.id, _days_ago(3))
    assert lg.reconcile_alerts()["reconciled_count"] == 0
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.4, rationale="first forecast")
    assert [e["id"] for e in lg.reconcile_alerts()["reconciled"]] == [a.id]


def test_reconcile_close_time_within_superseded_by_close_time_passed(tmp_path):
    lg = _ledger(tmp_path)
    # close_time already in the past so close_time_passed genuinely holds.
    q = lg.create_question(title="Closing soon?", resolution_criteria=CRIT,
                           close_time=_days_ago(1))
    within = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                             reason="close_time_within_7d", recommended_action="prep close")
    passed = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                             reason="close_time_passed", recommended_action="close or resolve")
    _age_alert(lg, within.id, _days_ago(2))
    _age_alert(lg, passed.id, _days_ago(1))

    result = lg.reconcile_alerts()
    reconciled_ids = {e["id"] for e in result["reconciled"]}
    assert within.id in reconciled_ids  # superseded -> closed
    assert passed.id not in reconciled_ids  # the superseding alert stays open
    assert "superseded" in (lg.get_alert(within.id).ack_note or "")


def test_reconcile_resolution_check_due_closes_on_confirmed_resolution(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Resolvable?", resolution_criteria=CRIT)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.7, rationale="prior")
    a = lg.create_alert(severity="high", scope_type="question", scope_ref=q.id,
                        reason="resolution_check_due", recommended_action="confirm resolution")
    _age_alert(lg, a.id, _days_ago(2))
    # Not resolved yet -> stays open (it was previously NO_AUTO/immortal).
    assert lg.reconcile_alerts()["reconciled_count"] == 0
    lg.resolve_question(question_id=q.id, outcome="yes")
    # The resolution transaction closes the alert immediately; reconciliation
    # has no later cleanup window to race.
    assert lg.reconcile_alerts()["reconciled"] == []
    assert lg.get_alert(a.id).ack_note == "auto_close:question_resolved"


def test_alert_key_folds_changing_display_detail(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Resolvable?", resolution_criteria=CRIT)

    first = lg.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=q.id,
        reason="resolution proposed: YES — first rationale",
        recommended_action="inspect first",
    )
    second = lg.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=q.id,
        reason="resolution proposed: YES — updated rationale",
        recommended_action="inspect updated",
        refresh_action=True,
    )

    assert second.id == first.id
    assert second.alert_key == "resolution_proposed:yes"
    assert second.seen_count == 2
    assert second.reason.endswith("updated rationale")


def test_alert_database_key_survives_concurrent_enqueue(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Concurrent?", resolution_criteria=CRIT)

    def enqueue(_index: int):
        return lg.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=q.id,
            reason="same_condition",
            recommended_action="review",
        ).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(enqueue, range(16)))

    assert len(set(ids)) == 1
    alerts = [alert for alert in lg.list_alerts() if alert.reason == "same_condition"]
    assert len(alerts) == 1
    assert alerts[0].seen_count == 16


def test_reconcile_resolution_check_due_closes_on_open_proposal(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Proposed?", resolution_criteria=CRIT)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.7, rationale="prior")
    a = lg.create_alert(severity="high", scope_type="question", scope_ref=q.id,
                        reason="resolution_check_due", recommended_action="confirm resolution")
    _age_alert(lg, a.id, _days_ago(2))
    # A confirm-me proposal alert is now open for the same question.
    lg.enqueue_resolution_proposal(question_id=q.id, outcome="yes", rationale="market settled")
    assert a.id in {e["id"] for e in lg.reconcile_alerts()["reconciled"]}


def test_reconcile_leaves_genuine_no_auto_open(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Assumption?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="assumption_invalidated:as_1", recommended_action="fix assumption")
    _age_alert(lg, a.id, _days_ago(30))
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="new")
    lg.add_evidence(question_id=q.id, source_or_note="read", claim="x")
    # Even with fresh evidence + a new snapshot, a genuine human-judgment class stays open.
    assert lg.reconcile_alerts()["reconciled_count"] == 0


def test_reconcile_dry_run_previews_without_acking(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Preview?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                        reason="last_update_7d_plus", recommended_action="x")
    _age_alert(lg, a.id, _days_ago(10))
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="new")
    preview = lg.reconcile_alerts(dry_run=True)
    assert preview["reconciled_count"] == 1
    assert lg.get_alert(a.id).acknowledged_at is None  # nothing mutated


# ---------------------------------------------------------------------------
# Fix 4 — ESCALATION: aged open alerts escalate severity
# ---------------------------------------------------------------------------


def test_escalation_thresholds(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Aging?", resolution_criteria=CRIT)
    fresh = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                            reason="escalation_probe:fresh", recommended_action="x")
    week = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                           reason="escalation_probe:week", recommended_action="x")
    old = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                          reason="escalation_probe:old", recommended_action="x")
    _age_alert(lg, week.id, _days_ago(8))
    _age_alert(lg, old.id, _days_ago(15))

    result = lg.escalate_aged_alerts()
    assert result["escalated_count"] == 2
    assert lg.get_alert(fresh.id).severity == "info"     # < 7d unchanged
    assert lg.get_alert(week.id).severity == "warning"   # >= 7d -> elevated
    assert lg.get_alert(old.id).severity == "high"       # >= 14d -> high


def test_escalation_only_raises_and_is_idempotent(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Idempotent?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="high", scope_type="question", scope_ref=q.id,
                        reason="escalation_probe:x", recommended_action="x")
    _age_alert(lg, a.id, _days_ago(8))
    # Already 'high' at 8d — escalation never downgrades to 'warning'.
    assert lg.escalate_aged_alerts()["escalated_count"] == 0
    assert lg.get_alert(a.id).severity == "high"

    b = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="escalation_probe:y", recommended_action="x")
    _age_alert(lg, b.id, _days_ago(20))
    assert lg.escalate_aged_alerts()["escalated_count"] == 1
    # Second pass is a no-op (already escalated).
    assert lg.escalate_aged_alerts()["escalated_count"] == 0


def test_escalation_skips_acknowledged(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Closed?", resolution_criteria=CRIT)
    a = lg.create_alert(severity="info", scope_type="question", scope_ref=q.id,
                        reason="escalation_probe:z", recommended_action="x")
    _age_alert(lg, a.id, _days_ago(30))
    lg.acknowledge_alert(a.id)
    assert lg.escalate_aged_alerts()["escalated_count"] == 0


def test_new_evidence_alerts_batch_by_question_and_prior_forecast(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Batch evidence?", resolution_criteria=CRIT)
    baseline = lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )

    first = lg.create_alert(
        severity="info",
        scope_type="question",
        scope_ref=q.id,
        reason="new_evidence:ev_one",
        recommended_action="Review the batch.",
    )
    second = lg.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=q.id,
        reason="new_evidence:ev_two",
        recommended_action="Review the batch.",
    )

    assert first.id == second.id
    stored = lg.get_alert(first.id)
    assert stored.alert_key == f"new_evidence_batch:{baseline.forecast_id}"
    assert stored.seen_count == 2
    assert stored.severity == "warning"


# ---------------------------------------------------------------------------
# Fix 1b — COLLAPSE migration for the existing duplicate backlog
# ---------------------------------------------------------------------------


def _raw_insert_alert(lg, *, alert_id, created_at, severity, scope_type, scope_ref, reason):
    with lg._connect() as conn:
        conn.execute(
            "INSERT INTO alert_events (id, created_at, severity, scope_type, scope_ref, "
            "reason, recommended_action) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alert_id, created_at, severity, scope_type, scope_ref, reason, "act"),
        )


def test_collapse_migration_folds_duplicates_keeping_oldest(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Dupes?", resolution_criteria=CRIT)
    # Simulate the pre-fix live state: three raw duplicate rows for one (scope, reason).
    _raw_insert_alert(lg, alert_id="al_oldest", created_at=_days_ago(9),
                      severity="info", scope_type="question", scope_ref=q.id,
                      reason="last_update_7d_plus")
    _raw_insert_alert(lg, alert_id="al_mid", created_at=_days_ago(5),
                      severity="warning", scope_type="question", scope_ref=q.id,
                      reason="last_update_7d_plus")
    _raw_insert_alert(lg, alert_id="al_new", created_at=_days_ago(1),
                      severity="info", scope_type="question", scope_ref=q.id,
                      reason="last_update_7d_plus")
    # A singleton group is untouched.
    _raw_insert_alert(lg, alert_id="al_single", created_at=_days_ago(2),
                      severity="info", scope_type="question", scope_ref=q.id,
                      reason="no_evidence")

    preview = lg.collapse_duplicate_alerts(dry_run=True)
    assert preview["groups_collapsed"] == 1
    assert preview["rows_folded"] == 2
    assert len(lg.list_alerts(unresolved_only=True)) == 4  # nothing mutated in dry-run

    result = lg.collapse_duplicate_alerts()
    assert result["groups_collapsed"] == 1
    assert result["rows_folded"] == 2
    open_now = lg.list_alerts(unresolved_only=True)
    open_ids = {a.id for a in open_now}
    assert "al_oldest" in open_ids  # kept oldest
    assert "al_mid" not in open_ids and "al_new" not in open_ids
    assert "al_single" in open_ids
    kept = lg.get_alert("al_oldest")
    assert kept.seen_count == 3  # folded count
    assert kept.severity == "warning"  # most-severe in the group
    # Folded rows are auditable + distinct from operator acks.
    folded = lg.get_alert("al_mid")
    assert folded.acknowledged_at is not None
    assert folded.ack_note and "collapsed" in folded.ack_note
    assert folded.dismissed_at is None


def test_collapse_migration_is_idempotent(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Idempotent collapse?", resolution_criteria=CRIT)
    for i in range(4):
        _raw_insert_alert(lg, alert_id=f"al_{i}", created_at=_days_ago(9 - i),
                          severity="info", scope_type="question", scope_ref=q.id,
                          reason="evidence_stale_7d_plus")
    assert lg.collapse_duplicate_alerts()["groups_collapsed"] == 1
    # Second pass: no duplicate groups remain.
    second = lg.collapse_duplicate_alerts()
    assert second["groups_collapsed"] == 0
    assert second["rows_folded"] == 0
    assert len(lg.list_alerts(unresolved_only=True)) == 1


def test_collapse_migration_coalesces_estimation_run_family(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="One estimation condition?", resolution_criteria=CRIT)
    for index, run_id in enumerate(("mr_first", "mr_second", "mr_third")):
        _raw_insert_alert(
            lg,
            alert_id=f"al_est_{index}",
            created_at=_days_ago(3 - index),
            severity="warning",
            scope_type="question",
            scope_ref=q.id,
            reason=f"forecast_estimation_required:{run_id}",
        )

    result = lg.collapse_duplicate_alerts()

    assert result["groups_collapsed"] == 1
    assert result["rows_folded"] == 2
    remaining = lg.list_alerts(unresolved_only=True)
    assert len(remaining) == 1
    assert remaining[0].alert_key == "forecast_estimation_required"
