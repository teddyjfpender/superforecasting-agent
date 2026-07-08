"""Hierarchical Platt calibration — per-cohort intercept offsets (BLF A4).

The desk's terminal calibration is a single global Platt map
``q = sigma(a*logit(p) + b)`` (the sqrt(3) variance-matching slope from Gate 1,
with ``b`` folded into the ``d`` bias term of
:func:`forecasting.bayes_toolkit.platt_scale`). BLF's finding — the biggest
single calibration component for weak base models — is that a *global* Platt map
OVER-shrinks cohorts whose empirical base rate is skewed: a Polymarket stratum
that mostly resolves one way, or an imported-baseline stratum with a synthetic
prior, wants a different intercept than a live desk forecast. This module fits
the **hierarchical** extension

    q = sigma(a*logit(p) + b + delta_s)

where ``s`` indexes OUR scoreboard cohorts (the strata
:func:`forecasting.ledger.scoring.cohort_scoreboard` already exposes:
``live_calibration_eligible`` / ``backtest`` / ``imported_baseline`` /
``market_nightly``, plus a venue refinement where a sub-stratum has the data).
The global slope ``a`` and intercept ``b`` are shared; each cohort earns an
**intercept offset** ``delta_s`` that is L2-regularized toward 0 (the identity
offset — ``delta_s == 0`` reduces EXACTLY to the global Platt map). This is the
random-intercept-with-shrinkage recipe from BLF's Appendix A: fit
``(a, b, {delta_s})`` by L2-regularized binary cross-entropy, the ridge acting
only on the offsets, its strength ``lambda`` chosen by leave-one-out CV.

Design discipline (each rule is a safeguard):

* **Only the offsets are penalized.** ``a`` and ``b`` are free (the global map
  must stay a maximum-likelihood Platt fit); ``lambda/2 * sum(delta_s^2)`` shrinks
  each cohort's deviation toward the pooled intercept. Small ``lambda`` ⇒ each
  cohort floats free (over-fit); large ``lambda`` ⇒ every offset collapses to 0
  and the model IS the global Platt. LOO-CV picks the middle.
* **Small-cohort fallback.** A cohort below :data:`DEFAULT_MIN_COHORT_N` resolved
  rows gets NO offset parameter at all — its rows share the global intercept
  ``b`` (``delta_s := 0``). Below the floor an offset is noise; folding the rows
  into the global fit is the honest default. The threshold is stated and
  configurable.
* **Convex, deterministic, dependency-light.** The L2-regularized BCE is convex;
  the fit is Newton/IRLS with an Armijo guard and a stdlib Gaussian-elimination
  solve — no scipy, no randomness beyond a seeded CV shuffle. Pure ``math``; the
  ledger glue (pulling cohort-tagged resolved rows) lives in
  :mod:`forecasting.ledger.scoring`.
* **Provenance.** :meth:`HierarchicalPlattModel.predict` returns the calibrated
  probability AND the exact ``delta_s`` (and whether the small-cohort fallback
  fired) that produced it, so every calibrated output records which offset
  applied.

Nothing here moves a live default. The model is fit read-only on resolved rows;
activation is a separate operator decision (see the ledger derivation, which is
default-OFF behind the same activation flag pattern as the sqrt(3) slope).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random
from typing import Any, Sequence

from forecasting.bayes_toolkit import inv_logit, logit, platt_scale

__all__ = [
    "CohortObservation",
    "HierarchicalPlattModel",
    "fit_hierarchical_platt",
    "validate_hierarchical_calibration",
    "DEFAULT_MIN_COHORT_N",
    "DEFAULT_LAMBDA_GRID",
]

# ── Tunable constants (every one is a documented safeguard) ──────────────────

# Below this many resolved rows a cohort gets NO offset (delta_s := 0) and shares
# the global intercept — an offset fit on a handful of rows is noise. Stated and
# overridable at every entry point.
DEFAULT_MIN_COHORT_N = 40
# Ridge-strength candidates for the offsets, swept by leave-one-out CV. The
# penalty is (lambda/2)*sum(delta^2) against a summed (not mean) BCE, so the grid
# spans "each cohort floats free" (small) to "every offset ~0, model == global"
# (large). Log-spaced so the CV curve is read on the right scale.
DEFAULT_LAMBDA_GRID = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0)
# Newton stopping: max iterations and the infinity-norm gradient tolerance.
_MAX_NEWTON_ITERS = 100
_GRAD_TOL = 1e-8
# A tiny diagonal jitter keeps the Newton solve well-posed when a cohort is
# (near-)separable. This is a numerical guard, NOT a prior on a or b.
_SOLVE_JITTER = 1e-10
# LOO is exact but O(n) refits; above this row count the CV falls back to k-fold.
_LOO_MAX_N = 200
_KFOLD_DEFAULT = 10
_CV_SEED = 20260708


# ── Observation contract ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CohortObservation:
    """One resolved binary forecast tagged with its scoreboard cohort.

    ``raw_p`` is the pre-adjustment committed P(yes) (the same raw probability the
    signed-bias loop uses for contamination control); ``outcome`` is 1.0 for a YES
    resolution else 0.0; ``cohort`` is the scoreboard stratum key; ``weight``
    carries an optional recency decay (default 1.0).
    """

    raw_p: float
    outcome: float
    cohort: str
    weight: float = 1.0


def _clean(rows: Sequence[CohortObservation]) -> list[CohortObservation]:
    out: list[CohortObservation] = []
    for r in rows:
        try:
            p = float(r.raw_p)
            y = float(r.outcome)
            w = float(r.weight)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(p) and math.isfinite(y) and math.isfinite(w)):
            continue
        if not (0.0 <= p <= 1.0) or w <= 0.0:
            continue
        cohort = str(r.cohort or "").strip() or "unknown"
        out.append(CohortObservation(raw_p=p, outcome=1.0 if y >= 0.5 else 0.0, cohort=cohort, weight=w))
    return out


# ── Numerically-stable primitives for the optimizer ──────────────────────────


def _sigmoid(z: float) -> float:
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _softplus(z: float) -> float:
    # log(1 + e^z), stable for large |z|.
    if z > 0.0:
        return z + math.log1p(math.exp(-z))
    return math.log1p(math.exp(z))


# ── The fitted model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HierarchicalPlattModel:
    """A fitted hierarchical Platt map ``q = sigma(a*logit(p) + b + delta_s)``.

    ``deltas`` holds an offset ONLY for cohorts that cleared ``min_cohort_n``;
    every other cohort (and any unseen cohort at predict time) falls back to the
    global map (``delta_s = 0``). ``lambda_`` is the LOO-CV-selected ridge
    strength. Fully serializable via :meth:`to_payload`.
    """

    a: float
    b: float
    deltas: dict[str, float]
    lambda_: float
    min_cohort_n: int
    cohort_n: dict[str, float]
    small_cohorts: list[str]
    n: int
    iterations: int
    converged: bool
    cv: dict[str, Any] = field(default_factory=dict)

    def delta_for(self, cohort: str) -> tuple[float, bool]:
        """Return ``(delta_s, fell_back)`` for a cohort — 0.0 + True when the
        cohort has no fitted offset (small-cohort or unseen → global map)."""

        key = str(cohort or "").strip() or "unknown"
        if key in self.deltas:
            return self.deltas[key], False
        return 0.0, True

    def predict(self, raw_p: float, cohort: str) -> dict[str, Any]:
        """Calibrated probability for one raw forecast, WITH provenance.

        Routes through the desk's single recalibration kernel
        :func:`forecasting.bayes_toolkit.platt_scale` — the intercept ``b +
        delta_s`` is carried in its ``d`` bias term as ``d = exp(b + delta_s)`` —
        so a calibrated commit uses the identical operator the live pool uses.
        """

        delta_s, fell_back = self.delta_for(cohort)
        intercept = self.b + delta_s
        q = platt_scale(float(raw_p), alpha=self.a, d=math.exp(intercept))
        return {
            "probability": q,
            "raw_probability": float(raw_p),
            "cohort": str(cohort or "").strip() or "unknown",
            "slope_a": self.a,
            "intercept_b": self.b,
            "delta_s": delta_s,
            "platt_d": math.exp(intercept),
            "small_cohort_fallback": fell_back,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "a": round(self.a, 6),
            "b": round(self.b, 6),
            "deltas": {k: round(v, 6) for k, v in sorted(self.deltas.items())},
            "lambda": self.lambda_,
            "min_cohort_n": self.min_cohort_n,
            "cohort_n": {k: round(v, 3) for k, v in sorted(self.cohort_n.items())},
            "small_cohorts": sorted(self.small_cohorts),
            "n": self.n,
            "iterations": self.iterations,
            "converged": self.converged,
            "cv": self.cv,
        }


# ── The convex fit (Newton / IRLS with a ridge on the offsets only) ──────────


def _design(
    rows: Sequence[CohortObservation], large_cohorts: Sequence[str]
) -> tuple[list[list[float]], list[float], list[float], list[int]]:
    """Return ``(features, y, w, ridge_mask)``.

    Feature layout per row: ``[logit(p), 1, 1{cohort==c_0}, ...]`` — column 0 is
    the slope ``a``, column 1 the global intercept ``b``, and one indicator per
    LARGE cohort for its offset ``delta``. ``ridge_mask`` marks which parameter
    columns are penalized (only the offsets)."""

    index = {c: j for j, c in enumerate(large_cohorts)}
    k = len(large_cohorts)
    feats: list[list[float]] = []
    ys: list[float] = []
    ws: list[float] = []
    for r in rows:
        phi = [logit(r.raw_p), 1.0] + [0.0] * k
        j = index.get(r.cohort)
        if j is not None:
            phi[2 + j] = 1.0
        feats.append(phi)
        ys.append(r.outcome)
        ws.append(r.weight)
    ridge_mask = [0, 0] + [1] * k
    return feats, ys, ws, ridge_mask


def _loss(
    feats: Sequence[Sequence[float]],
    ys: Sequence[float],
    ws: Sequence[float],
    theta: Sequence[float],
    lambda_: float,
    ridge_mask: Sequence[int],
) -> float:
    total = 0.0
    for phi, y, w in zip(feats, ys, ws):
        z = sum(t * f for t, f in zip(theta, phi))
        total += w * (_softplus(z) - y * z)
    reg = 0.0
    for t, m in zip(theta, ridge_mask):
        if m:
            reg += t * t
    return total + 0.5 * lambda_ * reg


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve ``matrix @ x = rhs`` by Gaussian elimination with partial pivoting.
    Returns ``None`` on a singular system."""

    n = len(rhs)
    aug = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-14:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col] / pv
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def _fit_params(
    feats: Sequence[Sequence[float]],
    ys: Sequence[float],
    ws: Sequence[float],
    lambda_: float,
    ridge_mask: Sequence[int],
) -> tuple[list[float], int, bool]:
    """Newton/IRLS minimization of the L2-regularized BCE. Convex ⇒ the Newton
    direction with an Armijo backtrack converges globally; returns
    ``(theta, iterations, converged)``."""

    p = len(ridge_mask)
    theta = [0.0] * p
    converged = False
    iterations = 0
    for iterations in range(1, _MAX_NEWTON_ITERS + 1):
        grad = [0.0] * p
        hess = [[0.0] * p for _ in range(p)]
        for phi, y, w in zip(feats, ys, ws):
            z = sum(t * f for t, f in zip(theta, phi))
            q = _sigmoid(z)
            g = w * (q - y)
            hw = w * q * (1.0 - q)
            for i in range(p):
                fi = phi[i]
                if fi:
                    grad[i] += g * fi
                    if hw:
                        row = hess[i]
                        for j in range(i, p):
                            fj = phi[j]
                            if fj:
                                row[j] += hw * fi * fj
        # Ridge on the offsets + a tiny jitter for a well-posed solve.
        for i in range(p):
            if ridge_mask[i]:
                grad[i] += lambda_ * theta[i]
                hess[i][i] += lambda_
            hess[i][i] += _SOLVE_JITTER
        for i in range(p):
            for j in range(i + 1, p):
                hess[j][i] = hess[i][j]
        if max(abs(gi) for gi in grad) < _GRAD_TOL:
            converged = True
            break
        step = _solve(hess, [-gi for gi in grad])
        if step is None:
            break
        # Armijo backtracking on the (convex) loss guards against overshoot.
        base = _loss(feats, ys, ws, theta, lambda_, ridge_mask)
        gdotd = sum(g * d for g, d in zip(grad, step))
        t = 1.0
        while t > 1e-6:
            trial = [th + t * d for th, d in zip(theta, step)]
            if _loss(feats, ys, ws, trial, lambda_, ridge_mask) <= base + 1e-4 * t * gdotd:
                break
            t *= 0.5
        theta = [th + t * d for th, d in zip(theta, step)]
    return theta, iterations, converged


