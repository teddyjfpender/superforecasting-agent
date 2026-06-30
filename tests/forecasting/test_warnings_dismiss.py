"""Slice 5 — DISMISS (ignore-a-group, RECORDED, not a bare-ack).

The load-bearing invariant: a dismissal is an EXPLICIT, RECORDED human silence —
NEVER a resolution and NEVER a silent bare-ack. It drops the open count (sets
``acknowledged_at``) but ALSO stamps a dismissal audit trail (note + actor +
``dismissed_at`` + ``dismiss_reason`` + TTL) that makes it visibly distinct from a
runner-resolution (which leaves ``dismissed_at`` NULL). A dismissed group
re-surfaces after the TTL rather than being silenced forever.
"""

from __future__ import annotations

import pytest

from forecasting.cron_runner import run_warning_resolution
from forecasting.ledger import ForecastLedger
from forecasting.warnings import select_open_warnings


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "dismiss.db"))
    lg.initialize_schema()
    return lg


def _alert(lg, *, reason: str, severity: str = "warning", scope_ref: str = "fq_x"):
    return lg.create_alert(
        severity=severity,
        scope_type="question",
        scope_ref=scope_ref,
        reason=reason,
        recommended_action="review",
    )


# ---------------------------------------------------------------------------
# Dismiss records note + actor + audit trail, and is NOT a resolution.
# ---------------------------------------------------------------------------


def test_dismiss_records_note_actor_and_is_not_a_resolution(tmp_path):
    lg = _ledger(tmp_path)
    alert = _alert(lg, reason="evidence_stale_7d_plus")

    dismissed = lg.dismiss_alerts(
        [alert.id],
        note="known noisy source — ignoring this batch for a week",
        actor="teddy",
        dismiss_reason="reason=evidence_stale",
        now="2026-06-30T00:00:00Z",
    )

    assert len(dismissed) == 1
    # The RETURNED object reflects the persisted trail (regression: it must be
    # re-read post-commit, not from inside the still-open write transaction).
    assert dismissed[0].dismiss_note == "known noisy source — ignoring this batch for a week"
    assert dismissed[0].dismiss_actor == "teddy"
    assert dismissed[0].dismissed_at == "2026-06-30T00:00:00Z"
    # The recorded silence carries its full audit trail.
    stored = lg.get_alert(alert.id)
    assert stored.dismiss_note == "known noisy source — ignoring this batch for a week"
    assert stored.dismiss_actor == "teddy"
    assert stored.dismiss_reason == "reason=evidence_stale"
    assert stored.dismissed_at == "2026-06-30T00:00:00Z"
    assert stored.dismiss_ttl_days == 7
    assert stored.is_dismissed is True
    # It dropped out of the OPEN backlog (acknowledged), so the count fell …
    assert stored.acknowledged_at == "2026-06-30T00:00:00Z"
    assert lg.list_alerts(unresolved_only=True) == []

    # … but it was NOT resolved: a resolution sweep neither sees it nor counts it.
    summary = run_warning_resolution(ledger=lg, now="2026-06-30T01:00:00Z")
    assert summary["processed"] == 0
    assert summary["total"] == 0
    assert summary["tally"].get("resolved", 0) == 0
    seen_ids = {r.get("alert_id") for r in summary["results"]}
    assert alert.id not in seen_ids


def test_dismissed_is_visibly_distinct_from_a_runner_resolution(tmp_path):
    lg = _ledger(tmp_path)
    # A genuine bookkeeping alert resolved by the runner (real close-out).
    resolved_alert = _alert(lg, reason="review_due", severity="info")
    # A separate alert the operator dismisses by hand.
    dismissed_alert = _alert(lg, reason="evidence_stale_7d_plus", scope_ref="fq_y")

    lg.dismiss_alerts([dismissed_alert.id], note="ignore for now", actor="teddy")
    run_warning_resolution(ledger=lg, now="2026-06-30T00:00:00Z")

    resolved = lg.get_alert(resolved_alert.id)
    dismissed = lg.get_alert(dismissed_alert.id)

    # Both are acknowledged (out of the open backlog) …
    assert resolved.acknowledged_at is not None
    assert dismissed.acknowledged_at is not None
    # … but ONLY the dismissal carries the dismissal trail — the resolution does not.
    assert resolved.dismissed_at is None
    assert resolved.is_dismissed is False
    assert dismissed.is_dismissed is True
    assert dismissed.dismiss_note == "ignore for now"


