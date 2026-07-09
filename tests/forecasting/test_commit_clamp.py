"""Commit-path probability clamp (BLF A7).

BLF clamps its final binary probability to [0.05, 0.95] to bound worst-case
Brier. Our extremization guards cover the CALIBRATION side; this is the terminal
COMMIT-path bound. The discipline under test:

* the clamp is applied to active agent commits
  (``live`` / ``market_nightly``), scoped to binary scalars;
* it is RECORDED in the snapshot metadata whenever it engages — never silent;
* it is the TERMINAL transform: upstream √3 Platt / quorum / learned-lesson
  calibration all run BEFORE the value reaches ``create_snapshot``, so the
  scored value is the clamped one;
* faithful external baselines (``imported_baseline``), benchmark replays
  (``backtest``), and distributions / vote-shares are left byte-identical
  (out of scope).
"""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.ledger.snapshots import (
    _COMMIT_PROBABILITY_CEIL,
    _COMMIT_PROBABILITY_FLOOR,
)
from forecasting.models import OutcomeSpace


def _ledger(tmp_path):
    return ForecastLedger(tmp_path / "clamp.db")


def _binary_question(ledger, *, title="Will the clamp engage?"):
    with allow_ledger_writes("test seed"):
        return ledger.create_question(
            title=title,
            resolution_criteria="Resolves YES if the stated event occurs by the deadline, else NO.",
            outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        )


def _commit(ledger, question_id, probability, *, origin="live"):
    with allow_ledger_writes("test commit"):
        snap = ledger.create_snapshot(
            question_id=question_id,
            probability_or_distribution=probability,
            rationale="Committed binary forecast for the clamp test.",
            forecast_origin=origin,
        )
    return ledger.get_snapshot(snap.forecast_id)


def test_clamp_engages_at_ceiling_and_records(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    snap = _commit(ledger, q.id, 0.99)
    # Persisted value is the clamped one, not 0.99.
    assert snap.probability_or_distribution == pytest.approx(_COMMIT_PROBABILITY_CEIL)
    clamp = (snap.metadata or {}).get("commit_clamp")
    assert clamp is not None
    assert clamp["original"] == pytest.approx(0.99)
    assert clamp["clamped"] == pytest.approx(0.95)
    assert clamp["bound"] == [_COMMIT_PROBABILITY_FLOOR, _COMMIT_PROBABILITY_CEIL]


def test_clamp_engages_at_floor_and_records(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    snap = _commit(ledger, q.id, 0.01)
    assert snap.probability_or_distribution == pytest.approx(_COMMIT_PROBABILITY_FLOOR)
    clamp = (snap.metadata or {}).get("commit_clamp")
    assert clamp is not None and clamp["original"] == pytest.approx(0.01)
    assert clamp["clamped"] == pytest.approx(0.05)


def test_in_band_probability_is_untouched_and_unrecorded(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    snap = _commit(ledger, q.id, 0.42)
    assert snap.probability_or_distribution == pytest.approx(0.42)
    # No clamp engaged → no metadata record (never a spurious "clamp" note).
    assert "commit_clamp" not in (snap.metadata or {})


def test_exact_bounds_do_not_record_a_clamp(tmp_path):
    ledger = _ledger(tmp_path)
    for p in (_COMMIT_PROBABILITY_FLOOR, _COMMIT_PROBABILITY_CEIL):
        q = _binary_question(ledger, title=f"boundary {p}")
        snap = _commit(ledger, q.id, p)
        assert snap.probability_or_distribution == pytest.approx(p)
        assert "commit_clamp" not in (snap.metadata or {})


def test_backtest_origin_is_recorded_faithfully(tmp_path):
    # Backtests are benchmark replays. Clamping them mutates the measurement and
    # makes a frozen market replay diverge from its paired baseline.
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    snap = _commit(ledger, q.id, 0.985, origin="backtest")
    assert snap.probability_or_distribution == pytest.approx(0.985)
    assert "commit_clamp" not in (snap.metadata or {})


def test_imported_baseline_is_recorded_faithfully(tmp_path):
    # A recorded market/crowd price is external truth — clamping it would
    # fabricate a different market price and corrupt the agent-vs-market head-to-head.
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    snap = _commit(ledger, q.id, 0.98, origin="imported_baseline")
    assert snap.probability_or_distribution == pytest.approx(0.98)
    assert "commit_clamp" not in (snap.metadata or {})


def test_distribution_payload_is_out_of_scope(tmp_path):
    ledger = _ledger(tmp_path)
    with allow_ledger_writes("test seed"):
        q = ledger.create_question(
            title="Where does the index close?",
            resolution_criteria="Resolves to the published closing level.",
            outcome_space=OutcomeSpace(type="distribution", units="points"),
        )
    payload = {
        "median": 100.0, "mean": 100.0, "sd": 6.0,
        "interval_50_low": 96.0, "interval_50_high": 104.0,
        "interval_90_low": 90.0, "interval_90_high": 110.0,
        "q05": 90.0, "q25": 96.0, "q50": 100.0, "q75": 104.0, "q95": 110.0,
    }
    with allow_ledger_writes("test commit"):
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=payload,
            rationale="Distribution forecast, never clamped.",
        )
    snap = ledger.get_snapshot(snap.forecast_id)
    assert "commit_clamp" not in (snap.metadata or {})


def test_clamp_is_terminal_the_scored_value_is_the_clamped_one(tmp_path):
    # Calibration (panel √3 Platt / quorum / learned-lesson) runs UPSTREAM of
    # create_snapshot; the clamp is the last transform, so the Brier reflects the
    # clamped 0.95, not the raw 0.99 — bounding worst-case error as intended.
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    _commit(ledger, q.id, 0.99)
    with allow_ledger_writes("test resolve"):
        ledger.resolve_question(question_id=q.id, outcome="no")
    score = ledger.get_current_score(q.id)
    assert score.brier_score == pytest.approx((0.95 - 0.0) ** 2)  # 0.9025, not 0.9801


def test_preview_reports_the_same_clamped_value_and_record(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    with allow_ledger_writes("test preview"):
        preview = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.99,
            rationale="Preview must agree with the commit it foreshadows.",
            preview=True,
        )
    assert preview["would_commit"] is True
    assert preview["probability_or_distribution"] == pytest.approx(0.95)
    assert preview["metadata"].get("commit_clamp", {}).get("clamped") == pytest.approx(0.95)
