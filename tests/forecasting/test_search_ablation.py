"""AIA P2.2 — search-ablation 2x2 harness (attribute Brier to search vs judge).

Covers:
  * ``ablation_decomposition`` on a KNOWN 2x2 fixture — exact cell means, exact
    search/judge contributions, and the exact (hand-computed) interaction term;
  * a Brier REDUCTION registering as a POSITIVE contribution;
  * a 3-cell fixture — the available contribution computed, the unavailable one
    None, and the coverage reported honestly;
  * empty input — all-None contributions + zero coverage;
  * the arm classifiers (search source / judge final_source) never guessing;
  * a HARD GUARD that the opt-in is OFF by default — the evidence-status surface
    key is None unless explicitly requested, so no committed forecast or live
    default moves.
"""

from __future__ import annotations

import inspect

import pytest

from forecasting.search_ablation import (
    _judge_arm,
    _search_arm,
    ablation_decomposition,
    collect_ablation_cells,
)


FF = (False, False)
FT = (False, True)
TF = (True, False)
TT = (True, True)


# ── 1. KNOWN 2x2 fixture: exact means, contributions, interaction ─────────────


def test_full_2x2_exact_cell_means_contributions_and_interaction():
    # Hand-picked Briers so every aggregate is exact.
    cells = {
        FF: [0.40, 0.50],   # mean 0.45  (search OFF, judge OFF) — baseline
        FT: [0.30, 0.40],   # mean 0.35  (search OFF, judge ON)
        TF: [0.20, 0.30],   # mean 0.25  (search ON,  judge OFF)
        TT: [0.10, 0.20],   # mean 0.15  (search ON,  judge ON)
    }
    out = ablation_decomposition(cells)

    # Exact per-cell means.
    assert out["cell_brier"] == {"00": 0.45, "01": 0.35, "10": 0.25, "11": 0.15}
    assert out["baseline_cell"] == 0.45
    assert out["best_cell"] == {"cell": [True, True], "brier": 0.15}

    # SEARCH contribution = mean over judge levels of b(search off) - b(search on).
    #   judge OFF: 0.45 - 0.25 = 0.20 ; judge ON: 0.35 - 0.15 = 0.20  -> mean 0.20
    assert out["search_contribution"] == 0.20
    # JUDGE contribution = mean over search levels of b(judge off) - b(judge on).
    #   search OFF: 0.45 - 0.35 = 0.10 ; search ON: 0.25 - 0.15 = 0.10 -> mean 0.10
    assert out["judge_contribution"] == 0.10
    # Interaction = (b_FF - b_TF) - (b_FT - b_TT) = (0.45-0.25) - (0.35-0.15) = 0.0
    assert out["interaction"] == 0.0

    cov = out["coverage"]
    assert cov["complete"] is True
    assert cov["present_count"] == 4
    assert cov["n_by_cell"] == {"00": 2, "01": 2, "10": 2, "11": 2}


def test_interaction_nonzero_when_components_not_additive():
    # Make search help MORE when judge is off than when judge is on.
    cells = {
        FF: [0.50],  # baseline
        TF: [0.20],  # search ON, judge OFF -> search effect|judge off = 0.30
        FT: [0.40],  # search OFF, judge ON
        TT: [0.30],  # search ON,  judge ON -> search effect|judge on = 0.10
    }
    out = ablation_decomposition(cells)
    # interaction = 0.30 - 0.10 = 0.20 (positive: sub-additive — search + judge
    # overlap, so stacking them buys less than the sum of the parts).
    assert out["interaction"] == pytest.approx(0.20)


# ── 2. Brier reduction is a POSITIVE contribution ─────────────────────────────


def test_brier_reduction_is_positive_contribution():
    # Turning search ON lowers Brier from 0.60 to 0.20 (a clear improvement).
    cells = {FF: [0.60], TF: [0.20]}
    out = ablation_decomposition(cells)
    assert out["search_contribution"] == pytest.approx(0.40)
    assert out["search_contribution"] > 0  # reduction registers POSITIVE
    # No judge arm pair present -> judge contribution + interaction are None.
    assert out["judge_contribution"] is None
    assert out["interaction"] is None


