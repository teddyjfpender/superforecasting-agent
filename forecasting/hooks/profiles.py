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
        "stale_evidence_justified": _O,
        "require_decision_readiness": _O,
        "require_panel": _O,
        "require_citations": _O,
        "require_evidence": _W,
        "require_outcome_paths": _O,
        "require_tail_base_rates": _O,
        "candidate_intervals_coherent": _W,
        "candidate_intervals_present": _O,
        "style_clean": _W,
        "lessons_applied": _O,
        "terminal_calibration_applied": _O,
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
        "require_outside_view_anchor": _O,
        # P3 gates — all OFF for scratch work.
        "outside_view_refresh": _O,
        "granularity_disciplined": _O,
        "crux_named": _O,
        "market_anchor_engaged": _O,
        "update_cadence_honored": _O,
        "thesis_aggregate_fresh": _O,
        "research_adequate": _O,
        "readiness_floor": _O,
        "no_watched_sources": _O,
    },
    # == the pre-hooks enforcement (tool require_* defaults + Phase 2 style gate),
    # which also equals the builtin default severities. Adopting it changes nothing.
    "standard": {
        "require_structured_reasoning": _E,
        "require_components": _E,
        "require_fresh_evidence": _E,
        "stale_evidence_justified": _W,
        "require_decision_readiness": _W,
        "require_panel": _E,
        "require_citations": _W,
        "require_evidence": _E,
        "require_outcome_paths": _W,
        # G1 — the Binface gate. WARN-FIRST in standard: 19/19 live share boards fail
        # today, so land it as a visible WARN (the require_outside_view_anchor
        # precedent — observe the fire rate for one review cycle, then promote to
        # ERROR in a small, numbers-citing commit). strict blocks now.
        "require_tail_base_rates": _W,
        # G2 — per-candidate interval coherence is a structural bug-catcher (0 live
        # failures), same class as uncertainty_well_formed: ERROR immediately.
        "candidate_intervals_coherent": _E,
        # G2 presence (P2) — WARN-FIRST in standard (high-impact scope; the committer
        # now auto-fills intervals, so this only nags an un-refreshed live board on
        # lint). Promote to ERROR after one review cycle once the fire rate is read.
        "candidate_intervals_present": _W,
        "style_clean": _E,
        "lessons_applied": _W,
        "terminal_calibration_applied": _W,
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
        # Outside-view anchoring is the single most reliable superforecasting
        # technique, so a HIGH-IMPACT live forecast must carry a reference-class
        # anchor — ERROR, not an ignored WARN (the audit's finding #4: the rule was
        # advisory and skipped ~96% of the time). The rule's own check scopes the
        # block to high-impact forecasts, so lower-impact commits and routine
        # re-forecasts are NOT hard-blocked (scoped to avoid bricking the re-forecast
        # flow — see _check_outside_view_anchor).
        "require_outside_view_anchor": _E,
        # G3 refresh tier — WARN-only in standard (its job is visibility; promoting it
        # would re-create the has_prior brick on routine re-forecasts). The first-commit
        # ERROR tier lives INSIDE require_outside_view_anchor above.
        "outside_view_refresh": _W,
        # G4 — WARN FOREVER (never ERROR: hard-gating precision teaches fabricated 0.43s).
        "granularity_disciplined": _W,
        # G7 — WARN-first (60/63 high-impact cruxless today); promote to ERROR after the
        # crux backfill lands and auto-promotion is observed filling new panels.
        "crux_named": _W,
        # G8 — WARN-first (6/7 market-watched record no comparison); promote to ERROR for
        # high-impact once the deviation-bet ledger accrues its first scored cohort.
        "market_anchor_engaged": _W,
        # G5 — WARN in standard: sweep-side, so "WARN" means a red desk badge + alert
        # priority, never a commit block (ERROR only in strict).
        "update_cadence_honored": _W,
        "thesis_aggregate_fresh": _W,
        "research_adequate": _W,
        "readiness_floor": _W,
        "no_watched_sources": _W,
    },
    # Everything blocking — for high-stakes desks that want full saturation.
    "strict": {
        "require_structured_reasoning": _E,
        "require_components": _E,
        "require_fresh_evidence": _E,
        "stale_evidence_justified": _E,
        "require_decision_readiness": _E,
        "require_panel": _E,
        "require_citations": _E,
        "require_evidence": _E,
        "require_outcome_paths": _E,
        "require_tail_base_rates": _E,
        "candidate_intervals_coherent": _E,
        "candidate_intervals_present": _E,
        "style_clean": _E,
        "lessons_applied": _E,
        "terminal_calibration_applied": _W,  # advisory even in strict (default 1.0 is a no-op stage)
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
        "require_outside_view_anchor": _E,
        # P3 gates block in strict (granularity stays advisory — precision is never
        # hard-gated, even here).
        "outside_view_refresh": _E,
        "granularity_disciplined": _W,
        "crux_named": _E,
        "market_anchor_engaged": _E,
        "update_cadence_honored": _E,
        "thesis_aggregate_fresh": _W,
        "research_adequate": _E,
        "readiness_floor": _E,
        "no_watched_sources": _E,
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
