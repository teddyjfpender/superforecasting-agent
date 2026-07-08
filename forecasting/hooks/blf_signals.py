"""BLF gate signals — the retroactivity backbone + panel-run readers.

The BLF harvest shipped its machinery (belief trajectories, K-trial + cross-model
pool shrinkage, deterministic specialists) but the gate lattice did not yet
REQUIRE or VALIDATE any of it. These three built-ins close that
(``belief_trajectory_present``, ``pool_shrinkage_recorded``,
``specialist_seat_considered``). The load-bearing discipline is that they bind
FORWARD ONLY — a panel that ran before the gates shipped is never retroactively
judged for a process it could not have followed.

The whole retroactivity guarantee rides one marker: :data:`PANEL_PROCESS_VERSION`,
stamped into ``panel_runs.spread_summary['process_version']`` by
``record_panel_run`` on EVERY run recorded from now on. A run without it predates
this slice, so :func:`panel_ran_post_harvest` is False and every BLF rule's
``applies()`` returns False for it. A read-only lint over the current live board
therefore fires these rules ~0 times (the actives' panels predate the marker),
which is the proof the guard holds.

This module is dict-in / bool-out (it reads persisted panel-run dicts as returned
by ``ledger.get_panel_run`` / ``list_panel_runs``) and stdlib-only, mirroring the
dependency-light discipline of the rest of ``forecasting/hooks``.
"""

from __future__ import annotations

from typing import Any

# The specialist seat ids the A5 harvest registers. Imported lazily-safe as a
# literal tuple so this module never pulls the specialists' data-plane deps.
_SPECIALIST_IDS = ("model:climatology_knn", "model:seasonal_naive", "model:living_model")

# Bump ONLY when the panel process changes in a way a gate must key on. A run's
# stamped version >= this ⇒ it ran under (at least) the BLF-gated process, so the
# BLF rules bind it. Pre-marker runs read as version 0 and are never bound.
PANEL_PROCESS_VERSION = 1

# A search-enabled panelist must revise its belief at least this many times (BLF's
# central result: sequential revision beats terminal synthesis). A single-step
# trajectory is allowed only WITH a recorded reason (the sole step's ``moved_by``
# or a ``single_step_reason`` note) — or when the run was not search-enabled (a
# panelist with no fresh evidence has nothing to revise against).
MIN_TRAJECTORY_STEPS = 2

# α reconstruction tolerance. The provenance rounds α to 6dp, so anything looser
# than a hair is a garbage/fabricated provenance, not a rounding artefact.
POOL_ALPHA_TOLERANCE = 1e-4


def _spread(panel_run: Any) -> dict[str, Any]:
    if not isinstance(panel_run, dict):
        return {}
    spread = panel_run.get("spread_summary")
    return spread if isinstance(spread, dict) else {}


def panel_ran_post_harvest(panel_run: Any) -> bool:
    """True iff this panel run was recorded AFTER the BLF gates shipped (it carries
    the :data:`PANEL_PROCESS_VERSION` marker). The single retroactivity gate every
    BLF rule keys on — a pre-marker run is never judged for the BLF process."""
    try:
        return int(_spread(panel_run).get("process_version") or 0) >= PANEL_PROCESS_VERSION
    except (TypeError, ValueError):
        return False


def _is_specialist_estimate(estimate: Any) -> bool:
    if not isinstance(estimate, dict):
        return False
    model = str(estimate.get("agent_model") or estimate.get("perspective") or "")
    if model in _SPECIALIST_IDS:
        return True
    meta = estimate.get("metadata")
    return isinstance(meta, dict) and isinstance(meta.get("specialist"), dict)


