from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError


def test_learned_error_review_persists_reasoning_before_closing_alerts(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will learned-error reviews be auditable?",
        resolution_criteria="Resolves yes if review reasoning is durable.",
        domain="macro",
        topics=["inflation"],
    )
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="Baseline with evidence and an outside view.",
    )
    profile_id = "dep_fixture"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO domain_error_profiles (
                id, domain, topic, question_type, sample_count,
                calibration_summary, recurring_errors, recommended_adjustments,
                updated_at
            ) VALUES (?, 'macro', 'inflation', 'binary', 1, ?, ?, ?, ?)
            """,
            (
                profile_id,
                json.dumps({"count": 1}),
                json.dumps(["base_rate_error"]),
                json.dumps(["Refresh the outside view."]),
                "2026-05-01T00:00:00Z",
            ),
        )
    alert = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason=f"domain_error_profile_applies:{profile_id}",
        recommended_action="Review the learned error profile.",
        now="2026-05-01T00:01:00Z",
    )

    result = ledger.review_learned_error_alerts(
        question.id,
        reviewed_by="reviewer-a",
        assessment=(
            "The current outside view was compared with the profile; no probability "
            "change is warranted because the evidence remains balanced."
        ),
        now="2026-05-01T00:02:00Z",
    )

    assert result["decision"] == "reviewed_no_change"
    assert result["closed_alert_ids"] == [alert.id]
    run = result["model_run"]
    assert run["model_type"] == "learned_error_profile_review"
    assert run["inputs"]["current_forecast_id"] == snapshot.forecast_id
    assert run["inputs"]["profile_ids"] == [profile_id]
    closed = ledger.get_alert(alert.id)
    assert closed.disposition == "reviewed_no_change"
    assert closed.ack_note == f"learned_error_review:{run['id']}:reviewed_no_change"


def test_learned_error_review_requires_substance_and_can_open_follow_up(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will a material learned error create follow-up work?",
        resolution_criteria="Resolves yes if the review creates a durable follow-up.",
        domain="macro",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline.",
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO domain_error_profiles (
                id, domain, question_type, sample_count, calibration_summary,
                recurring_errors, recommended_adjustments, updated_at
            ) VALUES ('dep_fixture', 'macro', 'binary', 1, '{}', '[]', '[]', ?)
            """,
            ("2026-05-01T00:00:00Z",),
        )
    ledger.create_alert(
        severity="warning",
        scope_type="question",
        scope_ref=question.id,
        reason="domain_error_profile_applies:dep_fixture",
        recommended_action="Review it.",
    )
    with pytest.raises(ValidationError, match="substantive"):
        ledger.review_learned_error_alerts(
            question.id, reviewed_by="reviewer-a", assessment="too short"
        )

    result = ledger.review_learned_error_alerts(
        question.id,
        reviewed_by="reviewer-a",
        assessment="The outside view is missing and the forecast must be refreshed.",
        decision="update_required",
    )

    follow_up = ledger.get_alert(result["follow_up_alert_id"])
    assert follow_up.reason.startswith("learned_error_update_required:")
    assert follow_up.acknowledged_at is None


def test_bounded_worker_persists_review_artifact_and_routes_required_update(tmp_path):
    from forecasting.learned_error_worker import run_learned_error_reviews

    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = ledger.create_question(
        title="Will the learned-error worker close the pilot review loop?",
        resolution_criteria="Resolves yes if review reasoning is persisted.",
        domain="macro",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.5,
        rationale="Baseline without the relevant outside view.",
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO domain_error_profiles (
                id, domain, question_type, sample_count, calibration_summary,
                recurring_errors, recommended_adjustments, updated_at
            ) VALUES ('dep_worker', 'macro', 'binary', 3, '{}', ?, ?, ?)
            """,
            (
                json.dumps(["base_rate_error"]),
                json.dumps(["Refresh the outside view."]),
                "2026-07-21T10:00:00Z",
            ),
        )
    original = ledger.create_alert(
        severity="high",
        scope_type="question",
        scope_ref=question.id,
        reason="domain_error_profile_applies:dep_worker",
        recommended_action="Review the learned error.",
    )

    results = run_learned_error_reviews(
        ledger,
        owner="review-worker",
        limit=1,
        reviewer=lambda payload: {
            "assessment": (
                "The current rationale omits the profile's base-rate correction, "
                "so a fresh forecast is required."
            ),
            "decision": "update_required",
        },
    )

    assert results[0]["status"] == "reviewed"
    assert ledger.get_alert(original.id).acknowledged_at is not None
    follow_ups = [
        alert
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.reason.startswith("learned_error_update_required:")
    ]
    assert len(follow_ups) == 1
    assert ledger.list_model_runs(question_id=question.id)[-1]["model_type"] == "learned_error_profile_review"
