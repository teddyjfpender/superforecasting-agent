"""Tests for the question machine-readiness composite (the operator's hidden-parameter
visibility) + its batched ledger reads + the workspace-payload wiring.

The operator can't see the machine-workability parameters a question carries (watched
sources, structured components, reference classes, executable triggers, an enabled
review schedule, close_time/impact/resolution). This lens scores that readiness 0-100
with EXACT per-gap fix hints, computed BATCHED for the whole book — no per-question
N+1. These tests pin the scorer (each dimension pos/neg), the batched-read correctness,
the absence of per-row ledger calls in the payload build, and the added timing budget.
"""

from __future__ import annotations

import time

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.readiness_lens import (
    READINESS_WEIGHTS,
    build_question_readiness,
    has_executable_trigger,
    question_machine_readiness,
)


# ── the pure scorer ───────────────────────────────────────────────────────────


def _full_kwargs() -> dict:
    """Every dimension satisfied → score 100, no gaps."""
    return dict(
        question_id="fq_x",
        watch_count=2,
        has_components=True,
        ref_class_count=1,
        update_triggers=[
            {"mechanism": "CPI print", "source_ref": "fred:CPIAUCSL", "operator": ">", "threshold": 3.0}
        ],
        has_scheduled_review=True,
        close_time="2026-12-31T00:00:00Z",
        impact="high",
        resolution_rule="Resolves yes if CPI YoY exceeds 3%.",
    )


def test_scorer_all_present_is_100_no_gaps():
    result = question_machine_readiness(**_full_kwargs())
    assert result["score"] == 100
    assert result["gaps"] == []
    assert sum(READINESS_WEIGHTS.values()) == 100  # weights are a genuine 0-100 scale


def test_scorer_all_missing_is_0_and_every_gap():
    result = question_machine_readiness(
        question_id="fq_x",
        watch_count=0,
        has_components=False,
        ref_class_count=0,
        update_triggers=[],
        has_scheduled_review=False,
        close_time=None,
        impact=None,
        resolution_rule=None,
    )
    assert result["score"] == 0
    assert {g["key"] for g in result["gaps"]} == set(READINESS_WEIGHTS)
    for gap in result["gaps"]:
        assert gap["label"]
        assert "or a T task" in gap["fix_hint"]  # every gap offers the free-text fix loop


# The value that FLIPS each dimension off (the rest stay satisfied).
_OFF = {
    "watches": {"watch_count": 0},
    "components": {"has_components": False},
    "scheduled": {"has_scheduled_review": False},
    "ref_classes": {"ref_class_count": 0},
    "triggers": {"update_triggers": [{"mechanism": "free-form note only"}]},  # not executable
    "close_time": {"close_time": None},
    "impact": {"impact": "   "},  # blank string is not "set"
    "resolution_rule": {"resolution_rule": None},
}


@pytest.mark.parametrize("dimension", list(READINESS_WEIGHTS))
def test_scorer_each_dimension_pos_neg(dimension):
    kwargs = _full_kwargs()
    kwargs.update(_OFF[dimension])
    result = question_machine_readiness(**kwargs)
    # Score drops by EXACTLY that dimension's weight, and exactly that gap appears.
    assert result["score"] == 100 - READINESS_WEIGHTS[dimension]
    keys = {g["key"] for g in result["gaps"]}
    assert keys == {dimension}
    gap = result["gaps"][0]
    assert gap["key"] == dimension
    assert gap["fix_hint"]
    # The id-scoped fix hints (a concrete per-question command) embed the question id.
    if dimension in {"watches", "scheduled", "ref_classes", "triggers"}:
        assert "fq_x" in gap["fix_hint"]


def test_has_executable_trigger_requires_source_operator_numeric_threshold():
    # Free-form note → not executable.
    assert has_executable_trigger([{"mechanism": "watch the Fed"}]) is False
    # operator but no source_ref → not executable.
    assert has_executable_trigger([{"mechanism": "m", "operator": ">", "threshold": 3.0}]) is False
    # source_ref + operator + numeric threshold → executable.
    assert has_executable_trigger(
        [{"mechanism": "m", "source_ref": "fred:X", "operator": ">=", "threshold": 2}]
    ) is True
    # bool threshold is rejected (bool is an int subclass).
    assert has_executable_trigger(
        [{"mechanism": "m", "source_ref": "fred:X", "operator": ">", "threshold": True}]
    ) is False
    assert has_executable_trigger(None) is False


# ── batched ledger reads ──────────────────────────────────────────────────────


