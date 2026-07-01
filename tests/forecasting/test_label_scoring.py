"""Tests for the classification scoreboard (the label analog of score_question)."""

from __future__ import annotations

import json

import pytest

from forecasting.label_scoring import (
    LABEL_TASK_TYPES,
    headline_accuracy,
    score_labels,
)


def _rows(pairs):
    return [{"id": i, "label": lbl} for i, lbl in pairs]


def test_perfect_relevance_accuracy():
    preds = _rows([("a", "irrelevant"), ("b", "relevant_interesting"), ("c", "relevant_uninteresting")])
    score = score_labels(preds, preds, task_type="relevance")
    assert score.n == 3
    assert score.accuracy == 1.0
    assert score.exact_match is None  # relevance reports accuracy, not exact_match
    assert score.macro_f1 == 1.0
    assert score.skipped == 0


def test_relevance_accuracy_and_per_class_f1():
    gold = _rows([("a", "irrelevant"), ("b", "relevant_interesting"), ("c", "relevant_interesting"), ("d", "irrelevant")])
    preds = _rows([("a", "irrelevant"), ("b", "relevant_interesting"), ("c", "irrelevant"), ("d", "irrelevant")])
    score = score_labels(preds, gold, task_type="relevance")
    # 3 of 4 correct (c is wrong).
    assert score.accuracy == 0.75
    by_label = {c["label"]: c for c in score.per_class}
    # irrelevant: predicted on a,c,d; gold a,d → tp=2, fp=1(c), fn=0 → P=2/3, R=1.0
    assert by_label["irrelevant"]["precision"] == pytest.approx(2 / 3)
    assert by_label["irrelevant"]["recall"] == 1.0
    # relevant_interesting: predicted on b; gold b,c → tp=1, fp=0, fn=1 → P=1.0, R=0.5
    assert by_label["relevant_interesting"]["precision"] == 1.0
    assert by_label["relevant_interesting"]["recall"] == 0.5


def test_positive_class_confusion_and_f1():
    gold = _rows([("a", "relevant_interesting"), ("b", "relevant_interesting"), ("c", "irrelevant"), ("d", "irrelevant")])
    preds = _rows([("a", "relevant_interesting"), ("b", "irrelevant"), ("c", "relevant_interesting"), ("d", "irrelevant")])
    score = score_labels(preds, gold, task_type="relevance", positive_class="relevant_interesting")
    assert score.confusion == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert score.positive_precision == 0.5
    assert score.positive_recall == 0.5
    assert score.positive_f1 == 0.5


def test_truncation_exact_match():
    gold = _rows([("d1", "12"), ("d2", "7"), ("d3", "0")])
    preds = _rows([("d1", "12"), ("d2", "8"), ("d3", "0")])
    score = score_labels(preds, gold, task_type="truncation")
    assert score.exact_match == pytest.approx(2 / 3)
    assert score.accuracy is None  # truncation reports exact_match, not accuracy
    assert score.per_class == []
    assert headline_accuracy(score) == pytest.approx(2 / 3)


def test_skipped_counts_missing_predictions():
    gold = _rows([("a", "irrelevant"), ("b", "irrelevant"), ("c", "irrelevant")])
    preds = _rows([("a", "irrelevant")])  # b, c have no prediction
    score = score_labels(preds, gold, task_type="relevance")
    assert score.n == 1
    assert score.skipped == 2
    assert score.accuracy == 1.0  # of the ones scored


def test_no_overlap_returns_empty():
    score = score_labels(_rows([("x", "a")]), _rows([("y", "b")]), task_type="relevance")
    assert score.n == 0
    assert score.accuracy is None
    assert "nothing scored" in score.notes


def test_cost_per_task():
    gold = _rows([("a", "irrelevant"), ("b", "irrelevant")])
    score = score_labels(gold, gold, task_type="relevance", cost=0.5)
    assert score.cost == 0.5
    assert score.cost_per_task == 0.25


def test_headline_accuracy_relevance():
    gold = _rows([("a", "irrelevant"), ("b", "relevant_interesting")])
    assert headline_accuracy(score_labels(gold, gold, task_type="relevance")) == 1.0


def test_bad_input_raises():
    with pytest.raises(ValueError):
        score_labels([{"id": "a"}], [{"id": "a", "label": "x"}], task_type="relevance")
    with pytest.raises(ValueError):
        score_labels([], [], task_type="not_a_task")


def test_label_score_action_end_to_end():
    from tools.forecasting_tool import forecast_ledger_tool

    out = forecast_ledger_tool(
        {
            "action": "label_score",
            "task_type": "relevance",
            "positive_class": "relevant_interesting",
            "predictions": [
                {"id": "a", "label": "relevant_interesting"},
                {"id": "b", "label": "irrelevant"},
            ],
            "gold": [
                {"id": "a", "label": "relevant_interesting"},
                {"id": "b", "label": "irrelevant"},
            ],
            "cost": 0.2,
        }
    )
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["label_score"]["accuracy"] == 1.0
    assert payload["label_score"]["cost_per_task"] == 0.1
    assert payload["label_score"]["confusion"] == {"tp": 1, "fp": 0, "tn": 1, "fn": 0}


def test_label_score_action_rejects_bad_task_type():
    from tools.forecasting_tool import forecast_ledger_tool

    out = forecast_ledger_tool(
        {"action": "label_score", "task_type": "bogus", "predictions": [], "gold": []}
    )
    payload = json.loads(out)
    assert payload.get("error")
    assert "task_type" in payload["error"]


def test_task_types_constant():
    assert LABEL_TASK_TYPES == frozenset({"relevance", "truncation"})
