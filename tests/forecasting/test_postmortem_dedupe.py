"""SLICE 5 (b): self_check's postmortem_due alert must dedupe against an already-open
alert for the same (scope_ref, reason) — mirroring the trigger_fired path — so
re-running self_check before reconcile cannot accumulate duplicate postmortem_due
alerts for the same resolved question."""

from __future__ import annotations

from forecasting import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "f.db"))
    ledger.initialize_schema()
    return ledger


def _resolved_scored_question(ledger, *, title: str):
    """A confirmed-resolved + auto-scored binary question with NO postmortem yet —
    exactly the state that makes self_check raise a postmortem_due alert."""
    q = ledger.create_question(
        title=title,
        resolution_criteria="Resolves yes if the official index closes above target; otherwise no.",
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.6,
        rationale="committed forecast",
        require_panel=False,
    )
    ledger.resolve_question(question_id=q.id, outcome="yes")  # confirmed + auto-scores
    return q


def _open_postmortem_alerts(ledger, question_id):
    return [
        a
        for a in ledger.list_alerts(unresolved_only=True)
        if a.scope_ref == question_id
        and a.reason in ("postmortem_due", "high_impact_postmortem_due")
    ]


def test_self_check_raises_postmortem_due_once(tmp_path):
    ledger = _ledger(tmp_path)
    q = _resolved_scored_question(ledger, title="Will the index close above target in 2026?")

    ledger.self_check(question_id=q.id)
    assert len(_open_postmortem_alerts(ledger, q.id)) == 1


def test_self_check_does_not_accumulate_duplicate_postmortem_due(tmp_path):
    ledger = _ledger(tmp_path)
    q = _resolved_scored_question(ledger, title="Will the index close above target in 2026?")

    # Run self_check repeatedly BEFORE any reconcile / postmortem is written.
    ledger.self_check(question_id=q.id)
    ledger.self_check(question_id=q.id)
    ledger.self_check(question_id=q.id)

    # Exactly one open postmortem_due alert — the dedupe guard held.
    assert len(_open_postmortem_alerts(ledger, q.id)) == 1


def test_dedupe_re_surfaces_after_acknowledge(tmp_path):
    """Acking the open alert clears the dedupe guard, so a genuinely-still-due
    postmortem re-surfaces on the next self_check (the signal is never lost)."""
    ledger = _ledger(tmp_path)
    q = _resolved_scored_question(ledger, title="Will the index close above target in 2026?")

    ledger.self_check(question_id=q.id)
    open_alerts = _open_postmortem_alerts(ledger, q.id)
    assert len(open_alerts) == 1
    ledger.acknowledge_alert(open_alerts[0].id)

    # Still no postmortem written → the condition still holds → re-surface a fresh one.
    ledger.self_check(question_id=q.id)
    assert len(_open_postmortem_alerts(ledger, q.id)) == 1


def test_dedupe_is_per_question(tmp_path):
    ledger = _ledger(tmp_path)
    q1 = _resolved_scored_question(ledger, title="Q1: index above target?")
    q2 = _resolved_scored_question(ledger, title="Q2: rate above target?")

    ledger.self_check()
    ledger.self_check()

    assert len(_open_postmortem_alerts(ledger, q1.id)) == 1
    assert len(_open_postmortem_alerts(ledger, q2.id)) == 1
