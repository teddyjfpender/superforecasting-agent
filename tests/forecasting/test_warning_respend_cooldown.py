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
