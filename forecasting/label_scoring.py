"""Classification scoring for triage / relevance labels.

The forecast ledger scores PROBABILITIES (Brier / log / proper score via
``ledger.score_question``). Triage labels are CLASSIFICATIONS, and a
classification needs a different scoreboard: accuracy, positive-class F1,
exact-match, and a confusion matrix. This module is the label analog of
``score_question`` — pure functions over ``(predictions, gold)``, with no DB
and no model call, so it is trivially testable and reusable by the triage
labeler, the contested-routing loop, and the doctor trust gate.

Motivation: the Thinking Machines / Bridgewater AIA "Learning to Replicate
Expert Judgment in Financial Tasks" study scores its six tasks with
Accuracy / positive-class F1 / Exact-Match — none of which the ledger could
compute, because it only had proper-scoring for probabilities. A triage label
literally could not be scored on its own terms before this module existed.

Two task families, mirroring the paper:
  * ``relevance``   — multi-class classification (e.g. the three-way
                      relevant_interesting / relevant_uninteresting / irrelevant
                      label). Headline metric: accuracy, plus per-class and
                      macro F1, plus a binary confusion against an optional
                      ``positive_class``.
  * ``truncation``  — cut-point / span extraction (where boilerplate begins).
                      Headline metric: exact-match accuracy (pred == gold).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

RELEVANCE_TASK = "relevance"
TRUNCATION_TASK = "truncation"
LABEL_TASK_TYPES = frozenset({RELEVANCE_TASK, TRUNCATION_TASK})


def _round(value: float | None, ndigits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


@dataclass(frozen=True)
class ClassMetrics:
    """Per-class precision / recall / F1 / support for a multi-class task."""

    label: str
    support: int
    predicted: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "support": self.support,
            "predicted": self.predicted,
            "precision": _round(self.precision),
            "recall": _round(self.recall),
            "f1": _round(self.f1),
        }


@dataclass(frozen=True)
class LabelScore:
    """The classification scoreboard — the label analog of ScoreRecord."""

    task_type: str
    n: int
    skipped: int
    accuracy: float | None
    exact_match: float | None
    positive_class: str | None
    positive_precision: float | None
    positive_recall: float | None
    positive_f1: float | None
    confusion: dict[str, int] | None
    per_class: list[dict[str, Any]]
    macro_f1: float | None
    cost: float | None
    cost_per_task: float | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "n": self.n,
            "skipped": self.skipped,
            "accuracy": _round(self.accuracy),
            "exact_match": _round(self.exact_match),
            "positive_class": self.positive_class,
            "positive_precision": _round(self.positive_precision),
            "positive_recall": _round(self.positive_recall),
            "positive_f1": _round(self.positive_f1),
            "confusion": dict(self.confusion) if self.confusion is not None else None,
            "per_class": list(self.per_class),
            "macro_f1": _round(self.macro_f1),
            "cost": _round(self.cost),
            "cost_per_task": _round(self.cost_per_task),
            "notes": self.notes,
        }


def _index_labels(rows: Sequence[Any], *, side: str) -> dict[str, str]:
    """Index ``[{id, label}, ...]`` by id, coercing labels to comparable str.

    A duplicate id is silently overwritten (last-write-wins) and is NOT reflected
    in the ``skipped`` count — ``skipped`` only ever counts gold ids that have no
    prediction. Labels are stringified so categorical strings and integer
    cut-points compare uniformly.
    """
    out: dict[str, str] = {}
    if not isinstance(rows, (list, tuple)):
        raise ValueError(f"{side} must be a list of {{id, label}} objects")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{side} entries must be objects with `id` and `label`")
        if "id" not in row or "label" not in row:
            raise ValueError(f"{side} entries require both `id` and `label`")
        out[str(row["id"])] = str(row["label"])
    return out


def score_labels(
    predictions: Sequence[Any],
    gold: Sequence[Any],
    *,
    task_type: str = RELEVANCE_TASK,
    positive_class: str | None = None,
    cost: float | None = None,
) -> LabelScore:
    """Score predicted labels against gold labels.

    ``predictions`` / ``gold`` are lists of ``{"id": ..., "label": ...}``. Only
    ids present in BOTH are scored; gold ids with no prediction are counted as
    ``skipped`` (a labeler that abstains is not silently credited). Predictions
    with no gold are ignored (nothing to score against).

    For ``relevance``: ``accuracy`` is the headline, with per-class and macro F1,
    and — when ``positive_class`` is given — that class's precision/recall/F1 and
    a binary confusion matrix.
    For ``truncation``: ``exact_match`` is the headline (pred == gold exactly);
    per-class metrics are omitted (cut-points are not classes).
    """
    if task_type not in LABEL_TASK_TYPES:
        raise ValueError(f"task_type must be one of {sorted(LABEL_TASK_TYPES)}")

    pred = _index_labels(predictions, side="predictions")
    truth = _index_labels(gold, side="gold")

    ids = [k for k in truth if k in pred]
    n = len(ids)
    skipped = sum(1 for k in truth if k not in pred)

    if n == 0:
        return LabelScore(
            task_type=task_type,
            n=0,
            skipped=skipped,
            accuracy=None,
            exact_match=None,
            positive_class=positive_class,
            positive_precision=None,
            positive_recall=None,
            positive_f1=None,
            confusion=None,
            per_class=[],
            macro_f1=None,
            cost=cost,
            cost_per_task=None,
            notes="no overlapping ids between predictions and gold — nothing scored",
        )

    correct = sum(1 for k in ids if pred[k] == truth[k])
    rate = correct / n

    accuracy: float | None = None
    exact_match: float | None = None
    per_class: list[dict[str, Any]] = []
    macro_f1: float | None = None

    if task_type == TRUNCATION_TASK:
        exact_match = rate
    else:
        accuracy = rate
        classes = sorted({truth[k] for k in ids} | {pred[k] for k in ids})
        f1s: list[float] = []
        for cls in classes:
            tp = sum(1 for k in ids if pred[k] == cls and truth[k] == cls)
            fp = sum(1 for k in ids if pred[k] == cls and truth[k] != cls)
            fn = sum(1 for k in ids if pred[k] != cls and truth[k] == cls)
            support = sum(1 for k in ids if truth[k] == cls)
            predicted = sum(1 for k in ids if pred[k] == cls)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall)
                else 0.0
            )
            per_class.append(
                ClassMetrics(cls, support, predicted, precision, recall, f1).to_dict()
            )
            f1s.append(f1)
        macro_f1 = sum(f1s) / len(f1s) if f1s else None

    positive_precision: float | None = None
    positive_recall: float | None = None
    positive_f1: float | None = None
    confusion: dict[str, int] | None = None
    if positive_class is not None:
        pos = str(positive_class)
        tp = sum(1 for k in ids if pred[k] == pos and truth[k] == pos)
        fp = sum(1 for k in ids if pred[k] == pos and truth[k] != pos)
        tn = sum(1 for k in ids if pred[k] != pos and truth[k] != pos)
        fn = sum(1 for k in ids if pred[k] != pos and truth[k] == pos)
        confusion = {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
        positive_precision = tp / (tp + fp) if (tp + fp) else 0.0
        positive_recall = tp / (tp + fn) if (tp + fn) else 0.0
        positive_f1 = (
            2 * positive_precision * positive_recall
            / (positive_precision + positive_recall)
            if (positive_precision + positive_recall)
            else 0.0
        )

    cost_per_task = (cost / n) if (cost is not None and n) else None

    headline = (
        f"exact_match={exact_match:.3f}"
        if task_type == TRUNCATION_TASK
        else f"accuracy={accuracy:.3f}"
    )
    notes = f"{task_type}: {headline} over n={n}"
    if skipped:
        notes += f" ({skipped} gold item(s) had no prediction, counted as skipped)"
    if positive_class is not None and positive_f1 is not None:
        notes += f"; positive_class='{positive_class}' F1={positive_f1:.3f}"

    return LabelScore(
        task_type=task_type,
        n=n,
        skipped=skipped,
        accuracy=accuracy,
        exact_match=exact_match,
        positive_class=positive_class,
        positive_precision=positive_precision,
        positive_recall=positive_recall,
        positive_f1=positive_f1,
        confusion=confusion,
        per_class=per_class,
        macro_f1=macro_f1,
        cost=cost,
        cost_per_task=cost_per_task,
        notes=notes,
    )


def headline_accuracy(score: LabelScore) -> float | None:
    """The single number a trust gate compares against a threshold.

    ``accuracy`` for relevance, ``exact_match`` for truncation — whichever the
    task family reports as its headline.
    """
    if score.task_type == TRUNCATION_TASK:
        return score.exact_match
    return score.accuracy
