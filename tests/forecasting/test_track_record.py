"""Component track record: measured Brier edge → advisory ensemble/panel weights.

Pure math gates (shrinkage, clipping, sample-size fail-safe) plus the ledger
integration: plant resolved binary questions whose snapshots carry ensemble
components / panel runs with a KNOWN better-than-aggregate component, and
assert the measured edge surfaces and maps to a >1 advisory weight while
thin samples fail safe to weight 1.0.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.track_record import (
    ComponentObservation,
    edge_to_weight,
    shrink_edge,
    summarize_components,
    weights_by_name,
)

CRITERIA = "Resolves to the official value reported by the named source on the close date."


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------

class TestMath:
    def test_shrink_edge_scales_with_sample_size(self):
        assert shrink_edge(0.10, 0) == 0.0
        small = shrink_edge(0.10, 5)
        large = shrink_edge(0.10, 100)
        assert 0 < small < large < 0.10

    def test_edge_to_weight_clips(self):
        assert edge_to_weight(0.0) == 1.0
        assert edge_to_weight(10.0) == 4.0
        assert edge_to_weight(-10.0) == 0.25
        assert edge_to_weight(0.05) == 1.0 + 4.0 * 0.05

    def test_summarize_gates_small_samples(self):
        obs = [
            ComponentObservation("market", "panel", f"q{i}", 0.05, 0.10)
            for i in range(3)
        ]
        [record] = summarize_components(obs, min_count=5)
        assert record.status == "insufficient_track_record"
        assert record.recommended_weight == 1.0
        assert record.edge_shrunk > 0  # direction still reported

    def test_summarize_measures_sufficient_samples(self):
        obs = [
            ComponentObservation("market", "panel", f"q{i}", 0.05, 0.10)
            for i in range(10)
        ]
        [record] = summarize_components(obs, min_count=5)
        assert record.status == "measured"
        assert record.edge_mean == pytest.approx(0.05)  # aggregate 0.10 - component 0.05
        assert record.recommended_weight > 1.0

    def test_negative_edge_downweights(self):
        obs = [
            ComponentObservation("red_team", "panel", f"q{i}", 0.20, 0.10)
            for i in range(10)
        ]
        [record] = summarize_components(obs, min_count=5)
        assert record.edge_mean < 0
        assert record.recommended_weight < 1.0

    def test_weights_by_name_filters_measured_and_kind(self):
        obs = [
            ComponentObservation("market", "panel", f"q{i}", 0.05, 0.10) for i in range(10)
        ] + [
            ComponentObservation("base_rate", "ensemble", f"q{i}", 0.05, 0.10) for i in range(10)
        ] + [
            ComponentObservation("thin", "panel", "q0", 0.05, 0.10)
        ]
        records = summarize_components(obs, min_count=5)
        weights = weights_by_name(records, kind="panel")
        assert set(weights) == {"market"}


# ---------------------------------------------------------------------------
# Ledger integration
# ---------------------------------------------------------------------------

def _plant_with_components(ledger, *, n, title_prefix):
    """``n`` resolved YES questions: aggregate committed at 0.6, component
    'market' at 0.9 (closer), component 'model' at 0.3 (worse)."""
    for i in range(n):
        q = ledger.create_question(
            title=f"{title_prefix} #{i}?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.6,
            rationale="planted",
            ensemble_components={
                "market": {"probability": 0.9},
                "model": {"probability": 0.3},
            },
        )
        ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)


def _plant_with_panel(ledger, *, n, title_prefix):
    """``n`` resolved YES questions with a panel run: 'outside' beats the
    aggregate, 'red_team' lags it."""
    for i in range(n):
        q = ledger.create_question(
            title=f"{title_prefix} #{i}?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        ledger.record_panel_run(
            question_id=q.id,
            estimates=[
                {"perspective": "outside", "probability": 0.9},
                {"perspective": "inside", "probability": 0.7},
                {"perspective": "red_team", "probability": 0.3},
            ],
            trim=0,
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.65,
            rationale="planted",
        )
        ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)


class TestLedgerTrackRecord:
    def test_empty_ledger_returns_no_records(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        assert ledger.component_track_record() == []

    def test_ensemble_component_edges_measured(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        _plant_with_components(ledger, n=8, title_prefix="Cut")
        records = {row["name"]: row for row in ledger.component_track_record()}
        assert records["market"]["kind"] == "ensemble"
        assert records["market"]["count"] == 8
        assert records["market"]["edge_mean"] > 0
        assert records["market"]["status"] == "measured"
        assert records["market"]["recommended_weight"] > 1.0
        assert records["model"]["edge_mean"] < 0
        assert records["model"]["recommended_weight"] < 1.0

    def test_small_samples_fail_safe(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        _plant_with_components(ledger, n=2, title_prefix="Hike")
        for row in ledger.component_track_record():
            assert row["status"] == "insufficient_track_record"
            assert row["recommended_weight"] == 1.0

    def test_panel_perspective_edges_measured(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        _plant_with_panel(ledger, n=6, title_prefix="Win")
        panel_rows = {
            row["name"]: row
            for row in ledger.component_track_record()
            if row["kind"] == "panel"
        }
        assert set(panel_rows) == {"outside", "inside", "red_team"}
        assert panel_rows["outside"]["edge_mean"] > 0
        assert panel_rows["red_team"]["edge_mean"] < 0

    def test_recommended_weights_advisory_surface(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        _plant_with_panel(ledger, n=6, title_prefix="Pass")
        weights = ledger.recommended_component_weights(kind="panel")
        assert weights["outside"] > 1.0
        assert weights["red_team"] < 1.0
        # ensemble kind excluded from the panel weight map
        assert "market" not in weights

    def test_unresolved_questions_do_not_count(self, tmp_path):
        ledger = ForecastLedger(tmp_path / "f.db")
        q = ledger.create_question(
            title="Will the open question resolve by 2027-01-01?",
            resolution_criteria=CRITERIA,
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale="open",
            ensemble_components={"market": {"probability": 0.5}},
        )
        assert ledger.component_track_record() == []
