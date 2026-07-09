"""§7.2 · PROFILE PIN — assert the EXACT severity map of the standard + strict
profiles so a refactor can never silently drop a P3 gate to a softer severity.

Today only lesson:* rules resist demotion; this pin makes any severity change on a
built-in a deliberate, reviewed diff. If you add a rule, add it here on purpose."""

from __future__ import annotations

from forecasting.hooks.builtins import BUILTIN_RULE_IDS
from forecasting.hooks.profiles import profile_severities

_E, _W, _O = "error", "warn", "off"

STANDARD = {
    "require_structured_reasoning": _E,
    "require_components": _E,
    "require_fresh_evidence": _E,
    "stale_evidence_justified": _W,
    "require_decision_readiness": _W,
    "require_panel": _E,
    "require_citations": _W,
    "require_evidence": _E,
    "evidence_depth": _W,
    "require_outside_view_anchor": _E,
    "outside_view_refresh": _W,
    "require_outcome_paths": _W,
    "require_tail_base_rates": _W,
    "candidate_intervals_coherent": _E,
    "candidate_intervals_present": _W,
    "granularity_disciplined": _W,
    "crux_named": _E,  # PROMOTED 2026-07-09 (crux backfill landed; high-impact scoped)
    "market_anchor_engaged": _W,
    "update_cadence_honored": _W,
    "style_clean": _E,
    # HELD AT WARN 2026-07-09 (ERROR would brick the documented use_active_lessons=false
    # opt-out); the rest of the wave PROMOTED (0 live failures) — see profiles.py.
    "lessons_applied": _W,
    "terminal_calibration_applied": _E,
    "output_renderable": _E,
    "uncertainty_well_formed": _E,
    "uncertainty_width_sane": _E,  # PROMOTED 2026-07-09
    "quorum_participation": _W,
    "quorum_required": _W,
    "quorum_judged": _E,  # PROMOTED 2026-07-09
    "tails_justified": _W,
    "calibration_bias_applied": _E,  # PROMOTED 2026-07-09
    "confidence_committed": _W,
    "reasoning_composition": _W,
    "thesis_aggregate_fresh": _W,
    "research_adequate": _W,
    "readiness_floor": _W,
    "no_watched_sources": _W,
    # BLF gates — A1 PROMOTED 2026-07-09 (post-harvest-scoped); A3 WARN-first; A5 WARN forever.
    "belief_trajectory_present": _E,
    "pool_shrinkage_recorded": _W,
    "specialist_seat_considered": _W,
    # Thesis-remediation gates — WARN-first in standard (correlation label WARN forever).
    "anchor_refs_attached": _W,
    "event_band_earned": _W,
    "health_not_probability": _W,
    "thesis_correlation_transparency": _W,
}

# The P3 gates and their strict-profile severities (granularity NEVER blocks).
STRICT_P3 = {
    "outside_view_refresh": _E,
    "granularity_disciplined": _W,
    "crux_named": _E,
    "market_anchor_engaged": _E,
    "update_cadence_honored": _E,
    # BLF: A1/A3 block in strict; A5 stays advisory (a recommendation, never a gate).
    "belief_trajectory_present": _E,
    "pool_shrinkage_recorded": _E,
    "specialist_seat_considered": _W,
    # Thesis-remediation: anchor + event/band honesty block in strict; the label stays WARN.
    "anchor_refs_attached": _E,
    "event_band_earned": _E,
    "health_not_probability": _E,
    "thesis_correlation_transparency": _W,
}


def test_standard_profile_is_pinned():
    resolved = {rid: profile_severities("standard")[rid].value for rid in BUILTIN_RULE_IDS}
    assert resolved == STANDARD


def test_every_builtin_is_pinned():
    # A new rule must be added to the pin ON PURPOSE (this fails loudly otherwise).
    assert set(BUILTIN_RULE_IDS) == set(STANDARD)


def test_strict_p3_gates_are_pinned():
    strict = profile_severities("strict")
    for rid, sev in STRICT_P3.items():
        assert strict[rid].value == sev, rid


def test_granularity_never_blocks_in_any_profile():
    # Scoped to the three LADDER profiles: superforecaster is the "10/10 or blocked"
    # tier where every rule (granularity included) blocks by design — excluded here.
    for profile in ("exploratory-lenient", "standard", "strict"):
        assert profile_severities(profile)["granularity_disciplined"].value in (_w for _w in (_W, _O))


_RANK = {_O: 0, _W: 1, _E: 2}


def test_ladder_is_monotonic_non_decreasing():
    """exploratory-lenient <= standard <= strict on EVERY rule — impact scaling moves
    a question UP this ladder, so a rung must never LOOSEN a rule (the inversion that
    the 2026-07-09 terminal_calibration/uncertainty_width strict-promotion fixed)."""
    lenient = profile_severities("exploratory-lenient")
    standard = profile_severities("standard")
    strict = profile_severities("strict")
    for rid in BUILTIN_RULE_IDS:
        assert _RANK[lenient[rid].value] <= _RANK[standard[rid].value] <= _RANK[strict[rid].value], rid


def test_superforecaster_profile_is_maximal():
    """The "10/10 or blocked" tier: EVERY built-in rule is ERROR, and it is >= strict
    on every rule (so opting in never loosens anything)."""
    sf = profile_severities("superforecaster")
    strict = profile_severities("strict")
    for rid in BUILTIN_RULE_IDS:
        assert sf[rid].value == _E, rid
        assert _RANK[sf[rid].value] >= _RANK[strict[rid].value], rid


def test_superforecaster_is_selectable_and_off_ladder():
    from forecasting.hooks.profiles import (
        HOOK_PROFILES,
        LADDER,
        SUPERFORECASTER_PROFILE,
        resolve_reasoning_requirement,
        scaled_profile,
    )

    # Selectable via the profile config (store.set_profile validates against this map).
    assert SUPERFORECASTER_PROFILE in HOOK_PROFILES
    # OFF the impact-scaling ladder: an opt-in tier, never auto-entered by scaling.
    assert SUPERFORECASTER_PROFILE not in LADDER
    assert scaled_profile(SUPERFORECASTER_PROFILE, ladder_delta=2) == SUPERFORECASTER_PROFILE
    # Its reasoning requirement is at least the strict breadth.
    sf_req, sf_min = resolve_reasoning_requirement(SUPERFORECASTER_PROFILE)
    strict_req, strict_min = resolve_reasoning_requirement("strict")
    assert set(strict_req) <= set(sf_req) and sf_min >= strict_min
