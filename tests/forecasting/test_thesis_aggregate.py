"""Unit tests for :mod:`forecasting.thesis` — honest thesis aggregation.

The module is pure math (no DB/IO). These tests assert the *honesty*
properties as hard invariants: correlated variance exceeds the naive
independence formula, n_eff < n_members, no signal → withheld (not fabricated),
no calibrated dispersion → band withheld, and direction-flips / staleness
behave exactly as specified.
"""

from __future__ import annotations

import math

import pytest

from forecasting.thesis import ThesisAggregate, aggregate_thesis


# ── helpers ──────────────────────────────────────────────────────────────────


def _binary(member_id, p, weight=1.0, direction="support", as_of=None, **kw):
    return {
        "member_id": member_id,
        "title": kw.pop("title", member_id.upper()),
        "kind": "binary",
        "direction": direction,
        "weight": weight,
        "probability": p,
        "as_of": as_of,
        **kw,
    }


def _dist(member_id, dist, *, target=None, hi_is_good=True, weight=1.0,
          direction="support", as_of=None, **kw):
    return {
        "member_id": member_id,
        "title": member_id.upper(),
        "kind": "distribution",
        "direction": direction,
        "weight": weight,
        "target": target,
        "hi_is_good": hi_is_good,
        "dist": dist,
        "as_of": as_of,
        **kw,
    }


def _naive_independent_var(agg: ThesisAggregate) -> float:
    """sum(w_norm^2 * sigma^2) — the independence formula the module refuses."""

    return sum((c["w_norm"] * c["sigma"]) ** 2 for c in agg.components)


def _correlated_var(agg: ThesisAggregate) -> float:
    wn = [c["w_norm"] for c in agg.components]
    sg = [c["sigma"] for c in agg.components]
    total = 0.0
    for i in range(len(wn)):
        for j in range(len(wn)):
            rij = 1.0 if i == j else agg.rho
            total += wn[i] * wn[j] * rij * sg[i] * sg[j]
    return total


# ── binary-only thesis ───────────────────────────────────────────────────────


def test_binary_only_thesis_basic():
    members = [_binary("a", 0.8, weight=2.0), _binary("b", 0.6, weight=1.0)]
    agg = aggregate_thesis(members)

    assert agg.health is not None and 0.0 < agg.health < 1.0
    assert agg.thesis_score is not None
    # Score is the weighted arithmetic mean: 100*(2*0.8 + 1*0.6)/3.
    assert agg.thesis_score == pytest.approx(100.0 * (2 * 0.8 + 1 * 0.6) / 3.0)
    # Health is the log-odds pool, distinct from the linear score.
    assert agg.health != pytest.approx(agg.thesis_score / 100.0)
    assert agg.coverage == pytest.approx(1.0)
    assert len(agg.components) == 2


def test_binary_only_band_withheld():
    """All-binary members carry no calibrated dispersion → band withheld."""

    agg = aggregate_thesis([_binary("a", 0.8), _binary("b", 0.6)])
    assert agg.band is None
    assert any("band withheld" in n for n in agg.notes)


# ── distributional via PMF ───────────────────────────────────────────────────


def test_distribution_pmf_mass_past_target():
    pmf = [
        {"label": "3.5", "probability": 0.1},
        {"label": "4.0", "probability": 0.2},
        {"label": "4.5", "probability": 0.4},
        {"label": "5.0", "probability": 0.3},
    ]
    # hi_is_good, target 4.0 → mass strictly above 4.0 = 0.4 + 0.3 = 0.7.
    agg = aggregate_thesis([_dist("d", {"pmf": pmf}, target=4.0, hi_is_good=True)])
    comp = agg.components[0]
    assert comp["s_raw"] == pytest.approx(0.7)
    assert "pmf_mass" in comp["flags"]
    assert comp["sigma"] == pytest.approx(math.sqrt(0.7 * 0.3))


def test_distribution_pmf_lo_is_good_flips_side():
    pmf = [
        {"bucket": "3.5", "p": 0.1},
        {"bucket": "4.5", "p": 0.6},
        {"bucket": "5.0", "p": 0.3},
    ]
    # hi_is_good False → good side is values below target 4.0 → only 0.1.
    agg = aggregate_thesis([_dist("d", {"pmf": pmf}, target=4.0, hi_is_good=False)])
    assert agg.components[0]["s_raw"] == pytest.approx(0.1)


# ── distributional via normal-threshold ──────────────────────────────────────