def _q(ledger, i, **over):
    defaults = dict(
        title=f"Will metric #{i} clear its bar in 2026?",
        resolution_criteria=f"Resolves yes if metric #{i} clears the bar by 2026-12-31.",
    )
    defaults.update(over)
    return ledger.create_question(**defaults)


def test_batched_watch_counts_match_singular(tmp_path):
    ledger = ForecastLedger(tmp_path / "b.db")
    a, b, c = _q(ledger, 1), _q(ledger, 2), _q(ledger, 3)
    ledger.add_watched_source(scope_type="question", scope_ref=a.id, source="fred:S1")
    ledger.add_watched_source(scope_type="question", scope_ref=a.id, source="fred:S2")
    ledger.add_watched_source(scope_type="question", scope_ref=b.id, source="fred:S3")
    # A non-active watch must NOT count (status filter): flip one to retired directly.
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE watched_sources SET status='retired' WHERE scope_ref=? AND source=?",
            (b.id, "fred:S3"),
        )

    counts = ledger.active_watched_source_counts([a.id, b.id, c.id])
    for qid in (a.id, b.id, c.id):
        expected = len(
            ledger.list_watched_sources(scope_type="question", scope_ref=qid, status="active")
        )
        assert counts.get(qid, 0) == expected
    assert counts.get(a.id, 0) == 2
    assert c.id not in counts  # no active watch → absent (caller defaults to 0)


def test_batched_ref_class_counts_match_singular(tmp_path):
    ledger = ForecastLedger(tmp_path / "b.db")
    a, b = _q(ledger, 1), _q(ledger, 2)
    ledger.add_reference_class(question_id=a.id, name="rc-1", inclusion_criteria="x", base_rate=0.3)
    ledger.add_reference_class(question_id=a.id, name="rc-2", inclusion_criteria="y", base_rate=0.4)

    counts = ledger.active_reference_class_counts([a.id, b.id])
    for qid in (a.id, b.id):
        expected = len(
            [rc for rc in ledger.list_reference_classes(qid) if rc.get("status") == "active"]
        )
        assert counts.get(qid, 0) == expected
    assert counts.get(a.id, 0) == 2
    assert b.id not in counts


def test_batched_readiness_reads_issue_one_query_each(tmp_path, monkeypatch):
    """The batched GROUP BYs open ONE connection for the WHOLE book (not one per
    question) — the desk N+1 lesson. Assert via a _connect call counter."""
    ledger = ForecastLedger(tmp_path / "b.db")
    ids = [_q(ledger, i).id for i in range(12)]
    for qid in ids[:6]:
        ledger.add_watched_source(scope_type="question", scope_ref=qid, source=f"fred:{qid}")
        ledger.add_reference_class(question_id=qid, name="rc", inclusion_criteria="x", base_rate=0.3)

    orig_connect = ledger._connect
    calls = {"n": 0}

    def counting_connect(*a, **k):
        calls["n"] += 1
        return orig_connect(*a, **k)

    monkeypatch.setattr(ledger, "_connect", counting_connect)
    ledger.active_watched_source_counts(ids)
    assert calls["n"] == 1  # one chunk, one connection — never per-question
    calls["n"] = 0
    ledger.active_reference_class_counts(ids)
    assert calls["n"] == 1


# ── workspace-payload wiring + no per-row N+1 ─────────────────────────────────


def _seed_book(ledger, n=6):
    ids = []
    for i in range(n):
        q = _q(ledger, i, close_time="2026-12-31T00:00:00Z", impact="high" if i % 2 else None)
        ids.append(q.id)
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution=0.4, rationale="seed",
            ensemble_components={"driver": {"weight": 1.0}} if i % 2 == 0 else None,
        )
        if i % 2 == 0:
            ledger.add_watched_source(scope_type="question", scope_ref=q.id, source=f"fred:{i}")
            ledger.add_reference_class(question_id=q.id, name="rc", inclusion_criteria="x", base_rate=0.3)
    return ids