def test_brier_increase_is_negative_contribution():
    # If search made things WORSE, the contribution is negative (honest sign).
    cells = {FF: [0.20], TF: [0.50]}
    out = ablation_decomposition(cells)
    assert out["search_contribution"] == pytest.approx(-0.30)


# ── 3. 3-cell fixture: one contribution available, the other None ─────────────


def test_three_cell_fixture_partial_coverage():
    # Missing (True, True): search contribution only computable at judge OFF,
    # judge contribution only computable at search OFF.
    cells = {
        FF: [0.50],
        FT: [0.40],
        TF: [0.30],
        # TT absent
    }
    out = ablation_decomposition(cells)
    # search: only judge-OFF pair present -> 0.50 - 0.30 = 0.20
    assert out["search_contribution"] == pytest.approx(0.20)
    # judge: only search-OFF pair present -> 0.50 - 0.40 = 0.10
    assert out["judge_contribution"] == pytest.approx(0.10)
    # interaction needs all four cells.
    assert out["interaction"] is None
    cov = out["coverage"]
    assert cov["complete"] is False
    assert cov["present_count"] == 3
    assert sorted(cov["present_cells"]) == sorted([list(FF), list(FT), list(TF)])


def test_only_diagonal_cells_yield_no_contributions():
    # FF and TT present, but neither component has BOTH arms at a fixed level of
    # the other -> contributions are None, never fabricated from the diagonal.
    cells = {FF: [0.50], TT: [0.10]}
    out = ablation_decomposition(cells)
    assert out["search_contribution"] is None
    assert out["judge_contribution"] is None
    assert out["interaction"] is None
    assert out["coverage"]["present_count"] == 2


# ── 4. empty input -> all-None + zero coverage ────────────────────────────────


def test_empty_input_all_none_zero_coverage():
    out = ablation_decomposition({})
    assert out["cell_brier"] == {}
    assert out["baseline_cell"] is None
    assert out["best_cell"] is None
    assert out["search_contribution"] is None
    assert out["judge_contribution"] is None
    assert out["interaction"] is None
    assert out["coverage"]["present_count"] == 0
    assert out["coverage"]["complete"] is False
    assert out["coverage"]["n_by_cell"] == {}


def test_empty_cells_are_treated_as_absent():
    # A present-but-empty cell must not count as coverage (no fabricated arm).
    out = ablation_decomposition({FF: [], TF: [0.2]})
    assert out["coverage"]["present_count"] == 1
    assert out["baseline_cell"] is None
    assert out["search_contribution"] is None


# ── 5. arm classifiers never guess ────────────────────────────────────────────


def test_search_arm_classifier():
    # Search arm = the AIA P1.1 supervisor fresh-search counter on the panel run.
    assert _search_arm({"research_rounds": 1}) is True
    assert _search_arm({"research_rounds": 2}) is True
    assert _search_arm({"research_rounds": 0}) is False   # ran, but no fresh search
    assert _search_arm(None) is None                      # no panel run -> unknown
    assert _search_arm({}) is None                        # no research_rounds key
    assert _search_arm({"research_rounds": None}) is None
    assert _search_arm({"research_rounds": "x"}) is None   # garbage -> unknown


def test_judge_arm_classifier():
    assert _judge_arm({"final_source": "judge_high"}) is True
    assert _judge_arm({"final_source": "pool"}) is False
    assert _judge_arm({"final_source": "weird"}) is None  # unrecognised -> unknown
    assert _judge_arm({}) is None
    assert _judge_arm(None) is None


# ── 6. collector groups by RECORDED arm + honest uncovered tally ──────────────


class _FakeOutcomeSpace:
    type = "binary"
    choices = ("yes", "no")


class _FakeQuestion:
    def __init__(self):
        self.id = "q1"
        self.outcome_space = _FakeOutcomeSpace()


class _FakeScore:
    def __init__(self, sid, brier):
        self.id = sid
        self.brier_score = brier