def test_distribution_normal_threshold():
    # Phi((mean-target)/sd) = Phi((4.5-4.0)/0.5) = Phi(1.0) ≈ 0.8413.
    agg = aggregate_thesis([_dist("d", {"mean": 4.5, "sd": 0.5}, target=4.0)])
    comp = agg.components[0]
    assert comp["s_raw"] == pytest.approx(0.8413, abs=1e-3)
    assert "normal_threshold" in comp["flags"]
    # sigma in 0..1 units is the slope phi(z), clamped to [0, 0.5].
    assert 0.0 < comp["sigma"] <= 0.5
    # A single dispersed normal member yields a real band.
    assert agg.band is not None


def test_distribution_normal_threshold_lo_is_good():
    agg = aggregate_thesis([_dist("d", {"mean": 4.5, "sd": 0.5}, target=4.0,
                                   hi_is_good=False)])
    # 1 - Phi(1.0) ≈ 0.1587.
    assert agg.components[0]["s_raw"] == pytest.approx(0.1587, abs=1e-3)


# ── distributional via min-max / point-map ───────────────────────────────────


def test_distribution_min_max_point_map_degenerate():
    # Only a mean + ci90 bounds → bounded index, no sd → degenerate point map.
    agg = aggregate_thesis(
        [_dist("d", {"mean": 6.0, "ci90": [2.0, 10.0]}, hi_is_good=True)]
    )
    comp = agg.components[0]
    # (6 - 2)/(10 - 2) = 0.5.
    assert comp["s_raw"] == pytest.approx(0.5)
    assert "point_map_degenerate" in comp["flags"]
    # NO invented sd → zero band contribution → band withheld.
    assert comp["sigma"] == 0.0
    assert agg.band is None
    assert any("band withheld" in n for n in agg.notes)


def test_distribution_min_max_flips_when_lo_is_good():
    agg = aggregate_thesis(
        [_dist("d", {"mean": 6.0, "ci90": [2.0, 10.0]}, hi_is_good=False)]
    )
    # 1 - 0.5 = 0.5 here (symmetric), use an asymmetric mean to verify flip.
    agg2 = aggregate_thesis(
        [_dist("d", {"mean": 4.0, "ci90": [2.0, 10.0]}, hi_is_good=False)]
    )
    # (4-2)/8 = 0.25 → flipped → 0.75.
    assert agg2.components[0]["s_raw"] == pytest.approx(0.75)


# ── inverted member drags health down ────────────────────────────────────────


def test_inverted_member_contributes_complement():
    # A 0.7 *inverted* member should contribute s_i = 0.3.
    agg = aggregate_thesis([_binary("a", 0.7, direction="inverted")])
    comp = agg.components[0]
    assert comp["s_raw"] == pytest.approx(0.7)
    assert comp["s_i"] == pytest.approx(0.3)
    assert agg.health == pytest.approx(0.3, abs=1e-3)


def test_inverted_member_lowers_health():
    support_only = aggregate_thesis([_binary("a", 0.8), _binary("b", 0.8)])
    with_inverted = aggregate_thesis(
        [_binary("a", 0.8), _binary("b", 0.8, direction="inverted")]
    )
    assert with_inverted.health < support_only.health


# ── staleness ────────────────────────────────────────────────────────────────


def test_stale_member_downweighted_but_kept():
    now = "2026-06-01T00:00:00Z"
    # Member ~60 days old with max_age 45 → in the linear-decay window.
    members = [
        _binary("fresh", 0.9, weight=1.0, as_of="2026-05-31T00:00:00Z"),
        _binary("aging", 0.2, weight=1.0, as_of="2026-04-02T00:00:00Z",
                max_age_days=45),
    ]
    agg = aggregate_thesis(members, now=now)
    aging = next(c for c in agg.components if c["member_id"] == "aging")
    # Down-weighted (w_norm < 0.5) but kept in the breakdown.
    assert 0.0 < aging["w_norm"] < 0.5
    assert aging["status"] == "ok"
    assert agg.coverage < 1.0


def test_member_beyond_two_horizons_is_zeroed_and_flagged():
    now = "2026-06-01T00:00:00Z"
    members = [
        _binary("fresh", 0.9, weight=1.0, as_of="2026-05-31T00:00:00Z"),
        _binary("ancient", 0.1, weight=1.0, as_of="2026-01-01T00:00:00Z",
                max_age_days=45),
    ]
    agg = aggregate_thesis(members, now=now)
    ancient = next(c for c in agg.components if c["member_id"] == "ancient")
    assert ancient["w_norm"] == 0.0
    assert "stale" in ancient["flags"]
    assert ancient["status"] == "stale"


