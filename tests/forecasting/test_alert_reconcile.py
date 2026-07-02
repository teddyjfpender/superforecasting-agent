"""Alert reconciliation: an open alert whose source-change was already consumed
(fresh evidence imported + a forecast committed after it fired) is auto-acked, so
the operator isn't buried in stale alerts — the alert-fatigue pain from feedback."""

from __future__ import annotations

import time

from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "alerts.db"))
    lg.initialize_schema()
    return lg


def test_reconcile_acks_consumed_alert_and_keeps_unconsumed_open(tmp_path):
    lg = _ledger(tmp_path)
    consumed_q = lg.create_question(title="Will the metric exceed target by close?", resolution_criteria=CRIT)
    open_q = lg.create_question(title="A second, untouched question on rates?", resolution_criteria=CRIT)

    a = lg.create_alert(
        severity="info", scope_type="question", scope_ref=consumed_q.id,
        reason="watched_source_changed:w1", recommended_action="review",
    )
    b = lg.create_alert(
        severity="info", scope_type="question", scope_ref=open_q.id,
        reason="watched_source_changed:w2", recommended_action="review",
    )

    time.sleep(1.1)  # evidence + snapshot must land strictly AFTER the alerts
    # consumed_q: the loop closed — evidence imported AND a forecast committed.
    lg.add_evidence(question_id=consumed_q.id, source_or_note="post-alert read", claim="value moved")
    lg.create_snapshot(question_id=consumed_q.id, probability_or_distribution=0.6, rationale="updated after source change")

    # dry-run previews without mutating.
    preview = lg.reconcile_alerts(dry_run=True)
    assert preview["reconciled_count"] == 1
    assert len(lg.list_alerts(unresolved_only=True)) == 2  # nothing acked yet

    result = lg.reconcile_alerts()
    assert [entry["id"] for entry in result["reconciled"]] == [a.id]
    still_open = lg.list_alerts(unresolved_only=True)
    assert [alert.id for alert in still_open] == [b.id]
    assert "no fresh evidence" in result["still_open"][0]["open_because"]

    # Idempotent: a reconciled ledger does nothing on a second pass.
    assert lg.reconcile_alerts()["reconciled_count"] == 0


def test_reconcile_score_clears_under_saturated_without_new_evidence(tmp_path, monkeypatch):
    """Wave 3 H4 regression: an under_saturated alert is SCORE-based, not evidence-based.
    It must auto-clear once the current snapshot's stored saturation score is at/above the
    bar, even when NO new evidence was imported (a non-evidence re-saturation). The generic
    evidence-AND-update reconcile would leave an evidence-free re-saturation stuck open."""
    import forecasting.hooks as hooks_mod

    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric exceed target by close?", resolution_criteria=CRIT)
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="baseline")
    score = ((snap.metadata or {}).get("saturation") or {}).get("score")
    assert isinstance(score, (int, float))

    a = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="under_saturated", recommended_action="raise saturation",
    )

    # Bar ABOVE the current score -> still under-saturated -> stays open (no evidence needed
    # for the decision either way; this is purely a score comparison).
    monkeypatch.setattr(hooks_mod, "sweep_alert_threshold", lambda *a, **k: float(score) + 10.0)
    r_open = lg.reconcile_alerts()
    assert r_open["reconciled_count"] == 0
    assert "still below the bar" in r_open["still_open"][0]["open_because"]

    # Bar BELOW the current score -> re-saturated -> clears WITHOUT importing any evidence.
    monkeypatch.setattr(hooks_mod, "sweep_alert_threshold", lambda *a, **k: max(0.0, float(score) - 10.0))
    r_clear = lg.reconcile_alerts()
    assert [entry["id"] for entry in r_clear["reconciled"]] == [a.id]
    assert lg.list_alerts(unresolved_only=True) == []


def test_reconcile_needs_both_evidence_and_update(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the indicator cross the line by close?", resolution_criteria=CRIT)
    lg.create_alert(
        severity="info", scope_type="question", scope_ref=q.id,
        reason="watched_source_changed:w", recommended_action="review",
    )
    time.sleep(1.1)
    # Evidence imported, but NO forecast update committed -> alert must stay open.
    lg.add_evidence(question_id=q.id, source_or_note="post-alert read", claim="value moved")
    result = lg.reconcile_alerts()
    assert result["reconciled_count"] == 0
    assert "no forecast update" in result["still_open"][0]["open_because"]
