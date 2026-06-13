"""Probability-mass audit for categorical forecasts: force every material
outcome through a named mechanism, flag unearned tail mass, and (opt-in)
refuse to commit a live forecast that anchors on answer-choice labels.

Models the real failure that prompted it: a multi-candidate race where a
named-but-non-live candidate (Conway) held a tail with no poll/ballot path.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.tail_audit import (
    OutcomePath,
    audit_outcomes,
    outcome_paths_from_inputs,
    render_audit_table,
)

NY12 = {"Lasher": 0.55, "Bores": 0.35, "Schlossberg": 0.07, "Conway": 0.017, "Other": 0.013}
NY12_PATHS = {
    "Lasher": {"path": "leads polls + endorsements + field", "evidence_strength": "strong"},
    "Bores": {"path": "strong fundraising + establishment lane", "evidence_strength": "strong"},
    "Schlossberg": {"path": "name ID + late volatility", "evidence_strength": "mixed"},
}


class TestAuditLogic:
    def test_named_but_nonlive_tail_is_unearned(self):
        audit = audit_outcomes(outcome_paths_from_inputs(NY12, NY12_PATHS))
        by = {v.name: v for v in audit.verdicts}
        # Conway: material mass, no path → unearned.
        assert by["Conway"].unearned is True
        assert by["Conway"].classification == "unpriced"
        # Live outcomes pass; residual within cap is fine.
        assert by["Lasher"].unearned is False
        assert by["Lasher"].classification == "live"
        assert by["Other"].unearned is False
        assert by["Other"].classification == "residual"
        assert not audit.passes
        assert audit.unearned_mass == pytest.approx(0.017, abs=1e-9)

    def test_all_paths_named_passes(self):
        paths = {
            **NY12_PATHS,
            "Conway": {"path": "credible surprise poll + endorsement cascade", "evidence_strength": "weak"},
        }
        audit = audit_outcomes(outcome_paths_from_inputs(NY12, paths))
        assert audit.passes
        assert audit.unearned_mass <= audit.threshold
        # A path with weak evidence is live_ish and gets a "justify the scale" note.
        conway = next(v for v in audit.verdicts if v.name == "Conway")
        assert conway.classification == "live_ish"
        assert "scale" in conway.note

    def test_negligible_tail_needs_no_path(self):
        dist = {"A": 0.6, "B": 0.398, "C": 0.002}  # C below 0.5% threshold
        audit = audit_outcomes(
            outcome_paths_from_inputs(dist, {"A": "leads", "B": "second"})
        )
        c = next(v for v in audit.verdicts if v.name == "C")
        assert c.classification == "remote_tail"
        assert c.unearned is False
        assert audit.passes

    def test_oversized_residual_is_flagged(self):
        dist = {"A": 0.55, "B": 0.35, "Other": 0.10}  # residual over the 5% cap
        audit = audit_outcomes(
            outcome_paths_from_inputs(dist, {"A": "leads", "B": "second"})
        )
        other = next(v for v in audit.verdicts if v.name == "Other")
        assert other.unearned is True
        assert audit.unearned_mass == pytest.approx(0.05, abs=1e-9)  # 0.10 - 0.05 cap

    def test_unnormalized_distribution_is_an_issue(self):
        dist = {"A": 0.6, "B": 0.6}
        audit = audit_outcomes(outcome_paths_from_inputs(dist, {"A": "x", "B": "y"}))
        assert not audit.passes
        assert any("sum" in i for i in audit.issues)

    def test_caller_classification_override_is_respected(self):
        rows = [
            OutcomePath("A", 0.6, path="leads", evidence_strength="strong"),
            OutcomePath("B", 0.4, classification="edge_case"),
        ]
        audit = audit_outcomes(rows)
        b = next(v for v in audit.verdicts if v.name == "B")
        assert b.classification == "edge_case"

    def test_render_table_marks_unearned(self):
        table = render_audit_table(audit_outcomes(outcome_paths_from_inputs(NY12, NY12_PATHS)))
        assert "FAIL" in table
        assert "Conway" in table
        assert "!" in table  # the unearned flag
        assert "null model" in table  # the sharper-null comparison line


class TestNullModel:
    def test_fat_no_path_tail_flagged_vs_null(self):
        # Conway 6% + Other 4% with no path → a fat tail vs the floored null.
        dist = {"Lasher": 0.50, "Bores": 0.33, "Schlossberg": 0.07, "Conway": 0.06, "Other": 0.04}
        audit = audit_outcomes(outcome_paths_from_inputs(dist, NY12_PATHS))
        nm = audit.null_model
        assert nm is not None
        # Conway (0.06) is the genuine no-path tail; "Other" is a residual
        # catch-all and is excluded from the null comparison.
        assert nm.agent_tail == pytest.approx(0.06, abs=1e-9)
        assert nm.null_tail < 0.02  # floored
        assert nm.ratio > 2.0
        assert nm.within_tolerance is False
        assert any("null model" in i for i in audit.issues)

    def test_null_model_within_tolerance_when_paths_named(self):
        paths = {**NY12_PATHS, "Conway": {"path": "surprise poll", "evidence_strength": "weak"}}
        audit = audit_outcomes(outcome_paths_from_inputs(NY12, paths))
        # Only the tiny residual "Other" lacks a path → tail is negligible.
        assert audit.null_model.within_tolerance is True

    def test_null_distribution_floors_no_path_outcomes(self):
        dist = {"A": 0.6, "B": 0.3, "C": 0.1}
        audit = audit_outcomes(outcome_paths_from_inputs(dist, {"A": "x", "B": "y"}))
        null = audit.null_model.null_distribution
        # C (no path) floored near zero; A and B keep their 2:1 ratio.
        assert null["C"] < 0.01
        assert null["A"] / null["B"] == pytest.approx(2.0, abs=0.05)


class TestCommitGate:
    def _question(self, ledger):
        return ledger.create_question(
            title="Who wins the 2026 NY-12 Democratic primary?",
            resolution_criteria="The certified winner of the 2026 NY-12 Democratic primary.",
            outcome_space=OutcomeSpace(
                type="categorical", choices=list(NY12)
            ),
        )

    def test_audit_always_recorded_on_categorical_snapshot(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = self._question(ledger)
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=NY12,
            rationale="planted",
        )
        assert "tail_audit" in snap.metadata
        assert snap.metadata["tail_audit"]["unearned_mass"] > 0

    def test_require_outcome_paths_blocks_unearned_tail(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = self._question(ledger)
        with pytest.raises(ValidationError, match="unearned tail mass"):
            ledger.create_snapshot(
                question_id=q.id,
                probability_or_distribution=NY12,
                rationale="planted",
                require_outcome_paths=True,
            )

    def test_require_outcome_paths_passes_when_paths_named(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = self._question(ledger)
        paths = {
            **NY12_PATHS,
            "Conway": "credible surprise poll + endorsement cascade",
        }
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=NY12,
            rationale="planted",
            outcome_paths=paths,
            require_outcome_paths=True,
        )
        assert snap.metadata["tail_audit"]["passes"] is True

    def test_exploratory_categorical_is_exempt(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = self._question(ledger)
        # Exploratory snapshots skip every commit gate, including this one.
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=NY12,
            rationale="scratch",
            forecast_origin="exploratory",
            require_outcome_paths=True,
        )
        assert snap.forecast_origin == "exploratory"

    def test_binary_forecast_unaffected(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = ledger.create_question(
            title="Will the FOMC cut at the December 2026 meeting?",
            resolution_criteria="Resolves YES if the Dec 2026 FOMC statement lowers the target range.",
        )
        snap = ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.6,
            rationale="planted",
            require_outcome_paths=True,  # no-op for binary
        )
        assert "tail_audit" not in snap.metadata
