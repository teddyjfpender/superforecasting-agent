"""Per-question minimum-requirement THRESHOLD threading: a gate reads
ctx.threshold(key) ?? <CONSTANT>, so a per-forecast override changes the gate's
verdict WITHOUT touching the default behaviour (no-override is byte-identical to
the legacy constant)."""

from __future__ import annotations

from forecasting.hooks import HookContext, Severity, run_hooks
from forecasting.hooks.builtins import (
    MAX_WIDTH_RATIO,
    MIN_PERSPECTIVES,
    MIN_SHARPNESS,
    NULL_EXCESS_TOLERANCE,
)
from forecasting.hooks.thresholds import THRESHOLD_BY_KEY, normalize_thresholds


def _ctx(**over) -> HookContext:
    base = dict(question_id="q", forecast_origin="live", event="update")
    base.update(over)
    return HookContext(**base)


def _verdict(ctx, rule_id, severity=Severity.ERROR):
    report = run_hooks(ctx, {rule_id: severity})
    return next((v for v in report.verdicts if v.rule_id == rule_id), None)


def test_quorum_participation_threshold_override_changes_outcome():
    # With the DEFAULT floor (3), a 2-perspective panel fails.
    assert MIN_PERSPECTIVES == 3
    base = _ctx(panel_run_count=1, panel_perspective_count=2, quorum_model_count=0)
    assert _verdict(base, "quorum_participation").passed is False

    # A per-question override LOWERING the floor to 2 makes the SAME forecast pass.
    overridden = _ctx(
        panel_run_count=1,
        panel_perspective_count=2,
        quorum_model_count=0,
        thresholds={"min_perspectives": 2},
    )
    assert _verdict(overridden, "quorum_participation").passed is True

    # And the default-floor behaviour is unchanged for a forecast with no override.
    assert _verdict(base, "quorum_participation").passed is False


def test_width_threshold_override_relaxes_the_warn():
    # 2.0x the range fails the default 1.0x ceiling.
    assert MAX_WIDTH_RATIO == 1.0
    base = _ctx(is_distribution=True, interval_width_ratio=2.0)
    assert _verdict(base, "uncertainty_width_sane", Severity.WARN).passed is False
    # Raising the allowed width to 3.0x passes it.
    loose = _ctx(is_distribution=True, interval_width_ratio=2.0, thresholds={"max_width_ratio": 3.0})
    assert _verdict(loose, "uncertainty_width_sane", Severity.WARN).passed is True


def test_sharpness_threshold_override_changes_confidence_gate():
    assert MIN_SHARPNESS == 0.05
    base = _ctx(sharpness=0.03)
    assert _verdict(base, "confidence_committed", Severity.WARN).passed is False
    # Lowering the minimum sharpness floor below 0.03 passes it.
    loose = _ctx(sharpness=0.03, thresholds={"min_sharpness": 0.01})
    assert _verdict(loose, "confidence_committed", Severity.WARN).passed is True


def test_null_excess_tolerance_override():
    assert NULL_EXCESS_TOLERANCE == 0.05
    base = _ctx(is_categorical=True, tail_null_excess=0.1)
    assert _verdict(base, "tails_justified", Severity.WARN).passed is False
    loose = _ctx(is_categorical=True, tail_null_excess=0.1, thresholds={"null_excess_tolerance": 0.2})
    assert _verdict(loose, "tails_justified", Severity.WARN).passed is True


def test_reasoning_methods_threshold_override():
    req = ("base_rate",)
    base = _ctx(reasoning_methods=("base_rate", "bayesian"), required_reasoning_methods=req, min_reasoning_methods=3)
    assert _verdict(base, "reasoning_composition", Severity.WARN).passed is False
    loose = _ctx(
        reasoning_methods=("base_rate", "bayesian"),
        required_reasoning_methods=req,
        min_reasoning_methods=3,
        thresholds={"min_reasoning_methods": 2},
    )
    assert _verdict(loose, "reasoning_composition", Severity.WARN).passed is True


def test_no_override_is_identical_to_constant():
    # The whole point: a forecast with empty thresholds behaves EXACTLY as the
    # legacy constant did. threshold() returns None → the gate uses its constant.
    ctx = _ctx()
    assert ctx.threshold("min_perspectives") is None
    assert ctx.threshold("max_width_ratio") is None


def test_normalize_thresholds_clamps_and_drops_unknown():
    out = normalize_thresholds({"min_perspectives": 99, "max_width_ratio": -5, "bogus": 1})
    assert out["min_perspectives"] == THRESHOLD_BY_KEY["min_perspectives"].maximum
    assert out["max_width_ratio"] == THRESHOLD_BY_KEY["max_width_ratio"].minimum
    assert "bogus" not in out


def test_looser_flag_direction():
    # lower_looser: below default is looser; higher_looser: above default is looser.
    mp = THRESHOLD_BY_KEY["min_perspectives"]
    assert mp.is_looser(2) is True and mp.is_looser(4) is False
    mw = THRESHOLD_BY_KEY["max_width_ratio"]
    assert mw.is_looser(2.0) is True and mw.is_looser(0.5) is False