def _cohort_counts(rows: Sequence[CohortObservation]) -> dict[str, float]:
    counts: dict[str, float] = {}
    for r in rows:
        counts[r.cohort] = counts.get(r.cohort, 0.0) + r.weight
    return counts


def _fit_at_lambda(
    rows: Sequence[CohortObservation], large_cohorts: Sequence[str], lambda_: float
) -> tuple[list[float], int, bool]:
    feats, ys, ws, ridge_mask = _design(rows, large_cohorts)
    return _fit_params(feats, ys, ws, lambda_, ridge_mask)


def _predict_z(theta: Sequence[float], index: dict[str, int], row: CohortObservation) -> float:
    z = theta[0] * logit(row.raw_p) + theta[1]
    j = index.get(row.cohort)
    if j is not None:
        z += theta[2 + j]
    return z


def _cv_bce(
    rows: Sequence[CohortObservation],
    large_cohorts: Sequence[str],
    lambda_: float,
    folds: int,
    rng: Random,
) -> float:
    """Mean held-out BCE at ``lambda_`` under k-fold (or LOO when folds==n)."""

    index = {c: j for j, c in enumerate(large_cohorts)}
    order = list(range(len(rows)))
    rng.shuffle(order)
    assign = {order[i]: i % folds for i in range(len(order))}
    total = 0.0
    weight = 0.0
    for f in range(folds):
        train = [rows[i] for i in range(len(rows)) if assign[i] != f]
        test = [rows[i] for i in range(len(rows)) if assign[i] == f]
        if not train or not test:
            continue
        theta, _it, _ok = _fit_at_lambda(train, large_cohorts, lambda_)
        for r in test:
            z = _predict_z(theta, index, r)
            total += r.weight * (_softplus(z) - r.outcome * z)
            weight += r.weight
    return total / weight if weight > 0 else float("inf")


