"""Scheduled-review idempotency + dedupe: a lazy prompter (or the agent re-running
an onboarding step) must not be able to spawn duplicate weekly reviews that each
fire independently — the exact pain reported in the first feedback pass."""

from __future__ import annotations

import sqlite3

import pytest

from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "sched.db"))
    lg.initialize_schema()
    return lg


def _question(lg) -> str:
    # domain="forecastbench" is auto-review-INELIGIBLE, so create_question adds no
    # default weekly review. These tests assert schedule_review idempotency/dedupe
    # from a clean slate, so the question must start with zero scheduled reviews.
    return lg.create_question(
        title="Will the metric exceed target by close?",
        resolution_criteria=CRIT,
        domain="forecastbench",
    ).id


def _enabled(lg) -> list[dict]:
    return [r for r in lg.list_scheduled_reviews() if r["enabled"]]


def test_schedule_review_is_idempotent_on_scope_cadence_reason(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly")
    b = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly")
    assert a["id"] == b["id"], "re-scheduling the same scope+cadence+reason must reuse the row"
    assert len(lg.list_scheduled_reviews()) == 1

    # A different cadence is a genuinely different schedule.
    c = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="daily")
    assert c["id"] != a["id"]
    assert len(lg.list_scheduled_reviews()) == 2


def test_schedule_review_upserts_settings_on_reschedule(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly", stale_days=7, auto_score=False)
    # Re-scheduling the same key with NEW settings must APPLY them (not silently
    # drop them), while still avoiding a duplicate row.
    b = lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="weekly", stale_days=21, auto_score=True, auto_postmortem=True
    )
    assert a["id"] == b["id"]
    assert len(lg.list_scheduled_reviews()) == 1
    row = lg.get_scheduled_review(a["id"])
    assert row["stale_days"] == 21
    assert row["auto_score"] == 1
    assert row["auto_postmortem"] == 1


def test_schedule_review_reactivates_a_disabled_duplicate(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    a = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly")
    lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly", enabled=False)
    # Still one row, now disabled — no duplicate was created.
    assert len(lg.list_scheduled_reviews()) == 1
    assert lg.get_scheduled_review(a["id"])["enabled"] == 0
    # Re-scheduling re-activates it rather than spawning a new one.
    lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly")
    assert len(lg.list_scheduled_reviews()) == 1
    assert lg.get_scheduled_review(a["id"])["enabled"] == 1


def test_database_rejects_new_active_duplicates(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    keep = lg.schedule_review(scope_type="question", scope_ref=qid, cadence="weekly")
    # The partial unique index is the final authority under concurrent writers.
    with lg._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_reviews (id, scope_type, scope_ref, cadence, stale_days, "
                "next_run_at, trigger_reason, enabled) VALUES (?,?,?,?,?,?,?,1)",
                ("sr_duplicate", "question", qid, "weekly", 7, "2026-07-01T00:00:00Z", "scheduled"),
            )
    assert [row["id"] for row in _enabled(lg)] == [keep["id"]]


def test_mark_question_review_due_creates_then_rearms(tmp_path):
    # The desk "run update" shortcut. With no schedule row it creates one due-now;
    # with an existing row it re-arms next_run_at to now (no duplicate).
    lg = _ledger(tmp_path)
    qid = _question(lg)
    r1 = lg.mark_question_review_due(qid)
    assert r1["queued"] and r1["scheduled"] == "created"
    assert lg.next_review_by_question()[qid]["next_run_at"] == r1["next_run_at"]
    before = len(_enabled(lg))
    r2 = lg.mark_question_review_due(qid)
    assert r2["scheduled"] == "rearmed"
    assert len(_enabled(lg)) == before  # re-arm, not a duplicate
