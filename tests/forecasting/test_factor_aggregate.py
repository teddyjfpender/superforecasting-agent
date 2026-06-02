"""Unit tests for :mod:`forecasting.factor` — honest factor-return aggregation.

The module is pure math (no DB/IO). These tests assert the *honesty* properties
as hard invariants: correlated variance exceeds the naive independence formula,
n_eff < n_constituents, no usable constituent → withheld (not fabricated), a
missing ``sd`` contributes zero variance (no invented dispersion), the downside
is a left-tail return (not a fabricated max-drawdown), and direction-flips /
staleness behave exactly as specified.
"""

from __future__ import annotations

import math

import pytest

from forecasting.factor import FactorAggregate, aggregate_factor

# A fixed "now" so staleness is deterministic (no datetime.now is ever called).
NOW = "2026-06-01T00:00:00Z"


def _c(member_id, weight, mean, sd, *, direction="long", as_of=NOW, **extra):
    """Build a constituent dict with sensible defaults."""

    base = {
        "member_id": member_id,
        "title": member_id.upper(),
        "weight": weight,
        "direction": direction,
        "as_of": as_of,
        "max_age_days": None,
        "mean": mean,
        "sd": sd,
    }
    base.update(extra)
    return base


def _naive_independent_var(agg: FactorAggregate) -> float:
    """Σ (w_norm σ)² — the independence formula we deliberately refuse."""

    return sum(
        (comp["w_norm"] * comp["sigma"]) ** 2
        for comp in agg.components
        if comp["sigma"] is not None
    )


# ── Basic shape: factor mean between constituent means ───────────────────────


def test_long_basket_mean_between_constituents():
    basket = [
        _c("a", 1.0, 8.0, 4.0),
        _c("b", 1.0, 12.0, 5.0),
        _c("c", 1.0, 10.0, 3.0),
    ]
    agg = aggregate_factor(basket, now=NOW)

    assert agg.mean is not None and agg.sd is not None
    # mu_f is a convex combination of {8, 12, 10} → strictly inside [8, 12].
    assert 8.0 < agg.mean < 12.0
    # Equal weights → simple average == 10.
    assert agg.mean == pytest.approx(10.0)
    assert agg.sd > 0.0
    assert agg.q50 == pytest.approx(agg.mean)


def test_short_constituent_flips_mean_sign():
    long_only = aggregate_factor(
        [_c("a", 1.0, 10.0, 3.0), _c("b", 1.0, 10.0, 3.0)], now=NOW
    )
    with_short = aggregate_factor(
        [_c("a", 1.0, 10.0, 3.0), _c("b", 1.0, 10.0, 3.0, direction="short")],
        now=NOW,
    )
    # The short name contributes -10 instead of +10, dragging mu_f down.
    assert with_short.mean is not None and long_only.mean is not None
    assert with_short.mean < long_only.mean
    assert with_short.mean == pytest.approx(0.0)  # +10 and -10 cancel
    # The signed mean is recorded negative for the short constituent.
    short_comp = next(c for c in with_short.components if c["member_id"] == "b")
    assert short_comp["mu"] == pytest.approx(-10.0)
    assert short_comp["direction"] == "short"


def test_wide_sd_widens_band():
    tight = aggregate_factor(
        [_c("a", 1.0, 10.0, 2.0), _c("b", 1.0, 10.0, 2.0)], now=NOW
    )
    wide = aggregate_factor(
        [_c("a", 1.0, 10.0, 2.0), _c("b", 1.0, 10.0, 8.0)], now=NOW
    )
    assert wide.sd > tight.sd
    # Wider sd → wider [q05, q95] interval around the same mean.
    assert (wide.q95 - wide.q05) > (tight.q95 - tight.q05)
    assert wide.mean == pytest.approx(tight.mean)


# ── Staleness ────────────────────────────────────────────────────────────────


def test_stale_constituent_down_weighted():
    # `b` is ~60 days old vs a 45-day horizon → decayed (fresh in (0.15, 1)).
    basket = [
        _c("a", 1.0, 6.0, 3.0),
        _c("b", 1.0, 20.0, 3.0, as_of="2026-04-02T00:00:00Z"),
    ]
    agg = aggregate_factor(basket, now=NOW)
    b = next(c for c in agg.components if c["member_id"] == "b")
    a = next(c for c in agg.components if c["member_id"] == "a")
    assert b["status"] == "decayed"
    assert 0.0 < b["w_norm"] < a["w_norm"]   # fresh `a` carries more weight
    assert agg.coverage < 1.0                 # down-weighting reduces coverage
    # mu_f is pulled toward the fresh constituent (6) away from the simple avg 13.
    assert agg.mean is not None and agg.mean < 13.0


