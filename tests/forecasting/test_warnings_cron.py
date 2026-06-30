"""`cron_runner.run_warning_resolution` (slice 3a): the factored, GATED,
INTERRUPTIBLE warning-resolution phase the CLI automode, the gateway background
job, and the agent tool all share.

Pins: dry-run is pure (no writes, plan only), real runs ack ONLY genuine gated
work (a bookkeeping notice) and leave un-fixable alerts OPEN, progress streams
per phase, and a cooperative cancel stops the sweep cleanly without writing.
"""

from __future__ import annotations

from forecasting.cron_runner import build_warning_runners, run_warning_resolution
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "w.db"))
    lg.initialize_schema()
    return lg


def _seed_alerts(lg: ForecastLedger) -> dict[str, str]:
    ids: dict[str, str] = {}
    ids["postmortem"] = lg.create_alert(
        severity="high", scope_type="question", scope_ref="fq_a",
        reason="postmortem_due", recommended_action="Run a postmortem.").id
    ids["material"] = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_c",
        reason="watched_source_changed:src1", recommended_action="Recheck the source.").id
    ids["no_auto"] = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_d",
        reason="domain_error_profile_applies:politics", recommended_action="Human review.").id
    ids["reforecast"] = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_e",
        reason="evidence_stale_7d_plus", recommended_action="Re-forecast.").id
    ids["bookkeeping"] = lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_f",
        reason="autopilot_enabled", recommended_action="Informational.").id
    return ids


def test_dry_run_is_pure_and_plans_by_priority(tmp_path):
    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    events: list[dict] = []
    summary = run_warning_resolution(
        ledger=lg, dry_run=True, progress=events.append
    )

    assert summary["dry_run"] is True
    assert summary["cancelled"] is False
    assert summary["total"] == 5
    assert summary["processed"] == 5
    assert summary["reconcile"] is None
    by_reason = {e["reason"]: e for e in summary["results"]}
    assert by_reason["postmortem_due"]["planned"] == "would_run"
    assert by_reason["watched_source_changed:src1"]["planned"] == "would_run"
    assert by_reason["domain_error_profile_applies:politics"]["planned"] == "surfaced"
    # No reforecast runner injected -> would_skip (NOT bare-acked).
    assert by_reason["evidence_stale_7d_plus"]["planned"] == "would_skip"
    assert by_reason["autopilot_enabled"]["planned"] == "would_acknowledge"

    # Streamed phases: a start, one per alert, and a done.
    phases = [e["phase"] for e in events]
    assert phases[0] == "start"
    assert phases[-1] == "done"
    assert phases.count("alert") == 5

    # The load-bearing invariant: a dry run writes NOTHING.
    assert len(lg.list_alerts(unresolved_only=True)) == 5


def test_real_run_acks_only_genuine_gated_work(tmp_path):
    """No reforecast runner; the questions don't exist so autopilot/score fail.
    The ONLY alert that should close is the bookkeeping notice — everything else
    stays OPEN (never bare-acked to drop the count)."""
    lg = _ledger(tmp_path)
    ids = _seed_alerts(lg)

    summary = run_warning_resolution(ledger=lg, reconcile=False)

    assert summary["dry_run"] is False
    by_id = {r["alert_id"]: r for r in summary["results"]}
    assert by_id[ids["bookkeeping"]]["status"] == "resolved"
    assert by_id[ids["bookkeeping"]]["acknowledged"] is True
    assert by_id[ids["no_auto"]]["status"] == "surfaced"
    assert by_id[ids["reforecast"]]["status"] == "skipped"
    # The postmortem/material runners run against non-existent questions -> they
    # perform no real work (raise or return falsy) -> left OPEN.
    assert by_id[ids["postmortem"]]["status"] in {"failed", "skipped"}
    assert by_id[ids["material"]]["status"] in {"failed", "skipped"}

    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert ids["bookkeeping"] not in open_now  # the only one acked
    assert ids["no_auto"] in open_now
    assert ids["reforecast"] in open_now
    assert ids["postmortem"] in open_now
    assert ids["material"] in open_now


def test_cancel_stops_cleanly_without_writing(tmp_path):
    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    summary = run_warning_resolution(
        ledger=lg, reconcile=True, should_cancel=lambda: True
    )

    assert summary["cancelled"] is True
    assert summary["processed"] == 0
    # Cancelled before the first alert -> nothing acked, nothing reconciled.
    assert summary["reconcile"] is None
    assert len(lg.list_alerts(unresolved_only=True)) == 5


