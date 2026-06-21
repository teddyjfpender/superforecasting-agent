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