# ---------------------------------------------------------------------------
# A non-empty note + actor is REQUIRED (no silent mass-dismiss).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("note", ["", "   ", None])
def test_dismiss_requires_a_non_empty_note(tmp_path, note):
    lg = _ledger(tmp_path)
    alert = _alert(lg, reason="evidence_stale_7d_plus")
    with pytest.raises(ValueError, match="note"):
        lg.dismiss_alerts([alert.id], note=note, actor="teddy")
    # Nothing was silenced — the alert is still OPEN.
    assert [a.id for a in lg.list_alerts(unresolved_only=True)] == [alert.id]


def test_dismiss_requires_an_actor(tmp_path):
    lg = _ledger(tmp_path)
    alert = _alert(lg, reason="evidence_stale_7d_plus")
    with pytest.raises(ValueError, match="actor"):
        lg.dismiss_alerts([alert.id], note="ignore", actor="")


def test_dismiss_never_clobbers_an_already_resolved_alert(tmp_path):
    lg = _ledger(tmp_path)
    alert = _alert(lg, reason="review_due", severity="info")
    lg.acknowledge_alert(alert.id, acknowledged_at="2026-06-29T00:00:00Z")

    dismissed = lg.dismiss_alerts([alert.id], note="too late", actor="teddy")

    assert dismissed == []  # the real resolution is untouched
    stored = lg.get_alert(alert.id)
    assert stored.acknowledged_at == "2026-06-29T00:00:00Z"
    assert stored.dismissed_at is None


# ---------------------------------------------------------------------------
# Bulk dismiss-a-group via the warning selector (reason/scope filter).
# ---------------------------------------------------------------------------


def test_dismiss_silences_a_whole_reason_group(tmp_path):
    lg = _ledger(tmp_path)
    for scope in ("fq_a", "fq_b", "fq_c"):
        _alert(lg, reason="evidence_stale_7d_plus", scope_ref=scope)
    _alert(lg, reason="review_due", scope_ref="fq_d", severity="info")  # a different group

    group = select_open_warnings(lg, reason="evidence_stale")
    dismissed = lg.dismiss_alerts(
        [w.id for w in group], note="batch noise", actor="ops"
    )

    assert len(dismissed) == 3
    remaining = lg.list_alerts(unresolved_only=True)
    assert {a.reason for a in remaining} == {"review_due"}  # the other group stays open


# ---------------------------------------------------------------------------
# TTL: a dismissed group RE-SURFACES after the window (not silenced forever).
# ---------------------------------------------------------------------------


def test_active_dismissal_keys_track_the_ttl_window(tmp_path):
    lg = _ledger(tmp_path)
    alert = _alert(lg, reason="evidence_stale_7d_plus", scope_ref="fq_x")
    lg.dismiss_alerts(
        [alert.id], note="ignore", actor="teddy", ttl_days=7, now="2026-06-30T00:00:00Z"
    )

    # Inside the window the (scope, reason) pair is an active silence …
    inside = lg.active_dismissal_keys(now="2026-07-03T00:00:00Z")
    assert ("fq_x", "evidence_stale_7d_plus") in inside

    # … and once the window elapses it drops out (so self_check re-emits).
    outside = lg.active_dismissal_keys(now="2026-07-08T00:00:01Z")
    assert ("fq_x", "evidence_stale_7d_plus") not in outside


def test_self_check_respects_dismissal_then_re_surfaces_after_ttl(tmp_path):
    lg = _ledger(tmp_path)
    question = lg.create_question(
        title="Will the index close above target by year end?",
        resolution_criteria="Resolves yes if the official index closes above the stated target at year end.",
    )

    def _open_no_snapshot_alerts():
        return [
            a
            for a in lg.list_alerts(unresolved_only=True)
            if a.scope_ref == question.id and a.reason == "no_forecast_snapshot"
        ]

    # 1. The un-forecast question surfaces a no_forecast_snapshot alert.
    lg.self_check(question_id=question.id, now="2026-06-30T00:00:00Z")
    first = _open_no_snapshot_alerts()
    assert len(first) == 1

    # 2. Dismiss it (recorded silence, 7-day TTL).
    lg.dismiss_alerts(
        [first[0].id], note="not ready to forecast yet", actor="teddy",
        ttl_days=7, now="2026-06-30T00:00:00Z",
    )
    assert _open_no_snapshot_alerts() == []

    # 3. Inside the window self_check does NOT re-emit the silenced group.
    lg.self_check(question_id=question.id, now="2026-07-02T00:00:00Z")
    assert _open_no_snapshot_alerts() == []

    # 4. After the window the still-true condition RE-SURFACES a fresh alert.
    lg.self_check(question_id=question.id, now="2026-07-09T00:00:00Z")
    resurfaced = _open_no_snapshot_alerts()
    assert len(resurfaced) == 1
    assert resurfaced[0].id != first[0].id  # a NEW alert, not the dismissed one
