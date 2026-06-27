"""Tests for the single Platt recalibration operator (AIA P0.1 + P2.5).

Covers:
  * ``platt_scale`` correctness (identity at alpha=1, monotone, extremizes away
    from 0.5, inverse symmetry, the d-bias term);
  * the ``extremize == platt_scale`` alias (one recalibrator);
  * the Baron-2014 == Platt-of-geometric-mean identity that ``combine_forecasts``
    documents;
  * the BYTE-IDENTICAL no-op invariant for ``aggregate_panel_estimates`` with the
    default (un-configured) per-question alpha.
"""

from __future__ import annotations

import math
import random

import pytest

from forecasting import bayes_toolkit as bt
from forecasting.bayes_toolkit import (
    combine_forecasts,
    extremize,
    inv_logit,
    log_odds_pool,
    logit,
    platt_scale,
)
from forecasting.models import ValidationError
from forecasting.panel import aggregate_panel_estimates


# ── platt_scale correctness ──────────────────────────────────────────────────


def test_platt_scale_signature_defaults():
    # The kernel defaults to the IDENTITY (alpha=1.0, d=1.0) so a bare platt_scale(p)
    # never silently extremizes; the variance-matching slope is an explicit constant.
    import inspect

    from forecasting.bayes_toolkit import PLATT_ALPHA_VARIANCE_MATCH

    sig = inspect.signature(platt_scale)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["p", "alpha", "d"]
    assert params[1].default == pytest.approx(1.0)
    assert params[2].default == pytest.approx(1.0)
    assert PLATT_ALPHA_VARIANCE_MATCH == pytest.approx(math.sqrt(3.0))


def test_platt_scale_identity_at_alpha_one_d_one():
    for p in (0.01, 0.2, 0.37, 0.5, 0.63, 0.8, 0.99):
        assert platt_scale(p, alpha=1.0, d=1.0) == pytest.approx(p, abs=1e-9)


def test_platt_scale_definition_matches_formula():
    # platt_scale(p) == inv_logit(alpha*logit(p) + log(d)) by construction.
    rng = random.Random(7)
    for _ in range(200):
        p = rng.uniform(0.01, 0.99)
        alpha = rng.uniform(0.3, 3.5)
        d = rng.uniform(0.4, 2.5)
        expected = inv_logit(alpha * logit(p) + math.log(d))
        assert platt_scale(p, alpha=alpha, d=d) == pytest.approx(expected, abs=1e-12)


def test_platt_scale_extremizes_away_from_half():
    # alpha > 1 sharpens away from 0.5; alpha < 1 flattens toward 0.5.
    assert platt_scale(0.6, alpha=1.5, d=1.0) > 0.6
    assert platt_scale(0.4, alpha=1.5, d=1.0) < 0.4
    assert 0.5 < platt_scale(0.6, alpha=0.5, d=1.0) < 0.6
    assert 0.4 < platt_scale(0.4, alpha=0.5, d=1.0) < 0.5
    # 0.5 is the fixed point for any slope when d == 1.
    assert platt_scale(0.5, alpha=2.3, d=1.0) == pytest.approx(0.5, abs=1e-12)


def test_platt_scale_is_monotone_in_p():
    prev = -1.0
    for i in range(1, 100):
        p = i / 100.0
        out = platt_scale(p, alpha=1.7, d=1.3)
        assert out > prev
        prev = out


def test_platt_scale_inverse_symmetry():
    # Applying alpha then 1/alpha (d=1) recovers the input (logit is affine).
    rng = random.Random(11)
    for _ in range(100):
        p = rng.uniform(0.02, 0.98)
        alpha = rng.uniform(0.4, 3.0)
        back = platt_scale(platt_scale(p, alpha=alpha, d=1.0), alpha=1.0 / alpha, d=1.0)
        assert back == pytest.approx(p, abs=1e-9)


def test_platt_scale_d_shifts_toward_yes_or_no():
    # d > 1 multiplies the odds (shifts toward YES); d < 1 toward NO.
    assert platt_scale(0.5, alpha=1.0, d=2.0) > 0.5
    assert platt_scale(0.5, alpha=1.0, d=0.5) < 0.5


