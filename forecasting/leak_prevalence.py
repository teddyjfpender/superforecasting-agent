"""Leak-prevalence back-out (AIA P1.2).

A high-recall LLM judge produces many FLAGS, but recall is bought with low
precision: most flags are false positives. Reporting a raw flag count as the
"leak rate" would massively overstate contamination. This module converts a raw
flag count into an honest TRUE-leak rate using the judge's measured precision
and recall.

Derivation (all PURE arithmetic):

    flags  = the judge's positive count over N cases.
    TP     = precision * flags          (flags that are real leaks)
    FN     = TP / recall - TP           (real leaks the judge missed)
    true_rate = (TP + FN) / N

So ``true_rate = (precision * flags) / (recall * N)``. With the paper's working
numbers (N=4411, flags=236, precision~0.198, recall~0.64) this lands near 1.65%,
a far cry from the raw 236/4411 = 5.4% flag rate — and that ~1-2% true rate is
what makes a headline Brier defensibly leak-proof.

The precision/recall numbers are PLACEHOLDERS and clearly labelled UNCALIBRATED:
they must be replaced once we hand-label a sample of flagged cases.
"""

from __future__ import annotations

from typing import Any


# Versioned calibration block. precision/recall are UNCALIBRATED placeholders
# carried straight from the paper's working figures — DO NOT cite the resulting
# true-rate as measured until these are replaced by hand-labelled estimates.
LEAK_JUDGE_CALIBRATION: dict[str, Any] = {
    "version": "leak-judge-calibration-v0-UNCALIBRATED",
    "calibrated": False,
    "precision": 0.198,
    "recall": 0.64,
    "labelled_sample_size": 0,
    "notes": (
        "UNCALIBRATED placeholder precision/recall from the AIA paper's working "
        "figures. Replace with hand-labelled estimates over a flagged-case sample "
        "before reporting true_rate as a measured quantity."
    ),
}


def estimate_true_leak_rate(
    N: int,
    flags: int,
    precision: float | None = None,
    recall: float | None = None,
) -> dict[str, Any]:
    """Back out the honest true-leak rate from a raw flag count.

    ``precision``/``recall`` default to the (UNCALIBRATED) calibration block.

    Returns a dict with the back-out and its components::

        {
            "N", "flags", "precision", "recall",
            "true_positives", "false_negatives", "true_leaks",
            "true_rate", "flag_rate", "calibrated"
        }

    Edge cases fail safe to ``true_rate = 0.0`` rather than dividing by zero.
    """

    if precision is None:
        precision = float(LEAK_JUDGE_CALIBRATION["precision"])
    if recall is None:
        recall = float(LEAK_JUDGE_CALIBRATION["recall"])

    n = max(int(N), 0)
    raw_flags = max(int(flags), 0)
    precision = max(float(precision), 0.0)
    recall = float(recall)

    flag_rate = (raw_flags / n) if n > 0 else 0.0

    if n <= 0 or recall <= 0.0:
        # No denominator (no cases) or an unusable recall — report zero true
        # leaks rather than dividing by zero or inflating the estimate.
        return {
            "N": n,
            "flags": raw_flags,
            "precision": precision,
            "recall": recall,
            "true_positives": 0.0,
            "false_negatives": 0.0,
            "true_leaks": 0.0,
            "true_rate": 0.0,
            "flag_rate": flag_rate,
            "calibrated": bool(LEAK_JUDGE_CALIBRATION["calibrated"]),
        }

    true_positives = precision * raw_flags
    # FN = TP/recall - TP  (the real leaks the high-recall judge still missed).
    false_negatives = true_positives / recall - true_positives
    true_leaks = true_positives + false_negatives
    true_rate = true_leaks / n

    return {
        "N": n,
        "flags": raw_flags,
        "precision": precision,
        "recall": recall,
        "true_positives": true_positives,
        "false_negatives": false_negatives,
        "true_leaks": true_leaks,
        "true_rate": true_rate,
        "flag_rate": flag_rate,
        "calibrated": bool(LEAK_JUDGE_CALIBRATION["calibrated"]),
    }
