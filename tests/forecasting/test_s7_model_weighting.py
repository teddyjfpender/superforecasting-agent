"""S7.5 track-record panelist weighting.

Reuses the existing track_record math (shrink_edge / edge_to_weight) but keys on
the panelist MODEL and scores each against the OUTCOME with the per-question
cross-model mean as the reference. Covers:
  * cold start (below the resolved-sample gate) → no weights → equal-weighted quorum;
  * post-sample measured weights (good model > 1, laggard < 1);
  * run_quorum consuming the weights (aggregate shifts, weights echoed);
  * the config gate (off ⇒ equal).
"""

from __future__ import annotations

import json

from forecasting.ledger import ForecastLedger
from forecasting.quorum import run_quorum
from forecasting.quorum_jobs import _track_record_weights_enabled

CRITERIA = "Resolves YES if the named official source reports the condition on the close date."


def _ledger(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "s7w.db"))
    lg.initialize_schema()
    return lg


def _plant_resolved_panels(ledger, *, n, good=0.85, bad=0.35, outcome="yes"):
    """``n`` resolved YES questions, each with a panel run where model
    ``good/model`` sits close to the outcome and ``bad/model`` lags it."""
    for i in range(n):
        q = ledger.create_question(
            title=f"Will planted market #{i} resolve yes?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        ledger.record_panel_run(
            question_id=q.id,
            estimates=[
                {"perspective": "good/model", "agent_model": "good/model", "probability": good},
                {"perspective": "bad/model", "agent_model": "bad/model", "probability": bad},
            ],
            trim=0,
        )
        ledger.resolve_question(question_id=q.id, outcome=outcome, auto_score=True)


class TestModelTrackRecord:
    def test_cold_start_returns_no_weights(self, tmp_path):
        ledger = _ledger(tmp_path)
        _plant_resolved_panels(ledger, n=6)  # below the default gate (10)
        records = {r["name"]: r for r in ledger.model_track_record()}
        assert records  # observations exist
        assert all(r["status"] == "insufficient_track_record" for r in records.values())
        assert all(r["recommended_weight"] == 1.0 for r in records.values())
        # No measured weights → dispatcher defaults everyone to 1.0.
        assert ledger.recommended_model_weights() == {}

    def test_measured_weights_after_sample(self, tmp_path):
        ledger = _ledger(tmp_path)
        _plant_resolved_panels(ledger, n=12)  # clears the gate
        weights = ledger.recommended_model_weights()
        assert set(weights) == {"good/model", "bad/model"}
        assert weights["good/model"] > 1.0  # beat the pack
        assert weights["bad/model"] < 1.0  # lagged the pack
        # Shrinkage keeps no model at the clip extremes on a modest sample.
        assert 1.0 < weights["good/model"] < 4.0

    def test_empty_ledger_no_records(self, tmp_path):
        ledger = _ledger(tmp_path)
        assert ledger.model_track_record() == []
        assert ledger.recommended_model_weights() == {}


class TestQuorumConsumesWeights:
    def _runner(self, table):
        def runner(model, system, user):
            if "JUDGE" in system:
                return json.dumps({"probability": 0.5, "rationale": "j"})
            return json.dumps({"probability": table[model], "rationale": "r"})

        return runner

    def test_weights_shift_aggregate_and_are_echoed(self):
        table = {"good/model": 0.30, "bad/model": 0.70}
        weights = {"good/model": 2.0, "bad/model": 0.5}
        weighted = run_quorum(
            question_title="Will the weighted pool move?",
            resolution_criteria="Resolves YES if X.",
            models=list(table),
            runner=self._runner(table),
            judge_model=None,
            trim=0,
            model_weights=weights,
        )
        equal = run_quorum(
            question_title="Will the weighted pool move?",
            resolution_criteria="Resolves YES if X.",
            models=list(table),
            runner=self._runner(table),
            judge_model=None,
            trim=0,
            model_weights=None,
        )
        # Equal weights on a symmetric pair ≈ 0.5; upweighting the 0.30 model pulls
        # the aggregate below it.
        assert equal.aggregate_probability == 0.5 or abs(equal.aggregate_probability - 0.5) < 1e-6
        assert weighted.aggregate_probability < equal.aggregate_probability
        # The applied weights are echoed so the operator sees why.
        assert weighted.model_weights_used == {"good/model": 2.0, "bad/model": 0.5}
        assert equal.model_weights_used == {}
        # Round-trips to a serialisable dict.
        json.dumps(weighted.to_dict())

    def test_default_equal_when_no_weights(self):
        table = {"a/x": 0.4, "b/y": 0.6}
        res = run_quorum(
            question_title="Will the default stay equal?",
            resolution_criteria="Resolves YES if X.",
            models=list(table),
            runner=self._runner(table),
            judge_model=None,
            trim=0,
        )
        assert all(f.weight == 1.0 for f in res.forecasts)
        assert res.model_weights_used == {}

    def test_unmeasured_model_defaults_to_one(self):
        table = {"known/model": 0.3, "stranger/model": 0.7}
        # Only one model has a measured weight; the other must default to 1.0.
        weights = {"known/model": 1.5}
        res = run_quorum(
            question_title="Will the stranger stay at 1.0?",
            resolution_criteria="Resolves YES if X.",
            models=list(table),
            runner=self._runner(table),
            judge_model=None,
            trim=0,
            model_weights=weights,
        )
        by_model = {f.model: f.weight for f in res.forecasts}
        assert by_model["known/model"] == 1.5
        assert by_model["stranger/model"] == 1.0
        assert res.model_weights_used == {"known/model": 1.5}


class TestConfigGate:
    def test_spec_off_disables(self):
        assert _track_record_weights_enabled({"track_record_weights": False}) is False

    def test_spec_on_enables(self):
        assert _track_record_weights_enabled({"track_record_weights": True}) is True

    def test_default_on_when_unspecified(self, monkeypatch):
        # No spec key + default config → ON (harmless-by-construction on cold start).
        assert _track_record_weights_enabled({}) is True
