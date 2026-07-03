"""Thesis EVENT-PROBABILITY layer — a thesis as a JOINT THRESHOLD EVENT.

``aggregate_thesis`` reports a mean index (weighted-mean health/score). But a
thesis like "Democrats take back the Senate" is really P(#member successes ≥ K).
Means are damped and threshold-insensitive; correlation only ever entered the
mean's band. :func:`forecasting.thesis.simulate_thesis_event` treats the thesis
as the event it is, via a seeded Gaussian-copula Monte Carlo.

These tests pin the honest invariants as hard checks: the rho=0 MC matches the
EXACT Poisson-binomial within tolerance, high correlation collapses toward
all-or-nothing, a battleground shift moves the event MORE than the mean (the
operator's damping complaint), direction flips + distribution exclusion behave
as specified, and each backend is seed-deterministic.
"""

from __future__ import annotations

import math

import pytest

from forecasting import ForecastLedger
from forecasting import thesis as thesis_math
from forecasting.dashboard import _workspace_thesis, build_thesis_summary
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.thesis import aggregate_thesis, simulate_thesis_event


# ── helpers ──────────────────────────────────────────────────────────────────


def _binary(member_id, p, *, direction="support", weight=1.0):
    return {
        "member_id": member_id,
        "title": member_id.upper(),
        "kind": "binary",
        "direction": direction,
        "weight": weight,
        "probability": p,
    }


def _dist(member_id, mean, sd=0.1):
    return {
        "member_id": member_id,
        "title": member_id.upper(),
        "kind": "distribution",
        "direction": "support",
        "weight": 1.0,
        "dist": {"mean": mean, "sd": sd},
        "target": 0.5,
        "hi_is_good": True,
    }


def _poisson_binomial_ge(ps, K):
    """EXACT P(count >= K) for independent Bernoulli(p_i) via DP convolution."""

    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for k, val in enumerate(dist):
            nxt[k] += val * (1.0 - p)
            nxt[k + 1] += val * p
        dist = nxt
    return sum(dist[K:])


def _mc_tol(result) -> float:
    """MC standard-error-scaled tolerance for the given draw count."""

    return max(0.02, 3.0 / math.sqrt(result.n_draws))


# ── VALIDATION: rho=0 matches the exact Poisson-binomial ─────────────────────


def test_rho_zero_matches_poisson_binomial():
    ps = [0.5, 0.6, 0.4, 0.55, 0.7]
    members = [_binary(chr(97 + i), p) for i, p in enumerate(ps)]
    for K in (1, 2, 3, 4, 5):
        res = simulate_thesis_event(
            members, {"kind": "count_threshold", "threshold": K}, rho=0.0, seed=2024
        )
        exact = _poisson_binomial_ge(ps, K)
        assert abs(res.event_probability - exact) < _mc_tol(res), (
            f"K={K}: MC {res.event_probability:.4f} vs exact {exact:.4f}"
        )


def test_rho_zero_matches_poisson_binomial_pure_python(monkeypatch):
    monkeypatch.setattr(thesis_math, "_np", None)
    ps = [0.45, 0.55, 0.5, 0.6]
    members = [_binary(chr(97 + i), p) for i, p in enumerate(ps)]
    res = simulate_thesis_event(
        members, {"kind": "count_threshold", "threshold": 2}, rho=0.0, seed=99
    )
    assert res.backend == "python" and res.n_draws == 2_000
    exact = _poisson_binomial_ge(ps, 2)
    assert abs(res.event_probability - exact) < _mc_tol(res)


# ── VALIDATION: high correlation collapses toward all-or-nothing ─────────────


