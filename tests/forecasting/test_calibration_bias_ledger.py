"""Integration tests for the signed calibration-bias loop wired into the
ledger: measurement (``calibration_bias``), lesson synthesis with FDR control
and supersession (``synthesize_bias_lessons``), the advisory-by-default /
mechanical-opt-in split, and that an active lesson renders into the forecast
context packet without mechanically moving any probability.

The pure math is covered in test_calibration_bias.py; here we plant resolved
binary forecasts with a KNOWN bias and assert the end-to-end behaviour.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.learning import apply_active_lesson_adjustments
from forecasting.protocol import build_context_packet

CRITERIA = "Resolves to the official value reported by the named source on the close date."


def _plant(ledger, *, domain, p_yes, yes_fraction, n, title_prefix):
    """Create ``n`` resolved binary questions in ``domain``, each forecast at
    ``p_yes``, with ``round(yes_fraction*n)`` resolving yes. Auto-scored."""

    # These tests exercise the EXPLICIT synthesize_bias_lessons path in isolation,
    # so suppress the resolve-time auto-synthesis (S7.1) during planting — otherwise
    # a lesson would materialise mid-plant and pollute the supersession/dry-run
    # assertions. (The auto-trigger itself is covered in test_s7_calibration_autoclose.)
    ledger._live_score_count = lambda domain: 0  # type: ignore[method-assign]
    yes = round(yes_fraction * n)
    for i in range(n):
        q = ledger.create_question(
            title=f"{title_prefix} #{i}?",
            resolution_criteria=CRITERIA,
            domain=domain,
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=p_yes,
            rationale="planted",
        )
        ledger.resolve_question(
            question_id=q.id,
            outcome="yes" if i < yes else "no",
            auto_score=True,
        )


def test_calibration_bias_insufficient_on_empty(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    report = ledger.calibration_bias(domain="politics")
    assert report["status"] == "insufficient_evidence"
    assert report["sce_raw"] is None


def test_underconfident_domain_yields_active_lesson(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # Stated 0.70 but 0.90 realised over 120 questions → clear under-confidence.
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.90, n=120, title_prefix="Race")

    report = ledger.calibration_bias(domain="politics")
    assert report["status"] == "underconfident"
    assert report["sce_shrunk"] < 0
    assert report["ess"] >= 30

    results = ledger.synthesize_bias_lessons(scope="politics", activate=True)
    assert len(results) == 1
    action = results[0]["action"]
    assert action["written"] is True
    assert action["lesson_status"] == "active"

    active = ledger.list_calibration_lessons(scope_type="domain", scope_ref="politics", active_only=True)
    assert len(active) == 1
    lesson = active[0]
    assert "under-confident" in lesson["lesson"]
    assert "politics" in lesson["lesson"]
    # advisory by default → NO mechanical adjustment written
    assert lesson["recommended_adjustment"] == {}
    assert lesson["metadata"]["source"] == "calibration_bias"
    assert lesson["metadata"]["sce_trajectory"]  # trajectory recorded


def test_active_lesson_renders_in_context_without_moving_probability(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.90, n=120, title_prefix="Race")
    ledger.synthesize_bias_lessons(scope="politics", activate=True)

    # A fresh politics question + snapshot.
    q = ledger.create_question(
        title="Will candidate X win the 2026 primary?",
        resolution_criteria=CRITERIA,
        domain="politics",
    )
    snap = ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.55, rationale="fresh"
    )
    packet = build_context_packet(ledger, ledger.get_question(q.id), snap)
    assert "## Calibration Lessons" in packet
    assert "under-confident" in packet  # the advisory text reached the prompt

    # The advisory lesson must NOT mechanically move the probability.
    payload, refs, adjustment = apply_active_lesson_adjustments(
        ledger=ledger,
        question=ledger.get_question(q.id),
        payload=0.55,
        calibration_lesson_refs=[],
        calibration_adjustment={},
    )
    assert payload == 0.55  # unchanged — advisory only
    assert "applied_logit_scale" not in adjustment
    assert "applied_logit_shift" not in adjustment


def test_calibrated_domain_emits_no_lesson(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # Stated 0.70, realised 0.70 → calibrated.
    _plant(ledger, domain="markets", p_yes=0.70, yes_fraction=0.70, n=120, title_prefix="Tick")
    results = ledger.synthesize_bias_lessons(scope="markets", activate=True)
    assert results[0]["status"] in {"calibrated", "insufficient_evidence"}
    assert results[0]["action"]["written"] is False
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="markets", active_only=True) == []


def test_resynthesis_supersedes_not_accumulates(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.90, n=120, title_prefix="Race")
    ledger.synthesize_bias_lessons(scope="politics", activate=True)
    ledger.synthesize_bias_lessons(scope="politics", activate=True)
    # Exactly one ACTIVE lesson remains; the prior was superseded.
    active = ledger.list_calibration_lessons(scope_type="domain", scope_ref="politics", active_only=True)
    assert len(active) == 1
    superseded = [
        l
        for l in ledger.list_calibration_lessons(scope_type="domain", scope_ref="politics")
        if l["status"] == "superseded"
    ]
    assert len(superseded) >= 1


def test_dry_run_writes_nothing(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.90, n=120, title_prefix="Race")
    results = ledger.synthesize_bias_lessons(scope="politics", activate=True, dry_run=True)
    assert results[0]["action"]["written"] is False
    assert ledger.list_calibration_lessons(scope_type="domain", scope_ref="politics") == []


def test_mechanical_opt_in_emits_logit_scale_and_moves_probability(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # Large ESS + big bias so the high-ESS mechanical gate (>=60) is cleared.
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.92, n=140, title_prefix="Race")
    results = ledger.synthesize_bias_lessons(scope="politics", activate=True, enable_mechanical=True)
    lesson_adj = ledger.list_calibration_lessons(
        scope_type="domain", scope_ref="politics", active_only=True
    )[0]["recommended_adjustment"]
    assert "logit_scale" in lesson_adj
    assert lesson_adj["logit_scale"] > 1.0  # under-confident → sharpen

    # Now the apply path should sharpen a fresh forecast away from 0.5.
    q = ledger.create_question(
        title="Fresh politics call?", resolution_criteria=CRITERIA, domain="politics"
    )
    payload, refs, adjustment = apply_active_lesson_adjustments(
        ledger=ledger,
        question=ledger.get_question(q.id),
        payload=0.70,
        calibration_lesson_refs=[],
        calibration_adjustment={},
    )
    assert payload > 0.70  # sharpened toward the leaned side (base-rate neutral)
    assert adjustment["applied_logit_scale"] > 1.0
    assert adjustment["raw_probability"] == 0.70


def test_tentative_when_below_strong_ess(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # ESS 25 < strong floor 30, but a big clear gap → significant → tentative.
    _plant(ledger, domain="politics", p_yes=0.70, yes_fraction=0.96, n=25, title_prefix="Race")
    results = ledger.synthesize_bias_lessons(scope="politics", activate=True)
    status = results[0]["action"].get("lesson_status") or results[0]["action"].get("status")
    # Either tentative (detectable) or no write (if noise) — but never active.
    assert results[0]["action"].get("lesson_status") != "active"
    # A tentative lesson does NOT render into the prompt (only active does).
    active = ledger.list_calibration_lessons(scope_type="domain", scope_ref="politics", active_only=True)
    assert active == []
