"""Multi-perspective forecast panel.

Single-agent forecasting collapses into one estimate per pass. Real
"forecast-desk" discipline gets its force from independent estimates, a
revealed spread, and odds-space aggregation. This module simulates that
inside one ``forecast update``: each perspective is a constrained framing
the agent runs separately (outside view only, inside view only, market
comparison, red-team, sanity check), and the toolkit aggregates the
results via trimmed geomean of odds (or log-odds pooling) with the spread
preserved as a first-class artifact on the snapshot.

This file is deliberately small: prompt templates + an aggregation
helper. The ledger handles persistence, the CLI / agent tool handle
orchestration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from forecasting.bayes_toolkit import (
    log_odds_pool,
    mean_probability,
    platt_scale,
    prob_to_odds,
)
from forecasting.models import ValidationError


# ── Perspectives ────────────────────────────────────────────────────────────


PANEL_PERSPECTIVES: dict[str, dict[str, str]] = {
    "outside": {
        "label": "Outside view",
        "system": (
            "You are a forecaster constrained to the OUTSIDE VIEW. Use only "
            "reference classes and base rates. Do NOT propose mechanistic "
            "models, do not weight recent news heavily, and do not introduce "
            "an inside-view causal story. Your job is to anchor the panel on "
            "what comparable historical cases imply."
        ),
        "instruction": (
            "Estimate the probability using base rates and reference classes "
            "only. Output: probability, 80% confidence interval, top 3 "
            "reasons, biggest crux, what observation would change your mind."
        ),
    },
    "inside": {
        "label": "Inside view / mechanistic model",
        "system": (
            "You are a forecaster constrained to the INSIDE VIEW. Build a "
            "mechanistic causal story from the available evidence. Do NOT "
            "anchor on base rates — the outside-view forecaster covers that. "
            "Your job is to capture mechanism-specific information the base "
            "rate would miss."
        ),
        "instruction": (
            "Estimate the probability using a mechanistic / causal model "
            "drawing on the live evidence and structural reasoning. Output: "
            "probability, 80% confidence interval, the causal chain you used, "
            "top 3 reasons, biggest crux, what would change your mind."
        ),
    },
    "market": {
        "label": "Market / expert comparison",
        "system": (
            "You are a forecaster constrained to MARKET AND EXPERT signal. "
            "Use prediction-market prices (de-vigged), polls, expert surveys, "
            "and analyst consensus. Apply likelihood ratios against the prior "
            "rather than re-deriving everything from scratch."
        ),
        "instruction": (
            "Estimate the probability using market + expert signals only. "
            "Output: probability, 80% confidence interval, the markets / "
            "experts you used and how you de-vigged or weighted them, biggest "
            "crux, what would change your mind."
        ),
    },
    "red_team": {
        "label": "Red team",
        "system": (
            "You are the RED-TEAM forecaster. Your job is to argue why the "
            "other panelists are wrong. Default toward the contrarian side of "
            "the consensus. Identify the strongest case that the probability "
            "should move the OPPOSITE direction from the panel's median."
        ),
        "instruction": (
            "Estimate the probability assuming the panel's median is wrong. "
            "Output: probability, 80% confidence interval, the three "
            "strongest reasons the panel is biased, biggest crux, what would "
            "change your mind."
        ),
    },
    "sanity": {
        "label": "Unconditional sanity check",
        "system": (
            "You are the SANITY-CHECK forecaster. Provide a quick gut-feel "
            "unconditional probability without decomposing into conditionals. "
            "This is the cross-check against the panel's structured "
            "estimates: when your number diverges sharply from theirs, that "
            "is information."
        ),
        "instruction": (
            "Estimate the probability as a single gut-feel number with no "
            "structured decomposition. Output: probability, 80% confidence "
            "interval, one-sentence reason, biggest crux."
        ),
    },
}


DEFAULT_PANEL_PERSPECTIVES: tuple[str, ...] = (
    "outside",
    "inside",
    "market",
    "red_team",
    "sanity",
)


PANEL_AGGREGATION_METHODS = frozenset(
    {"trimmed_geomean_odds", "log_odds_pool", "median", "mean"}
)

# The DEFAULT aggregation method. SELECTABLE alternatives live in
# PANEL_AGGREGATION_METHODS, but the live default is pinned here and asserted by
# tests: an un-configured panel/quorum must stay byte-identical to history. Never
# change this constant to make the convexity baseline ('mean') the silent default.
DEFAULT_PANEL_AGGREGATION_METHOD = "trimmed_geomean_odds"


# ── Aggregation ─────────────────────────────────────────────────────────────


@dataclass
class PanelAggregation:
    """Result of aggregating a panel of estimates for a binary question.

    ``aggregate_probability`` is the FINAL (terminally-calibrated) panel scalar.
    ``pre_extremize_probability`` mirrors :class:`bayes_toolkit.PoolResult`: it
    is the bare pooled scalar BEFORE the terminal Platt calibration, and is
    ``None`` when no calibration was applied (the identity alpha=1.0 path), so an
    un-configured question is byte-identical to the historical bare pool.
    ``applied_alpha`` is the per-question Platt slope actually applied
    (``alpha_extremize``); 1.0 means no-op.
    """

    method: str
    aggregate_probability: float
    spread: dict[str, float]
    trim: int
    estimates: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)
    pre_extremize_probability: float | None = None
    applied_alpha: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "aggregate_probability": round(self.aggregate_probability, 6),
            "spread": {
                k: (round(v, 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                for k, v in self.spread.items()
            },
            "trim": self.trim,
            "estimates": self.estimates,
            "notes": self.notes,
            "pre_extremize_probability": (
                None if self.pre_extremize_probability is None
                else round(self.pre_extremize_probability, 6)
            ),
            "applied_alpha": round(self.applied_alpha, 6),
        }


def aggregate_panel_estimates(
    estimates: Sequence[Mapping[str, Any]],
    *,
    method: str = DEFAULT_PANEL_AGGREGATION_METHOD,
    trim: int = 1,
    alpha_extremize: float = 1.0,
) -> PanelAggregation:
    """Aggregate per-perspective probability estimates into a panel decision.

    ``method``:
      - ``trimmed_geomean_odds`` (default): drop the ``trim`` highest and
        ``trim`` lowest probabilities, then take the weighted geometric mean
        of odds via :func:`forecasting.bayes_toolkit.log_odds_pool`. Defaults
        to ``trim=1`` to match the Samotsvety-style "drop the extremes" rule
        — set ``trim=0`` for no trimming.
      - ``log_odds_pool``: full geometric mean of odds with weights (no trim).
      - ``median``: weighted median of probabilities. Robust but ignores
        confidence — use when forecasters disagree on the order of magnitude.
      - ``mean``: weighted arithmetic mean of probabilities (AIA P1.4). The
        convexity-backed BASELINE — ``Brier(mean) <= mean(Brier)`` by Jensen — so
        it is the floor any pool/judge must beat. SELECTABLE only; never the
        default.

    The spread artifact captures the panel disagreement so it can be shown
    next to the aggregate ("the spread is the most valuable part").

    Terminal calibration (AIA P0.1): after the pool, the scalar is passed
    through the desk's single recalibration kernel
    :func:`forecasting.bayes_toolkit.platt_scale` with a per-question
    ``alpha_extremize`` slope, defaulting to ``1.0`` (the identity) so an
    un-configured question is BYTE-IDENTICAL to the historical bare pool — the
    hard invariant. At the identity, ``pre_extremize_probability`` stays ``None``
    (mirroring :class:`bayes_toolkit.PoolResult`). The MEASURED per-scope
    confidence rescale is applied separately downstream in
    :func:`forecasting.learning.apply_active_lesson_adjustments` (the fixed
    de-hedge and the learned correction compose along the pipeline, NOT at this
    one call site — never multiply them here or the learned slope double-applies).
    """

    cleaned = _clean_estimates(estimates)
    if not cleaned:
        raise ValidationError("panel aggregation requires at least one estimate")

    method = (method or "").strip().lower()
    if method not in PANEL_AGGREGATION_METHODS:
        raise ValidationError(
            "method must be one of " + ", ".join(sorted(PANEL_AGGREGATION_METHODS))
        )
    if trim < 0:
        raise ValidationError("trim must be >= 0")

    annotated, dropped = _apply_trim(cleaned, trim)
    kept = [row for row in annotated if not row["trimmed"]]
    if not kept:
        raise ValidationError("trim removed every panel estimate; reduce trim")
    notes = [f"trimmed {dropped} extreme estimates"] if dropped else []

    probs = [row["probability"] for row in kept]
    weights = [row["weight"] for row in kept]
    if method in {"trimmed_geomean_odds", "log_odds_pool"}:
        aggregate = log_odds_pool(probs, weights)
    elif method == "mean":
        # The convexity-backed simple-mean BASELINE (AIA P1.4): weighted
        # arithmetic mean in probability space. Brier(mean) <= mean(Brier) by
        # Jensen, so this is the formal floor any pool/judge must beat. Selectable
        # only — the desk default stays trimmed_geomean_odds. The terminal Platt
        # alpha below still applies identically after it.
        aggregate = mean_probability(probs, weights)
    else:  # median
        aggregate = float(median(probs))

    # ── terminal Platt calibration ────────────────────────────────────────────
    # Apply the per-question extremization slope. At the identity (1.0) this is a
    # strict no-op: the pre_extremize field stays None and the aggregate is
    # byte-identical to the bare pool.
    alpha = float(alpha_extremize)
    pre_extremize: float | None = None
    if alpha != 1.0:
        pre_extremize = float(aggregate)
        aggregate = platt_scale(aggregate, alpha=alpha, d=1.0)
        notes.append(
            f"terminal Platt calibration alpha={alpha:g}:"
            f" {pre_extremize:.4f} -> {float(aggregate):.4f}"
        )

    spread = _spread_summary([row["probability"] for row in cleaned])
    # Fold the terminal-calibration markers into the persisted spread so the
    # stage is observable downstream (the desk + the skipped-terminal-calibration
    # hook) without a schema migration — mirrors how disagreement_signal rides
    # along here. ``applied_alpha`` is always present (1.0 = no-op);
    # ``pre_extremize_probability`` is present only when calibration ran.
    spread["applied_alpha"] = round(alpha, 6)
    spread["terminal_calibration_applied"] = alpha != 1.0
    if pre_extremize is not None:
        spread["pre_extremize_probability"] = round(pre_extremize, 6)
    return PanelAggregation(
        method=method,
        aggregate_probability=float(aggregate),
        spread=spread,
        trim=trim,
        estimates=annotated,
        notes=notes,
        pre_extremize_probability=pre_extremize,
        applied_alpha=alpha,
    )


def _clean_estimates(estimates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(estimates):
        if not isinstance(raw, Mapping):
            raise ValidationError(f"panel estimates[{index}] must be an object")
        probability = raw.get("probability")
        if probability is None:
            for alt in ("p", "prob", "probability_or_distribution"):
                if raw.get(alt) is not None:
                    probability = raw[alt]
                    break
        if probability is None:
            raise ValidationError(f"panel estimates[{index}] requires 'probability'")
        try:
            probability = float(probability)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"panel estimates[{index}].probability must be numeric"
            ) from exc
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValidationError(
                f"panel estimates[{index}].probability must be in [0, 1]"
            )
        weight_raw = raw.get("weight", 1.0)
        try:
            weight = float(weight_raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"panel estimates[{index}].weight must be numeric"
            ) from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValidationError(
                f"panel estimates[{index}].weight must be > 0"
            )
        perspective = str(raw.get("perspective") or raw.get("name") or f"perspective_{index + 1}")
        ci_low = _optional_float(raw.get("confidence_low"))
        ci_high = _optional_float(raw.get("confidence_high"))
        if ci_low is not None and ci_high is not None and ci_low > ci_high:
            raise ValidationError(
                f"panel estimates[{index}] confidence_low must be <= confidence_high"
            )
        out.append(
            {
                "perspective": perspective,
                "probability": probability,
                "weight": weight,
                "confidence_low": ci_low,
                "confidence_high": ci_high,
                "rationale": str(raw.get("rationale") or "").strip(),
                "reasons_up": _string_list(raw.get("reasons_up")),
                "reasons_down": _string_list(raw.get("reasons_down")),
                "change_my_mind": _string_list(raw.get("change_my_mind")),
                "crux": (raw.get("crux") or None) and str(raw.get("crux")).strip(),
                "agent_model": (raw.get("agent_model") or None),
                "metadata": dict(raw.get("metadata") or {}),
                "trimmed": False,
            }
        )
    return out


def _apply_trim(rows: list[dict[str, Any]], trim: int) -> tuple[list[dict[str, Any]], int]:
    if trim <= 0 or len(rows) <= 2 * trim:
        return [dict(row) for row in rows], 0
    order = sorted(range(len(rows)), key=lambda i: rows[i]["probability"])
    trimmed_positions = set(order[:trim]) | set(order[-trim:])
    annotated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row = dict(row)
        row["trimmed"] = index in trimmed_positions
        annotated.append(row)
    return annotated, 2 * trim


def _spread_summary(probabilities: Sequence[float]) -> dict[str, float]:
    if not probabilities:
        return {}
    sorted_probs = sorted(probabilities)
    n = len(sorted_probs)
    summary = {
        "min": sorted_probs[0],
        "max": sorted_probs[-1],
        "median": float(median(sorted_probs)),
        "range": sorted_probs[-1] - sorted_probs[0],
        "p25": _percentile(sorted_probs, 25),
        "p75": _percentile(sorted_probs, 75),
        "iqr": _percentile(sorted_probs, 75) - _percentile(sorted_probs, 25),
        "count": float(n),
    }
    # Fold the log-odds disagreement scalar into the spread so it is persisted
    # on every panel run and rendered by the desk without extra plumbing.
    summary.update(disagreement_signal(sorted_probs))
    return summary


# ── Disagreement signal ──────────────────────────────────────────────────────
#
# Disagreement is the most valuable part of a panel: a wide spread is epistemic
# uncertainty the aggregate hides. We measure it in LOG-ODDS space (the space
# the panel pools in) so an order-of-magnitude split low in the range counts as
# much as one mid-range, and squash it to a [0, 1] index that can be regressed
# against realised error downstream (see the calibration learning loop).

_LOGIT_EPS = 1e-6
# Logit-space dispersion knee: sd≈2 (panelists split ~0.12 vs ~0.88) → ~0.76.
_DISAGREEMENT_SCALE = 2.0


def _logit(p: float) -> float:
    p = min(max(float(p), _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return math.log(p / (1.0 - p))


def _disagreement_band(index: float) -> str:
    if index < 0.15:
        return "calm"
    if index < 0.40:
        return "moderate"
    if index < 0.65:
        return "high"
    return "severe"


def disagreement_signal(
    probabilities: Sequence[float],
    weights: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Quantify panel disagreement as a first-class, learnable signal.

    Returns ``sd_logit`` (weighted std of the logits), ``disagreement_index``
    (``tanh(sd_logit / scale)`` in [0, 1]), ``disagreement_band`` (calm /
    moderate / high / severe), and ``prob_range``. A single estimate has zero
    disagreement by definition. Keys are prefixed so they merge cleanly into a
    spread summary.
    """

    probs = [float(p) for p in probabilities]
    if not probs:
        raise ValidationError("disagreement_signal requires at least one probability")
    n = len(probs)
    if weights is None:
        weights = [1.0] * n
    weights = [float(w) for w in weights]
    if len(weights) != n:
        raise ValidationError("weights length must match probabilities length")
    total_w = sum(weights)
    if total_w <= 0:
        raise ValidationError("weights must sum to > 0")

    logits = [_logit(p) for p in probs]
    mean = sum(w * x for w, x in zip(weights, logits)) / total_w
    if n == 1:
        sd = 0.0
    else:
        var = sum(w * (x - mean) ** 2 for w, x in zip(weights, logits)) / total_w
        sd = math.sqrt(max(var, 0.0))
    # Round first, then band off the rounded value, so the stored index and
    # band never disagree — and any consumer that recomputes the band from the
    # index (e.g. the desk meter) lands on the same label at the boundaries.
    index = round(math.tanh(sd / _DISAGREEMENT_SCALE), 6)
    return {
        "sd_logit": round(sd, 6),
        "disagreement_index": index,
        "disagreement_band": _disagreement_band(index),
        "prob_range": round(max(probs) - min(probs), 6),
    }


