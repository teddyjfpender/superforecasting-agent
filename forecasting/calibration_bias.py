"""Signed calibration-bias measurement and a *safe* self-correction loop.

The forecasting desk already measures an **unsigned** Expected Calibration
Error (the reliability curve in :meth:`ForecastLedger.calibration_summary`).
Unsigned ECE cannot tell *over*-confidence from *under*-confidence, so it
cannot drive a "you have been running ~12pp under-confident in politics"
lesson. This module adds the **signed** measurement and the machinery that
turns it into a calibration lesson — engineered, above all, *not* to teach the
model to over-bias over time.

Design rules (every one exists to stop a runaway feedback loop):

* **Signed Calibration Error (SCE) on the P(yes) axis, not a confidence fold.**
  The naive ``mean(max(p,1-p)) - hit_rate`` metric mechanically manufactures
  *over*-confidence near p=0.5 (a perfectly-calibrated 55% reads as
  over-confident), which would teach the model to hedge. We instead score each
  resolved binary forecast by its signed contribution::

      c_i = sign(p_yes_i - 0.5) * (p_yes_i - outcome_i)        # outcome in {0,1}

  Dropping forecasts within ``_NEUTRAL_BAND`` of 0.5 (where the leaning side is
  arbitrary), ``SCE = weighted_mean(c_i)``. **SCE < 0 ⇒ under-confident**
  (outcomes landed more on the leaned side than stated); **SCE > 0 ⇒
  over-confident**. Because each ``c_i`` is a per-observation quantity, the
  confidence interval and the H0:SCE=0 p-value are a plain weighted-mean test —
  no bespoke statistics — and ``|SCE| <= ECE`` holds by the triangle
  inequality (asserted in tests).

* **Fail safe under thin/noisy data.** Every sample threshold is expressed in
  Kish *effective* sample size (so recency decay cannot silently defeat a
  raw-n gate). Below the floor the verdict is ``insufficient_evidence`` and
  nothing is emitted. A scope must clear its own CI (exclude 0 by a margin)
  *and* survive Benjamini-Hochberg FDR control across the family of scopes
  before any lesson is written — scanning a dozen domains at 95% would
  otherwise emit a spurious lesson roughly every other cycle.

* **Advisory by default, mechanical only on opt-in.** A lesson is bounded,
  shape-specific, symmetric *text* the agent reasons about; the numeric nudge
  is empty unless ``enable_mechanical`` is set. When enabled the nudge is a
  base-rate-neutral ``logit_scale`` (sharpen/flatten around 0.5 — *never* an
  additive shift, which would chase the realized yes/no base rate), shrunk
  toward zero (empirical Bayes), damped by a partial gain, magnitude-capped,
  and hysteretically dead-banded.

* **Convergence is monitored, not proved.** The actuator is a language model
  reading prose, so "gain<1 ⇒ contraction" does not hold. Instead the per-scope
  ``|SCE|`` trajectory is tracked; a lesson is suppressed/demoted when the bias
  grows for two consecutive cycles or flips sign against the active lesson —
  the overshoot/oscillation signature.

Pure math: stdlib ``math`` only. No DB, no I/O, no wall-clock — callers pass
recency weights and prior trajectory in, so this module stays deterministic and
unit-testable. The ledger glue (pulling scored binary forecasts, the lesson-free
stratification, applying the ``logit_scale`` nudge, writing lessons) lives in
:mod:`forecasting.ledger` and :mod:`forecasting.learning`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "Observation",
    "CalibrationBiasReport",
    "assess_bias",
    "decide_disposition",
    "benjamini_hochberg",
    "effective_sample_size",
    "signed_calibration_error",
    "leaned_side_hit_rate",
    "extremization_alpha_gate",
    "HedgingDiagnosis",
    "diagnose_hedging",
]

# ── Tunable constants (every one is a safeguard knob) ────────────────────────

# Forecasts within this band of 0.5 have no well-defined "leaned side"; the
# max(p,1-p) fold would fabricate confidence here, so they are excluded.
_NEUTRAL_BAND = 0.05
# Effective-sample floors below which a scope is `insufficient_evidence`.
_ESS_MIN_DOMAIN = 12.0
_ESS_MIN_GLOBAL = 20.0
# Two-sided significance for the CI gate / H0:SCE=0 test.
_ALPHA = 0.05
_Z_ALPHA = 1.959963984540054  # Phi^{-1}(0.975)
# The CI must clear zero by this margin (in SCE units) — not merely touch it.
_CI_MARGIN = 0.0
# Empirical-Bayes shrinkage constant: weight on the raw estimate is ess/(ess+k).
_SHRINK_K = 20.0
# Advisory deadband: |shrunk SCE| below this is "calibrated", emit no direction.
_DEADBAND = 0.03
# Strong-evidence gates for AUTO-ACTIVATION (else the lesson stays tentative).
_STRONG_ESS = 30.0
_STRONG_MAG = 0.08
# Benjamini-Hochberg false-discovery rate across the per-cycle scope family.
_FDR_Q = 0.10
# Mechanical-path knobs (only consulted when enable_mechanical=True).
_MECH_MIN_ESS = 60.0          # numeric nudge stays silent below this ESS
_MECH_GAIN = 0.5              # partial-correction gain (<1)
_MECH_CAP = 0.20              # max |logit_scale - 1|
_MECH_DEADBAND_ENTER = 0.03   # stop correcting below this |shrunk SCE|
_MECH_DEADBAND_EXIT = 0.06    # don't (re)start correcting until above this
_MECH_REF = 0.10              # |shrunk SCE| that maps to a full gain*cap step


# ── Small local helpers ──────────────────────────────────────────────────────


def _coerce_float(value: Any) -> float | None:
    """Best-effort finite float, else ``None`` (booleans rejected)."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _normal_sf(z: float) -> float:
    """Upper-tail standard-normal survival function, 1 - Phi(z)."""

    return 0.5 * math.erfc(z / math.sqrt(2.0))