def _select_lambda(
    rows: Sequence[CohortObservation],
    large_cohorts: Sequence[str],
    lambda_grid: Sequence[float],
    folds: int | None,
) -> tuple[float, list[dict[str, float]]]:
    """Leave-one-out (or k-fold) CV selection of the ridge strength.

    Ties go to the LARGER lambda (the more-regularized, lower-variance model) —
    the conservative default when two strengths hold out equally well."""

    n = len(rows)
    k = folds if folds is not None else (n if n <= _LOO_MAX_N else _KFOLD_DEFAULT)
    k = max(2, min(k, n))
    curve: list[dict[str, float]] = []
    for lam in lambda_grid:
        rng = Random(_CV_SEED)
        curve.append({"lambda": float(lam), "cv_bce": _cv_bce(rows, large_cohorts, float(lam), k, rng)})
    best = min(curve, key=lambda row: (row["cv_bce"], -row["lambda"]))
    return best["lambda"], curve


def fit_hierarchical_platt(
    observations: Sequence[CohortObservation],
    *,
    min_cohort_n: int = DEFAULT_MIN_COHORT_N,
    lambda_grid: Sequence[float] = DEFAULT_LAMBDA_GRID,
    lambda_: float | None = None,
    cv_folds: int | None = None,
) -> HierarchicalPlattModel:
    """Fit ``q = sigma(a*logit(p) + b + delta_s)`` on cohort-tagged resolved rows.

    Offsets are fit ONLY for cohorts clearing ``min_cohort_n`` (others fall back
    to the global map, ``delta_s = 0``); the ridge strength ``lambda_`` is chosen
    by leave-one-out CV over ``lambda_grid`` (pass ``lambda_`` to skip CV, e.g.
    inside a held-out validation loop). Raises :class:`ValueError` only on an
    empty clean sample — callers that want a fail-safe should guard that.
    """

    rows = _clean(observations)
    if not rows:
        raise ValueError("hierarchical Platt fit requires at least one resolved row")

    counts = _cohort_counts(rows)
    large_cohorts = sorted(c for c, n in counts.items() if n >= float(min_cohort_n))
    small_cohorts = sorted(c for c in counts if c not in set(large_cohorts))

    if lambda_ is not None:
        chosen_lambda = float(lambda_)
        cv_info: dict[str, Any] = {"selected_by": "explicit", "lambda": chosen_lambda}
    elif not large_cohorts:
        # Nothing to regularize — the model is a plain global Platt fit.
        chosen_lambda = 0.0
        cv_info = {"selected_by": "no_large_cohorts", "lambda": 0.0}
    else:
        chosen_lambda, curve = _select_lambda(rows, large_cohorts, lambda_grid, cv_folds)
        n = len(rows)
        cv_info = {
            "selected_by": "loo" if (cv_folds is None and n <= _LOO_MAX_N) else "kfold",
            "folds": cv_folds if cv_folds is not None else (n if n <= _LOO_MAX_N else _KFOLD_DEFAULT),
            "lambda": chosen_lambda,
            "grid": [dict(row) for row in curve],
        }

    theta, iterations, converged = _fit_at_lambda(rows, large_cohorts, chosen_lambda)
    deltas = {c: theta[2 + j] for j, c in enumerate(large_cohorts)}
    return HierarchicalPlattModel(
        a=theta[0],
        b=theta[1],
        deltas=deltas,
        lambda_=chosen_lambda,
        min_cohort_n=int(min_cohort_n),
        cohort_n=counts,
        small_cohorts=small_cohorts,
        n=len(rows),
        iterations=iterations,
        converged=converged,
        cv=cv_info,
    )