def _percentile(sorted_probs: Sequence[float], pct: float) -> float:
    if not sorted_probs:
        return float("nan")
    if len(sorted_probs) == 1:
        return float(sorted_probs[0])
    rank = (pct / 100.0) * (len(sorted_probs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_probs[lo])
    return float(sorted_probs[lo] * (hi - rank) + sorted_probs[hi] * (rank - lo))


def _optional_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError("confidence bounds must be numeric") from exc
    if not math.isfinite(value):
        raise ValidationError("confidence bounds must be finite")
    if not 0.0 <= value <= 1.0:
        raise ValidationError("confidence bounds must be in [0, 1]")
    return value


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValidationError("reasons fields must be strings or lists of strings")
    return [str(item).strip() for item in items if str(item).strip()]


# ── Gating heuristic ────────────────────────────────────────────────────────


def should_run_panel(
    *,
    impact: str | None,
    has_prior_snapshot: bool,
    force: bool | None = None,
) -> bool:
    """Decide whether a panel should run by default.

    The three trigger rules:
      1. Explicit ``force=True`` from the caller.
      2. The question is tagged ``impact="high"``.
      3. There is no prior forecast snapshot — the first forecast for a
         question is the cheapest moment to establish a panel baseline.

    ``force=False`` overrides everything (caller explicitly opted out).
    """

    if force is False:
        return False
    if force is True:
        return True
    if (impact or "").strip().lower() == "high":
        return True
    if not has_prior_snapshot:
        return True
    return False


# ── Prompt builders ─────────────────────────────────────────────────────────


def build_perspective_prompts(
    *,
    question_title: str,
    resolution_criteria: str,
    context_packet: str,
    perspectives: Iterable[str] = DEFAULT_PANEL_PERSPECTIVES,
) -> dict[str, dict[str, str]]:
    """Return system+user prompts per perspective for the agent to run.

    Each prompt instructs the agent to return a JSON object with
    ``probability``, ``confidence_low``, ``confidence_high``, ``rationale``,
    ``reasons_up``, ``reasons_down``, ``change_my_mind``, ``crux``. The agent
    runs them silently and only reveals the spread after all submissions —
    discussion is for error correction, not consensus manufacture.
    """

    out: dict[str, dict[str, str]] = {}
    user_template = (
        "## Forecast Question\n"
        f"{question_title}\n\n"
        "## Resolution Criteria\n"
        f"{resolution_criteria}\n\n"
        "## Shared Ledger Context\n"
        f"{context_packet}\n\n"
        "## Submission\n"
        "Return ONLY a JSON object with keys:\n"
        "- probability: number in [0, 1]\n"
        "- confidence_low: number in [0, 1] (10th percentile)\n"
        "- confidence_high: number in [0, 1] (90th percentile)\n"
        "- rationale: one paragraph\n"
        "- reasons_up: array of 1-3 concrete reasons\n"
        "- reasons_down: array of 1-3 concrete reasons\n"
        "- change_my_mind: array of 1-3 observations that would force a material update\n"
        "- crux: one sentence naming the single biggest uncertainty"
    )
    for name in perspectives:
        spec = PANEL_PERSPECTIVES.get(name)
        if spec is None:
            raise ValidationError(
                f"unknown panel perspective '{name}'. Known: "
                + ", ".join(sorted(PANEL_PERSPECTIVES))
            )
        out[name] = {
            "label": spec["label"],
            "system": spec["system"] + "\n\n" + spec["instruction"],
            "user": user_template,
        }
    return out


__all__ = [
    "PANEL_PERSPECTIVES",
    "DEFAULT_PANEL_PERSPECTIVES",
    "PANEL_AGGREGATION_METHODS",
    "DEFAULT_PANEL_AGGREGATION_METHOD",
    "PanelAggregation",
    "aggregate_panel_estimates",
    "build_perspective_prompts",
    "should_run_panel",
    "disagreement_signal",
]
