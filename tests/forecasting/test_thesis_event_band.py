"""Thesis EVENT-PROBABILITY BAND — the honest interval ON the headline itself.

``simulate_thesis_event`` returns a POINT P(event): it conditions on member
POINT probabilities and a POINT rho, so it can only ever be a dot. For an
all-binary thesis (a Senate control tracker) the mean-index band is honestly
WITHHELD too (binary members carry no calibrated 0..1-unit dispersion). The
operator therefore sees a headline with no interval at all.

:func:`forecasting.thesis.simulate_thesis_event_band` fixes that by propagating
PARAMETER uncertainty — each member probability perturbed in logit space (using
the member's own published interval where it has one, else a documented default
width) and rho jittered over a sensitivity range — through the SAME
Gaussian-copula event MC, and reports p10/p50/p90 of the event probability.

These tests pin the honest invariants as hard checks: tighter inputs → tighter
band, a wide member → wider band, more rho spread → wider band, the point
headline is ALWAYS inside its own band (central-in-band), point-only members are
propagated with the documented default width (never a fabricated zero), and each
backend is seed-deterministic.
"""

from __future__ import annotations

import pytest

from forecasting import thesis as thesis_math
from forecasting.thesis import simulate_thesis_event, simulate_thesis_event_band


# ── helpers ──────────────────────────────────────────────────────────────────


def _binary(member_id, p, *, direction="support", weight=1.0, **extra):
    row = {
        "member_id": member_id,
        "title": member_id.upper(),
        "kind": "binary",
        "direction": direction,
        "weight": weight,
        "probability": p,
    }
    row.update(extra)
    return row


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


def _width(band) -> float:
    return band.p90 - band.p10


# Modest draws keep the suite snappy; effect sizes below are large enough that
# the parameter signal dominates the residual (CRN-cancelled) MC noise.
_FAST = dict(inner_draws=2500, param_draws=160)


# ── VALIDATION: tighter member uncertainty → tighter band ────────────────────


def test_tighter_members_give_a_tighter_band():
    # Toss-up-heavy thesis (most band-sensitive): shrink the per-member logit
    # width and the event band must shrink with it.
    members = [_binary(chr(97 + i), 0.5) for i in range(6)]
    event = {"kind": "count_threshold", "threshold": 3}
    tight = simulate_thesis_event_band(members, event, rho=0.3, seed=42, sigma_logit=0.10, rho_spread=0.0, **_FAST)
    wide = simulate_thesis_event_band(members, event, rho=0.3, seed=42, sigma_logit=0.60, rho_spread=0.0, **_FAST)
    assert _width(tight) < _width(wide)


def test_one_wide_member_widens_the_band():
    # All members publish a NARROW interval except one, which publishes a WIDE
    # one. The single wide member must widen the whole event band.
    narrow_ci = [0.45, 0.55]  # ~±5pp
    wide_ci = [0.20, 0.80]    # ~±30pp
    all_narrow = [_binary(chr(97 + i), 0.5, p_ci90=narrow_ci) for i in range(6)]
    one_wide = [_binary(chr(97 + i), 0.5, p_ci90=(wide_ci if i == 0 else narrow_ci)) for i in range(6)]
    event = {"kind": "count_threshold", "threshold": 3}
    base = simulate_thesis_event_band(all_narrow, event, rho=0.3, seed=7, rho_spread=0.0, **_FAST)
    widened = simulate_thesis_event_band(one_wide, event, rho=0.3, seed=7, rho_spread=0.0, **_FAST)
    assert _width(widened) > _width(base)
    # And the wide member's interval was actually consumed (not the default).
    assert widened.members_with_interval == 6 and widened.members_defaulted == 0


# ── VALIDATION: more rho spread → wider band (rho is a judgement call) ────────


def test_more_rho_spread_widens_the_band():
    members = [_binary(chr(97 + i), 0.45 + 0.02 * i) for i in range(6)]
    event = {"kind": "count_threshold", "threshold": 3}
    tight_rho = simulate_thesis_event_band(members, event, rho=0.4, seed=11, sigma_logit=0.2, rho_spread=0.02, **_FAST)
    wide_rho = simulate_thesis_event_band(members, event, rho=0.4, seed=11, sigma_logit=0.2, rho_spread=0.40, **_FAST)
    assert _width(wide_rho) > _width(tight_rho)


# ── central-in-band: the point headline is ALWAYS inside its own band ─────────


def test_central_in_band_holds_for_internal_point():
    members = [_binary(chr(97 + i), 0.3 + 0.08 * i) for i in range(5)]
    band = simulate_thesis_event_band(members, {"kind": "count_threshold", "threshold": 2}, rho=0.35, seed=3, **_FAST)
    assert band.p10 <= band.center <= band.p90
    assert band.p10 <= band.p50 <= band.p90


def test_central_in_band_brackets_an_explicit_headline_center():
    # The ledger passes the 20k-draw headline as ``center``; the band must bracket
    # THAT, widening minimally with a note when it sits just outside the cloud.
    members = [_binary(chr(97 + i), 0.5) for i in range(5)]
    event = {"kind": "count_threshold", "threshold": 3}
    # A deliberately off-centre headline forces the widen-to-bracket guard.
    band = simulate_thesis_event_band(members, event, rho=0.3, seed=9, center=0.95, **_FAST)
    assert band.p10 <= 0.95 <= band.p90
    assert any("central-in-band" in n for n in band.notes)