# ── Held-out validation: global vs hierarchical Brier, per cohort ────────────


def _brier(q: float, y: float) -> float:
    return (q - y) ** 2


def validate_hierarchical_calibration(
    observations: Sequence[CohortObservation],
    *,
    min_cohort_n: int = DEFAULT_MIN_COHORT_N,
    lambda_grid: Sequence[float] = DEFAULT_LAMBDA_GRID,
    folds: int = 5,
) -> dict[str, Any]:
    """Held-out per-cohort Brier — the evidence for flipping hierarchical mode ON.

    Runs ``folds``-fold CV. For each fold the training rows fit two maps at a
    common CV-selected ``lambda`` (so the comparison isolates the OFFSETS, not
    lambda-selection noise): the **global** Platt map (all offsets forced to 0)
    and the **hierarchical** map. Every held-out row is scored by both, plus the
    raw (identity) forecast as a floor. Returns a per-cohort and overall Brier
    table with the hierarchical-minus-global delta (positive ⇒ hierarchical
    helps) and a conservative recommendation. Read-only; moves nothing.
    """

    rows = _clean(observations)
    out: dict[str, Any] = {
        "n": len(rows),
        "folds": folds,
        "min_cohort_n": int(min_cohort_n),
        "cohorts": {},
        "overall": {},
        "recommendation": "insufficient_data",
        "notes": [],
    }
    if len(rows) < max(2 * folds, 2 * int(min_cohort_n)):
        out["notes"].append(
            f"only {len(rows)} rows — below the {max(2 * folds, 2 * int(min_cohort_n))} needed "
            "for a {folds}-fold held-out comparison"
        )
        return out

    counts = _cohort_counts(rows)
    large_cohorts = sorted(c for c, n in counts.items() if n >= float(min_cohort_n))
    if not large_cohorts:
        out["notes"].append(
            f"no cohort clears min_cohort_n={int(min_cohort_n)} — hierarchical reduces to global"
        )
        out["recommendation"] = "keep_global"
        return out

    # One CV-selected lambda on the full data, reused across folds (documented).
    chosen_lambda, lam_curve = _select_lambda(rows, large_cohorts, lambda_grid, None)
    out["lambda"] = chosen_lambda
    out["lambda_grid"] = [dict(r) for r in lam_curve]

    index = {c: j for j, c in enumerate(large_cohorts)}
    rng = Random(_CV_SEED)
    order = list(range(len(rows)))
    rng.shuffle(order)
    assign = {order[i]: i % folds for i in range(len(order))}

    # Per-cohort accumulators for identity / global / hierarchical held-out Brier.
    acc: dict[str, dict[str, float]] = {}

    def _bump(cohort: str, field_name: str, value: float, w: float) -> None:
        bucket = acc.setdefault(cohort, {"n": 0.0, "identity": 0.0, "global": 0.0, "hierarchical": 0.0})
        if field_name == "n":
            bucket["n"] += w
        else:
            bucket[field_name] += w * value

    for f in range(folds):
        train = [rows[i] for i in range(len(rows)) if assign[i] != f]
        test = [rows[i] for i in range(len(rows)) if assign[i] == f]
        if not train or not test:
            continue
        theta_h, _i1, _c1 = _fit_at_lambda(train, large_cohorts, chosen_lambda)
        theta_g, _i2, _c2 = _fit_at_lambda(train, (), chosen_lambda)  # no offsets
        for r in test:
            q_id = r.raw_p
            zg = theta_g[0] * logit(r.raw_p) + theta_g[1]
            q_g = inv_logit(zg)
            q_h = inv_logit(_predict_z(theta_h, index, r))
            _bump(r.cohort, "n", 0.0, r.weight)
            _bump(r.cohort, "identity", _brier(q_id, r.outcome), r.weight)
            _bump(r.cohort, "global", _brier(q_g, r.outcome), r.weight)
            _bump(r.cohort, "hierarchical", _brier(q_h, r.outcome), r.weight)

    cohort_table: dict[str, Any] = {}
    tot = {"n": 0.0, "identity": 0.0, "global": 0.0, "hierarchical": 0.0}
    improved_large = 0
    for cohort, bucket in sorted(acc.items()):
        n_c = bucket["n"]
        if n_c <= 0:
            continue
        b_id = bucket["identity"] / n_c
        b_g = bucket["global"] / n_c
        b_h = bucket["hierarchical"] / n_c
        is_large = cohort in index
        delta = b_g - b_h  # >0 ⇒ hierarchical lowers Brier
        cohort_table[cohort] = {
            "n": round(n_c, 3),
            "has_offset": is_large,
            "brier_identity": round(b_id, 6),
            "brier_global": round(b_g, 6),
            "brier_hierarchical": round(b_h, 6),
            "delta_brier_global_minus_hier": round(delta, 6),
            "hierarchical_helps": bool(delta > 0),
        }
        for key in tot:
            tot[key] += bucket[key]
        if is_large and delta > 0:
            improved_large += 1

    overall = {}
    if tot["n"] > 0:
        overall = {
            "n": round(tot["n"], 3),
            "brier_identity": round(tot["identity"] / tot["n"], 6),
            "brier_global": round(tot["global"] / tot["n"], 6),
            "brier_hierarchical": round(tot["hierarchical"] / tot["n"], 6),
            "delta_brier_global_minus_hier": round((tot["global"] - tot["hierarchical"]) / tot["n"], 6),
        }
    out["cohorts"] = cohort_table
    out["overall"] = overall

    # Conservative recommendation: flip ON only when the hierarchical map does not
    # regress the pooled held-out Brier AND at least one offset-carrying cohort
    # improves. Otherwise keep the global map.
    if overall and overall["delta_brier_global_minus_hier"] >= 0 and improved_large >= 1:
        out["recommendation"] = "flip_on"
    else:
        out["recommendation"] = "keep_global"
    out["large_cohorts_improved"] = improved_large
    out["large_cohorts"] = list(large_cohorts)
    return out
