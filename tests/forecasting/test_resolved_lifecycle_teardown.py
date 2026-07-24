from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.models import ValidationError, utc_now_iso


def test_confirmed_resolution_transactionally_stops_question_work(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will the release ship?",
        resolution_criteria="Resolves yes when the official release ships.",
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="manual release tracker",
        source_type="manual",
    )
    review = ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="weekly",
    )
    alert = ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question.id,
        reason="review_due",
        recommended_action="Review it.",
    )
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO autopilot_policies (
                id, question_id, enabled, mode, cadence, scheduled_review_id,
                materiality_policy, guardrail_policy, notification_policy,
                created_at, updated_at
            ) VALUES (?, ?, 1, 'propose', 'weekly', ?, '{}', '{}', '{}', ?, ?)
            """,
            ("ap_test", question.id, review["id"], now, now),
        )
        conn.execute(
            """
            INSERT INTO forecast_update_proposals (
                id, question_id, proposed_probability_or_distribution,
                rationale, created_at
            ) VALUES (?, ?, '0.6', 'pending update', ?)
            """,
            ("fup_test", question.id, now),
        )

    ledger.resolve_question(question_id=question.id, outcome="yes", auto_score=False)

    assert ledger.get_question(question.id).status == "resolved"
    assert ledger.get_watched_source(watch["id"])["status"] == "inactive"
    assert ledger.get_scheduled_review(review["id"])["enabled"] == 0
    assert ledger.get_autopilot_policy("ap_test")["enabled"] is False
    assert ledger.get_forecast_update_proposal("fup_test")["status"] == "rejected"
    closed_alert = ledger.get_alert(alert.id)
    assert closed_alert.acknowledged_at is not None
    assert closed_alert.ack_note == "auto_close:question_resolved"
    assert closed_alert.disposition == "resolved_by_resolution"
    tasks = ledger.list_operational_tasks(status="pending")
    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "finalize_resolution"


def test_proposed_resolution_does_not_stop_question_work(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will the release ship?",
        resolution_criteria="Resolves yes when the official release ships.",
    )
    watch = ledger.add_watched_source(
        scope_type="question",
        scope_ref=question.id,
        source="manual release tracker",
        source_type="manual",
    )

    ledger.resolve_question(
        question_id=question.id,
        outcome="yes",
        resolution_status="proposed",
        criteria_satisfied=False,
        auto_score=False,
    )

    assert ledger.get_watched_source(watch["id"])["status"] == "active"


def test_resolution_followup_scores_and_postmortems_exactly_once(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will resolution follow-up be idempotent?",
        resolution_criteria="Resolves yes when the result is confirmed.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Pre-resolution estimate.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes", auto_score=False)

    first = ledger.run_resolution_finalization_tasks(owner="worker-a")
    second = ledger.run_resolution_finalization_tasks(owner="worker-b")

    assert len(first) == 1
    assert first[0]["status"] == "completed"
    assert first[0]["disposition"] == "resolved_by_resolution"
    assert second == []
    assert len([score for score in ledger.list_scores() if score.question_id == question.id]) == 1
    assert len(ledger.list_postmortems(question_id=question.id)) == 1


def test_warning_tick_drains_resolution_finalization_without_manual_worker(tmp_path):
    from forecasting.cron_runner import run_warning_automode

    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will the recurring worker finalize a resolution?",
        resolution_criteria="Resolves yes when the result is confirmed.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Pre-resolution estimate.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes", auto_score=False)

    # Keep the generated task due regardless of the wall clock running this test.
    result = run_warning_automode(
        ledger=ledger,
        state_path=tmp_path / "worker-state.json",
        now="2099-07-21T12:00:00Z",
    )

    assert len(result["resolution_finalization"]) == 1
    assert result["resolution_finalization"][0]["status"] == "completed"
    assert len(ledger.list_scores()) == 1
    assert len(ledger.list_postmortems(question_id=question.id)) == 1


def test_resolved_question_rejects_new_snapshot_without_explicit_backfill(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will post-resolution forecast writes be rejected?",
        resolution_criteria="Resolves yes if the write is rejected after confirmation.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="Pre-resolution forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    with pytest.raises(ValidationError, match="after resolution"):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.7,
            rationale="Late write.",
        )

    historical = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.55,
        rationale="Explicit historical correction backfill.",
        set_current=False,
        allow_resolved_backfill=True,
    )
    assert historical.question_id == question.id
