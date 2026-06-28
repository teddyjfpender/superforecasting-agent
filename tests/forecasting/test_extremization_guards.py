"""AIA P2.3 — extremization safety guards.

The machinery that makes ACTIVATING the terminal Platt calibration (the sqrt(3)
variance-matching slope) safe + sharp on our own data:

  * ``platt_scale_anchored`` — extremize the deviation from the reference-class
    BASE RATE (the form that outperformed all 0.5-anchored methods on 899
    Metaculus questions); identity at alpha=1, == ``platt_scale`` at base_rate=0.5;
  * a pure help/hurt gate that forces alpha=1.0 on a wrong-sided scope;
  * ``diagnose_hedging`` — recommend alpha>1 ONLY when center-heavy AND
    under-confident;
  * ``sweep_platt_alpha`` / ``expected_brier_delta_by_bin`` — read-only sweeps.

HARD INVARIANT pinned here: NO default moved — the per-question alpha_extremize
default is still exactly 1.0 (no extremization happens by default).
"""

from __future__ import annotations

import math
import random

import pytest

from forecasting.bayes_toolkit import (
    PLATT_ALPHA_VARIANCE_MATCH,
    inv_logit,
    logit,
    platt_scale,
    platt_scale_anchored,
)
from forecasting.calibration_bias import (
    Observation,
    diagnose_hedging,
    extremization_alpha_gate,
    leaned_side_hit_rate,
    signed_calibration_error,
)
from forecasting.backtesting import (
    expected_brier_delta_by_bin,
    sweep_platt_alpha,
)
from forecasting.models import ValidationError


# ── 1. platt_scale_anchored ──────────────────────────────────────────────────


def test_platt_scale_anchored_identity_at_alpha_one():
    rng = random.Random(1)
    for _ in range(200):
        p = rng.uniform(0.01, 0.99)
        base = rng.uniform(0.05, 0.95)
        assert platt_scale_anchored(p, base, alpha=1.0) == pytest.approx(p, abs=1e-9)


def test_platt_scale_anchored_reduces_to_platt_at_base_half():
    rng = random.Random(2)
    for _ in range(200):
        p = rng.uniform(0.01, 0.99)
        alpha = rng.uniform(0.3, 3.0)
        assert platt_scale_anchored(p, 0.5, alpha=alpha) == pytest.approx(
            platt_scale(p, alpha=alpha, d=1.0), abs=1e-12
        )


def test_platt_scale_anchored_matches_formula():
    rng = random.Random(3)
    for _ in range(200):
        p = rng.uniform(0.01, 0.99)
        base = rng.uniform(0.02, 0.98)
        alpha = rng.uniform(0.3, 3.0)
        anchor = logit(base)
        expected = inv_logit(anchor + alpha * (logit(p) - anchor))
        assert platt_scale_anchored(p, base, alpha=alpha) == pytest.approx(expected, abs=1e-12)


def test_platt_scale_anchored_extremizes_away_from_base_rate_not_half():
    # With a base rate of 0.2 and a forecast slightly above it, alpha>1 pushes
    # AWAY from 0.2 (upward), even though it is still below 0.5. A 0.5-anchored
    # Platt would push the same point DOWN (toward 0.5). This is the key behaviour.
    base = 0.2
    p = 0.3
    anchored = platt_scale_anchored(p, base, alpha=1.6)
    centered = platt_scale(p, alpha=1.6, d=1.0)
    assert anchored > p          # away from the base rate (0.2), upward
    assert centered < p          # toward 0.5, downward
    # base_rate itself is the fixed point of the anchored form.
    assert platt_scale_anchored(base, base, alpha=2.4) == pytest.approx(base, abs=1e-12)
    # A point below the base rate is pushed further down (away from base).
    assert platt_scale_anchored(0.1, base, alpha=1.6) < 0.1


def test_platt_scale_anchored_guards_inputs():
    with pytest.raises(ValidationError):
        platt_scale_anchored(0.5, 0.3, alpha=0.0)
    with pytest.raises(ValidationError):
        platt_scale_anchored(0.5, 0.3, alpha=-1.0)
    # base_rate / p at the exact boundary are clamped interior, not a crash:
    # the result stays a finite probability in [0,1] instead of raising on a
    # log(0) / inf log-odds.
    out = platt_scale_anchored(1.0, 0.0, alpha=1.5)
    assert 0.0 <= out <= 1.0 and math.isfinite(out)


# ── 2. help/hurt gate ────────────────────────────────────────────────────────


def _wrong_sided_obs(n: int = 40, hit: float = 0.4) -> list[Observation]:
    """Forecasts leaning YES at 0.7 that land YES only ``hit`` of the time."""
    rng = random.Random(10)
    out: list[Observation] = []
    for _ in range(n):
        outcome = 1.0 if rng.random() < hit else 0.0
        out.append(Observation(p_yes=0.7, outcome=outcome))
    return out


def _strong_sided_obs(n: int = 40, hit: float = 0.85) -> list[Observation]:
    rng = random.Random(11)
    out: list[Observation] = []
    for _ in range(n):
        outcome = 1.0 if rng.random() < hit else 0.0
        out.append(Observation(p_yes=0.7, outcome=outcome))
    return out