def test_limit_and_scope_bound_the_sweep(tmp_path):
    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    only_one = run_warning_resolution(ledger=lg, dry_run=True, limit=1)
    assert only_one["total"] == 1

    scoped = run_warning_resolution(ledger=lg, dry_run=True, scope="fq_f")
    assert scoped["total"] == 1
    assert scoped["results"][0]["reason"] == "autopilot_enabled"


def test_tier_filter_bounds_the_sweep(tmp_path):
    """`run_warning_resolution(tier=...)` threads the per-tier kind filter into
    select_open_warnings so a bulk pass only considers that tier's backlog."""
    lg = _ledger(tmp_path)
    _seed_alerts(lg)  # one each: postmortem, material, no_auto, reforecast, bookkeeping

    # The reforecast tier sees ONLY the REFORECAST alert.
    refo = run_warning_resolution(ledger=lg, dry_run=True, tier="reforecast")
    assert refo["total"] == 1
    assert refo["results"][0]["reason"] == "evidence_stale_7d_plus"

    # The free tier excludes REFORECAST and NO_AUTO (4 of the 5 seeded, minus the
    # one reforecast and the one no_auto -> postmortem + material + bookkeeping).
    free = run_warning_resolution(ledger=lg, dry_run=True, tier="free")
    free_reasons = {r["reason"] for r in free["results"]}
    assert "evidence_stale_7d_plus" not in free_reasons
    assert "domain_error_profile_applies:politics" not in free_reasons
    assert free["total"] == 3


def test_kinds_filter_bounds_the_sweep(tmp_path):
    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    only = run_warning_resolution(ledger=lg, dry_run=True, kinds=["postmortem"])
    assert only["total"] == 1
    assert only["results"][0]["reason"] == "postmortem_due"


def test_build_warning_runners_leaves_reforecast_unwired_by_default(tmp_path):
    lg = _ledger(tmp_path)
    runners = build_warning_runners(lg)
    # The non-LLM gated runners are wired; the LLM reforecast pass is opt-in.
    assert runners.reforecast_runner is None
    assert runners.autopilot_runner is not None
    assert runners.score_runner is not None        # SCORE — score_question
    assert runners.postmortem_runner is not None   # POSTMORTEM — create_postmortem


def test_reconcile_never_bare_acks_a_still_valid_no_auto_alert(tmp_path):
    """End-of-sweep reconcile may ack source-driven alerts the operator worked
    past (fresh evidence + a new snapshot landed after them), but it must NEVER
    auto-ack a NO_AUTO human-judgment alert — a new forecast does not address an
    invalidated assumption, so closing it would be the very bare-ack the
    dispatcher forbids. Pins the NO_AUTO exclusion in reconcile_alerts."""
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the index close above target in 2026?",
        resolution_criteria="Resolves yes if the official index closes above target; otherwise no.",
    )

    # Two open alerts: one reforecast class (source-driven, legitimately
    # reconcilable) and one NO_AUTO class. Backdate both well into the past so the
    # evidence + snapshot below are unambiguously AFTER them (create_alert stamps
    # "now" at second granularity, so without backdating the comparison would tie).
    reforecast_alert = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="evidence_stale_7d_plus", recommended_action="Re-forecast.")
    no_auto_alert = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="assumption_invalidated:as_1", recommended_action="Human review.")
    with lg._connect() as conn:
        conn.execute(
            "UPDATE alert_events SET created_at = ? WHERE id IN (?, ?)",
            ("2020-01-01T00:00:00Z", reforecast_alert.id, no_auto_alert.id),
        )

    # Fresh evidence + a new forecast snapshot, both well after the backdated
    # alerts, so reconcile's (evidence_after AND update_after) condition holds.
    lg.add_evidence(question_id=q.id, source_or_note="A fresh note")
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.6, rationale="updated",
        require_panel=False)

    result = lg.reconcile_alerts()

    reconciled_ids = {r["id"] for r in result["reconciled"]}
    still_open_ids = {s["id"] for s in result["still_open"]}
    # The source-driven alert is reconciled; the NO_AUTO alert stays OPEN.
    assert reforecast_alert.id in reconciled_ids
    assert no_auto_alert.id in still_open_ids
    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert no_auto_alert.id in open_now            # never bare-acked
    assert reforecast_alert.id not in open_now