def belief_trajectory_signals(panel_run: Any) -> tuple[bool, tuple[str, ...], bool]:
    """``(ok, offenders, search_enabled)`` for a panel run's per-panelist belief
    trajectories.

    A panelist PASSES when it carries >= :data:`MIN_TRAJECTORY_STEPS` belief steps,
    OR a single step WITH a recorded reason, OR a single step on a NON-search run
    (nothing fresh to revise against). A panelist with zero steps (post-marker, so
    it should have emitted one), or a lone unexplained step on a search-enabled
    run, is an offender named by its model/perspective. Deterministic specialist
    seats are exempt (they have no linguistic belief state). Search-enabledness is
    read from the run's ``supervisor_search`` spread flag."""
    spread = _spread(panel_run)
    search_enabled = bool(spread.get("supervisor_search"))
    offenders: list[str] = []
    for est in (panel_run.get("estimates") if isinstance(panel_run, dict) else None) or []:
        if not isinstance(est, dict) or _is_specialist_estimate(est):
            continue
        meta = est.get("metadata") if isinstance(est.get("metadata"), dict) else {}
        traj = meta.get("belief_trajectory")
        steps = len(traj) if isinstance(traj, list) else 0
        name = str(est.get("agent_model") or est.get("perspective") or "?")
        if steps >= MIN_TRAJECTORY_STEPS:
            continue
        if steps == 1:
            if not search_enabled:
                continue
            sole = traj[0] if isinstance(traj[0], dict) else {}
            reason = str(sole.get("moved_by") or meta.get("single_step_reason") or "").strip()
            if reason:
                continue
        offenders.append(name)
    return (not offenders), tuple(offenders), search_enabled


def validate_pool_shrinkage_alpha(provenance: Any, *, tolerance: float = POOL_ALPHA_TOLERANCE) -> bool:
    """True iff ``provenance``'s recorded α reconstructs from the documented A3
    formula within ``tolerance``. Any missing/non-numeric field, or an α that does
    not match ``clamp01(max(floor, 1 − c·max(0, var_logit − calm_var)))`` (an
    anchorless provenance must record the α=1 identity), is garbage."""
    if not isinstance(provenance, dict) or not provenance:
        return False
    try:
        alpha = float(provenance["alpha"])
        var_logit = float(provenance["var_logit"])
        floor = float(provenance["floor"])
        c = float(provenance["c"])
        calm_var = float(provenance["calm_var"])
    except (KeyError, TypeError, ValueError):
        return False
    anchor = provenance.get("anchor")
    shrunk = bool(provenance.get("shrunk"))
    if anchor is None:
        # Nothing to shrink toward — the only honest record is the strict identity.
        return abs(alpha - 1.0) <= tolerance and not shrunk
    excess = max(0.0, var_logit - calm_var)
    expected = min(1.0, max(0.0, max(floor, 1.0 - c * excess)))
    return abs(alpha - expected) <= max(tolerance, 1e-6)


def pool_shrinkage_signals(panel_run: Any) -> tuple[bool, bool, bool]:
    """``(present, valid, non_calm)`` for a quorum run's cross-model pool shrinkage.

    ``present`` — the A3 provenance dict is recorded on the run's spread.
    ``valid`` — its α reconstructs from the formula (True by default when absent,
    so the validator never false-fires on a run that simply carries no provenance).
    ``non_calm`` — the panel's disagreement exceeded the calm dead-zone (read from
    the persisted ``disagreement_band``), so a shrink toward the anchor was in
    play. Anchorless absence is legitimate (nothing to shrink toward); the gate
    pairs ``non_calm`` with the context's market-link signal to scope the absence
    fault to a run that genuinely should have recorded a shrink."""
    spread = _spread(panel_run)
    prov = spread.get("pool_shrinkage")
    band = str(spread.get("disagreement_band") or "").strip().lower()
    non_calm = band not in ("", "calm")
    if isinstance(prov, dict) and prov:
        return True, validate_pool_shrinkage_alpha(prov), non_calm
    return False, True, non_calm


def specialist_seat_signals(panel_run: Any) -> tuple[bool, bool]:
    """``(seat_present, declined)`` — whether a deterministic specialist seat
    produced a forecast in this run, and whether any offered seat honestly DECLINED
    (a ``SpecialistDeclined`` recorded in the run's ``specialist_seats`` spread
    summary). A declined seat is honest coverage, so the gate passes on it."""
    present = any(
        _is_specialist_estimate(est)
        for est in ((panel_run.get("estimates") if isinstance(panel_run, dict) else None) or [])
    )
    summary = _spread(panel_run).get("specialist_seats")
    declined = bool(isinstance(summary, dict) and summary.get("declined"))
    if isinstance(summary, dict) and summary.get("ran"):
        present = True
    return present, declined


__all__ = [
    "PANEL_PROCESS_VERSION",
    "MIN_TRAJECTORY_STEPS",
    "POOL_ALPHA_TOLERANCE",
    "panel_ran_post_harvest",
    "belief_trajectory_signals",
    "validate_pool_shrinkage_alpha",
    "pool_shrinkage_signals",
    "specialist_seat_signals",
]