def test_gate_forces_identity_on_wrong_sided_scope():
    obs = _wrong_sided_obs(hit=0.4)
    hit_rate, mean_forecast, ess = leaned_side_hit_rate(obs)
    assert hit_rate is not None and hit_rate <= 0.5  # wrong-sided
    verdict = extremization_alpha_gate(PLATT_ALPHA_VARIANCE_MATCH, obs)
    assert verdict["permitted"] is False
    assert verdict["allowed_alpha"] == 1.0


def test_gate_forces_identity_on_correct_sided_but_overconfident_scope():
    # The MAJOR fix: a scope leaning 0.7 that is right only ~0.6 of the time is
    # correct-sided (hit>0.5) BUT over-confident — extremizing it RAISES Brier, so
    # the gate must block it. Gating on hit_rate>0.5 would have wrongly permitted it.
    obs = _strong_sided_obs(hit=0.6)
    hit_rate, mean_forecast, ess = leaned_side_hit_rate(obs)
    assert hit_rate is not None and hit_rate > 0.5  # correct-sided
    assert hit_rate < mean_forecast  # but over-confident (claims ~0.7, right ~0.6)
    verdict = extremization_alpha_gate(PLATT_ALPHA_VARIANCE_MATCH, obs)
    assert verdict["permitted"] is False
    assert verdict["allowed_alpha"] == 1.0


def test_gate_permits_extremization_on_underconfident_scope():
    obs = _strong_sided_obs(hit=0.85)
    hit_rate, mean_forecast, ess = leaned_side_hit_rate(obs)
    assert hit_rate is not None and hit_rate > mean_forecast  # under-confident
    verdict = extremization_alpha_gate(PLATT_ALPHA_VARIANCE_MATCH, obs)
    assert verdict["permitted"] is True
    assert verdict["allowed_alpha"] == pytest.approx(PLATT_ALPHA_VARIANCE_MATCH)


def test_gate_passes_alpha_at_or_below_one_through_unchanged():
    # alpha<=1 is never extremization; the gate only ever removes it.
    obs = _wrong_sided_obs()
    for a in (1.0, 0.7):
        verdict = extremization_alpha_gate(a, obs)
        assert verdict["allowed_alpha"] == a
        assert verdict["permitted"] is True


def test_gate_forces_identity_below_sample_floor():
    obs = _strong_sided_obs(n=4)  # below the ESS floor
    verdict = extremization_alpha_gate(PLATT_ALPHA_VARIANCE_MATCH, obs, min_ess=12.0)
    assert verdict["permitted"] is False
    assert verdict["allowed_alpha"] == 1.0


# ── 3. diagnose_hedging ──────────────────────────────────────────────────────


def _center_heavy_underconfident() -> list[Observation]:
    """Forecasts clustered near 0.5 (hedged) whose leaned side comes true MORE
    often than stated — the under-confident, center-ward-hedging signature."""
    rng = random.Random(20)
    out: list[Observation] = []
    for _ in range(60):
        # Lean slightly YES (0.58) but outcome lands YES 85% of the time => SCE<0.
        outcome = 1.0 if rng.random() < 0.85 else 0.0
        out.append(Observation(p_yes=0.58, outcome=outcome))
    return out


def _sharp_overconfident() -> list[Observation]:
    """Confident forecasts (0.9) whose leaned side comes true LESS often
    (0.6) — sharp + over-confident: must NOT be told to extremize."""
    rng = random.Random(21)
    out: list[Observation] = []
    for _ in range(60):
        outcome = 1.0 if rng.random() < 0.6 else 0.0
        out.append(Observation(p_yes=0.9, outcome=outcome))
    return out


def test_diagnose_hedging_flags_center_ward_under_confidence():
    obs = _center_heavy_underconfident()
    diag = diagnose_hedging(obs)
    assert diag.center_ward_hedge is True
    assert diag.center_mass_fraction >= 0.5
    assert diag.sce is not None and diag.sce < 0.0


def test_diagnose_hedging_does_not_flag_sharp_overconfident():
    obs = _sharp_overconfident()
    diag = diagnose_hedging(obs)
    # Sharp (no central mass) AND over-confident (SCE>0) — never extremize.
    assert diag.center_ward_hedge is False
    assert diag.center_mass_fraction < 0.5
    assert diag.sce is not None and diag.sce > 0.0


def test_diagnose_hedging_does_not_flag_center_heavy_but_overconfident():
    # Center-heavy but the leaned side comes true LESS often than stated (SCE>0):
    # the high central mass alone is NOT enough — must also be under-confident.
    rng = random.Random(22)
    obs = [
        Observation(p_yes=0.58, outcome=(1.0 if rng.random() < 0.45 else 0.0))
        for _ in range(60)
    ]
    diag = diagnose_hedging(obs)
    assert diag.center_mass_fraction >= 0.5  # center-heavy
    assert diag.sce is not None and diag.sce > 0.0  # over-confident
    assert diag.center_ward_hedge is False


# ── 4. sweep_platt_alpha + expected_brier_delta_by_bin ───────────────────────


