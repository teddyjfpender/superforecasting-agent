"""Tests for the Market Models compute engine (forecasting.market_compute)."""

from __future__ import annotations

import importlib

import pytest

import forecasting.market_compute as mc


def test_ols_matches_hand_checked_values():
    # y = 2x + 1 exactly → slope 2, intercept 1, r2 1.0
    out = mc.compute("ols", {"x": [0, 1, 2, 3, 4], "y": [1, 3, 5, 7, 9], "extrapolate_to": [5]})
    assert out["ok"] and not out["degraded"]
    b = out["block"]
    assert b["type"] == "regression"
    assert b["coeffs"][0]["value"] == pytest.approx(2.0, abs=1e-9)
    assert b["intercept"]["value"] == pytest.approx(1.0, abs=1e-9)
    assert b["r2"] == pytest.approx(1.0, abs=1e-9)
    # extrapolation at x=5 → y=11
    assert b["extrapolation"][0]["y"] == pytest.approx(11.0, abs=1e-6)
    assert b["prediction_band"]  # bands present


def test_ols_noisy_slope_and_r2_reasonable():
    out = mc.compute("ols", {"x": [1, 2, 3, 4, 5], "y": [2.1, 3.9, 6.2, 7.8, 10.1]})
    b = out["block"]
    assert b["coeffs"][0]["value"] == pytest.approx(2.0, abs=0.2)
    assert 0.98 < b["r2"] <= 1.0


def test_ols_degrades_on_too_few_points():
    out = mc.compute("ols", {"x": [1], "y": [2]})
    assert out["degraded"] and not out["ok"]
    assert out["block"]["type"] == "finding"


def test_multivariate_recovers_known_plane():
    # y = 3 + 2*x1 - 1*x2
    X = [[1, 1], [2, 1], [1, 2], [3, 2], [2, 3], [4, 1]]
    y = [3 + 2 * a - b for a, b in X]
    out = mc.compute("multivariate", {"X": X, "y": y, "x_labels": ["x1", "x2"], "y_label": "y"})
    assert out["ok"]
    coeffs = {c["name"]: c["value"] for c in out["block"]["coeffs"]}
    assert coeffs["x1"] == pytest.approx(2.0, abs=1e-6)
    assert coeffs["x2"] == pytest.approx(-1.0, abs=1e-6)
    assert out["block"]["intercept"]["value"] == pytest.approx(3.0, abs=1e-6)
    assert out["block"]["r2"] == pytest.approx(1.0, abs=1e-6)


def test_normal_equations_fallback_matches_numpy(monkeypatch):
    # Force the pure-Python solver and confirm it recovers the same plane.
    monkeypatch.setattr(mc, "_np", None)
    X = [[1, 1], [2, 1], [1, 2], [3, 2], [2, 3], [4, 1]]
    y = [3 + 2 * a - b for a, b in X]
    out = mc.compute("multivariate", {"X": X, "y": y, "x_labels": ["x1", "x2"]})
    coeffs = {c["name"]: c["value"] for c in out["block"]["coeffs"]}
    assert coeffs["x1"] == pytest.approx(2.0, abs=1e-6)
    assert coeffs["x2"] == pytest.approx(-1.0, abs=1e-6)


def test_montecarlo_is_seed_reproducible_and_bands_ordered():
    payload = {"start": 100, "drift": 0.0, "vol": 0.05, "steps": 6, "n_paths": 500, "seed": 42}
    a = mc.compute("montecarlo", payload)
    b = mc.compute("montecarlo", dict(payload))
    assert a["block"]["median"] == b["block"]["median"]  # same seed → identical
    band = a["block"]["bands"][0]
    for lo, hi in zip(band["lower"], band["upper"]):
        assert lo <= hi  # percentile band ordered