def effective_sample_size(weights: Sequence[float]) -> float:
    """Kish effective sample size ``(sum w)^2 / sum w^2`` (0 for no weight).

    With uniform weights this is just the count; with recency decay it is the
    smaller number of "equivalent equally-weighted" observations, which is what
    every sample gate in this module is expressed against.
    """

    total = 0.0
    total_sq = 0.0
    for w in weights:
        wf = _coerce_float(w) or 0.0
        if wf <= 0.0:
            continue
        total += wf
        total_sq += wf * wf
    if total_sq <= 0.0:
        return 0.0
    return (total * total) / total_sq


# ── Observation contract ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One resolved binary forecast, reduced to what the metric needs.

    ``p_yes`` is the committed (or, for contamination control, the *raw*
    pre-adjustment) P(yes); ``outcome`` is 1.0 if the question resolved yes,
    0.0 if no. ``weight`` carries recency decay (default 1.0). ``lesson_active``
    flags whether a same-scope active calibration lesson was in context at
    forecast time — used to keep lesson-derivation on the clean, lesson-free
    stratum.
    """

    p_yes: float
    outcome: float
    weight: float = 1.0
    lesson_active: bool = False
    horizon_days: float | None = None

    def signed_contribution(self) -> float | None:
        """``c_i = sign(p_yes-0.5) * (p_yes-outcome)`` or ``None`` if neutral."""

        side = self.p_yes - 0.5
        if abs(side) < _NEUTRAL_BAND:
            return None
        return (1.0 if side > 0 else -1.0) * (self.p_yes - self.outcome)


def _included(observations: Sequence[Observation]) -> list[Observation]:
    """Observations with a usable P(yes) and outcome outside the neutral band."""

    out: list[Observation] = []
    for obs in observations:
        p = _coerce_float(obs.p_yes)
        y = _coerce_float(obs.outcome)
        w = _coerce_float(obs.weight)
        if p is None or y is None or w is None or w <= 0.0:
            continue
        if not (0.0 <= p <= 1.0):
            continue
        if abs(p - 0.5) < _NEUTRAL_BAND:
            continue
        out.append(obs)
    return out


# ── Core scalar metric, CI, p-value ──────────────────────────────────────────


def signed_calibration_error(observations: Sequence[Observation]) -> float | None:
    """Weighted-mean signed contribution; ``None`` if no usable observation.

    Negative ⇒ under-confident, positive ⇒ over-confident.
    """

    rows = _included(observations)
    num = 0.0
    den = 0.0
    for obs in rows:
        c = obs.signed_contribution()
        if c is None:
            continue
        w = float(obs.weight)
        num += w * c
        den += w
    if den <= 0.0:
        return None
    return num / den


def _weighted_mean_ci(
    pairs: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float, float] | None:
    """Return ``(mean, se, ess, z, two_sided_p)`` for weighted (value, weight).

    The SE is the weighted standard error of the mean; ESS is Kish's. ``None``
    when there is no usable weight. A degenerate single-effective-point sample
    yields ``se==0`` and ``p==1`` (correctly un-actionable).
    """

    num = 0.0
    den = 0.0
    den_sq = 0.0
    for value, weight in pairs:
        v = _coerce_float(value)
        w = _coerce_float(weight)
        if v is None or w is None or w <= 0.0:
            continue
        num += w * v
        den += w
        den_sq += w * w
    if den <= 0.0:
        return None
    mean = num / den
    ess = (den * den) / den_sq if den_sq > 0 else 0.0
    var_num = 0.0
    for value, weight in pairs:
        v = _coerce_float(value)
        w = _coerce_float(weight)
        if v is None or w is None or w <= 0.0:
            continue
        var_num += w * (v - mean) ** 2
    # Unbiased-ish weighted variance of the mean using ESS degrees of freedom.
    if ess > 1.0:
        sample_var = var_num / den * (ess / (ess - 1.0))
        se = math.sqrt(max(sample_var, 0.0) / ess)
    else:
        se = 0.0
    if se > 0.0:
        z = mean / se
        p = 2.0 * _normal_sf(abs(z))
    else:
        z = 0.0
        p = 1.0
    return mean, se, ess, z, p


def benjamini_hochberg(pvalues: Sequence[float | None], q: float = _FDR_Q) -> list[bool]:
    """Benjamini-Hochberg FDR control. ``True`` ⇒ that scope survives.

    Controls the *rate* of false discoveries across the family of scopes tested
    in one cycle — which empirical-Bayes shrinkage does **not** do (shrinkage
    only attenuates magnitude). ``None`` p-values never survive.
    """

    indexed = [(i, p) for i, p in enumerate(pvalues) if isinstance(p, (int, float))]
    m = len(indexed)
    survived = [False] * len(pvalues)
    if m == 0:
        return survived
    ordered = sorted(indexed, key=lambda t: t[1])
    threshold_rank = -1
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= (rank / m) * q:
            threshold_rank = rank
    if threshold_rank < 0:
        return survived
    for rank, (idx, _) in enumerate(ordered, start=1):
        if rank <= threshold_rank:
            survived[idx] = True
    return survived


# ── AIA P2.3: extremization safety guards (pure analysis, no defaults moved) ─

# A scope is only allowed alpha>1 when its leaned-side hit rate clears 0.5 by
# this margin — a regime we are RELIABLY correct-sided on. Extremizing a
# wrong-sided (<=0.5) scope amplifies Brier, so the gate clamps alpha back to
# the identity there. (This is a SAFETY clamp on top of the per-question
# alpha_extremize, whose default stays 1.0 — nothing here turns extremization on.)
_HIT_RATE_MARGIN = 0.02
# Hedging diagnosis: the P(yes) mass inside this central band counts as "hedged"
# (deviating little from a coin flip). center_ward_hedge requires BOTH a high
# central-mass fraction AND SCE<0 (genuinely under-confident), so a sharp /
# over-confident scope is never told to extremize.
_HEDGE_CENTER_LO = 0.35
_HEDGE_CENTER_HI = 0.65
_HEDGE_CENTER_FRACTION = 0.5


def leaned_side_hit_rate(
    observations: Sequence[Observation],
) -> tuple[float | None, float | None, float]:
    """Weighted leaned-side hit rate AND the mean committed forecast on that side.

    For each non-neutral observation (``_included`` already drops the neutral band)
    the "leaned side" is YES when ``p_yes>0.5`` else NO; a hit is ``outcome==1`` on a
    YES lean (or ``outcome==0`` on a NO lean), and the committed forecast on the
    leaned side is ``max(p_yes, 1-p_yes)``. Returns ``(hit_rate, mean_forecast,
    ess)``. Extremizing only LOWERS Brier when the empirical hit rate EXCEEDS the
    mean committed forecast (the scope is UNDER-confident on its leaned side) — that
    is the condition :func:`extremization_alpha_gate` checks, not merely hit_rate>0.5.
    ``hit_rate``/``mean_forecast`` are ``None`` when there is no usable sample.
    """

    num = 0.0
    fcst = 0.0
    den = 0.0
    weights: list[float] = []
    for obs in _included(observations):
        leaned_yes = obs.p_yes > 0.5
        hit = (obs.outcome >= 0.5) if leaned_yes else (obs.outcome < 0.5)
        commit = obs.p_yes if leaned_yes else (1.0 - obs.p_yes)
        w = float(obs.weight)
        num += w * (1.0 if hit else 0.0)
        fcst += w * commit
        den += w
        weights.append(w)
    if den <= 0.0:
        return None, None, 0.0
    return num / den, fcst / den, effective_sample_size(weights)


def extremization_alpha_gate(
    proposed_alpha: float,
    observations: Sequence[Observation],
    *,
    margin: float = _HIT_RATE_MARGIN,
    min_ess: float = _ESS_MIN_DOMAIN,
) -> dict[str, Any]:
    """Permit ``alpha>1`` ONLY on a scope that is UNDER-confident on its leaned side.

    Pure help/hurt gate: extremizing sharpens the forecast away from 0.5 on its
    leaned side, which only LOWERS Brier when the empirical leaned-side hit rate
    EXCEEDS the mean committed forecast there (the scope is right MORE often than it
    claims). Gating on ``hit_rate > 0.5`` is insufficient — a scope leaning 0.7 that
    is right 0.59 of the time is correct-sided yet OVER-confident, and extremizing it
    raises Brier. So the threshold is the leaned-side mean forecast ``+ margin``. A
    scope that does not clear it (or lacks the effective sample) has its alpha forced
    to ``1.0``. ``alpha <= 1`` always passes through unchanged (this gate only ever
    *removes* extremization). ``allowed_alpha`` is what the caller should use.
    """

    alpha = float(proposed_alpha)
    hit_rate, mean_forecast, ess = leaned_side_hit_rate(observations)
    threshold = (mean_forecast + float(margin)) if mean_forecast is not None else None
    if alpha <= 1.0:
        return {
            "proposed_alpha": alpha,
            "allowed_alpha": alpha,
            "hit_rate": hit_rate,
            "mean_forecast": mean_forecast,
            "ess": ess,
            "threshold": threshold,
            "permitted": True,
            "reason": "alpha<=1 is never extremization — passed through",
        }
    if hit_rate is None or mean_forecast is None or ess < float(min_ess):
        return {
            "proposed_alpha": alpha,
            "allowed_alpha": 1.0,
            "hit_rate": hit_rate,
            "mean_forecast": mean_forecast,
            "ess": ess,
            "threshold": threshold,
            "permitted": False,
            "reason": f"effective sample {ess:.1f} < floor {float(min_ess):.0f} — alpha forced to 1.0",
        }
    if hit_rate > threshold:
        return {
            "proposed_alpha": alpha,
            "allowed_alpha": alpha,
            "hit_rate": hit_rate,
            "mean_forecast": mean_forecast,
            "ess": ess,
            "threshold": threshold,
            "permitted": True,
            "reason": (
                f"under-confident: leaned-side hit rate {hit_rate:.3f} > mean forecast "
                f"{mean_forecast:.3f} + margin {float(margin):.3f} — extremization permitted"
            ),
        }
    return {
        "proposed_alpha": alpha,
        "allowed_alpha": 1.0,
        "hit_rate": hit_rate,
        "mean_forecast": mean_forecast,
        "ess": ess,
        "threshold": threshold,
        "permitted": False,
        "reason": (
            f"not under-confident: hit rate {hit_rate:.3f} <= mean forecast "
            f"{mean_forecast:.3f} + margin — extremization would not help, alpha forced to 1.0"
        ),
    }


@dataclass(frozen=True)
class HedgingDiagnosis:
    """Whether a scope's RAW forecasts cluster toward the center while the scope
    is under-confident — the ONLY signature under which ``alpha>1`` is advised."""

    center_ward_hedge: bool
    center_mass_fraction: float
    sce: float | None
    n: int
    ess: float
    histogram: list[dict[str, Any]]
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "center_ward_hedge": self.center_ward_hedge,
            "center_mass_fraction": round(self.center_mass_fraction, 5),
            "sce": None if self.sce is None else round(self.sce, 5),
            "n": self.n,
            "ess": round(self.ess, 3),
            "histogram": self.histogram,
            "reason": self.reason,
        }


def diagnose_hedging(
    observations: Sequence[Observation],
    *,
    center_lo: float = _HEDGE_CENTER_LO,
    center_hi: float = _HEDGE_CENTER_HI,
    center_fraction: float = _HEDGE_CENTER_FRACTION,
) -> HedgingDiagnosis:
    """Histogram the RAW pre-adjustment P(yes) and decide whether to recommend alpha>1.

    Reads ``obs.p_yes`` (which on the calibration path carries the *raw*
    pre-adjustment probability — see :class:`Observation` and the ledger glue
    that threads ``calibration_adjustment['raw_probability']`` into it). Returns
    ``center_ward_hedge=True`` ONLY when BOTH:

    * the central-mass fraction (weighted share of forecasts in
      ``[center_lo, center_hi]``) is high (``>= center_fraction``), AND
    * the signed calibration error is negative (genuinely under-confident).

    A sharp scope (little central mass) or an over-confident one (SCE>=0) returns
    ``center_ward_hedge=False`` — do NOT extremize. The histogram bins are fixed
    decile-style buckets over [0,1] for an auditable shape (NOT the equal-freq
    SCE binning).
    """

    rows = [
        obs
        for obs in observations
        if (
            (p := _coerce_float(obs.p_yes)) is not None
            and 0.0 <= p <= 1.0
            and (w := _coerce_float(obs.weight)) is not None
            and w > 0.0
        )
    ]
    n = len(rows)
    edges = [i / 10.0 for i in range(11)]
    histogram: list[dict[str, Any]] = []
    center_w = 0.0
    total_w = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        bw = 0.0
        for obs in rows:
            p = float(obs.p_yes)
            # right-closed final bin so p==1.0 lands somewhere.
            if (lo <= p < hi) or (hi == 1.0 and p == 1.0):
                bw += float(obs.weight)
        histogram.append({"lo": round(lo, 2), "hi": round(hi, 2), "weight": round(bw, 4)})
        total_w += bw
    for obs in rows:
        p = float(obs.p_yes)
        if center_lo <= p <= center_hi:
            center_w += float(obs.weight)
    center_mass_fraction = (center_w / total_w) if total_w > 0 else 0.0
    ess = effective_sample_size([obs.weight for obs in rows])
    sce = signed_calibration_error(observations)

    center_heavy = center_mass_fraction >= float(center_fraction)
    under_confident = sce is not None and sce < 0.0
    center_ward_hedge = bool(center_heavy and under_confident)

    if center_ward_hedge:
        reason = (
            f"center-mass {center_mass_fraction:.2f} >= {center_fraction:.2f} AND SCE {sce:.3f} < 0 "
            "(under-confident hedging) — anchored extremization (alpha>1) may help"
        )
    elif not center_heavy:
        reason = (
            f"center-mass {center_mass_fraction:.2f} < {center_fraction:.2f} — already sharp, "
            "do not extremize"
        )
    elif sce is None:
        reason = "no usable signed-calibration signal — do not extremize"
    else:
        reason = (
            f"SCE {sce:.3f} >= 0 (calibrated or over-confident) — do not extremize"
        )

    return HedgingDiagnosis(
        center_ward_hedge=center_ward_hedge,
        center_mass_fraction=center_mass_fraction,
        sce=sce,
        n=n,
        ess=ess,
        histogram=histogram,
        reason=reason,
    )


# ── Reliability-curve shape (for human-readable advisory text only) ──────────


def _curve_shape(rows: Sequence[Observation]) -> list[dict[str, Any]]:
    """Coarse equal-frequency bins over P(yes) with signed per-bin gaps.

    Used only to describe *where* on the probability axis the bias sits in the
    advisory text. Coarsened so each bin clears a handful of points; the scalar
    SCE and its CI do not depend on this binning.
    """

    pts = sorted(rows, key=lambda o: o.p_yes)
    n = len(pts)
    if n == 0:
        return []
    n_bins = 3 if n < 40 else (5 if n < 80 else 10)
    n_bins = max(1, min(n_bins, n))
    bins: list[dict[str, Any]] = []
    size = math.ceil(n / n_bins)
    for start in range(0, n, size):
        chunk = pts[start : start + size]
        if not chunk:
            continue
        wsum = sum(float(o.weight) for o in chunk)
        if wsum <= 0:
            continue
        mean_pred = sum(float(o.weight) * o.p_yes for o in chunk) / wsum
        obs_freq = sum(float(o.weight) * o.outcome for o in chunk) / wsum
        side = 1.0 if mean_pred > 0.5 else -1.0
        signed_gap = side * (mean_pred - obs_freq)  # <0 under, >0 over
        bins.append(
            {
                "lo": round(min(o.p_yes for o in chunk), 3),
                "hi": round(max(o.p_yes for o in chunk), 3),
                "ess": round(effective_sample_size([o.weight for o in chunk]), 2),
                "mean_predicted": round(mean_pred, 4),
                "observed_frequency": round(obs_freq, 4),
                "signed_gap": round(signed_gap, 4),
                "direction": "under" if signed_gap < 0 else "over",
            }
        )
    return bins


def _expected_calibration_error(shape: Sequence[dict[str, Any]]) -> float | None:
    """Sample(ESS)-weighted mean absolute bin gap — the unsigned companion."""

    num = 0.0
    den = 0.0
    for b in shape:
        ess = float(b.get("ess") or 0.0)
        gap = b.get("signed_gap")
        if ess <= 0 or gap is None:
            continue
        num += ess * abs(float(gap))
        den += ess
    return num / den if den > 0 else None


# ── The report ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalibrationBiasReport:
    """Outcome of measuring one scope. ``status`` is the *measurement* verdict;
    the *disposition* (whether to write a lesson and at what status) is decided
    separately by :func:`decide_disposition` so cross-scope FDR and trajectory
    monitoring stay out of the per-scope math."""

    scope_type: str
    scope_ref: str | None
    status: str  # insufficient_evidence | calibrated | underconfident | overconfident
    n: int
    ess: float
    sce_raw: float | None
    sce_shrunk: float | None
    ci_low: float | None
    ci_high: float | None
    pvalue: float | None
    ece: float | None
    ess_min: float
    direction: str | None  # "under" | "over" | None
    curve_shape: list[dict[str, Any]] = field(default_factory=list)
    advisory_text: str | None = None
    recommended_adjustment: dict[str, Any] = field(default_factory=dict)
    horizon_label: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def has_detectable_bias(self) -> bool:
        return self.status in {"underconfident", "overconfident"}

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "scope_ref": self.scope_ref,
            "status": self.status,
            "n": self.n,
            "ess": round(self.ess, 3),
            "sce_raw": None if self.sce_raw is None else round(self.sce_raw, 5),
            "sce_shrunk": None if self.sce_shrunk is None else round(self.sce_shrunk, 5),
            "ci_low": None if self.ci_low is None else round(self.ci_low, 5),
            "ci_high": None if self.ci_high is None else round(self.ci_high, 5),
            "pvalue": None if self.pvalue is None else round(self.pvalue, 5),
            "ece": None if self.ece is None else round(self.ece, 5),
            "ess_min": self.ess_min,
            "direction": self.direction,
            "curve_shape": self.curve_shape,
            "advisory_text": self.advisory_text,
            "recommended_adjustment": self.recommended_adjustment,
            "horizon_label": self.horizon_label,
            "notes": self.notes,
        }


def _horizon_label(rows: Sequence[Observation]) -> str | None:
    """Coarse horizon descriptor so advisory text does not over-generalise from
    a fast-resolving (selection-biased) subsample."""

    horizons = [o.horizon_days for o in rows if _coerce_float(o.horizon_days) is not None]
    if not horizons:
        return None
    med = sorted(horizons)[len(horizons) // 2]
    if med <= 14:
        return "short-horizon (<=2w) resolutions"
    if med <= 90:
        return "medium-horizon (<=3m) resolutions"
    return "long-horizon (>3m) resolutions"


def _advisory_text(
    *,
    scope_ref: str | None,
    direction: str,
    magnitude_pp: int,
    n: int,
    shape: Sequence[dict[str, Any]],
    horizon_label: str | None,
) -> str:
    """Bounded, shape-specific, symmetric advisory. Deliberately NOT a blanket
    'be bolder/more cautious' — broad confidence-directional prose has large,
    hard-to-control behavioural gain (see commit 552808fb8)."""

    scope = f"in {scope_ref}" if scope_ref else "across forecasts"
    # Name the worst-offending bin matching the dominant direction.
    side = "under" if direction == "underconfident" else "over"
    candidates = [b for b in shape if b.get("direction") == side]
    where = ""
    if candidates:
        worst = max(candidates, key=lambda b: abs(float(b.get("signed_gap") or 0.0)))
        where = f" The gap is largest for forecasts in the {worst['lo']:.2f}-{worst['hi']:.2f} range."
    horizon = f" Measured on {horizon_label}." if horizon_label else ""
    if direction == "underconfident":
        body = (
            f"Over {n} resolved binary questions {scope}, outcomes landed on the "
            f"leaned side more often than stated — about {magnitude_pp}pp "
            f"under-confident.{where} When you reach a confident call there, check "
            f"you are not hedging: if you cannot name a credible path for the "
            f"residual tail mass, concentrate it on the supported outcome."
        )
    else:
        body = (
            f"Over {n} resolved binary questions {scope}, the leaned side came "
            f"true less often than stated — about {magnitude_pp}pp "
            f"over-confident.{where} When you reach for a sharp call there, "
            f"stress-test the disconfirming case and widen toward the evidence "
            f"before committing."
        )
    return body + horizon + (
        " This is a measured tendency on past resolutions, not a rule — weigh it "
        "against the specifics of this question."
    )


def _recommended_adjustment(
    *,
    direction: str,
    sce_shrunk: float,
    ess: float,
    enable_mechanical: bool,
    prior_scale: float | None,
) -> dict[str, Any]:
    """Empty unless mechanical is opted-in AND the strong numeric gates pass.

    The nudge is a base-rate-neutral ``logit_scale`` (>1 sharpens / <1 flattens
    around 0.5), shrunk-magnitude × partial gain, magnitude-capped, with a
    hysteretic deadband so a correction is not abruptly withdrawn (which would
    create a limit cycle)."""

    if not enable_mechanical:
        return {}
    if ess < _MECH_MIN_ESS:
        return {}
    mag = abs(sce_shrunk)
    # Hysteresis: once correcting, keep correcting down to ENTER; only (re)start
    # above EXIT. ``prior_scale`` (the currently active scale, if any) tells us
    # whether we are already in the correcting regime.
    already_correcting = prior_scale is not None and abs((prior_scale or 1.0) - 1.0) > 1e-9
    floor = _MECH_DEADBAND_ENTER if already_correcting else _MECH_DEADBAND_EXIT
    if mag < floor:
        return {}
    step = _clamp(_MECH_GAIN * (mag / _MECH_REF) * _MECH_CAP, 0.0, _MECH_CAP)
    if step <= 0.0:
        return {}
    # under-confident ⇒ sharpen (scale>1); over-confident ⇒ flatten (scale<1).
    scale = 1.0 + step if direction == "underconfident" else 1.0 - step
    return {
        "logit_scale": round(scale, 4),
        "basis": "signed_calibration_error",
        "gain": _MECH_GAIN,
        "cap": _MECH_CAP,
        "note": "base-rate-neutral confidence rescale around 0.5",
    }


def assess_bias(
    observations: Sequence[Observation],
    *,
    scope_type: str = "domain",
    scope_ref: str | None = None,
    lesson_free_only: bool = True,
    enable_mechanical: bool = False,
    prior_scale: float | None = None,
    ess_min: float | None = None,
    shrink_prior: float = 0.0,
) -> CalibrationBiasReport:
    """Measure signed calibration bias for one scope.

    ``lesson_free_only`` restricts *derivation* to forecasts that had no active
    same-scope lesson in context (contamination control); the loop otherwise
    measures its own advice. ``shrink_prior`` is the empirical-Bayes target
    (0.0, or a pooled global SCE) toward which the domain estimate shrinks.
    """

    floor = ess_min if ess_min is not None else (
        _ESS_MIN_GLOBAL if scope_type == "global" else _ESS_MIN_DOMAIN
    )
    notes: list[str] = []

    pool = list(observations)
    if lesson_free_only:
        clean = [o for o in pool if not o.lesson_active]
        contaminated = len(pool) - len(clean)
        if contaminated:
            notes.append(
                f"excluded {contaminated} lesson-active forecast(s) from derivation"
            )
        pool = clean

    rows = _included(pool)
    n = len(rows)
    ess = effective_sample_size([o.weight for o in rows])
    shape = _curve_shape(rows)
    ece = _expected_calibration_error(shape)
    horizon_label = _horizon_label(rows)

    base = CalibrationBiasReport(
        scope_type=scope_type,
        scope_ref=scope_ref,
        status="insufficient_evidence",
        n=n,
        ess=ess,
        sce_raw=None,
        sce_shrunk=None,
        ci_low=None,
        ci_high=None,
        pvalue=None,
        ece=ece,
        ess_min=floor,
        direction=None,
        curve_shape=shape,
        horizon_label=horizon_label,
        notes=notes,
    )

    if ess < floor:
        notes.append(f"effective sample {ess:.1f} < floor {floor:.0f}")
        return base

    pairs = [
        (c, float(o.weight))
        for o in rows
        if (c := o.signed_contribution()) is not None
    ]
    stats = _weighted_mean_ci(pairs)
    if stats is None:
        return base
    sce_raw, se, _ess2, _z, pvalue = stats
    ci_low = sce_raw - _Z_ALPHA * se
    ci_high = sce_raw + _Z_ALPHA * se

    # Empirical-Bayes shrinkage toward the prior (0 or pooled global SCE).
    shrink_w = ess / (ess + _SHRINK_K)
    sce_shrunk = shrink_prior + shrink_w * (sce_raw - shrink_prior)

    # CI gate: the interval must clear zero by the margin.
    ci_excludes_zero = (ci_low > _CI_MARGIN) or (ci_high < -_CI_MARGIN)
    significant = ci_excludes_zero and (pvalue is not None and pvalue <= _ALPHA)

    if not significant or abs(sce_shrunk) < _DEADBAND:
        status = "calibrated"
        direction = None
        advisory = None
        adjustment: dict[str, Any] = {}
        if not significant:
            notes.append("CI includes zero / not significant — no direction emitted")
        else:
            notes.append(f"|shrunk SCE| {abs(sce_shrunk):.3f} within deadband {_DEADBAND}")
    else:
        direction_word = "underconfident" if sce_shrunk < 0 else "overconfident"
        status = direction_word
        direction = "under" if sce_shrunk < 0 else "over"
        magnitude_pp = int(round(abs(sce_shrunk) * 100))
        advisory = _advisory_text(
            scope_ref=scope_ref,
            direction=direction_word,
            magnitude_pp=magnitude_pp,
            n=n,
            shape=shape,
            horizon_label=horizon_label,
        )
        adjustment = _recommended_adjustment(
            direction=direction_word,
            sce_shrunk=sce_shrunk,
            ess=ess,
            enable_mechanical=enable_mechanical,
            prior_scale=prior_scale,
        )

    return CalibrationBiasReport(
        scope_type=scope_type,
        scope_ref=scope_ref,
        status=status,
        n=n,
        ess=ess,
        sce_raw=sce_raw,
        sce_shrunk=sce_shrunk,
        ci_low=ci_low,
        ci_high=ci_high,
        pvalue=pvalue,
        ece=ece,
        ess_min=floor,
        direction=direction,
        curve_shape=shape,
        advisory_text=advisory,
        recommended_adjustment=adjustment,
        horizon_label=horizon_label,
        notes=notes,
    )


# ── Disposition: cross-scope FDR + trajectory monitoring → lesson status ─────


def decide_disposition(
    report: CalibrationBiasReport,
    *,
    bh_survived: bool,
    trajectory: Sequence[float] = (),
    strong_ess: float = _STRONG_ESS,
    strong_mag: float = _STRONG_MAG,
) -> dict[str, Any]:
    """Decide whether to write a lesson for ``report`` and at what status.

    Returns ``{"lesson_status": one of none|tentative|active|suppressed,
    "reasons": [...]}``. ``trajectory`` is the prior ``|SCE|`` history for the
    scope (oldest→newest, *excluding* this cycle); a bias that has grown for two
    consecutive cycles, or flipped sign against an active lesson, is suppressed
    rather than re-pushed — the only defensible convergence guard for an LLM
    actuator.
    """

    reasons: list[str] = []
    if not report.has_detectable_bias:
        return {"lesson_status": "none", "reasons": ["no detectable bias"]}
    if not bh_survived:
        return {"lesson_status": "none", "reasons": ["did not survive BH FDR control"]}

    # Trajectory / oscillation guard. Append this cycle's magnitude and look at
    # the last three points: two consecutive increases ⇒ we are diverging.
    mag = abs(report.sce_shrunk or 0.0)
    hist = [abs(float(h)) for h in trajectory] + [mag]
    if len(hist) >= 3 and hist[-1] > hist[-2] > hist[-3]:
        return {
            "lesson_status": "suppressed",
            "reasons": ["|SCE| rose for two consecutive cycles — suppressing to avoid overshoot"],
        }

    strong = (
        report.ess >= strong_ess
        and mag >= strong_mag
    )
    if strong:
        reasons.append(f"ess {report.ess:.0f} >= {strong_ess:.0f} and |shrunk| {mag:.3f} >= {strong_mag}")
        return {"lesson_status": "active", "reasons": reasons}
    reasons.append("detectable but below strong-activation gates — tentative")
    return {"lesson_status": "tentative", "reasons": reasons}