def test_high_correlation_collapses_toward_all_or_nothing():
    # Five identical p=0.5 members. Independent: P(any) >> P(all). As rho -> 0.95
    # the latent draws co-move, so members succeed/fail together and P(count>=K)
    # for every K collapses toward the single common latent's ~0.5.
    members = [_binary(chr(97 + i), 0.5) for i in range(5)]
    ind_any = simulate_thesis_event(members, {"kind": "any"}, rho=0.0, seed=7).event_probability
    ind_all = simulate_thesis_event(members, {"kind": "all"}, rho=0.0, seed=7).event_probability
    cor_any = simulate_thesis_event(members, {"kind": "any"}, rho=0.95, seed=7).event_probability
    cor_all = simulate_thesis_event(members, {"kind": "all"}, rho=0.95, seed=7).event_probability

    ind_gap = ind_any - ind_all
    cor_gap = cor_any - cor_all
    assert ind_gap > 0.9                    # independence: any≈0.97, all≈0.03
    assert cor_gap < 0.5 * ind_gap          # correlation collapses the gap
    # Both correlated tails sit near the common p (all-or-nothing on one draw).
    assert 0.3 < cor_any < 0.7 and 0.3 < cor_all < 0.7


# ── VALIDATION: a battleground shift moves the EVENT more than the MEAN ───────


def test_battleground_shift_moves_event_more_than_mean():
    # The operator's damping complaint, as a hard test. A toss-up seat crossing
    # 50% barely nudges the weighted-mean index but pivots the threshold event.
    base = [_binary("a", 0.70), _binary("b", 0.62), _binary("c", 0.50),
            _binary("d", 0.46), _binary("e", 0.30)]
    shifted = [_binary("a", 0.70), _binary("b", 0.62), _binary("c", 0.58),
               _binary("d", 0.46), _binary("e", 0.30)]
    ev0 = simulate_thesis_event(base, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=1).event_probability
    ev1 = simulate_thesis_event(shifted, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=1).event_probability
    mean0 = aggregate_thesis(base, rho=0.3).thesis_score / 100.0
    mean1 = aggregate_thesis(shifted, rho=0.3).thesis_score / 100.0
    assert abs(ev1 - ev0) > abs(mean1 - mean0)


def test_top_sensitivity_is_the_tossup_race():
    # "Which race matters": the seat nearest 50% moves P(event) most.
    members = [_binary("safe_d", 0.9), _binary("tossup", 0.5),
               _binary("lean_r", 0.35), _binary("safe_r", 0.1)]
    res = simulate_thesis_event(
        members, {"kind": "count_threshold", "threshold": 2}, rho=0.2, seed=11
    )
    top = res.top_sensitivities(1)[0]
    assert top["member_id"] == "tossup"


# ── VALIDATION: direction flips (a counter member's success = NOT the event) ──


def test_direction_flip_inverts_effective_probability():
    support = [_binary("a", 0.6), _binary("b", 0.6), _binary("c", 0.8, direction="support")]
    inverted = [_binary("a", 0.6), _binary("b", 0.6), _binary("c", 0.8, direction="inverted")]
    p_support = simulate_thesis_event(support, {"kind": "all"}, rho=0.0, seed=5).event_probability
    p_inverted = simulate_thesis_event(inverted, {"kind": "all"}, rho=0.0, seed=5).event_probability
    # P(all) = 0.6*0.6*0.8 = 0.288 vs 0.6*0.6*(1-0.8) = 0.072.
    assert abs(p_support - 0.288) < 0.02
    assert abs(p_inverted - 0.072) < 0.02


def test_counter_member_sensitivity_is_negative():
    inverted = [_binary("a", 0.6), _binary("b", 0.6), _binary("c", 0.8, direction="inverted")]
    res = simulate_thesis_event(inverted, {"kind": "all"}, rho=0.0, seed=5)
    counter = next(s for s in res.sensitivities if s["member_id"] == "c")
    # Raising the underlying member's probability LOWERS the (inverted) event.
    assert counter["sensitivity"] < 0


# ── VALIDATION: distribution members excluded with an honest note ─────────────


def test_distribution_member_excluded_with_note():
    members = [_binary("a", 0.6), _dist("cap", 0.5), _binary("b", 0.4)]
    res = simulate_thesis_event(members, {"kind": "any"}, rho=0.2, seed=3)
    assert res.participants == 2
    assert any(e["member_id"] == "cap" for e in res.excluded)
    assert any("distribution member" in n for n in res.notes)


