"""Thesis correlation MATRIX (feedback item #6B): members co-move unequally, so a
thesis can supply real pairwise correlations instead of one global scalar rho —
sharpening the honest band + effective-N rather than over/under-counting variance."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.thesis import aggregate_thesis

CRIT = "Resolves to the official value reported by the named source on the close date."
THCRIT = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _dist(member_id: str, mean: float, sd: float, weight: float = 1.0) -> dict:
    return {
        "member_id": member_id,
        "kind": "distribution",
        "direction": "support",
        "weight": weight,
        "dist": {"mean": mean, "sd": sd},
        "target": 0.5,
        "hi_is_good": True,
    }


MEMBERS = [_dist("coding", 0.6, 0.15), _dist("nvidia", 0.55, 0.18), _dist("power", 0.5, 0.2)]


def test_matrix_with_lower_correlation_raises_neff_and_tightens_band():
    scalar = aggregate_thesis(MEMBERS, rho=0.4)
    low = aggregate_thesis(
        MEMBERS, rho=0.4,
        correlation_matrix={"coding:nvidia": 0.1, "nvidia:power": 0.1, "coding:power": 0.1},
    )
    assert scalar.band is not None and low.band is not None
    # Less co-movement than the scalar 0.4 -> more effective independence.
    assert low.n_eff > scalar.n_eff
    assert (low.band[2] - low.band[0]) < (scalar.band[2] - scalar.band[0])
    assert any("matrix" in note for note in low.notes)


def test_unspecified_pairs_fall_back_to_scalar_rho():
    base = aggregate_thesis(MEMBERS, rho=0.4)
    # A matrix that only pins ONE pair leaves the others on the scalar fallback.
    partial = aggregate_thesis(MEMBERS, rho=0.4, correlation_matrix={"coding:nvidia": 0.4})
    assert abs(partial.n_eff - base.n_eff) < 1e-9  # 0.4 == the scalar -> identical


def test_key_formats_are_accepted():
    # frozenset, tuple, "a:b" and "a|b" all key the same pair.
    for key in [frozenset({"coding", "nvidia"}), ("coding", "nvidia"), "coding:nvidia", "coding|nvidia"]:
        agg = aggregate_thesis(MEMBERS, rho=0.4, correlation_matrix={key: 0.1})
        assert any("matrix" in note for note in agg.notes)


def _dist_q(lg, title, mean):
    q = lg.create_question(title=title, resolution_criteria=CRIT, outcome_space=OutcomeSpace(type="distribution", units="x"))
    lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": mean, "sd": 0.15, "q05": mean - 0.25, "q50": mean, "q95": mean + 0.25}, rationale="x")
    return q


def test_ledger_stores_and_applies_pairwise_correlations(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "tc.db"))
    lg.initialize_schema()
    a, b, c = _dist_q(lg, "A?", 0.6), _dist_q(lg, "B?", 0.55), _dist_q(lg, "C?", 0.5)
    th = lg.create_question(title="scarcity thesis", resolution_criteria=THCRIT, outcome_space=OutcomeSpace(type="thesis"))
    for m in (a, b, c):
        lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0, target=0.5)
    base = lg.aggregate_thesis(th.id, commit=False)["payload"]
    for x, y in [(a, b), (b, c), (a, c)]:
        lg.set_thesis_correlation(th.id, x.id, y.id, 0.1)
    low = lg.aggregate_thesis(th.id, commit=False)["payload"]
    # Lower pinned correlation than the scalar 0.4 default -> higher effective N.
    assert low["n_eff"] > base["n_eff"]


def test_set_correlation_rejects_non_members_and_out_of_range(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "tc2.db"))
    lg.initialize_schema()
    a, b = _dist_q(lg, "A?", 0.6), _dist_q(lg, "B?", 0.55)
    stranger = _dist_q(lg, "S?", 0.5)
    th = lg.create_question(title="thesis", resolution_criteria=THCRIT, outcome_space=OutcomeSpace(type="thesis"))
    lg.add_thesis_member(th.id, a.id, direction="support", weight=1.0)
    lg.add_thesis_member(th.id, b.id, direction="support", weight=1.0)
    with pytest.raises(ValidationError):
        lg.set_thesis_correlation(th.id, a.id, stranger.id, 0.3)  # stranger not a member
    with pytest.raises(ValidationError):
        lg.set_thesis_correlation(th.id, a.id, b.id, 1.5)  # out of [0, 0.95]
    with pytest.raises(ValidationError, match="must not contain"):
        lg.set_thesis_correlation(th.id, "a|b", a.id, 0.3)  # '|' would corrupt the stored pair key