def test_all_stale_withheld_not_fabricated():
    old = "2026-01-01T00:00:00Z"  # > 2*45 days before NOW → fully stale
    basket = [
        _c("a", 1.0, 10.0, 3.0, as_of=old),
        _c("b", 2.0, 5.0, 2.0, as_of=old),
    ]
    agg = aggregate_factor(basket, now=NOW)
    assert agg.mean is None
    assert agg.sd is None
    assert agg.q05 is None and agg.q50 is None and agg.q95 is None
    assert agg.downside is None and agg.cvar is None
    assert agg.coverage == 0.0
    assert agg.n_eff == 0.0
    assert any("withheld" in n for n in agg.notes)
    # Every constituent is still listed (auditability), even when withheld.
    assert len(agg.components) == 2
    assert agg.to_payload() == {"coverage": 0.0, "n_eff": 0.0}


# ── Single constituent & weight-0 ────────────────────────────────────────────


def test_single_constituent():
    agg = aggregate_factor([_c("solo", 1.0, 7.0, 4.0)], now=NOW)
    assert agg.mean == pytest.approx(7.0)
    assert agg.sd == pytest.approx(4.0)        # n=1 → factor sd == its own sd
    assert agg.n_eff == pytest.approx(1.0)
    assert len(agg.components) == 1
    assert agg.components[0]["contribution"] == pytest.approx(7.0)


def test_weight_zero_kept_in_components():
    basket = [
        _c("a", 1.0, 10.0, 3.0),
        _c("z", 0.0, 99.0, 50.0),  # zero weight: ignored numerically, kept listed
    ]
    agg = aggregate_factor(basket, now=NOW)
    z = next(c for c in agg.components if c["member_id"] == "z")
    assert z["w_norm"] == pytest.approx(0.0)
    assert z["contribution"] == pytest.approx(0.0)
    assert len(agg.components) == 2
    # The weight-0 name does not move the factor mean/sd.
    assert agg.mean == pytest.approx(10.0)
    assert agg.sd == pytest.approx(3.0)


# ── Correlation honesty ──────────────────────────────────────────────────────


def test_rho_zero_honored_only_when_explicit_float():
    basket = [_c("a", 1.0, 10.0, 4.0), _c("b", 1.0, 8.0, 4.0)]
    # Explicit float 0.0 → independence honored.
    indep = aggregate_factor(basket, rho=0.0, now=NOW)
    assert indep.rho == 0.0
    # With rho=0, Var collapses to the independence sum.
    assert indep.sd**2 == pytest.approx(_naive_independent_var(indep))

    # Default (no rho passed) is correlated, NOT independence.
    default = aggregate_factor(basket, now=NOW)
    assert default.rho == pytest.approx(0.4)
    assert default.sd > indep.sd


def test_default_rho_variance_exceeds_naive_independent():
    basket = [
        _c("a", 1.0, 10.0, 4.0),
        _c("b", 1.0, 8.0, 5.0),
        _c("c", 1.0, 12.0, 3.0),
    ]
    agg = aggregate_factor(basket, now=NOW)  # default rho=0.4
    naive = _naive_independent_var(agg)
    # Correlation-honest: correlated variance strictly exceeds independence.
    assert agg.sd**2 > naive


def test_n_eff_below_constituent_count():
    basket = [
        _c("a", 1.0, 10.0, 4.0),
        _c("b", 1.0, 8.0, 5.0),
        _c("c", 1.0, 12.0, 3.0),
    ]
    agg = aggregate_factor(basket, now=NOW)
    # Three co-moving names buy less than three independent samples.
    assert agg.n_eff < 3.0
    assert agg.n_eff > 1.0


def test_rho_estimate_is_mild_constant():
    basket = [_c("a", 1.0, 10.0, 4.0), _c("b", 1.0, 9.0, 4.0)]
    agg = aggregate_factor(basket, rho="estimate", now=NOW)
    assert 0.0 <= agg.rho <= 0.95
    # Tight dispersion → higher implied co-movement than the 0.4 default.
    assert agg.rho > 0.4
    assert any("estimated" in n for n in agg.notes)


