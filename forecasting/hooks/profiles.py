"""Curated hook profiles + the strictness ladder.

A profile is a named map of rule_id -> Severity. ``standard`` is the default
enforcement tier; ``strict`` promotes the advisory rules to blocking;
``exploratory-lenient`` drops everything to advisory. Impact scaling moves a
question up/down this ``exploratory-lenient < standard < strict`` ladder without
per-question config.

``superforecaster`` (OFF the ladder, opt-in) is the "10/10 or blocked" tier: EVERY
rule blocks. It is strictly >= ``strict`` on every rule and is the TARGET default
once the remaining WARN classes are remediated — see its construction below.

Promotion discipline (the ``require_outside_view_anchor`` precedent, reused here):
land a rule WARN, read its live fire rate off the adherence scorecard for a review
cycle, then promote WARN->ERROR in a small commit that CITES the numbers. The
2026-07-09 promotion wave (remediation sweep 2, verified 0 live failures on all
176 live actives) flipped seven such rules; ``forecast hooks promotions`` prints
the standing queue of the next candidates.
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
        "evidence_depth": _O,
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
        # BLF gates — all OFF for scratch work.
        "belief_trajectory_present": _O,
        "pool_shrinkage_recorded": _O,
        "specialist_seat_considered": _O,
        # Thesis-remediation gates — all OFF for scratch work.
        "anchor_refs_attached": _O,
        "event_band_earned": _O,
        "health_not_probability": _O,
        "thesis_correlation_transparency": _O,
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
        "evidence_depth": _W,
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
        # HELD AT WARN 2026-07-09 — see the promotion report. Verified 0/163 live fail,
        # but ERROR would brick the DOCUMENTED live opt-out `use_active_lessons=false`
        # (protocol.py:123: "Pass false only to deliberately commit your raw number").
        # Promote deliberately alongside a protocol-doc + opt-out-test update, or after
        # the opt-out records a skip reason the gate honors. exploratory origin already
        # commits raw numbers, so the relief valve exists.
        "lessons_applied": _W,
        # PROMOTED 2026-07-09 (0/153 live fail): the terminal Platt/calibration stage
        # is a structural requirement, not a no-op — its absence blocks a live commit.
        "terminal_calibration_applied": _E,
        # v2 — structural OUTPUT rules block (bug-catchers; programmatic auto-fix);
        # soft-confidence + quorum-participation stay advisory by default.
        "output_renderable": _E,
        "uncertainty_well_formed": _E,
        # PROMOTED 2026-07-09 (0/68 live fail): a 90% band wider than the whole bounded
        # range is a malformed output (same class as uncertainty_well_formed), not a
        # fuzzy judgment — it blocks. (The width THRESHOLD stays per-question tunable.)
        "uncertainty_width_sane": _E,
        "quorum_participation": _W,
        "quorum_required": _W,
        # PROMOTED 2026-07-09 (0/173 live fail): a commit that leans on an UNJUDGED
        # quorum run now blocks — a quorum is only decision-grade once judged.
        "quorum_judged": _E,
        "tails_justified": _W,
        # PROMOTED 2026-07-09 (0/163 live fail): a live commit that skipped the
        # over/under-confidence calibration-bias adjustment now blocks.
        "calibration_bias_applied": _E,
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
        # G7 — PROMOTED 2026-07-09 (crux backfill landed; remediation sweep 2 shows
        # 0/62 high-impact live fail). A high-impact live commit with no registered
        # crux now BLOCKS. The rule's check scopes the block to high-impact (the panel
        # auto-promotes its cruxes pre-gate), so routine medium-impact commits are
        # untouched — see _check_crux_named.
        "crux_named": _E,
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
        # BLF A1 — PROMOTED 2026-07-09 (remediation sweep 2, 0/42 live fail): a
        # post-harvest panel that recorded NO belief trajectory now blocks the commit
        # (the rule's check is inert unless the linked panel is post-harvest, so
        # pre-marker panels are untouched). A3 stays WARN-first (pool_shrinkage fires
        # only on a non-calm quorum; land WARN, promote once the marker saturates).
        "belief_trajectory_present": _E,
        "pool_shrinkage_recorded": _W,
        # BLF A5 — WARN FOREVER (a specialist on the wrong question class is worse than
        # none, so this never hard-gates — same doctrine as granularity_disciplined).
        "specialist_seat_considered": _W,
        # Thesis-remediation gates. anchor_refs_attached is a mechanical defect (WARN-first
        # in standard since a live-fire backfill just drained it; ERROR strict). event_band_
        # earned is WARN (the fix is set-event / a member-interval backfill). health_not_
        # probability WARN (conformance). thesis_correlation_transparency WARN FOREVER (an
        # honest label, never a block — same doctrine as granularity/specialist).
        "anchor_refs_attached": _W,
        "event_band_earned": _W,
        "health_not_probability": _W,
        "thesis_correlation_transparency": _W,
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
        "evidence_depth": _E,
        "require_outcome_paths": _E,
        "require_tail_base_rates": _E,
        "candidate_intervals_coherent": _E,
        "candidate_intervals_present": _E,
        "style_clean": _E,
        "lessons_applied": _E,
        # ERROR in strict since 2026-07-09: standard promoted it, so strict must be
        # >= standard (the ladder must never invert on impact scale-up).
        "terminal_calibration_applied": _E,
        # v2
        "output_renderable": _E,
        "uncertainty_well_formed": _E,
        # ERROR in strict since 2026-07-09 (standard promoted it; strict >= standard).
        "uncertainty_width_sane": _E,
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
        # BLF A1/A3 block in strict (a high-stakes desk demands the sequential-revision
        # process + reconstructable shrink provenance). A5 stays advisory — a specialist
        # seat is a recommendation, never a hard requirement, even here.
        "belief_trajectory_present": _E,
        "pool_shrinkage_recorded": _E,
        "specialist_seat_considered": _W,
        # Thesis-remediation gates. The mechanical orphaned-anchor + the event/band
        # honesty gates BLOCK in strict; the correlation label stays advisory (an honest
        # label is never a hard requirement, even here — like granularity/specialist).
        "anchor_refs_attached": _E,
        "event_band_earned": _E,
        "health_not_probability": _E,
        "thesis_correlation_transparency": _W,
    },
}

# ── The "10/10 or blocked" tier ───────────────────────────────────────────────
# The superforecaster profile is EVERY built-in rule at ERROR — strict plus every
# gate ERROR, the just-promoted set, AND the rules strict deliberately leaves WARN
# (confidence_committed, granularity_disciplined, specialist_seat_considered,
# thesis_correlation_transparency) pushed to ERROR too. It embodies the operator's
# end state: "hooks on by default that don't allow anything less than a 10/10 style
# forecast." It is deliberately OFF the impact-scaling ladder (scaled_profile leaves
# it unchanged) — a desk opts in explicitly via ``forecast hooks set-profile
# superforecaster`` or per-question ``metadata.forecast_hooks.profile``.
#
# Constructed from BUILTIN_RULE_IDS so a NEW rule is born blocking here (correct for
# the maximal tier), and it is provably >= strict on every rule (ERROR dominates).
#
# THIS IS THE TARGET DEFAULT. It is not yet DEFAULT_PROFILE because these rule
# classes still carry material WARN debt on the live book (they would brick the
# routine commit/re-forecast flow today) and must be remediated first:
#   - reasoning_composition   (63/173 live fail — breadth-of-methods backfill)
#   - update_cadence_honored  (cadence: 41/173 past cadence × grace)
#   - evidence_depth          (31/173 under the source-count floor)
#   - market_anchor_engaged   (19/38 market-watched record no comparison)
#   - require_tail_base_rates (tail base rates: 15/24 share boards unanchored)
#   - require_panel / require_structured_reasoning (panel/structured blocks pending
#                              the codex-quorum reset that stalled panel runs)
# As ``forecast hooks promotions`` drains each class to 0 live failures, promote it
# in ``standard`` (§ the promotion discipline above); when the list is empty,
# ``superforecaster`` becomes ``DEFAULT_PROFILE``.
HOOK_PROFILES["superforecaster"] = {rid: _E for rid in BUILTIN_RULE_IDS}

DEFAULT_PROFILE = "standard"

# The maximal-strictness opt-in tier. NOT the default until the WARN classes listed
# on the superforecaster construction above are remediated to 0 live failures.
SUPERFORECASTER_PROFILE = "superforecaster"

# Rules deliberately HELD below ERROR in standard even at 0 live failures — a clean
# live sweep is necessary but NOT sufficient (a promotion must not brick a documented
# flow). ``forecast hooks promotions`` annotates these so the queue never reads as an
# instruction to flip them.
PROMOTION_HOLDS: dict[str, str] = {
    "lessons_applied": (
        "ERROR would brick the documented use_active_lessons=false opt-out "
        "(protocol.py: 'Pass false only to deliberately commit your raw number')"
    ),
}

# Required reasoning composition per profile: (must_include_all, min_distinct_count).
# The min count forces breadth beyond the required set.
REASONING_REQUIRED: dict[str, tuple[tuple[str, ...], int]] = {
    "exploratory-lenient": ((), 0),
    "standard": (("outside_view", "base_rate"), 3),
    "strict": (("outside_view", "base_rate", "pre_mortem", "disconfirmation"), 5),
    # >= strict (the maximal tier demands at least the strict breadth).
    "superforecaster": (("outside_view", "base_rate", "pre_mortem", "disconfirmation"), 5),
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
