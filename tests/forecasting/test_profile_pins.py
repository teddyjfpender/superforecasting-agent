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
    "crux_named": _W,
    "market_anchor_engaged": _W,
    "update_cadence_honored": _W,
    "style_clean": _E,
    "lessons_applied": _W,
    "terminal_calibration_applied": _W,
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
    "research_adequate": _W,
    "readiness_floor": _W,
    "no_watched_sources": _W,
    # BLF gates — WARN-first in standard (A5 is WARN forever).
    "belief_trajectory_present": _W,
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
    for profile in ("exploratory-lenient", "standard", "strict"):
        assert profile_severities(profile)["granularity_disciplined"].value in (_w for _w in (_W, _O))
