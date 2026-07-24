from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from forecasting import ForecastLedger
from forecasting.models import utc_now_iso


CRITERIA = "Resolves yes if the official result is published by 2027-12-31, otherwise no."


def _question(ledger: ForecastLedger, title: str):
    return ledger.create_question(
        title=title,
        resolution_criteria=CRITERIA,
        domain="forecastbench",
    )


def test_due_review_is_claimed_by_only_one_worker(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = _question(ledger, "Will the claimed review run once?")
    review = ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="daily",
        next_run_at="2026-01-01T00:00:00Z",
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_self_check(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return []

    monkeypatch.setattr(ledger, "self_check", slow_self_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            ledger.run_due_scheduled_reviews,
            now="2026-01-02T00:00:00Z",
            worker_id="worker-a",
        )
        assert started.wait(timeout=5)
        second = pool.submit(
            ledger.run_due_scheduled_reviews,
            now="2026-01-02T00:00:00Z",
            worker_id="worker-b",
        )
        second_result = second.result(timeout=5)
        release.set()
        first_result = first.result(timeout=5)

    assert calls == 1
    assert len(first_result) == 1
    assert second_result == []
    stored = ledger.get_scheduled_review(review["id"])
    assert stored["attempt_count"] == 1
    assert stored["lease_owner"] is None
    assert len(ledger.list_scheduled_review_runs(scheduled_review_id=review["id"])) == 1


def test_long_review_heartbeats_lease_and_cannot_be_reclaimed(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = _question(ledger, "Will a long review renew its lease?")
    review = ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="daily",
        next_run_at="2026-01-01T00:00:00Z",
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_self_check(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return []

    monkeypatch.setattr(ledger, "self_check", slow_self_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            ledger.run_due_scheduled_reviews,
            now=utc_now_iso(),
            worker_id="worker-a",
            lease_seconds=1,
        )
        assert started.wait(timeout=5)
        time.sleep(1.3)
        second = pool.submit(
            ledger.run_due_scheduled_reviews,
            now=utc_now_iso(),
            worker_id="worker-b",
            lease_seconds=1,
        )
        assert second.result(timeout=5) == []
        release.set()
        assert len(first.result(timeout=5)) == 1

    assert calls == 1
    assert ledger.get_scheduled_review(review["id"])["attempt_count"] == 1


def test_broken_review_is_recorded_and_does_not_abort_next(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    broken = _question(ledger, "Will the broken review be isolated?")
    healthy = _question(ledger, "Will the healthy review still run?")
    for question in (broken, healthy):
        ledger.schedule_review(
            scope_type="question",
            scope_ref=question.id,
            cadence="daily",
            next_run_at="2026-01-01T00:00:00Z",
        )

    def self_check(**kwargs):
        if kwargs.get("question_id") == broken.id:
            raise RuntimeError("source adapter exploded")
        return []

    monkeypatch.setattr(ledger, "self_check", self_check)
    results = ledger.run_due_scheduled_reviews(
        now="2026-01-02T00:00:00Z",
        worker_id="worker-a",
    )

    by_question = {item["review"]["scope_ref"]: item for item in results}
    assert by_question[broken.id]["run"]["status"] == "failed_retryable"
    assert by_question[broken.id]["run"]["metadata"]["review_errors"] == [
        "source adapter exploded"
    ]
    assert by_question[healthy.id]["run"]["status"] == "completed_no_change"


def test_unchanged_reviews_back_off_but_deadline_clamp_remains_available(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = _question(ledger, "Will unchanged reviews adapt their cadence?")
    review = ledger.schedule_review(
        scope_type="question",
        scope_ref=question.id,
        cadence="daily",
        next_run_at="2026-01-02T00:00:00Z",
        trigger_reason="adaptive-test",
    )
    monkeypatch.setattr(ledger, "self_check", lambda **_kwargs: [])

    for stamp in (
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
        "2026-01-04T00:00:00Z",
    ):
        ledger.run_due_scheduled_reviews(now=stamp)

    stored = ledger.get_scheduled_review(review["id"])
    assert stored["unchanged_streak"] == 3
    assert stored["adaptive_multiplier"] == 2
    assert stored["next_run_at"] == "2026-01-06T00:00:00Z"
