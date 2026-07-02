"""Deterministic quant-compute engine for Market Models.

Every number a Market Model presents is computed here, not narrated by the LLM,
so results are auditable + reproducible (seeded). Mirrors the numpy-optional
contract of ``forecasting/bayes_toolkit.py``: pure-Python/stdlib math by default,
NumPy/SciPy accelerate when present (auto-provisioned via the ``forecast.bayes``
lazy group), and the advanced econometrics families use statsmodels when present
(``market.econometrics`` group) else return a typed ``degraded`` result.

Each ``compute(model_type, payload)`` call returns:
    {"ok": bool, "block": <presentation block dict>, "degraded": bool,
     "reason": str, "summary": {<key scalars>}, "backend": {...}}
The ``block`` is a ready-to-render presentation block (see forecasting.presentation).
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any, Sequence

try:  # pragma: no cover - import guard
    import numpy as _np
except Exception:  # pragma: no cover - numpy optional
    _np = None

# ``scipy.stats`` costs ~0.3s to import; keep it off the hot import path and load
# it lazily on first use (or when a diagnostic queries availability). The
# module-global sentinel stays ``None`` until then; ``_scipy_stats_probed``
# records a prior (possibly failing) attempt so we never retry it per call.
_scipy_stats = None
_scipy_stats_probed = False


def _get_scipy_stats():
    """Return ``scipy.stats`` (cached) or ``None`` if unavailable. Lazy import."""

    global _scipy_stats, _scipy_stats_probed
    if _scipy_stats is None and not _scipy_stats_probed:
        _scipy_stats_probed = True
        try:  # pragma: no cover - import guard
            from scipy import stats as _s
        except Exception:  # pragma: no cover - scipy optional
            _s = None
        _scipy_stats = _s
    return _scipy_stats


# statsmodels drags scipy in at import time and is only needed for the advanced
# econometric families; keep it off the hot import path and provision it lazily
# via ``ensure_econometrics``. The sentinel stays ``None`` until then.
_sm = None


CORE_MODELS = frozenset(
    {"ols", "multivariate", "loglinear", "timeseries_trend", "correlation", "montecarlo", "scenario"}
)
ECONOMETRIC_MODELS = frozenset({"cointegration", "event_study", "arima", "backtest"})
MODEL_TYPES = CORE_MODELS | ECONOMETRIC_MODELS


def backends() -> dict[str, bool]:
    # Probe scipy (cached) so a diagnostic query reports its true availability
    # rather than the lazy sentinel — the module docstring calls this out as an
    # intended trigger ("or when a diagnostic queries availability"), and it
    # matches ``bayes_toolkit.using_industry_libraries``. statsmodels stays a raw
    # sentinel: it is only provisioned (heavily) via ``ensure_econometrics`` for
    # the advanced families, so backends() must not drag it in.
    return {"numpy": _np is not None, "scipy": _get_scipy_stats() is not None, "statsmodels": _sm is not None}


def ensure_industry_backends() -> dict[str, bool]:
    """Provision numpy+scipy (forecast.bayes). No-op once present; safe offline."""
    global _np, _scipy_stats, _scipy_stats_probed
    if _np is not None and _get_scipy_stats() is not None:
        return backends()
    try:
        from tools.lazy_deps import ensure as _ensure

        _ensure("forecast.bayes", prompt=False)
    except Exception:
        pass
    if _np is None:
        try:  # pragma: no cover
            import numpy as _m

            _np = _m
        except Exception:
            pass
    if _scipy_stats is None:
        try:  # pragma: no cover
            from scipy import stats as _s

            _scipy_stats = _s
        except Exception:
            pass
        _scipy_stats_probed = True
    return backends()


def ensure_econometrics() -> dict[str, bool]:
    """Provision statsmodels (market.econometrics) for advanced families."""
    global _sm
    ensure_industry_backends()
    if _sm is None:
        # Fast path: statsmodels already installed → import without touching
        # lazy_deps (matches the old eager-import behavior for present installs).
        try:  # pragma: no cover - depends on environment
            import statsmodels.api as _m0  # noqa: N813

            _sm = _m0
        except Exception:
            pass
    if _sm is None:
        try:
            from tools.lazy_deps import ensure as _ensure

            _ensure("market.econometrics", prompt=False)
            import statsmodels.api as _m  # noqa: N813

            _sm = _m
        except Exception:  # pragma: no cover - depends on environment
            pass
    return backends()


# ── numeric helpers ──────────────────────────────────────────────────────────


def _floats(values: Sequence[Any]) -> list[float]:
    out: list[float] = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def _t_quantile(df: int, p: float = 0.975) -> float:
    """Two-sided t critical value; scipy when present else a normal approx."""
    if df <= 0:
        return 1.96
    _stats = _get_scipy_stats()
    if _stats is not None:
        try:
            return float(_stats.t.ppf(p, df))
        except Exception:  # pragma: no cover
            pass
    # crude small-sample bump over the 1.96 normal value
    return 1.96 + 2.8 / max(1, df)


def _degraded(model_type: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "degraded": True,
        "reason": reason,
        "block": {"type": "finding", "claim": reason, "confidence": "low", "note": f"{model_type}: degraded"},
        "summary": {},
        "backend": backends(),
    }


# ── core: regression family ───────────────────────────────────────────────────


def _ols_1d(x: list[float], y: list[float]) -> dict[str, float] | None:
    n = len(x)
    if n < 2 or len(y) != n:
        return None
    sx, sy = sum(x), sum(y)
    xbar, ybar = sx / n, sy / n
    sxx = sum((xi - xbar) ** 2 for xi in x)  # Sxx (centered)
    if sxx <= 0:
        return None
    sxy = sum((x[i] - xbar) * (y[i] - ybar) for i in range(n))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    resid = [y[i] - (intercept + slope * x[i]) for i in range(n)]
    ss_res = sum(r * r for r in resid)
    ss_tot = sum((yi - ybar) ** 2 for yi in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = max(1, n - 2)
    residual_std = math.sqrt(ss_res / dof)
    slope_se = residual_std / math.sqrt(sxx) if sxx > 0 else 0.0
    intercept_se = residual_std * math.sqrt(1.0 / n + xbar * xbar / sxx)
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "n": n,
        "residual_std": residual_std,
        "slope_se": slope_se,
        "intercept_se": intercept_se,
        "xbar": xbar,
        "sxx": sxx,
    }


def _pred_interval(fit: dict[str, float], x0: float) -> tuple[float, float, float]:
    """(yhat, lo, hi) prediction interval for a new x0 from a 1d OLS fit."""
    yhat = fit["intercept"] + fit["slope"] * x0
    n, sxx, xbar = fit["n"], fit["sxx"], fit["xbar"]
    t = _t_quantile(n - 2)
    se_pred = fit["residual_std"] * math.sqrt(1.0 + 1.0 / n + (x0 - xbar) ** 2 / sxx)
    return yhat, yhat - t * se_pred, yhat + t * se_pred


def _solve_normal_equations(rows: list[list[float]], y: list[float]) -> list[float] | None:
    """Least squares via normal equations (X^T X b = X^T y), pure-Python.

    ``rows`` includes the intercept column. Small-k Gaussian elimination — used
    when numpy is absent. Returns coefficient vector or None if singular.
    """
    k = len(rows[0])
    ata = [[0.0] * k for _ in range(k)]
    aty = [0.0] * k
    for r, yi in zip(rows, y):
        for i in range(k):
            aty[i] += r[i] * yi
            for j in range(k):
                ata[i][j] += r[i] * r[j]
    # Gaussian elimination with partial pivoting on [ata | aty]
    for col in range(k):
        piv = max(range(col, k), key=lambda r: abs(ata[r][col]))
        if abs(ata[piv][col]) < 1e-12:
            return None
        ata[col], ata[piv] = ata[piv], ata[col]
        aty[col], aty[piv] = aty[piv], aty[col]
        pv = ata[col][col]
        for j in range(col, k):
            ata[col][j] /= pv
        aty[col] /= pv
        for r in range(k):
            if r != col and abs(ata[r][col]) > 0:
                factor = ata[r][col]
                for j in range(col, k):
                    ata[r][j] -= factor * ata[col][j]
                aty[r] -= factor * aty[col]
    return aty


def _regression_block(
    *,
    x: list[float],
    y: list[float],
    x_label: str,
    y_label: str,
    method: str,
    extrapolate_to: list[float] | None,
) -> dict[str, Any]:
    fit = _ols_1d(x, y)
    if fit is None:
        return _degraded(method, "regression needs >=2 points with non-zero x variance")
    pts = [{"x": x[i], "y": y[i]} for i in range(len(x))]
    xs_sorted = sorted(x)
    fit_line = [{"x": xv, "y": fit["intercept"] + fit["slope"] * xv} for xv in (xs_sorted[0], xs_sorted[-1])]
    pred_band = []
    for xv in xs_sorted:
        yhat, lo, hi = _pred_interval(fit, xv)
        pred_band.append({"x": xv, "y": yhat, "lo": lo, "hi": hi})
    extrapolation = []
    for xv in extrapolate_to or []:
        yhat, lo, hi = _pred_interval(fit, float(xv))
        extrapolation.append({"x": float(xv), "y": yhat, "lo": lo, "hi": hi})
    block = {
        "type": "regression",
        "method": method,
        "x_labels": [x_label],
        "y_label": y_label,
        "coeffs": [{"name": x_label, "value": fit["slope"], "std_err": fit["slope_se"]}],
        "intercept": {"value": fit["intercept"], "std_err": fit["intercept_se"]},
        "r2": fit["r2"],
        "n": fit["n"],
        "residual_std": fit["residual_std"],
        "points": pts,
        "fit_line": fit_line,
        "prediction_band": pred_band,
        "extrapolation": extrapolation,
    }
    return {
        "ok": True,
        "degraded": False,
        "reason": "",
        "block": block,
        "summary": {"slope": fit["slope"], "intercept": fit["intercept"], "r2": fit["r2"], "n": fit["n"]},
        "backend": backends(),
    }


def _multivariate_block(payload: dict) -> dict[str, Any]:
    rows = payload.get("X") or []
    y = _floats(payload.get("y") or [])
    names = list(payload.get("x_labels") or [])
    y_label = str(payload.get("y_label") or "y")
    X = [[float(v) for v in row] for row in rows if isinstance(row, (list, tuple))]
    if len(X) < 2 or len(X) != len(y) or not X[0]:
        return _degraded("multivariate", "multivariate regression needs an X matrix aligned with y (>=2 rows)")
    k = len(X[0])
    if not names or len(names) != k:
        names = [f"x{i+1}" for i in range(k)]
    design = [[1.0, *row] for row in X]  # intercept column
    if _np is not None:
        try:
            A = _np.array(design, dtype=float)
            b = _np.array(y, dtype=float)
            coef, *_ = _np.linalg.lstsq(A, b, rcond=None)
            coef = [float(c) for c in coef]
        except Exception:  # pragma: no cover
            coef = _solve_normal_equations(design, y)
    else:
        coef = _solve_normal_equations(design, y)
    if not coef:
        return _degraded("multivariate", "design matrix is singular (collinear regressors?)")
    yhat = [sum(c * xv for c, xv in zip(coef, design[i])) for i in range(len(y))]
    ybar = sum(y) / len(y)
    ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(len(y)))
    ss_tot = sum((yi - ybar) ** 2 for yi in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    n = len(y)
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / max(1, (n - k - 1))
    block = {
        "type": "regression",
        "method": "multivariate",
        "x_labels": names,
        "y_label": y_label,
        "coeffs": [{"name": names[i], "value": coef[i + 1]} for i in range(k)],
        "intercept": {"value": coef[0]},
        "r2": r2,
        "adj_r2": adj_r2,
        "n": n,
        "residual_std": math.sqrt(ss_res / max(1, n - k - 1)),
        "points": [],
        "fit_line": [],
    }
    return {
        "ok": True,
        "degraded": False,
        "reason": "",
        "block": block,
        "summary": {"r2": r2, "adj_r2": adj_r2, "n": n, "coeffs": coef},
        "backend": backends(),
    }


# ── core: other families ──────────────────────────────────────────────────────


def _timeseries_trend_block(payload: dict) -> dict[str, Any]:
    series = _floats(payload.get("values") or payload.get("y") or [])
    if len(series) < 2:
        return _degraded("timeseries_trend", "trend needs >=2 observations")
    x = [float(i) for i in range(len(series))]
    horizon = int(payload.get("horizon") or 0)
    extra = [float(len(series) + h) for h in range(horizon)] if horizon > 0 else None
    res = _regression_block(
        x=x,
        y=series,
        x_label=str(payload.get("x_label") or "t"),
        y_label=str(payload.get("y_label") or "value"),
        method="timeseries_trend",
        extrapolate_to=extra,
    )
    return res


def _correlation_block(payload: dict) -> dict[str, Any]:
    a = _floats(payload.get("a") or payload.get("x") or [])
    b = _floats(payload.get("b") or payload.get("y") or [])
    n = min(len(a), len(b))
    if n < 2:
        return _degraded("correlation", "correlation needs >=2 aligned pairs")
    a, b = a[:n], b[:n]
    try:
        r = statistics.correlation(a, b) if hasattr(statistics, "correlation") else _pearson(a, b)
    except Exception:
        r = _pearson(a, b)
    p_value = None
    _stats = _get_scipy_stats()
    if _stats is not None:
        try:
            p_value = float(_stats.pearsonr(a, b)[1])
        except Exception:  # pragma: no cover
            p_value = None
    block = {
        "type": "metric",
        "label": f"corr({payload.get('a_label','a')}, {payload.get('b_label','b')})",
        "value": round(r, 4),
        "unit": "r",
        "note": f"n={n}" + (f", p={p_value:.4g}" if p_value is not None else ""),
    }
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"r": r, "p_value": p_value, "n": n}, "backend": backends()}


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = math.sqrt(sum((ai - ma) ** 2 for ai in a))
    vb = math.sqrt(sum((bi - mb) ** 2 for bi in b))
    return cov / (va * vb) if va > 0 and vb > 0 else 0.0


def _montecarlo_block(payload: dict) -> dict[str, Any]:
    """Geometric/arithmetic random-walk simulation → median + percentile bands."""
    start = float(payload.get("start") or 0.0)
    drift = float(payload.get("drift") or 0.0)
    vol = float(payload.get("vol") or 0.0)
    steps = int(payload.get("steps") or 12)
    n_paths = int(payload.get("n_paths") or 1000)
    seed = int(payload.get("seed") or 1729)
    mode = str(payload.get("mode") or "geometric")
    if steps < 1 or n_paths < 1:
        return _degraded("montecarlo", "montecarlo needs steps>=1 and n_paths>=1")
    n_paths = min(n_paths, 20000)
    rng = random.Random(seed)
    finals_by_step: list[list[float]] = [[] for _ in range(steps)]
    for _ in range(n_paths):
        v = start
        for s in range(steps):
            shock = rng.gauss(0.0, 1.0)
            if mode == "geometric":
                v *= math.exp(drift + vol * shock)
            else:
                v += drift + vol * shock
            finals_by_step[s].append(v)
    x = list(range(1, steps + 1))
    median = [_percentile(col, 50) for col in finals_by_step]
    band_specs = payload.get("bands") or [[10, 90], [25, 75]]
    bands = []
    for lo_p, hi_p in band_specs:
        bands.append(
            {
                "p_lo": lo_p,
                "p_hi": hi_p,
                "lower": [_percentile(col, lo_p) for col in finals_by_step],
                "upper": [_percentile(col, hi_p) for col in finals_by_step],
            }
        )
    block = {"type": "fan", "x": x, "median": median, "bands": bands, "n_paths": n_paths, "seed": seed}
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"final_median": median[-1], "n_paths": n_paths, "seed": seed}, "backend": backends()}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (p / 100.0) * (len(s) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (rank - lo)


def _scenario_block(payload: dict) -> dict[str, Any]:
    scenarios = payload.get("scenarios") or []
    clean = [s for s in scenarios if isinstance(s, dict) and s.get("name")]
    if not clean:
        return _degraded("scenario", "scenario needs at least one named scenario")
    block = {"type": "scenario", "scenarios": clean}
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"count": len(clean)}, "backend": backends()}


# ── advanced econometrics (statsmodels-gated) ─────────────────────────────────


def _backtest_block(payload: dict) -> dict[str, Any]:
    """Simple long/flat backtest from a return series + signal (pure-Python)."""
    returns = _floats(payload.get("returns") or [])
    signal = payload.get("signal") or []
    if len(returns) < 2:
        return _degraded("backtest", "backtest needs a return series with >=2 points")
    pos = [1.0 if (i < len(signal) and signal[i]) else (0.0 if signal else 1.0) for i in range(len(returns))]
    strat = [pos[i] * returns[i] for i in range(len(returns))]
    equity, eq = [], 1.0
    for r in strat:
        eq *= 1.0 + r
        equity.append(eq)
    total = equity[-1] - 1.0
    mean = sum(strat) / len(strat)
    sd = statistics.pstdev(strat) if len(strat) > 1 else 0.0
    sharpe = (mean / sd) * math.sqrt(252) if sd > 0 else 0.0
    peak, mdd = -math.inf, 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1.0)
    block = {
        "type": "table",
        "title": "Backtest summary",
        "columns": [{"key": "metric", "label": "Metric"}, {"key": "value", "label": "Value", "align": "right"}],
        "rows": [
            {"metric": "Total return", "value": f"{total*100:.1f}%"},
            {"metric": "Sharpe (ann.)", "value": f"{sharpe:.2f}"},
            {"metric": "Max drawdown", "value": f"{mdd*100:.1f}%"},
        ],
    }
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"total_return": total, "sharpe": sharpe, "max_drawdown": mdd}, "backend": backends()}


def _cointegration_block(payload: dict) -> dict[str, Any]:
    a = _floats(payload.get("a") or [])
    b = _floats(payload.get("b") or [])
    n = min(len(a), len(b))
    if n < 8:
        return _degraded("cointegration", "cointegration needs >=8 aligned observations")
    if _sm is None:
        return _degraded("cointegration", "cointegration requires statsmodels; install the market.econometrics group")
    try:
        from statsmodels.tsa.stattools import coint

        t_stat, p_value, _ = coint(a[:n], b[:n])
    except Exception as e:  # pragma: no cover
        return _degraded("cointegration", f"cointegration failed: {e}")
    block = {
        "type": "finding",
        "claim": f"Engle-Granger cointegration p={p_value:.4g} (t={t_stat:.3f})",
        "confidence": "high" if p_value < 0.05 else "low",
        "note": "p<0.05 ⇒ the series are cointegrated (a stable long-run relationship).",
    }
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"t_stat": float(t_stat), "p_value": float(p_value), "n": n}, "backend": backends()}


def _arima_block(payload: dict) -> dict[str, Any]:
    series = _floats(payload.get("values") or [])
    horizon = int(payload.get("horizon") or 6)
    order = tuple(payload.get("order") or (1, 1, 1))
    if len(series) < 10:
        return _degraded("arima", "ARIMA needs >=10 observations")
    if _sm is None:
        return _degraded("arima", "ARIMA requires statsmodels; install the market.econometrics group")
    try:
        from statsmodels.tsa.arima.model import ARIMA

        fit = ARIMA(series, order=order).fit()
        fc = fit.get_forecast(steps=horizon)
        mean = [float(v) for v in fc.predicted_mean]
        ci = fc.conf_int(alpha=0.2)
        lower = [float(row[0]) for row in ci]
        upper = [float(row[1]) for row in ci]
    except Exception as e:  # pragma: no cover
        return _degraded("arima", f"ARIMA failed: {e}")
    x = list(range(len(series) + 1, len(series) + horizon + 1))
    block = {
        "type": "fan",
        "title": f"ARIMA{order} forecast",
        "x": x,
        "median": mean,
        "bands": [{"p_lo": 10, "p_hi": 90, "lower": lower, "upper": upper}],
        "n_paths": 0,
        "seed": 0,
    }
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"forecast": mean, "order": list(order)}, "backend": backends()}


def _event_study_block(payload: dict) -> dict[str, Any]:
    """Cumulative abnormal return around an event vs a simple mean baseline."""
    returns = _floats(payload.get("returns") or [])
    idx = int(payload.get("event_index") or -1)
    window = int(payload.get("window") or 5)
    if len(returns) < 2 * window + 1 or not (window <= idx < len(returns) - window):
        return _degraded("event_study", "event_study needs an event_index with a full +/- window of returns")
    pre = returns[max(0, idx - 5 * window) : idx - window] or returns[:idx]
    baseline = sum(pre) / len(pre) if pre else 0.0
    car_points = []
    car = 0.0
    for offset in range(-window, window + 1):
        ar = returns[idx + offset] - baseline
        car += ar
        car_points.append({"x": offset, "y": car})
    block = {
        "type": "timeseries",
        "title": "Cumulative abnormal return around event",
        "series": [{"name": "CAR", "points": car_points}],
        "x_unit": "days from event",
    }
    return {"ok": True, "degraded": False, "reason": "", "block": block,
            "summary": {"car_total": car_points[-1]["y"], "baseline": baseline}, "backend": backends()}


# ── dispatch ──────────────────────────────────────────────────────────────────


def compute(model_type: str, payload: dict | None = None) -> dict[str, Any]:
    """Run a deterministic computation; returns a uniform result with a block."""
    payload = payload or {}
    mt = str(model_type or "").strip().lower()

    if mt in ECONOMETRIC_MODELS:
        ensure_econometrics()

    if mt == "ols":
        x = _floats(payload.get("x") or [])
        y = _floats(payload.get("y") or [])
        n = min(len(x), len(y))
        return _regression_block(
            x=x[:n],
            y=y[:n],
            x_label=str(payload.get("x_label") or "x"),
            y_label=str(payload.get("y_label") or "y"),
            method="ols",
            extrapolate_to=[float(v) for v in (payload.get("extrapolate_to") or [])],
        )
    if mt == "loglinear":
        x = _floats(payload.get("x") or [])
        y = _floats(payload.get("y") or [])
        n = min(len(x), len(y))
        if any(v <= 0 for v in y[:n]):
            return _degraded("loglinear", "loglinear requires strictly positive y")
        logy = [math.log(v) for v in y[:n]]
        res = _regression_block(
            x=x[:n], y=logy, x_label=str(payload.get("x_label") or "x"),
            y_label=f"ln({payload.get('y_label','y')})", method="loglinear",
            extrapolate_to=[float(v) for v in (payload.get("extrapolate_to") or [])],
        )
        return res
    if mt == "multivariate":
        return _multivariate_block(payload)
    if mt == "timeseries_trend":
        return _timeseries_trend_block(payload)
    if mt == "correlation":
        return _correlation_block(payload)
    if mt == "montecarlo":
        return _montecarlo_block(payload)
    if mt == "scenario":
        return _scenario_block(payload)
    if mt == "backtest":
        return _backtest_block(payload)
    if mt == "cointegration":
        return _cointegration_block(payload)
    if mt == "arima":
        return _arima_block(payload)
    if mt == "event_study":
        return _event_study_block(payload)

    return _degraded(mt or "unknown", f"unknown model_type {model_type!r}; supported: {sorted(MODEL_TYPES)}")