def test_all_stale_withholds_everything():
    now = "2026-06-01T00:00:00Z"
    members = [
        _binary("a", 0.9, as_of="2026-01-01T00:00:00Z", max_age_days=30),
        _binary("b", 0.2, as_of="2026-01-01T00:00:00Z", max_age_days=30),
    ]
    agg = aggregate_thesis(members, now=now)
    assert agg.health is None
    assert agg.thesis_score is None
    assert agg.band is None
    assert agg.coverage == 0.0
    assert agg.n_eff == 0.0
    # Withheld, NOT fabricated — and every member still listed.
    assert any("withheld" in n and "not fabricated" in n for n in agg.notes)
    assert len(agg.components) == 2


# ── single member / weight-0 row ─────────────────────────────────────────────


def test_single_member():
    agg = aggregate_thesis([_binary("solo", 0.65)])
    assert agg.health == pytest.approx(0.65, abs=1e-3)
    assert agg.thesis_score == pytest.approx(65.0)
    assert agg.coverage == pytest.approx(1.0)
    # Leave-one-out on the only contributor is undefined → 0 delta.
    assert agg.components[0]["marginal_health_delta"] == 0.0


def test_weight_zero_row_kept_in_breakdown():
    members = [_binary("a", 0.8, weight=1.0), _binary("z", 0.1, weight=0.0)]
    agg = aggregate_thesis(members)
    zrow = next(c for c in agg.components if c["member_id"] == "z")
    assert zrow["w_norm"] == 0.0
    assert zrow["contribution_pts"] == 0.0
    # The zero-weight member does not move the score.
    assert agg.thesis_score == pytest.approx(80.0)
    assert len(agg.components) == 2


def test_unusable_member_kept_with_status():
    members = [
        _binary("good", 0.8, weight=1.0),
        {"member_id": "bad", "kind": "distribution", "direction": "support",
         "weight": 1.0, "dist": {}, "as_of": None},
    ]
    agg = aggregate_thesis(members)
    bad = next(c for c in agg.components if c["member_id"] == "bad")
    assert bad["status"] == "unusable"
    assert "unusable" in bad["flags"]
    assert bad["w_norm"] == 0.0
    # Usable member still drives the result.
    assert agg.thesis_score == pytest.approx(80.0)


# ── rho handling ─────────────────────────────────────────────────────────────


def test_rho_zero_only_honored_when_explicit_float():
    members = [_dist("d1", {"mean": 4.5, "sd": 0.5}, target=4.0),
               _dist("d2", {"mean": 4.2, "sd": 0.6}, target=4.0)]
    agg0 = aggregate_thesis(members, rho=0.0)
    assert agg0.rho == 0.0
    # With rho=0 the correlated var collapses to the naive independent var.
    assert _correlated_var(agg0) == pytest.approx(_naive_independent_var(agg0))


def test_default_rho_is_not_independence():
    members = [_dist("d1", {"mean": 4.5, "sd": 0.5}, target=4.0),
               _dist("d2", {"mean": 4.2, "sd": 0.6}, target=4.0)]
    agg = aggregate_thesis(members)  # default rho
    assert agg.rho == pytest.approx(0.4)


def test_rho_estimate_string():
    members = [_dist("d1", {"mean": 4.9, "sd": 0.5}, target=4.0),   # high s
               _dist("d2", {"mean": 3.5, "sd": 0.5}, target=4.0)]   # low s
    agg = aggregate_thesis(members, rho="estimate")
    # rho = clamp(0.6 - 0.25*spread, 0, 0.95); spread > 0 → rho < 0.6.
    assert 0.0 <= agg.rho < 0.6


def test_rho_invalid_string_raises():
    with pytest.raises(ValueError):
        aggregate_thesis([_binary("a", 0.5)], rho="nonsense")


# ── honest variance: correlated > naive independent ──────────────────────────


def test_correlated_var_exceeds_naive_independent_default_rho():
    members = [_dist("d1", {"mean": 4.5, "sd": 0.5}, target=4.0, weight=1.0),
               _dist("d2", {"mean": 4.3, "sd": 0.4}, target=4.0, weight=1.0),
               _dist("d3", {"mean": 4.1, "sd": 0.6}, target=4.0, weight=1.0)]
    agg = aggregate_thesis(members)  # rho=0.4 default
    corr = _correlated_var(agg)
    naive = _naive_independent_var(agg)
    assert corr > naive
    # And the band must reflect the (larger) correlated variance.
    assert agg.band is not None
    q05, q50, q95 = agg.band
    assert q05 <= q50 <= q95