def _hedged_fixture(n: int = 400) -> list[tuple[float, float]]:
    """A synthetically HEDGED, correct-sided set: forecasts pulled toward 0.5
    relative to the true probability, so sharpening (alpha>1) lowers Brier."""
    rng = random.Random(30)
    pairs: list[tuple[float, float]] = []
    for _ in range(n):
        true_p = rng.choice([0.15, 0.3, 0.7, 0.85])
        outcome = 1.0 if rng.random() < true_p else 0.0
        # Hedged report: shrink the true log-odds toward 0 (toward 0.5).
        raw = inv_logit(0.55 * logit(true_p))
        pairs.append((raw, outcome))
    return pairs


def test_sweep_finds_min_brier_alpha_above_one_on_hedged_fixture():
    pairs = _hedged_fixture()
    result = sweep_platt_alpha(pairs)
    assert result["n"] == len(pairs)
    assert result["best_alpha"] is not None
    # A hedged-but-correct-sided set is de-hedged by alpha>1.
    assert result["best_alpha"] > 1.0
    # Extremizing beats the identity here.
    assert result["best_brier"] < result["identity_brier"]


def test_sweep_reports_sqrt3_point_and_loo():
    pairs = _hedged_fixture()
    result = sweep_platt_alpha(pairs)
    assert result["alpha_sqrt3"] == pytest.approx(math.sqrt(3.0))
    assert result["brier_at_sqrt3"] is not None
    # brier_at_sqrt3 equals the exact Platt-sqrt(3) mean Brier (not grid-snapped).
    expected = sum(
        (platt_scale(p, alpha=math.sqrt(3.0), d=1.0) - o) ** 2 for p, o in pairs
    ) / len(pairs)
    assert result["brier_at_sqrt3"] == pytest.approx(expected, abs=1e-12)
    # Leave-one-out: the modal per-fold alpha generalizes (>1 on a hedged set), and
    # the honest out-of-sample loo_brier is reported.
    assert result["loo_modal_alpha"] is not None
    assert result["loo_modal_alpha"] > 1.0
    assert result["loo_brier"] is not None


def test_sweep_accepts_observation_objects():
    obs = [Observation(p_yes=p, outcome=o) for p, o in _hedged_fixture(n=120)]
    result = sweep_platt_alpha(obs)
    assert result["n"] == 120
    assert result["best_alpha"] is not None


def test_sweep_empty_is_safe():
    result = sweep_platt_alpha([])
    assert result["n"] == 0
    assert result["best_alpha"] is None
    assert result["alpha_sqrt3"] == pytest.approx(math.sqrt(3.0))


def test_expected_brier_delta_concentrates_in_mid_bins():
    # Hand-built reliability shape: each bin's mean prediction is HEDGED toward
    # 0.5 relative to the observed frequency (under-confident), so alpha>1 helps.
    # The 0.5-straddling bin gains ~nothing (platt fixes 0.5).
    shape = [
        {"lo": 0.15, "hi": 0.25, "ess": 30.0, "mean_predicted": 0.30, "observed_frequency": 0.20},
        {"lo": 0.45, "hi": 0.55, "ess": 30.0, "mean_predicted": 0.50, "observed_frequency": 0.50},
        {"lo": 0.65, "hi": 0.75, "ess": 30.0, "mean_predicted": 0.70, "observed_frequency": 0.80},
    ]
    rows = expected_brier_delta_by_bin(shape, alpha=math.sqrt(3.0))
    by_center = {round((r["lo"] + r["hi"]) / 2, 2): r for r in rows}
    mid_low = by_center[0.20]["brier_delta"]
    middle = by_center[0.50]["brier_delta"]
    mid_high = by_center[0.70]["brier_delta"]
    # The mid bins (0.2-0.3 / 0.65-0.75) gain; the central bin is ~identity.
    assert mid_low > 0
    assert mid_high > 0
    assert abs(middle) < 1e-9
    assert mid_low > abs(middle)
    assert mid_high > abs(middle)


# ── 5. NO default moved — alpha_extremize is still exactly 1.0 ────────────────


def test_alpha_extremize_default_is_still_one_point_zero():
    from forecasting.hooks.thresholds import (
        DEFAULT_ALPHA_EXTREMIZE,
        THRESHOLD_BY_KEY,
        resolve_alpha_extremize,
    )

    # The spec default AND every resolution path return the identity.
    assert DEFAULT_ALPHA_EXTREMIZE == 1.0
    assert THRESHOLD_BY_KEY["alpha_extremize"].default == 1.0
    assert resolve_alpha_extremize(None) == 1.0
    assert resolve_alpha_extremize({}) == 1.0
    assert resolve_alpha_extremize({"forecast_hooks": {"thresholds": {}}}) == 1.0


def test_platt_scale_kernel_default_still_identity():
    # The shared recalibration kernel itself is unchanged: bare platt_scale(p) is
    # the identity, so adding the anchored form moved no default.
    for p in (0.05, 0.25, 0.5, 0.71, 0.93):
        assert platt_scale(p) == pytest.approx(p, abs=1e-9)