def test_band_brackets_the_real_headline_from_the_point_sim():
    # End-to-end honesty: the actual simulate_thesis_event headline is inside the
    # band computed with that headline as the centre.
    members = [_binary(chr(97 + i), 0.30 + 0.09 * i) for i in range(6)]
    event = {"kind": "count_threshold", "threshold": 4}
    point = simulate_thesis_event(members, event, rho=0.35, seed=555)
    band = simulate_thesis_event_band(members, event, rho=0.35, seed=555, center=point.event_probability, **_FAST)
    assert band.p10 <= point.event_probability <= band.p90


# ── unquantified honesty: point-only members use the DOCUMENTED default width ─


def test_point_only_members_use_documented_default_width_not_zero():
    members = [_binary(chr(97 + i), 0.5) for i in range(4)]  # no intervals published
    band = simulate_thesis_event_band(members, {"kind": "any"}, rho=0.3, seed=1, **_FAST)
    assert band.members_defaulted == 4 and band.members_with_interval == 0
    assert band.sigma_logit_default > 0
    # The band is genuinely non-degenerate (a fabricated zero-width dispersion
    # would collapse p10==p90); the default width propagates real uncertainty.
    assert band.p90 > band.p10
    assert any("point probability" in n and "logit" in n for n in band.notes)


def test_member_interval_overrides_the_default():
    members = [_binary("a", 0.5, p_ci90=[0.4, 0.6]), _binary("b", 0.5), _binary("c", 0.5, p_sd=0.05)]
    band = simulate_thesis_event_band(members, {"kind": "any"}, rho=0.3, seed=1, **_FAST)
    # a (ci90) + c (p_sd) publish their own width; b falls back to the default.
    assert band.members_with_interval == 2 and band.members_defaulted == 1


# ── withhold (never fabricate) when nothing participates ──────────────────────


def test_withheld_when_no_binary_member():
    band = simulate_thesis_event_band([_dist("d", 0.5)], {"kind": "any"}, rho=0.2, seed=1)
    assert band.p10 is None and band.p50 is None and band.p90 is None
    assert band.center is None and band.participants == 0
    assert any("withheld" in n for n in band.notes)


def test_distribution_members_do_not_participate_in_the_band():
    members = [_binary("a", 0.6), _dist("cap", 0.5), _binary("b", 0.4)]
    band = simulate_thesis_event_band(members, {"kind": "any"}, rho=0.2, seed=3, **_FAST)
    assert band.participants == 2


# ── determinism (per backend) ─────────────────────────────────────────────────


def test_seed_determinism_numpy():
    members = [_binary(chr(97 + i), 0.4 + 0.05 * i) for i in range(5)]
    event = {"kind": "count_threshold", "threshold": 3}
    a = simulate_thesis_event_band(members, event, rho=0.4, seed=777, **_FAST)
    b = simulate_thesis_event_band(members, event, rho=0.4, seed=777, **_FAST)
    assert a.backend == "numpy"
    assert (a.p10, a.p50, a.p90) == (b.p10, b.p50, b.p90)


def test_seed_determinism_python(monkeypatch):
    monkeypatch.setattr(thesis_math, "_np", None)
    members = [_binary(chr(97 + i), 0.4 + 0.05 * i) for i in range(5)]
    event = {"kind": "count_threshold", "threshold": 3}
    a = simulate_thesis_event_band(members, event, rho=0.4, seed=777, param_draws=24, inner_draws=400)
    b = simulate_thesis_event_band(members, event, rho=0.4, seed=777, param_draws=24, inner_draws=400)
    assert a.backend == "python"
    assert (a.p10, a.p50, a.p90) == (b.p10, b.p50, b.p90)


def test_python_fallback_caps_draws():
    # The pure-python fallback caps draws so it stays snappy offline.
    import forecasting.thesis as tm

    original = tm._np
    tm._np = None
    try:
        members = [_binary(chr(97 + i), 0.5) for i in range(4)]
        band = simulate_thesis_event_band(
            members, {"kind": "any"}, rho=0.3, seed=1, inner_draws=99999, param_draws=99999
        )
        assert band.inner_draws <= tm._EVENT_BAND_INNER_PYTHON
        assert band.param_draws <= tm._EVENT_BAND_OUTER_PYTHON
    finally:
        tm._np = original


def test_different_seed_changes_the_band():
    members = [_binary(chr(97 + i), 0.5) for i in range(6)]
    event = {"kind": "count_threshold", "threshold": 3}
    a = simulate_thesis_event_band(members, event, rho=0.3, seed=1, **_FAST)
    b = simulate_thesis_event_band(members, event, rho=0.3, seed=2, **_FAST)
    assert (a.p10, a.p90) != (b.p10, b.p90)


# ── payload shape ─────────────────────────────────────────────────────────────


def test_payload_is_flat_numeric_event_band_fields():
    members = [_binary(chr(97 + i), 0.5) for i in range(5)]
    band = simulate_thesis_event_band(members, {"kind": "count_threshold", "threshold": 3}, rho=0.3, seed=1, **_FAST)
    payload = band.to_payload()
    assert set(payload) == {"event_p10", "event_p50", "event_p90"}
    assert all(isinstance(v, float) for v in payload.values())
    assert payload["event_p10"] <= payload["event_p50"] <= payload["event_p90"]


def test_withheld_band_has_empty_payload():
    band = simulate_thesis_event_band([_dist("d", 0.5)], {"kind": "any"}, rho=0.2, seed=1)
    assert band.to_payload() == {}