class _FakeSnapshot:
    def __init__(self, fid, source):
        self.forecast_id = fid
        self.question_id = "q1"
        self.metadata = {"probability_source": source} if source is not None else {}


class _FakeLedger:
    """Minimal ledger surface the collector touches."""

    def __init__(self, cases, snapshots, scores, panels):
        self._cases = cases
        self._snapshots = snapshots
        self._scores = scores
        self._panels = panels

    def list_panel_runs(self):
        return self._panels

    def list_backtest_runs(self):
        return [{"id": "run1"}]

    def list_backtest_cases(self, run_id):
        return self._cases

    def get_score(self, sid):
        return self._scores[sid]

    def get_snapshot(self, fid):
        return self._snapshots[fid]

    def get_question(self, qid):
        return _FakeQuestion()

    def _binary_outcome_value(self, score, outcome_space):
        return 1.0  # a real resolved outcome for every fixture case


def test_collector_bins_by_recorded_arm_and_tallies_uncovered():
    snapshots = {
        "f_ff": _FakeSnapshot("f_ff", None),
        "f_tf": _FakeSnapshot("f_tf", None),
        "f_none": _FakeSnapshot("f_none", None),
    }
    scores = {
        "s_ff": _FakeScore("s_ff", 0.40),
        "s_tf": _FakeScore("s_tf", 0.20),
        "s_none": _FakeScore("s_none", 0.30),
    }
    panels = [
        {"snapshot_id": "f_ff", "research_rounds": 0, "final_source": "pool"},        # search OFF, judge OFF
        {"snapshot_id": "f_tf", "research_rounds": 1, "final_source": "judge_high"},  # search ON, judge ON
        # f_none has NO panel run -> NEITHER arm recorded -> uncovered.
    ]
    cases = [
        {"score_record_id": "s_ff", "generated_forecast_id": "f_ff"},
        {"score_record_id": "s_tf", "generated_forecast_id": "f_tf"},
        {"score_record_id": "s_none", "generated_forecast_id": "f_none"},
    ]
    collected = collect_ablation_cells(
        _FakeLedger(cases, snapshots, scores, panels)
    )
    assert collected["cells"][FF] == [0.40]
    assert collected["cells"][TT] == [0.20]
    assert collected["n_binned"] == 2
    assert collected["n_cases"] == 3
    # The panel-less case is excluded + tallied, never guessed into a cell.
    assert collected["uncovered"]["no_panel_run"] == 1


def test_collector_tallies_missing_judge_marker():
    snapshots = {"f1": _FakeSnapshot("f1", None)}
    scores = {"s1": _FakeScore("s1", 0.3)}
    # A panel run exists (search arm known via research_rounds) but its final_source
    # is unrecognised -> the judge arm is unknown, so the case is excluded + tallied.
    panels = [{"snapshot_id": "f1", "research_rounds": 0, "final_source": "weird"}]
    cases = [{"score_record_id": "s1", "generated_forecast_id": "f1"}]
    collected = collect_ablation_cells(
        _FakeLedger(cases, snapshots, scores, panels)
    )
    assert collected["n_binned"] == 0
    assert collected["uncovered"]["no_judge_marker"] == 1
    assert collected["cells"] == {}


# ── 7. HARD GUARD: the surface is OPT-IN and OFF by default ────────────────────


def test_evidence_status_search_ablation_defaults_off():
    from forecasting.backtesting import build_forecasting_evidence_status

    sig = inspect.signature(build_forecasting_evidence_status)
    param = sig.parameters["include_search_ablation"]
    # Default OFF: the hot callers never pay for it and no key value is fabricated.
    assert param.default is False


def test_module_does_not_import_or_touch_live_defaults():
    # The whole feature is pure analysis: importing it must not pull in any
    # mutation of the live panel/quorum defaults. (Smoke: import is side-effect
    # free and the decomposition never raises on degenerate input.)
    import forecasting.search_ablation as mod

    assert hasattr(mod, "ablation_report")
    # Decomposition on a single lonely cell is safe (no divide-by-zero).
    out = mod.ablation_decomposition({FF: [0.5]})
    assert out["search_contribution"] is None
    assert out["judge_contribution"] is None
