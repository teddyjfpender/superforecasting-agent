"""Canonical reasoning-method taxonomy for the reasoning-composition hook.

The agent self-tags which methods it used (a `reasoning_methods` list on the
snapshot); the hook checks the set/count/composition against a profile's required
set. This module is the single source of truth for the vocabulary + normalization
(so "base-rate", "base rate", "BASE_RATE" all map to the `base_rate` slug).
"""

from __future__ import annotations

# slug -> one-line description (shown by `forecast hooks explain` + the TUI).
REASONING_METHODS: dict[str, str] = {
    "reductive": "Reduce the question to simpler sub-problems and solve those.",
    "deductive": "Derive the conclusion from general premises (top-down, truth-preserving).",
    "inductive": "Generalize from specific observations to a likely pattern.",
    "abductive": "Infer the best explanation that accounts for the evidence.",
    "bayesian": "Update a prior on likelihood ratios in log-odds.",
    "base_rate": "Anchor on how often things of this sort happen (reference class).",
    "analogy": "Reason from a structurally similar past case.",
    "causality": "Trace the causal mechanism / pathway to the outcome.",
    "systems": "Reason about feedback loops, stocks/flows, second-order effects.",
    "game_theory": "Model strategic incentives + equilibria of the actors.",
    "dialectics": "Thesis vs antithesis -> synthesis; reason through opposing positions.",
    "outside_view": "Take the statistical outside view before the case-specific story.",
    "inside_view": "Build the case-specific mechanistic model.",
    "fermi": "Decompose into estimable factors and multiply (order-of-magnitude).",
    "decomposition": "Break the estimate into pooled drivers / components.",
    "conditional": "Reason through conditional branches (if X then Y) + chain them.",
    "comparative": "Compare against related cases / a peer set to place the estimate.",
    "trend_extrapolation": "Extend an observed trend, with skepticism about persistence.",
    "mean_reversion": "Weight reversion toward a long-run mean / equilibrium.",
    "extremizing": "Sharpen a pooled estimate away from the crowd when warranted.",
    "calibration": "Reason from your own track record / calibration lessons.",
    "disconfirmation": "Actively seek evidence that would refute the leaning view.",
    "pre_mortem": "Imagine the forecast failed and work backward to why.",
    "question_framing": "Interrogate / sharpen the resolution criteria before pricing.",
    "steelmanning": "Build the strongest version of the opposing case.",
    "strawmanning": "(anti-pattern) a weak caricature of the opposing case.",
}

METHOD_SLUGS: frozenset[str] = frozenset(REASONING_METHODS)


def normalize_method(name: str) -> str | None:
    """Map a free-form label to a canonical slug, or None if unknown."""
    if not isinstance(name, str):
        return None
    slug = name.strip().lower().replace(" ", "_").replace("-", "_")
    # tolerate a few common phrasings
    aliases = {
        "base_rates": "base_rate", "outside": "outside_view", "inside": "inside_view",
        "premortem": "pre_mortem", "pre_mortem_reasoning": "pre_mortem",
        "fermi_estimation": "fermi", "game_theoretic": "game_theory",
        "trend": "trend_extrapolation", "trend_extrapolation_with_skepticism": "trend_extrapolation",
        "reversion": "mean_reversion", "framing": "question_framing",
    }
    slug = aliases.get(slug, slug)
    return slug if slug in METHOD_SLUGS else None


def normalize_methods(methods) -> tuple[list[str], list[str]]:
    """Return (recognized_slugs_deduped, unknown_inputs)."""
    recognized: list[str] = []
    unknown: list[str] = []
    for m in methods or []:
        slug = normalize_method(m)
        if slug is None:
            unknown.append(str(m))
        elif slug not in recognized:
            recognized.append(slug)
    return recognized, unknown
