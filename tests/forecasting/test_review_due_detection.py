"""Cheap due-detection reads that back the gateway due-sweeper.

The Desk shows a review as "due now" the instant its next_run_at passes; the
gateway sweeper decides whether to act using these two indexed reads (a COUNT and
a MIN) rather than materializing every row. These tests pin their semantics.
"""

from __future__ import annotations

from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "due.db"))
    lg.initialize_schema()
    return lg


def _question(lg) -> str:
    # domain="forecastbench" is auto-review-INELIGIBLE, so create_question adds no
    # default weekly review — the tests start from zero scheduled reviews.
    return lg.create_question(
        title="Will the metric exceed target by close?",
        resolution_criteria=CRIT,
        domain="forecastbench",
    ).id


def test_count_due_only_counts_enabled_and_past(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    now = "2026-07-02T12:00:00Z"

    # Nothing scheduled yet → nothing due.
    assert lg.count_due_scheduled_reviews(now=now) == 0
    assert lg.next_scheduled_review_at() is None

    # One in the past (DUE), one in the future (NOT due).
    lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="daily",
        next_run_at="2026-07-02T09:00:00Z", trigger_reason="scheduled",
    )
    lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="weekly",
        next_run_at="2026-07-09T09:00:00Z", trigger_reason="horizon",
    )
    assert lg.count_due_scheduled_reviews(now=now) == 1
    # The soonest enabled next_run_at (the past one) — a past value means overdue.
    assert lg.next_scheduled_review_at() == "2026-07-02T09:00:00Z"


def test_count_due_ignores_disabled_rows(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    now = "2026-07-02T12:00:00Z"
    row = lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="daily",
        next_run_at="2026-07-02T09:00:00Z", trigger_reason="scheduled",
    )
    assert lg.count_due_scheduled_reviews(now=now) == 1

    # Disable it — it must vanish from BOTH the due count and the soonest read.
    with lg._connect() as conn:
        conn.execute("UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?", (row["id"],))
    assert lg.count_due_scheduled_reviews(now=now) == 0
    assert lg.next_scheduled_review_at() is None


def test_next_scheduled_review_at_returns_soonest(tmp_path):
    lg = _ledger(tmp_path)
    qid = _question(lg)
    lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="weekly",
        next_run_at="2026-08-01T00:00:00Z", trigger_reason="scheduled",
    )
    lg.schedule_review(
        scope_type="question", scope_ref=qid, cadence="daily",
        next_run_at="2026-07-15T00:00:00Z", trigger_reason="horizon",
    )
    assert lg.next_scheduled_review_at() == "2026-07-15T00:00:00Z"