def test_workspace_payload_carries_readiness(tmp_path):
    from forecasting.dashboard import build_workspace_payload

    ledger = ForecastLedger(tmp_path / "b.db")
    ids = _seed_book(ledger, 4)
    payload = build_workspace_payload(
        ledger=ledger, limit=1000, include_related=False, include_lessons=False
    )
    by_id = {f["id"]: f for f in payload["forecasts"]}
    assert set(by_id) == set(ids)
    for item in by_id.values():
        assert "src_count" in item
        assert isinstance(item["readiness"], dict)
        assert 0 <= item["readiness"]["score"] <= 100
        for gap in item["readiness"]["gaps"]:
            assert {"key", "label", "fix_hint"} <= set(gap)
    # An even-index question got a watch + component + ref class; an odd one didn't.
    even = by_id[ids[0]]
    odd = by_id[ids[1]]
    assert even["src_count"] == 1
    assert odd["src_count"] == 0
    assert even["readiness"]["score"] > odd["readiness"]["score"]
    assert "watches" not in {g["key"] for g in even["readiness"]["gaps"]}
    assert "watches" in {g["key"] for g in odd["readiness"]["gaps"]}


def test_payload_readiness_uses_batched_reads_not_per_question(tmp_path, monkeypatch):
    """No per-row N+1: building the whole book's readiness must NOT call the singular
    per-question list_watched_sources / list_reference_classes even once (the payload
    reads them BATCHED). Follows the desk payload regression pattern — a monkeypatch
    call counter asserting per-row-call absence."""
    from forecasting.dashboard import build_workspace_payload

    ledger = ForecastLedger(tmp_path / "b.db")
    _seed_book(ledger, 6)

    per_row = {"watch": 0, "ref": 0}
    orig_watch = ledger.list_watched_sources
    orig_ref = ledger.list_reference_classes

    def spy_watch(*a, **k):
        per_row["watch"] += 1
        return orig_watch(*a, **k)

    def spy_ref(*a, **k):
        per_row["ref"] += 1
        return orig_ref(*a, **k)

    monkeypatch.setattr(ledger, "list_watched_sources", spy_watch)
    monkeypatch.setattr(ledger, "list_reference_classes", spy_ref)

    build_workspace_payload(
        ledger=ledger, limit=1000, include_related=False, include_lessons=False
    )
    assert per_row == {"watch": 0, "ref": 0}


def test_payload_readiness_added_cost_within_budget(tmp_path):
    """Timing probe on a synthetic 120-question book: the two added batched GROUP BYs
    + the pure scorer over the whole book stay far under the <15ms added budget.
    Generous ceiling so the guard flags an accidental N+1 regression, never flakes."""
    ledger = ForecastLedger(tmp_path / "b.db")
    ids = _seed_book(ledger, 120)
    next_reviews = ledger.next_review_by_question()
    questions = ledger.list_questions(status="active", limit=1000)

    t0 = time.perf_counter()
    watch_counts = ledger.active_watched_source_counts(ids)
    ref_counts = ledger.active_reference_class_counts(ids)
    for q in questions:
        question_machine_readiness(
            question_id=q.id,
            watch_count=watch_counts.get(q.id, 0),
            has_components=False,
            ref_class_count=ref_counts.get(q.id, 0),
            update_triggers=q.update_triggers,
            has_scheduled_review=q.id in next_reviews,
            close_time=q.close_time,
            impact=q.impact,
            resolution_rule=q.resolution_criteria,
        )
    added_ms = (time.perf_counter() - t0) * 1000.0
    assert added_ms < 60.0, f"readiness added cost {added_ms:.1f}ms exceeded the budget guard"


# ── single-question composite (the RPC helper) ────────────────────────────────


def test_build_question_readiness_composite(tmp_path):
    ledger = ForecastLedger(tmp_path / "b.db")
    q = _q(ledger, 1, close_time="2026-12-31T00:00:00Z", impact="high")
    # Fresh question auto-schedules a weekly review + carries a resolution rule; it
    # has no watches / components / ref classes / executable triggers yet.
    composite = build_question_readiness(ledger, q.id)
    assert composite["question_id"] == q.id
    assert composite["title"] == q.title
    assert composite["src_count"] == 0
    keys = {g["key"] for g in composite["gaps"]}
    assert {"watches", "components", "ref_classes", "triggers"} <= keys
    assert "scheduled" not in keys  # auto-scheduled on create
    assert "resolution_rule" not in keys
    assert "close_time" not in keys
    assert "impact" not in keys

    # Add a watch → the watches gap closes and src_count + score rise.
    ledger.add_watched_source(scope_type="question", scope_ref=q.id, source="fred:X")
    after = build_question_readiness(ledger, q.id)
    assert after["src_count"] == 1
    assert "watches" not in {g["key"] for g in after["gaps"]}
    assert after["score"] > composite["score"]


def test_build_question_readiness_unknown_id_raises(tmp_path):
    ledger = ForecastLedger(tmp_path / "b.db")
    with pytest.raises(Exception):
        build_question_readiness(ledger, "fq_does_not_exist")