def test_platt_scale_rejects_nonpositive_alpha_and_d():
    with pytest.raises(ValidationError):
        platt_scale(0.5, alpha=0.0, d=1.0)
    with pytest.raises(ValidationError):
        platt_scale(0.5, alpha=-1.0, d=1.0)
    with pytest.raises(ValidationError):
        platt_scale(0.5, alpha=1.0, d=0.0)


# ── extremize is a thin alias of platt_scale ─────────────────────────────────


def test_extremize_is_platt_scale_alias():
    rng = random.Random(3)
    for _ in range(300):
        p = rng.uniform(0.01, 0.99)
        factor = rng.uniform(0.3, 3.5)
        assert extremize(p, factor) == platt_scale(p, alpha=factor, d=1.0)


def test_extremize_identity_at_factor_one_unchanged():
    # The historical no-op behaviour at factor==1.0 must be exactly preserved.
    for p in (0.05, 0.25, 0.5, 0.71, 0.93):
        assert extremize(p, 1.0) == pytest.approx(p, abs=1e-9)
        # And matches the legacy closed form inv_logit(1.0 * logit(p)).
        assert extremize(p, 1.0) == inv_logit(1.0 * logit(p))


def test_extremize_matches_legacy_closed_form():
    # Pin that extremize is still exactly inv_logit(factor * logit(p)) for callers.
    rng = random.Random(99)
    for _ in range(200):
        p = rng.uniform(0.01, 0.99)
        factor = rng.uniform(0.5, 2.5)
        assert extremize(p, factor) == pytest.approx(
            inv_logit(factor * logit(p)), abs=1e-12
        )


# ── P2.5: Baron-2014 == Platt-of-geometric-mean identity ─────────────────────


def test_log_odds_pool_extremize_is_platt_of_geomean():
    """combine_forecasts(method='log_odds_pool', extremize=a).probability ==
    platt_scale(geometric_mean_of_odds(p_i), a) for random inputs."""
    rng = random.Random(2014)
    for _ in range(200):
        n = rng.randint(2, 6)
        probs = [rng.uniform(0.02, 0.98) for _ in range(n)]
        weights = [rng.uniform(0.1, 3.0) for _ in range(n)]
        alpha = rng.uniform(0.5, 2.5)
        components = [
            {"name": f"s{i}", "p": p, "weight": w}
            for i, (p, w) in enumerate(zip(probs, weights))
        ]
        result = combine_forecasts(
            components, method="log_odds_pool", extremize=alpha
        )
        # geometric mean of odds == log_odds_pool of the components.
        geomean = log_odds_pool(probs, weights)
        expected = platt_scale(geomean, alpha=alpha, d=1.0)
        assert result.probability == pytest.approx(expected, abs=1e-9)


def test_log_odds_pool_at_alpha_one_is_bare_geomean():
    # The identity at alpha==1 reduces to the bare geometric-mean-of-odds pool.
    probs = [0.3, 0.55, 0.7, 0.42]
    weights = [1.0, 2.0, 0.5, 1.5]
    components = [
        {"name": f"s{i}", "p": p, "weight": w}
        for i, (p, w) in enumerate(zip(probs, weights))
    ]
    result = combine_forecasts(components, method="log_odds_pool", extremize=1.0)
    assert result.probability == pytest.approx(log_odds_pool(probs, weights), abs=1e-12)


# ── BYTE-IDENTICAL no-op invariant for the panel terminal calibration ────────


def _five_estimates():
    return [
        {"perspective": "outside", "probability": 0.4},
        {"perspective": "inside", "probability": 0.6},
        {"perspective": "market", "probability": 0.55},
        {"perspective": "red_team", "probability": 0.2},
        {"perspective": "sanity", "probability": 0.5},
    ]


