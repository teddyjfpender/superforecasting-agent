"""Origin gating for active calibration-lesson adjustments.

Regression: the default-on measured-bias correction is derived from the LIVE
stratum (synthesize_bias_lessons measures forecast_origin='live'), so it must NOT
silently fold into closed-book `backtest` / `imported_baseline` commits — that
would contaminate the very benchmark that grounds can_claim_live_superforecasting.
"""

from __future__ import annotations

from forecasting.learning import should_apply_active_lessons


def test_live_defaults_on():
    assert should_apply_active_lessons(None, "live") is True
    assert should_apply_active_lessons(None, None) is True  # unset origin == live


def test_backtest_and_imported_default_off():
    assert should_apply_active_lessons(None, "backtest") is False
    assert should_apply_active_lessons(None, "imported_baseline") is False


def test_explicit_opt_in_overrides_backtest_default():
    assert should_apply_active_lessons(True, "backtest") is True
    assert should_apply_active_lessons(True, "imported_baseline") is True


def test_explicit_opt_out_wins_for_live():
    assert should_apply_active_lessons(False, "live") is False


def test_exploratory_is_never_adjusted_even_when_forced():
    assert should_apply_active_lessons(None, "exploratory") is False
    assert should_apply_active_lessons(True, "exploratory") is False