def test_correlation_perfect_positive():
    out = mc.compute("correlation", {"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]})
    assert out["summary"]["r"] == pytest.approx(1.0, abs=1e-9)


def test_timeseries_trend_extrapolates():
    out = mc.compute("timeseries_trend", {"values": [10, 12, 14, 16], "horizon": 2})
    assert out["ok"]
    assert out["block"]["extrapolation"][0]["y"] == pytest.approx(18.0, abs=1e-6)


def test_advanced_family_degrades_without_statsmodels(monkeypatch):
    monkeypatch.setattr(mc, "_sm", None)
    monkeypatch.setattr(mc, "ensure_econometrics", lambda: mc.backends())
    out = mc.compute("cointegration", {"a": list(range(12)), "b": list(range(12))})
    assert out["degraded"] and "statsmodels" in out["reason"]


def test_backtest_summary_pure_python():
    out = mc.compute("backtest", {"returns": [0.01, -0.02, 0.03, 0.0, 0.01], "signal": [1, 1, 1, 1, 1]})
    assert out["ok"]
    assert out["block"]["type"] == "table"
    assert "total_return" in out["summary"]


def test_module_imports_cleanly():
    importlib.reload(mc)
    assert "ols" in mc.MODEL_TYPES and "arima" in mc.MODEL_TYPES


# ── out-of-sample honesty (backtest) ──────────────────────────────────────────


def test_backtest_in_sample_only_note_and_byte_stable_keys():
    # Old params (no holdout): the existing rows/columns/summary scalars must be
    # byte-identical to the pre-honesty output (stored model_runs read them), and
    # the block must now carry an explicit "in-sample only" honesty note.
    out = mc.compute("backtest", {"returns": [0.01, -0.02, 0.03, 0.0, 0.01], "signal": [1, 1, 1, 1, 1]})
    b = out["block"]
    assert b["type"] == "table"
    assert b["columns"] == [
        {"key": "metric", "label": "Metric"},
        {"key": "value", "label": "Value", "align": "right"},
    ]
    assert b["rows"] == [
        {"metric": "Total return", "value": "3.0%"},
        {"metric": "Sharpe (ann.)", "value": "5.86"},
        {"metric": "Max drawdown", "value": "-2.0%"},
    ]
    assert out["summary"]["total_return"] == pytest.approx(0.02968894, abs=1e-8)
    assert out["summary"]["sharpe"] == pytest.approx(5.8620505255, abs=1e-8)
    assert out["summary"]["max_drawdown"] == pytest.approx(-0.02, abs=1e-12)
    # No holdout keys leak into the summary for old params.
    assert not any(k.startswith(("oos_", "is_", "wf_")) for k in out["summary"])
    assert "in-sample only" in b["note"].lower()


def test_backtest_holdout_separates_in_and_out_of_sample():
    # Overfit-friendly series: strongly positive on the train window, negative on
    # the held-out tail. In-sample metrics must beat out-of-sample by a wide margin.
    returns = [0.10] * 7 + [-0.10] * 3
    out = mc.compute("backtest", {"returns": returns, "signal": [1] * 10, "holdout_fraction": 0.3})
    s = out["summary"]
    assert s["n_train"] == 7 and s["n_test"] == 3
    assert s["holdout_fraction"] == pytest.approx(0.3)
    # 1.1**7 - 1 in-sample vs 0.9**3 - 1 out-of-sample (hand-checkable).
    assert s["is_total_return"] == pytest.approx(1.1 ** 7 - 1.0, abs=1e-9)
    assert s["oos_total_return"] == pytest.approx(0.9 ** 3 - 1.0, abs=1e-9)
    assert s["is_total_return"] > 0.0 > s["oos_total_return"]
    assert s["is_total_return"] != s["oos_total_return"]
    # Side-by-side presentation: new columns + row keys, existing keys untouched.
    b = out["block"]
    assert [c["key"] for c in b["columns"]] == ["metric", "value", "in_sample", "out_of_sample"]
    assert b["rows"][0]["metric"] == "Total return"
    assert b["rows"][0]["in_sample"] == "94.9%" and b["rows"][0]["out_of_sample"] == "-27.1%"
    assert "out-of-sample" in b["note"].lower()


def test_backtest_walk_forward_reports_rolling_oos():
    returns = [0.10] * 7 + [-0.10] * 3
    out = mc.compute("backtest", {"returns": returns, "signal": [1] * 10, "walk_forward": 3})
    s = out["summary"]
    assert s["wf_splits"] == 3
    assert "wf_oos_total_return_mean" in s
    assert "walk-forward" in out["block"]["note"].lower()


# ── out-of-sample honesty (regression) ────────────────────────────────────────


def test_regression_in_sample_only_note_when_no_holdout():
    out = mc.compute("ols", {"x": [0, 1, 2, 3, 4], "y": [1, 3, 5, 7, 9]})
    b = out["block"]
    assert b["validation"] == {"mode": "in_sample_only"}
    assert "in-sample only" in b["note"].lower()
    # Existing keys still present and unchanged in shape.
    assert b["r2"] == pytest.approx(1.0, abs=1e-9)
    assert not any(k in out["summary"] for k in ("oos_rmse", "oos_mae", "interval_coverage"))


def test_regression_holdout_out_of_sample_metrics_and_coverage():
    # A parabola is overfit-friendly for a straight line: a fit on the low-x train
    # window extrapolates badly onto the high-x held-out tail (large OOS error, most
    # held-out points fall OUTSIDE the prediction interval).
    x = list(range(10))
    y = [v * v for v in x]
    out = mc.compute("ols", {"x": x, "y": y, "holdout_fraction": 0.3})
    v = out["block"]["validation"]
    assert v["mode"] == "holdout"
    assert v["n_train"] == 7 and v["n_test"] == 3
    assert v["oos_rmse"] > 0.0 and v["oos_mae"] > 0.0
    # In-sample r2 (linear on a parabola) is high-ish but the OOS error is huge:
    # the held-out RMSE dwarfs the in-sample residual std — fit is not skill.
    assert v["in_sample_r2"] == out["block"]["r2"]
    assert v["oos_rmse"] > out["block"]["residual_std"]
    # Coverage is a fraction in [0, 1]: exactly 1 of the 3 held-out points is inside.
    assert v["interval_coverage"] == pytest.approx(1.0 / 3.0)
    # New OOS scalars mirrored into the summary; old keys still present.
    assert out["summary"]["oos_rmse"] == pytest.approx(v["oos_rmse"])
    assert out["summary"]["interval_coverage"] == pytest.approx(1.0 / 3.0)
    assert "slope" in out["summary"] and "r2" in out["summary"]


def test_regression_holdout_full_interval_coverage_on_clean_line():
    # A perfectly linear series: the train-only refit predicts the held-out tail
    # exactly, so OOS RMSE is ~0 and every held-out point is inside the interval.
    x = list(range(10))
    y = [2 * v + 1 for v in x]
    out = mc.compute("ols", {"x": x, "y": y, "holdout_fraction": 0.3})
    v = out["block"]["validation"]
    assert v["oos_rmse"] == pytest.approx(0.0, abs=1e-9)
    assert v["interval_coverage"] == pytest.approx(1.0)


def test_timeseries_trend_threads_holdout():
    out = mc.compute("timeseries_trend", {"values": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "holdout_fraction": 0.3})
    assert out["block"]["validation"]["mode"] == "holdout"
    assert out["block"]["validation"]["n_test"] == 3


def test_holdout_paths_work_without_numpy_or_scipy(monkeypatch):
    # Force the pure-Python fallbacks (no numpy, no scipy t-quantile) and confirm
    # the new OOS code still computes identical error metrics + a valid coverage.
    monkeypatch.setattr(mc, "_np", None)
    monkeypatch.setattr(mc, "_scipy_stats", None)
    monkeypatch.setattr(mc, "_scipy_stats_probed", True)

    bt = mc.compute("backtest", {"returns": [0.10] * 7 + [-0.10] * 3, "signal": [1] * 10, "holdout_fraction": 0.3})
    assert bt["summary"]["oos_total_return"] == pytest.approx(0.9 ** 3 - 1.0, abs=1e-9)

    x = list(range(10))
    y = [v * v for v in x]
    reg = mc.compute("ols", {"x": x, "y": y, "holdout_fraction": 0.3})
    v = reg["block"]["validation"]
    # RMSE/MAE are backend-independent (no t-quantile); assert they still compute.
    assert v["oos_rmse"] == pytest.approx(23.1589, abs=1e-3)
    assert v["oos_mae"] == pytest.approx(21.6667, abs=1e-3)
    assert 0.0 <= v["interval_coverage"] <= 1.0
