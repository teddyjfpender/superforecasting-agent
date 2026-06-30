"""Slice 7 — the continuous warning-automode cron orchestration.

Pins the load-bearing split: the FREE tier sweeps every cycle UNBUDGETED at zero
token spend (the injected paid closures are never invoked there), while the PAID
tier (reforecast + evidence_collection) is BOUNDED two ways — a per-cycle
agent-run budget (the limit cap) AND a minimum interval between paid passes
(tracked in a state file). The no-bare-ack invariant is preserved throughout:
the paid runner only acks an alert when it returns truthy gated work.
"""

from __future__ import annotations

from forecasting.cron_runner import run_warning_automode
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "w.db"))
    lg.initialize_schema()
    return lg


def _seed(lg: ForecastLedger, *, n_free: int, n_paid: int) -> None:
    # FREE-tier alerts: bookkeeping notices (acked by the non-LLM close-out).
    for i in range(n_free):
        lg.create_alert(
            severity="info", scope_type="question", scope_ref=f"fq_free_{i}",
            reason="autopilot_enabled", recommended_action="Informational.")
    # PAID-tier alerts: staleness -> REFORECAST (needs the LLM update pass).
    for i in range(n_paid):
        lg.create_alert(
            severity="warning", scope_type="question", scope_ref=f"fq_paid_{i}",
            reason="evidence_stale_7d_plus", recommended_action="Re-forecast.")


def test_free_tier_unbudgeted_paid_tier_respects_per_cycle_cap(tmp_path):
    lg = _ledger(tmp_path)
    _seed(lg, n_free=5, n_paid=4)

    calls: list[str] = []

    def fake_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return {"question_id": warning.scope_ref, "status": "committed"}

    state_path = tmp_path / "automode_state.json"
    result = run_warning_automode(
        ledger=lg,
        reforecast_runner=fake_reforecast,
        paid_budget=2,
        paid_min_interval_hours=6.0,
        state_path=state_path,
        now="2026-06-30T12:00:00",
    )

    # FREE tier ran UNBUDGETED: all 5 bookkeeping notices closed this cycle.
    free = result["free"]
    assert free["total"] == 5
    assert free["processed"] == 5
    assert free["tally"].get("resolved") == 5

    # PAID tier ran but was CAPPED at the budget (2 of the 4 stale alerts), so the
    # expensive agent runner fired at most `budget` times.
    assert result["paid_ran"] is True
    paid = result["paid"]
    assert paid["total"] == 2  # tier filter + limit cap applied before limit
    assert paid["processed"] == 2
    assert len(calls) == 2

    # The 2 capped paid alerts were acked (real gated work); the other 2 stay OPEN.
    open_reasons = [a.reason for a in lg.list_alerts(unresolved_only=True)]
    assert open_reasons.count("evidence_stale_7d_plus") == 2
    assert "autopilot_enabled" not in open_reasons

    # The paid run stamped the state file so the next cycle's interval gate sees it.
    assert result["last_paid_run_at"] == "2026-06-30T12:00:00"


def test_min_interval_gate_blocks_paid_but_free_still_runs(tmp_path):
    lg = _ledger(tmp_path)
    _seed(lg, n_free=3, n_paid=3)

    calls: list[str] = []

    def fake_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return {"question_id": warning.scope_ref, "status": "committed"}

    state_path = tmp_path / "automode_state.json"

    # Cycle 1 at noon: paid runs (no prior run on record).
    run_warning_automode(
        ledger=lg, reforecast_runner=fake_reforecast, paid_budget=1,
        paid_min_interval_hours=6.0, state_path=state_path, now="2026-06-30T12:00:00",
    )
    assert len(calls) == 1

    _seed(lg, n_free=2, n_paid=0)  # add fresh free work for cycle 2

    # Cycle 2 only 1h later: the 6h interval gate BLOCKS the paid tier, but the
    # free tier still runs unbudgeted.
    result2 = run_warning_automode(
        ledger=lg, reforecast_runner=fake_reforecast, paid_budget=1,
        paid_min_interval_hours=6.0, state_path=state_path, now="2026-06-30T13:00:00",
    )
    assert result2["paid_ran"] is False
    assert "min interval" in (result2["paid_skipped_reason"] or "")
    assert len(calls) == 1  # NO new paid agent run
    assert result2["free"]["processed"] >= 2  # free tier still cleared its backlog


def test_force_paid_overrides_the_interval_gate(tmp_path):
    lg = _ledger(tmp_path)
    _seed(lg, n_free=0, n_paid=2)

    calls: list[str] = []

    def fake_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return {"question_id": warning.scope_ref, "status": "committed"}

    state_path = tmp_path / "automode_state.json"
    run_warning_automode(
        ledger=lg, reforecast_runner=fake_reforecast, paid_budget=5,
        paid_min_interval_hours=6.0, state_path=state_path, now="2026-06-30T12:00:00",
    )
    assert len(calls) == 2
    _seed(lg, n_free=0, n_paid=2)
    result = run_warning_automode(
        ledger=lg, reforecast_runner=fake_reforecast, paid_budget=5,
        paid_min_interval_hours=6.0, state_path=state_path, now="2026-06-30T12:05:00",
        force_paid=True,
    )
    assert result["paid_ran"] is True
    assert len(calls) == 4  # forced through the gate


def test_no_agent_runners_runs_free_only_never_bare_acks_paid(tmp_path):
    lg = _ledger(tmp_path)
    _seed(lg, n_free=2, n_paid=3)

    state_path = tmp_path / "automode_state.json"
    # No reforecast_runner / evidence_search injected -> paid tier has nothing to
    # spend, so it is skipped and the stale alerts stay OPEN (never bare-acked).
    result = run_warning_automode(
        ledger=lg, paid_budget=3, paid_min_interval_hours=0.0,
        state_path=state_path, now="2026-06-30T12:00:00",
    )
    assert result["paid_ran"] is False
    assert "no agent runners" in (result["paid_skipped_reason"] or "")
    assert result["free"]["tally"].get("resolved") == 2
    open_reasons = [a.reason for a in lg.list_alerts(unresolved_only=True)]
    assert open_reasons.count("evidence_stale_7d_plus") == 3  # all paid alerts OPEN


def test_zero_budget_disables_paid_tier(tmp_path):
    lg = _ledger(tmp_path)
    _seed(lg, n_free=1, n_paid=2)

    calls: list[str] = []

    def fake_reforecast(_led, warning):
        calls.append(warning.scope_ref)
        return {"status": "committed"}

    state_path = tmp_path / "automode_state.json"
    result = run_warning_automode(
        ledger=lg, reforecast_runner=fake_reforecast, paid_budget=0,
        paid_min_interval_hours=0.0, state_path=state_path, now="2026-06-30T12:00:00",
    )
    assert result["paid_ran"] is False
    assert "budget is 0" in (result["paid_skipped_reason"] or "")
    assert len(calls) == 0
