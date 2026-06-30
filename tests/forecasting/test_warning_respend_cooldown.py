"""Slice 8 — re-spend safety for the continuous paid (LLM) warning tier.

Pins the two load-bearing guarantees that stop an unattended automode loop from
burning the token budget re-attempting the same alert:

  * PER-CYCLE SPEND CAP — ``run_warning_resolution(spend_cap=N)`` halts the sweep
    in the loop the moment N agent runs have fired (``budget_exhausted=True``); the
    alerts it never reached stay OPEN.
  * PER-ALERT COOLDOWN — a paid attempt that does NOT resolve an alert stamps an
    exponential backoff (``record_alert_attempt`` → ``last_attempted_at`` +
    ``attempt_count``). The alert stays OPEN (never a bare-ack) but is COOLED DOWN:
    it is excluded from selection until its window elapses, and each repeated
    failure doubles the next window.
"""

from __future__ import annotations

from forecasting import warnings as fwarn
from forecasting.cron_runner import run_warning_resolution
from forecasting.ledger import ForecastLedger
from forecasting.warnings import respend_backoff_hours


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "w.db"))
    lg.initialize_schema()
    return lg


def _seed_paid(lg: ForecastLedger, n: int) -> None:
    # staleness alerts route to the REFORECAST (paid / agent-tier) kind.
    for i in range(n):
        lg.create_alert(
            severity="warning", scope_type="question", scope_ref=f"fq_paid_{i}",
            reason="evidence_stale_7d_plus", recommended_action="Re-forecast.")


def _open_reason(lg: ForecastLedger, reason: str) -> list:
    return [a for a in lg.list_alerts(unresolved_only=True) if a.reason == reason]


# ---------------------------------------------------------------------------
# Backoff schedule (pure)
# ---------------------------------------------------------------------------


def test_backoff_is_exponential_and_capped():
    assert respend_backoff_hours(0) == 0.0           # never attempted -> attemptable
    assert respend_backoff_hours(1) == 24.0          # 1st failure -> 24h
    assert respend_backoff_hours(2) == 48.0          # doubles
    assert respend_backoff_hours(3) == 96.0
    # capped so a long-failing alert is still re-checked (does not recede forever)
    assert respend_backoff_hours(99) == fwarn.RESPEND_BACKOFF_CAP_HOURS


# ---------------------------------------------------------------------------
# Per-cycle spend cap halts the sweep IN THE LOOP
# ---------------------------------------------------------------------------


def test_per_cycle_spend_cap_halts_the_sweep(tmp_path):
    lg = _ledger(tmp_path)
    _seed_paid(lg, 3)

    calls: list[str] = []

    def failing_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return None  # did no real gated work -> dispatcher reports "failed", no ack

    result = run_warning_resolution(
        ledger=lg,
        tier="reforecast",
        reforecast_runner=failing_reforecast,
        cooldown=True,
        spend_cap=2,
        now="2026-06-30T12:00:00",
    )

    # The cap halted the sweep after exactly 2 agent runs, even though 3 were open.
    assert len(calls) == 2
    assert result["spent"] == 2
    assert result["budget_exhausted"] is True

    # No bare-ack: every alert is still OPEN (the 2 failed, the 3rd was never reached).
    assert len(_open_reason(lg, "evidence_stale_7d_plus")) == 3

    # The 2 ATTEMPTED alerts were stamped with a cooldown; the un-reached one was not.
    attempts = sorted(a.attempt_count for a in lg.list_alerts(unresolved_only=True))
    assert attempts == [0, 1, 1]