def test_panel_default_alpha_is_byte_identical_to_bare_pool():
    """The hard invariant: aggregate_panel_estimates with the DEFAULT alpha
    (1.0, the un-configured question) is byte-identical to the prior bare pool."""
    for method, trim in (
        ("trimmed_geomean_odds", 1),
        ("log_odds_pool", 0),
        ("median", 0),
    ):
        agg_default = aggregate_panel_estimates(
            _five_estimates(), method=method, trim=trim
        )
        # Reconstruct the historical bare pool directly.
        cleaned = _five_estimates()
        if method == "median":
            from statistics import median

            kept = [e["probability"] for e in cleaned]
            bare = float(median(kept))
        elif method == "trimmed_geomean_odds":
            agg_for_trim = aggregate_panel_estimates(cleaned, method=method, trim=trim)
            kept = [
                e["probability"] for e in agg_for_trim.estimates if not e["trimmed"]
            ]
            bare = log_odds_pool(kept, [1.0] * len(kept))
        else:
            kept = [e["probability"] for e in cleaned]
            bare = log_odds_pool(kept, [1.0] * len(kept))

        # Byte-identical: exact float equality, not approx.
        assert agg_default.aggregate_probability == bare
        # No calibration recorded at the identity.
        assert agg_default.pre_extremize_probability is None
        assert agg_default.applied_alpha == 1.0
        assert agg_default.spread["terminal_calibration_applied"] is False


def test_panel_alpha_extremize_applies_platt_to_pool():
    bare = aggregate_panel_estimates(_five_estimates(), method="log_odds_pool", trim=0)
    calibrated = aggregate_panel_estimates(
        _five_estimates(), method="log_odds_pool", trim=0, alpha_extremize=1.5
    )
    assert calibrated.applied_alpha == pytest.approx(1.5)
    assert calibrated.pre_extremize_probability == pytest.approx(
        bare.aggregate_probability, abs=1e-12
    )
    assert calibrated.aggregate_probability == pytest.approx(
        platt_scale(bare.aggregate_probability, alpha=1.5, d=1.0), abs=1e-12
    )


def test_panel_alpha_extremize_applies_platt_to_the_pool():
    # The per-question alpha_extremize is the ONLY panel-stage recalibration slope
    # (the learned lesson rescale is applied separately downstream, never composed
    # here). A non-identity alpha Platt-scales the bare pool + records the pre value.
    bare = aggregate_panel_estimates(_five_estimates(), method="log_odds_pool", trim=0)
    extr = aggregate_panel_estimates(
        _five_estimates(), method="log_odds_pool", trim=0, alpha_extremize=1.8
    )
    assert extr.applied_alpha == pytest.approx(1.8)
    assert extr.pre_extremize_probability == pytest.approx(bare.aggregate_probability)
    assert extr.aggregate_probability == pytest.approx(
        platt_scale(bare.aggregate_probability, alpha=1.8, d=1.0), abs=1e-12
    )


# ── learning.py logit_scale path is the same operator as before ──────────────


def _legacy_logit(probability: float) -> float:
    # The DELETED private learning._logit (1e-6 clamp).
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def _legacy_sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def test_learning_logit_scale_path_matches_legacy(tmp_path):
    """The learned logit_scale path now routes through platt_scale; its committed
    output must equal the old _sigmoid(_logit(p) * scale) operator (post the
    shared 0.01/0.99 clamp + 6-place round both versions apply)."""
    from forecasting import ForecastLedger
    from forecasting.learning import apply_active_lesson_adjustments

    ledger = ForecastLedger(tmp_path / "learn.db")

    class _Q:
        id = "q_test"
        domain = "politics"
        topics: tuple = ()

        class outcome_space:
            type = "binary"

    # Drive the scale path directly via a fabricated active lesson by monkeypatching
    # the lesson lookup so we don't depend on the synthesis pipeline.
    import forecasting.learning as learning_mod

    orig = learning_mod.active_lessons_for_question
    try:
        # Cover BOTH a sharpening (>1) and a FLATTENING (<1) scale, AND exact 0/1 +
        # near-boundary inputs — the regime where the kernel's 1e-9 clamp would
        # diverge from the legacy 1e-6 clamp without the pre-clamp guard.
        for scale in (1.4, 0.3):
            fake_lessons = [
                {
                    "id": "lesson_scale",
                    "scope_type": "domain",
                    "scope_ref": "politics",
                    "recommended_adjustment": {"logit_scale": scale},
                }
            ]
            learning_mod.active_lessons_for_question = lambda *_a, _l=fake_lessons, **_k: _l
            for raw in (0.55, 0.2, 0.8, 0.37, 0.0, 1.0, 1e-7, 0.9999999):
                payload, _refs, adjustment = apply_active_lesson_adjustments(
                    ledger=ledger,
                    question=_Q(),
                    payload=raw,
                    calibration_lesson_refs=[],
                    calibration_adjustment={},
                )
                legacy = _legacy_sigmoid(_legacy_logit(raw) * scale)
                legacy_committed = round(min(max(legacy, 0.01), 0.99), 6)
                assert adjustment["applied_logit_scale"] == scale
                assert payload == legacy_committed, (scale, raw, payload, legacy_committed)
    finally:
        learning_mod.active_lessons_for_question = orig