def test_unusable_binary_excluded():
    members = [_binary("a", 0.6), {"member_id": "b", "title": "B", "kind": "binary",
                                   "direction": "support", "weight": 1.0, "probability": None}]
    res = simulate_thesis_event(members, {"kind": "any"}, rho=0.0, seed=1)
    assert res.participants == 1
    assert any(e["reason"] == "no usable probability" for e in res.excluded)


# ── event-kind resolution + guards ───────────────────────────────────────────


def test_all_and_any_resolve_thresholds():
    members = [_binary(chr(97 + i), 0.5) for i in range(4)]
    assert simulate_thesis_event(members, {"kind": "all"}, rho=0.0, seed=1).event["threshold"] == 4
    assert simulate_thesis_event(members, {"kind": "any"}, rho=0.0, seed=1).event["threshold"] == 1


def test_withheld_when_no_binary_member():
    res = simulate_thesis_event([_dist("d", 0.5)], {"kind": "any"}, rho=0.2, seed=1)
    assert res.event_probability is None
    assert res.participants == 0
    assert any("withheld" in n for n in res.notes)


def test_count_threshold_requires_threshold():
    with pytest.raises(ValueError):
        simulate_thesis_event([_binary("a", 0.5)], {"kind": "count_threshold"}, rho=0.0)


def test_invalid_event_kind_raises():
    with pytest.raises(ValueError):
        simulate_thesis_event([_binary("a", 0.5)], {"kind": "nonsense"}, rho=0.0)


def test_count_distribution_summary_keys():
    members = [_binary(chr(97 + i), 0.5) for i in range(6)]
    res = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=2)
    assert set(res.count_distribution) == {"p10", "p50", "p90", "mean"}
    cd = res.count_distribution
    assert cd["p10"] <= cd["p50"] <= cd["p90"]
    assert 0.0 <= cd["mean"] <= 6.0


# ── determinism (per backend) ────────────────────────────────────────────────


def test_seed_determinism_numpy():
    members = [_binary(chr(97 + i), 0.4 + 0.05 * i) for i in range(5)]
    a = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.4, seed=777)
    b = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.4, seed=777)
    assert a.backend == "numpy"
    assert a.event_probability == b.event_probability
    assert a.count_distribution == b.count_distribution


def test_seed_determinism_python(monkeypatch):
    monkeypatch.setattr(thesis_math, "_np", None)
    members = [_binary(chr(97 + i), 0.4 + 0.05 * i) for i in range(5)]
    a = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.4, seed=777)
    b = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.4, seed=777)
    assert a.backend == "python"
    assert a.event_probability == b.event_probability


def test_different_seed_changes_result():
    members = [_binary(chr(97 + i), 0.5) for i in range(6)]
    a = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=1)
    b = simulate_thesis_event(members, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=2)
    # Same target, different draws — MC noise means they should differ slightly.
    assert a.event_probability != b.event_probability


def test_pairwise_correlation_matrix_applied():
    members = [_binary("a", 0.6), _binary("b", 0.55), _binary("c", 0.5)]
    res = simulate_thesis_event(
        members, {"kind": "count_threshold", "threshold": 2}, rho=0.4,
        correlation_matrix={"a:b": 0.1}, seed=1,
    )
    assert any("pairwise correlation" in n for n in res.notes)


def test_rho_estimate_string():
    members = [_binary("a", 0.6), _binary("b", 0.5), _binary("c", 0.4)]
    res = simulate_thesis_event(members, {"kind": "any"}, rho="estimate", seed=1)
    assert 0.0 <= res.rho <= 0.95


# ══════════════════════════════════════════════════════════════════════════════
# LEDGER + DASHBOARD integration
# ══════════════════════════════════════════════════════════════════════════════

CRIT = "Resolves to the official value reported by the named source on the close date."
TH = "Aggregate health of the tagged member forecasts; reviewed as members update."