# ── n_eff < n_members ────────────────────────────────────────────────────────


def test_n_eff_below_n_members_under_correlation():
    members = [_dist("d1", {"mean": 4.5, "sd": 0.5}, target=4.0),
               _dist("d2", {"mean": 4.3, "sd": 0.4}, target=4.0),
               _dist("d3", {"mean": 4.1, "sd": 0.6}, target=4.0)]
    agg = aggregate_thesis(members)  # correlated
    assert agg.n_eff < len(members)
    assert agg.n_eff > 1.0


def test_n_eff_equals_n_members_when_independent_and_equal_weight():
    members = [_dist("d1", {"mean": 4.5, "sd": 0.5}, target=4.0, weight=1.0),
               _dist("d2", {"mean": 4.3, "sd": 0.4}, target=4.0, weight=1.0)]
    agg = aggregate_thesis(members, rho=0.0)
    assert agg.n_eff == pytest.approx(2.0)


# ── contributions sum to score ───────────────────────────────────────────────


def test_contributions_sum_to_score():
    members = [
        _binary("a", 0.8, weight=2.0),
        _dist("b", {"mean": 4.5, "sd": 0.5}, target=4.0, weight=1.0),
        _binary("c", 0.4, weight=1.0, direction="inverted"),
        _binary("z", 0.9, weight=0.0),
    ]
    agg = aggregate_thesis(members)
    total = sum(c["contribution_pts"] for c in agg.components)
    assert total == pytest.approx(agg.thesis_score, abs=1e-9)


# ── leave-one-out marginal signs ─────────────────────────────────────────────


def test_leave_one_out_marginal_sign_sensible():
    # b is bullish (high s_i), c is bearish (low s_i).
    members = [
        _binary("a", 0.6, weight=1.0),
        _binary("b", 0.95, weight=1.0),   # raises health
        _binary("c", 0.10, weight=1.0),   # lowers health
    ]
    agg = aggregate_thesis(members)
    by_id = {c["member_id"]: c for c in agg.components}
    # Removing a bullish member would lower health → its presence raised it →
    # marginal_health_delta = health(all) - health(without) > 0.
    assert by_id["b"]["marginal_health_delta"] > 0
    assert by_id["c"]["marginal_health_delta"] < 0


# ── coverage in (0, 1] ───────────────────────────────────────────────────────


def test_coverage_in_unit_interval():
    now = "2026-06-01T00:00:00Z"
    members = [
        _binary("fresh", 0.8, weight=1.0, as_of="2026-05-30T00:00:00Z"),
        _binary("aging", 0.5, weight=1.0, as_of="2026-04-10T00:00:00Z",
                max_age_days=45),
    ]
    agg = aggregate_thesis(members, now=now)
    assert 0.0 < agg.coverage <= 1.0


def test_coverage_one_when_all_fresh():
    agg = aggregate_thesis([_binary("a", 0.8), _binary("b", 0.6)])
    assert agg.coverage == pytest.approx(1.0)


# ── spread summary + payload ─────────────────────────────────────────────────


def test_spread_summary_orders_and_iqr():
    members = [_binary("a", 0.2), _binary("b", 0.5), _binary("c", 0.9)]
    agg = aggregate_thesis(members)
    s = agg.spread
    assert s["min"] == pytest.approx(0.2)
    assert s["max"] == pytest.approx(0.9)
    assert s["median"] == pytest.approx(0.5)
    assert s["iqr"] == pytest.approx(s["p75"] - s["p25"])


def test_to_payload_omits_band_keys_when_withheld():
    agg = aggregate_thesis([_binary("a", 0.8), _binary("b", 0.6)])
    payload = agg.to_payload()
    assert "q05" not in payload and "q95" not in payload
    assert payload["health"] == agg.health
    assert payload["thesis_score"] == agg.thesis_score


def test_to_payload_includes_band_keys_when_present():
    agg = aggregate_thesis([_dist("d", {"mean": 4.5, "sd": 0.5}, target=4.0)])
    payload = agg.to_payload()
    assert "q05" in payload and "q50" in payload and "q95" in payload


def test_empty_members_withholds():
    agg = aggregate_thesis([])
    assert agg.health is None
    assert agg.thesis_score is None
    assert agg.coverage == 0.0
    assert agg.components == []
