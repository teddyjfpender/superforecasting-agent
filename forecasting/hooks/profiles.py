"""Curated hook profiles + the strictness ladder.

A profile is a named map of rule_id -> Severity. ``standard`` is defined to equal
the system's pre-hooks enforcement (the tool's require_* defaults + the Phase 2
style gate), so adopting config-driven policy is a no-op on upgrade. ``strict``
promotes the advisory rules to blocking; ``exploratory-lenient`` drops everything
to advisory. Impact scaling moves a question up/down this ladder without
per-question config.
"""

from __future__ import annotations

from forecasting.hooks.builtins import BUILTIN_RULE_IDS
from forecasting.hooks.spec import Severity

# Ordered loosest -> strictest. impact_scaling deltas move along this ladder.
LADDER: tuple[str, ...] = ("exploratory-lenient", "standard", "strict")

_E, _W, _O = Severity.ERROR, Severity.WARN, Severity.OFF

HOOK_PROFILES: dict[str, dict[str, Severity]] = {
    # All advisory: nothing blocks. For low-stakes / scratch work.
    "exploratory-lenient": {
        "require_structured_reasoning": _W,
        "require_components": _W,
        "require_fresh_evidence": _O,
        "require_decision_readiness": _O,
        "require_panel": _O,
        "require_citations": _O,
        "require_outcome_paths": _O,
        "style_clean": _W,
        "lessons_applied": _O,
        # v2
        "output_renderable": _W,
        "uncertainty_well_formed": _W,
        "uncertainty_width_sane": _O,
        "quorum_participation": _O,
        "quorum_required": _O,
        "quorum_judged": _O,
        "tails_justified": _O,
        "calibration_bias_applied": _O,
        "confidence_committed": _O,
        "reasoning_composition": _O,
        "thesis_aggregate_fresh": _O,
    },
    # == the pre-hooks enforcement (tool require_* defaults + Phase 2 style gate),
    # which also equals the builtin default severities. Adopting it changes nothing.
    "standard": {
        "require_structured_reasoning": _E,
        "require_components": _E,
        "require_fresh_evidence": _E,
        "require_decision_readiness": _W,
        "require_panel": _E,
        "require_citations": _W,
        "require_outcome_paths": _W,
        "style_clean": _E,
        "lessons_applied": _W,
        # v2 — structural OUTPUT rules block (bug-catchers; programmatic auto-fix);
        # reasoning + soft-confidence + quorum-participation are advisory by default.
        "output_renderable": _E,
        "uncertainty_well_formed": _E,
        "uncertainty_width_sane": _W,
        "quorum_participation": _W,
        "quorum_required": _W,
        "quorum_judged": _W,
        "tails_justified": _W,
        "calibration_bias_applied": _W,
        "confidence_committed": _W,
        "reasoning_composition": _W,
        "thesis_aggregate_fresh": _W,
    },
    # Everything blocking — for high-stakes desks that want full saturation.
    "strict": {
        "require_structured_reasoning": _E,
        "require_components": _E,
        "require_fresh_evidence": _E,
        "require_decision_readiness": _E,
        "require_panel": _E,
        "require_citations": _E,
        "require_outcome_paths": _E,
        "style_clean": _E,
        "lessons_applied": _E,
        # v2
        "output_renderable": _E,
        "uncertainty_well_formed": _E,
        "uncertainty_width_sane": _W,   # width is genuinely fuzzy; stays advisory even in strict
        "quorum_participation": _E,
        "quorum_required": _E,
        "quorum_judged": _E,
        "tails_justified": _E,
        "calibration_bias_applied": _E,
        "confidence_committed": _W,     # soft min-sharpness with escape; never a hard block
        "reasoning_composition": _E,
        "thesis_aggregate_fresh": _W,
    },
}

DEFAULT_PROFILE = "standard"

# Required reasoning composition per profile: (must_include_all, min_distinct_count).
# The min count forces breadth beyond the required set.
REASONING_REQUIRED: dict[str, tuple[tuple[str, ...], int]] = {
    "exploratory-lenient": ((), 0),
    "standard": (("outside_view", "base_rate"), 3),
    "strict": (("outside_view", "base_rate", "pre_mortem", "disconfirmation"), 5),
}


def resolve_reasoning_requirement(profile_name: str) -> tuple[tuple[str, ...], int]:
    """(required-method set, min distinct count) for a profile."""
    return REASONING_REQUIRED.get(profile_name) or REASONING_REQUIRED[DEFAULT_PROFILE]


def profile_severities(name: str) -> dict[str, Severity]:
    """The rule_id -> Severity map for a named profile (falls back to standard)."""
    base = HOOK_PROFILES.get(name) or HOOK_PROFILES[DEFAULT_PROFILE]
    # Ensure every built-in rule has an entry (default to the standard severity).
    out = dict(HOOK_PROFILES[DEFAULT_PROFILE])
    out.update(base)
    for rid in BUILTIN_RULE_IDS:
        out.setdefault(rid, Severity.WARN)
    return out


def scaled_profile(name: str, *, ladder_delta: int) -> str:
    """Move ``name`` up/down the strictness ladder by ``ladder_delta`` rungs,
    clamped to the ends. Unknown profiles are returned unchanged (custom profiles
    are not on the built-in ladder)."""
    if name not in LADDER or not ladder_delta:
        return name
    idx = LADDER.index(name)
    new_idx = max(0, min(len(LADDER) - 1, idx + ladder_delta))
    return LADDER[new_idx]