def test_rho_invalid_string_raises():
    with pytest.raises(ValueError):
        aggregate_factor([_c("a", 1.0, 10.0, 3.0)], rho="bogus", now=NOW)


# ── Contribution / coverage invariants ───────────────────────────────────────


def test_contributions_sum_to_mean():
    basket = [
        _c("a", 2.0, 10.0, 4.0),
        _c("b", 1.0, 6.0, 3.0, direction="short"),
        _c("c", 3.0, 4.0, 2.0),
    ]
    agg = aggregate_factor(basket, now=NOW)
    total = sum(c["contribution"] for c in agg.components)
    assert total == pytest.approx(agg.mean)


def test_coverage_in_unit_interval():
    fresh = aggregate_factor([_c("a", 1.0, 10.0, 3.0)], now=NOW)
    assert 0.0 < fresh.coverage <= 1.0
    assert fresh.coverage == pytest.approx(1.0)


# ── No invented dispersion ───────────────────────────────────────────────────


def test_missing_sd_contributes_zero_variance():
    with_sd = aggregate_factor(
        [_c("a", 1.0, 10.0, 4.0), _c("b", 1.0, 8.0, 4.0)], now=NOW
    )
    # `b` has no sd → flagged no_dispersion, sigma 0, contributes 0 to variance.
    one_missing = aggregate_factor(
        [_c("a", 1.0, 10.0, 4.0), _c("b", 1.0, 8.0, None)], now=NOW
    )
    b = next(c for c in one_missing.components if c["member_id"] == "b")
    assert b["sigma"] == pytest.approx(0.0)
    assert "no_dispersion" in b["flags"]
    # The factor sd is strictly smaller when a name lacks dispersion — and it is
    # NOT fabricated: only `a` (sigma 4, w_norm 0.5) drives variance.
    assert one_missing.sd < with_sd.sd
    assert one_missing.sd == pytest.approx(0.5 * 4.0)  # w_norm_a * sigma_a
    # `b` still contributes to the mean (its mean is known, just not its spread).
    assert one_missing.mean == pytest.approx(9.0)


def test_all_missing_sd_degenerate_band():
    agg = aggregate_factor(
        [_c("a", 1.0, 10.0, None), _c("b", 1.0, 6.0, None)], now=NOW
    )
    assert agg.sd == pytest.approx(0.0)
    assert agg.q05 == pytest.approx(agg.mean)
    assert agg.q95 == pytest.approx(agg.mean)
    assert agg.downside == pytest.approx(agg.mean)
    assert agg.cvar == pytest.approx(agg.mean)
    assert any("degenerate" in n for n in agg.notes)


# ── Downside ordering under normality ────────────────────────────────────────


def test_downside_ordering_cvar_le_downside_le_mean():
    basket = [
        _c("a", 1.0, 10.0, 4.0),
        _c("b", 1.0, 8.0, 5.0),
    ]
    agg = aggregate_factor(basket, now=NOW)
    assert agg.cvar is not None and agg.downside is not None and agg.mean is not None
    # Expected shortfall is deeper in the left tail than the 5% quantile,
    # which in turn sits below the mean.
    assert agg.cvar <= agg.downside <= agg.mean
    assert agg.downside == pytest.approx(agg.q05)
    # Exact normal relationships.
    assert agg.downside == pytest.approx(agg.mean - 1.645 * agg.sd)
    es_mult = (math.exp(-0.5 * 1.645**2) / math.sqrt(2 * math.pi)) / 0.05
    assert agg.cvar == pytest.approx(agg.mean - es_mult * agg.sd)


def test_normal_approx_flagged():
    agg = aggregate_factor([_c("a", 1.0, 10.0, 3.0)], now=NOW)
    assert "normal_approx" in agg.notes


def test_to_payload_keys_present_when_usable():
    agg = aggregate_factor([_c("a", 1.0, 10.0, 3.0)], now=NOW)
    payload = agg.to_payload()
    for key in (
        "factor_mean",
        "factor_sd",
        "volatility",
        "q05",
        "q50",
        "q95",
        "downside",
        "cvar",
        "coverage",
        "n_eff",
    ):
        assert key in payload
    assert payload["volatility"] == payload["factor_sd"]