def test_reconcile_runs_even_when_the_spend_cap_halts_the_sweep(tmp_path):
    """A BUDGET halt only caps the PAID agent sweep — the cheap, free, non-agent
    end-of-sweep reconcile bookkeeping must STILL run so a budget-capped cycle
    closes its already-consumed / condition-resolved alerts. Pins that reconcile is
    no longer gated on ``not budget_exhausted``."""
    lg = _ledger(tmp_path)

    # A real question carrying a reconcilable (non-paid, non-NO_AUTO) alert: it fired
    # BEFORE fresh evidence + a new snapshot landed, so reconcile should ack it.
    q = lg.create_question(
        title="Will the official index close above target in 2026?",
        resolution_criteria="Resolves yes if the official index closes above target; otherwise no.",
    )
    reconcilable = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="watched_source_changed:src1", recommended_action="Recheck the source.")
    with lg._connect() as conn:
        conn.execute(
            "UPDATE alert_events SET created_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00Z", reconcilable.id),
        )
    lg.add_evidence(question_id=q.id, source_or_note="A fresh reading landed after the alert.")
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="updated",
        require_panel=False)

    # Two PAID (reforecast-tier) alerts + a spend cap of 1 so the sweep halts after
    # one agent run, leaving budget_exhausted=True. The reconcilable material-change
    # alert is a DIFFERENT tier, so it is never selected by the tier="reforecast" pass.
    _seed_paid(lg, 2)

    def failing_reforecast(_led, _warning):
        return None  # no real gated work → "failed", no ack

    result = run_warning_resolution(
        ledger=lg, tier="reforecast", reforecast_runner=failing_reforecast,
        cooldown=True, spend_cap=1, reconcile=True, now="2026-06-30T12:00:00",
    )

    # The cap halted the paid sweep…
    assert result["budget_exhausted"] is True
    assert result["spent"] == 1
    # …yet reconcile STILL ran and closed the condition-resolved alert.
    assert result["reconcile"] is not None
    assert result["reconcile"]["reconciled_count"] >= 1
    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert reconcilable.id not in open_now             # reconciled despite the budget halt
    # The paid backlog itself is untouched by reconcile (no fresh evidence/snapshot).
    assert len(_open_reason(lg, "evidence_stale_7d_plus")) == 2


# ---------------------------------------------------------------------------
# A failing alert is NOT re-attempted within its backoff window
# ---------------------------------------------------------------------------


def test_failing_alert_not_reattempted_within_backoff_window(tmp_path):
    lg = _ledger(tmp_path)
    _seed_paid(lg, 2)

    calls: list[str] = []

    def failing_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return None

    # Cycle 1 at noon: both stale alerts attempted, both fail -> stamped (attempt 1).
    c1 = run_warning_resolution(
        ledger=lg, tier="reforecast", reforecast_runner=failing_reforecast,
        cooldown=True, spend_cap=5, now="2026-06-30T12:00:00",
    )
    assert len(calls) == 2
    assert c1["spent"] == 2
    assert all(a.attempt_count == 1 for a in lg.list_alerts(unresolved_only=True))

    # Cycle 2 only 1h later: both alerts are inside the 24h backoff window, so they
    # are filtered out of selection entirely -> the paid runner is NOT re-invoked.
    c2 = run_warning_resolution(
        ledger=lg, tier="reforecast", reforecast_runner=failing_reforecast,
        cooldown=True, spend_cap=5, now="2026-06-30T13:00:00",
    )
    assert len(calls) == 2          # NO new spend
    assert c2["total"] == 0          # nothing eligible this cycle
    assert c2["spent"] == 0
    # Still OPEN, still attempt_count==1 (a cooldown is not an ack and did not bump).
    assert len(_open_reason(lg, "evidence_stale_7d_plus")) == 2
    assert all(a.attempt_count == 1 for a in lg.list_alerts(unresolved_only=True))

    # Cycle 3 once the 24h window has elapsed: eligible again -> retried, fail again,
    # and the backoff count grows (so the NEXT window doubles).
    c3 = run_warning_resolution(
        ledger=lg, tier="reforecast", reforecast_runner=failing_reforecast,
        cooldown=True, spend_cap=5, now="2026-07-01T13:00:00",
    )
    assert len(calls) == 4          # both retried
    assert c3["spent"] == 2
    assert all(a.attempt_count == 2 for a in lg.list_alerts(unresolved_only=True))


# ---------------------------------------------------------------------------
# A SUCCESSFUL paid attempt acks (drops out) and is never cooled down
# ---------------------------------------------------------------------------


def test_successful_attempt_acks_and_never_stamps_cooldown(tmp_path):
    lg = _ledger(tmp_path)
    _seed_paid(lg, 1)

    def good_reforecast(_led, warning):
        return {"question_id": warning.scope_ref, "status": "committed"}

    run_warning_resolution(
        ledger=lg, tier="reforecast", reforecast_runner=good_reforecast,
        cooldown=True, spend_cap=5, now="2026-06-30T12:00:00",
    )

    # Real gated work -> acked, drops out of the open backlog, no cooldown stamp.
    assert _open_reason(lg, "evidence_stale_7d_plus") == []
    acked = [a for a in lg.list_alerts(unresolved_only=False)][0]
    assert acked.acknowledged_at is not None
    assert acked.attempt_count == 0
    assert acked.last_attempted_at is None