def test_learning_module_has_no_private_logit_sigmoid():
    # The duplicates must be DELETED — there is one recalibrator.
    import forecasting.learning as learning_mod

    assert not hasattr(learning_mod, "_logit")
    assert not hasattr(learning_mod, "_sigmoid")


# ── the skipped-terminal-calibration WARN hook ───────────────────────────────


def _hook_ctx(**overrides):
    from forecasting.hooks.spec import HookContext

    base = dict(
        question_id="q1",
        forecast_origin="live",
        event="update",
        panel_linked=True,
        terminal_calibration_present=True,
    )
    base.update(overrides)
    return HookContext(**base)


def test_terminal_calibration_rule_passes_when_present():
    from forecasting.hooks.builtins import _check_terminal_calibration_applied

    ok, _msg, _facts = _check_terminal_calibration_applied(_hook_ctx())
    assert ok is True


def test_terminal_calibration_rule_warns_when_skipped():
    from forecasting.hooks.builtins import (
        _applies_terminal_calibration,
        _check_terminal_calibration_applied,
    )

    ctx = _hook_ctx(terminal_calibration_present=False)
    assert _applies_terminal_calibration(ctx) is True
    ok, msg, _facts = _check_terminal_calibration_applied(ctx)
    assert ok is False
    assert "terminal Platt calibration" in msg


def test_terminal_calibration_rule_skips_without_panel():
    from forecasting.hooks.builtins import _applies_terminal_calibration

    # No panel linked -> nothing to skip, the rule does not apply.
    assert _applies_terminal_calibration(
        _hook_ctx(panel_linked=False, terminal_calibration_present=False)
    ) is False


def test_terminal_calibration_rule_exempts_exploratory():
    from forecasting.hooks.builtins import _applies_terminal_calibration

    ctx = _hook_ctx(forecast_origin="exploratory", terminal_calibration_present=False)
    assert _applies_terminal_calibration(ctx) is False


def test_terminal_calibration_rule_default_severity_is_warn():
    from forecasting.hooks.builtins import _RULE_BY_ID
    from forecasting.hooks.spec import Severity

    rule = _RULE_BY_ID["terminal_calibration_applied"]
    assert rule.default_severity is Severity.WARN


def test_alpha_extremize_threshold_registered():
    from forecasting.hooks.thresholds import (
        DEFAULT_ALPHA_EXTREMIZE,
        THRESHOLD_BY_KEY,
        resolve_alpha_extremize,
    )

    assert "alpha_extremize" in THRESHOLD_BY_KEY
    assert DEFAULT_ALPHA_EXTREMIZE == 1.0
    # Un-configured question resolves to the identity default.
    assert resolve_alpha_extremize(None) == 1.0
    assert resolve_alpha_extremize({}) == 1.0
    # A configured slope is read (and re-clamped) from forecast_hooks.thresholds.
    meta = {"forecast_hooks": {"thresholds": {"alpha_extremize": 1.6}}}
    assert resolve_alpha_extremize(meta) == pytest.approx(1.6)
    # Out-of-range is clamped to the spec bounds, never degenerate.
    meta_hi = {"forecast_hooks": {"thresholds": {"alpha_extremize": 99.0}}}
    assert resolve_alpha_extremize(meta_hi) == THRESHOLD_BY_KEY["alpha_extremize"].maximum