def _senate(tmp_path, probs=(0.75, 0.62, 0.51, 0.48, 0.35)):
    ledger = ForecastLedger(tmp_path / "f.db")
    seats = []
    for i, p in enumerate(probs):
        q = ledger.create_question(title=f"Dem holds seat {i}?", resolution_criteria=CRIT, domain="politics")
        ledger.create_snapshot(question_id=q.id, probability_or_distribution=p, rationale="poll avg")
        seats.append(q)
    thesis = ledger.create_question(
        title="Democrats take back the Senate", resolution_criteria=TH,
        domain="politics", outcome_space=OutcomeSpace(type="thesis"),
    )
    for s in seats:
        ledger.add_thesis_member(thesis.id, s.id, direction="support", weight=1.0)
    return ledger, thesis, seats


def test_set_thesis_event_stores_and_loads(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    spec = ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    assert spec == {"kind": "count_threshold", "threshold": 3}
    reloaded = ledger.get_question(thesis.id)
    assert ledger._thesis_event_spec(reloaded) == {"kind": "count_threshold", "threshold": 3}


def test_set_thesis_event_validation(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    with pytest.raises(ValidationError):
        ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=None)
    with pytest.raises(ValidationError):
        ledger.set_thesis_event(thesis.id, kind="bogus", threshold=1)


def test_clear_thesis_event(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    assert ledger.clear_thesis_event(thesis.id) is True
    assert ledger._thesis_event_spec(ledger.get_question(thesis.id)) is None
    assert ledger.clear_thesis_event(thesis.id) is False


def test_aggregate_stamps_event_probability_alongside_mean_index(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    res = ledger.aggregate_thesis(thesis.id, rho=0.4)
    payload = res["payload"]
    # Event probability rides in the (flat, numeric) snapshot payload as headline.
    assert isinstance(payload["event_probability"], float)
    # The mean-index diagnostics are preserved, not removed.
    assert payload["health"] is not None and payload["thesis_score"] is not None
    # Structured detail lives in the snapshot metadata (payload must stay numeric).
    snap = ledger.get_current_snapshot(thesis.id)
    detail = snap.metadata["event"]
    assert detail["event"]["threshold"] == 3
    assert set(detail["count_distribution"]) == {"p10", "p50", "p90", "mean"}
    assert len(detail["sensitivities"]) == 5


def test_aggregate_event_is_seed_deterministic(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    a = ledger.aggregate_thesis(thesis.id, rho=0.4, now="2026-07-03T00:00:00Z", commit=False)
    b = ledger.aggregate_thesis(thesis.id, rho=0.4, now="2026-07-03T00:00:00Z", commit=False)
    assert a["payload"]["event_probability"] == b["payload"]["event_probability"]


def test_aggregate_without_event_spec_has_no_event_probability(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    res = ledger.aggregate_thesis(thesis.id, rho=0.4)
    assert "event_probability" not in res["payload"]


def test_dashboard_summary_headline_prefers_event(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    ledger.aggregate_thesis(thesis.id, rho=0.4)
    row = next(r for r in build_thesis_summary(ledger=ledger) if r["id"] == thesis.id)
    assert row["event_probability"] is not None
    assert row["headline_probability"] == row["event_probability"]
    assert row["count_distribution"] is not None
    assert row["top_sensitivities"] and len(row["top_sensitivities"]) <= 5


def test_dashboard_summary_headline_falls_back_to_health(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.aggregate_thesis(thesis.id, rho=0.4)  # no event configured
    row = next(r for r in build_thesis_summary(ledger=ledger) if r["id"] == thesis.id)
    assert row["event_probability"] is None
    assert row["headline_probability"] == row["health_probability"]


def test_workspace_thesis_surfaces_event(tmp_path):
    ledger, thesis, _ = _senate(tmp_path)
    ledger.set_thesis_event(thesis.id, kind="count_threshold", threshold=3)
    ledger.aggregate_thesis(thesis.id, rho=0.4)
    ws = _workspace_thesis(ledger, ledger.get_question(thesis.id))
    assert ws["event_probability"] is not None
    assert ws["headline_probability"] == ws["event_probability"]
    assert ws["event"]["threshold"] == 3
    assert ws["count_distribution"] is not None
    assert ws["event_detail"]["participants"] == 5
