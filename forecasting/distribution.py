"""Distribution recenter assist — the *real fix path* for a central-in-band warning.

The central-in-band invariant (``forecasting.hooks.distribution``) fires when a
forecast's central tendency (median/mean) lies OUTSIDE its own uncertainty band —
the disconnected-band bug (e.g. mean 44.7 with ci90 ``[-4.7, 5]``). That class is
classified ``NO_AUTO`` by the warning dispatcher: it needs a human's deliberate
re-estimate, never a silent auto-ack to make the number drop.

This module gives that warning a real, mechanical fix path so it is no longer
*unresolvable*: :func:`recenter_distribution` re-estimates the band so it is
centered on the central tendency, preserving each interval's HALF-WIDTH (the
forecaster's expressed uncertainty) while translating it so the point sits back
inside. It is deliberately **pure + stdlib-only** and is NOT auto-applied: the
dispatcher keeps central-in-band ``NO_AUTO``/surfaced until a recenter is validated
and explicitly chosen by the sheet/automode operator. Exposing the helper is what
turns "unresolvable" into "a fix the human CAN run", without weakening the
load-bearing rule (no bare-ack, real gated work only).

Recenter vs. autofix: ``hooks.autofix_distribution`` reorders / clamps / nests
malformed intervals but never moves a band that is well-formed-yet-disconnected
from its point. Recenter is the complementary operation — it ONLY translates a
band when the central tendency sits outside it, and leaves an already-consistent
payload untouched.
"""

from __future__ import annotations

import math
from typing import Any

from forecasting.distribution_summary import summarize_distribution

__all__ = ["recenter_distribution", "would_recenter"]


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _central(view: dict[str, Any]) -> float | None:
    """The central tendency the band must contain: median preferred, else mean
    (matches the hooks central-in-band check)."""
    median, mean = view.get("median"), view.get("mean")
    if _finite(median):
        return float(median)
    if _finite(mean):
        return float(mean)
    return None


def _clamp_bounds(bounds: list[float] | None) -> tuple[float | None, float | None]:
    if (
        bounds
        and len(bounds) == 2
        and _finite(bounds[0])
        and _finite(bounds[1])
        and bounds[0] <= bounds[1]
    ):
        return float(bounds[0]), float(bounds[1])
    return None, None


def _recentered_band(
    iv: Any,
    central: float,
    *,
    lo_b: float | None,
    hi_b: float | None,
) -> list[float] | None:
    """Translate an interval so its MIDPOINT equals ``central`` (preserving its
    half-width), then clamp to bounds. Returns None when the interval is malformed
    (recenter only touches well-formed-yet-disconnected bands; malformed bounds are
    ``autofix_distribution``'s job)."""
    if not (isinstance(iv, (list, tuple)) and len(iv) == 2 and _finite(iv[0]) and _finite(iv[1])):
        return None
    lo, hi = float(iv[0]), float(iv[1])
    if lo > hi:
        lo, hi = hi, lo
    half = (hi - lo) / 2.0
    nlo, nhi = central - half, central + half
    if lo_b is not None and hi_b is not None:
        # Clamping must keep ``central`` inside, so clamp the band edges into bounds.
        nlo = max(lo_b, min(nlo, hi_b))
        nhi = max(lo_b, min(nhi, hi_b))
        if nlo > nhi:
            nlo = nhi = max(lo_b, min(central, hi_b))
    return [nlo, nhi]


def would_recenter(payload: Any, *, bounds: list[float] | None = None) -> bool:
    """True iff :func:`recenter_distribution` would change ``payload`` — i.e. the
    payload is a continuous distribution whose central tendency lies OUTSIDE at
    least one present band. Pure, no mutation. Used by surfaces that want to offer
    the recenter action only when it is actually applicable."""
    _, fixes = recenter_distribution(payload, bounds=bounds)
    return bool(fixes)


def recenter_distribution(
    payload: Any,
    *,
    bounds: list[float] | None = None,
) -> tuple[Any, list[str]]:
    """Recenter a distribution's band(s) on its central tendency.

    Returns ``(fixed_payload, applied_fixes)``. When the central tendency already
    lies inside every present band (or the payload is not a continuous
    distribution), the ORIGINAL payload is returned unchanged with an empty fix
    list — recenter is a no-op on a consistent forecast. When a band is
    disconnected from the point, that band is translated so the point sits at its
    midpoint (half-width preserved), clamped to bounds, and ci50 is re-nested
    inside ci90. The corrected intervals are written under the canonical
    ``interval_50_*`` / ``interval_90_*`` keys the chart parser prefers.

    NOTE: this is the fix path a human/operator CAN run for a central-in-band
    warning; the dispatcher does NOT auto-apply it (central-in-band stays
    ``NO_AUTO``/surfaced until validated + explicitly chosen).
    """
    if not isinstance(payload, dict):
        return payload, []

    view = summarize_distribution(payload)
    if view is None or view.get("pmf"):
        # Not a continuous distribution (binary / candidate-share PMF): nothing to
        # recenter — the band invariant does not apply.
        return payload, []

    central = _central(view)
    if central is None:
        return payload, []

    lo_b, hi_b = _clamp_bounds(bounds)
    fixes: list[str] = []
    fixed = dict(payload)

    def _band_for(name: str) -> list[float] | None:
        return view.get(name)

    ci90 = _band_for("ci90")
    ci50 = _band_for("ci50")

    def _needs_recenter(iv: Any) -> bool:
        if not (isinstance(iv, (list, tuple)) and len(iv) == 2 and _finite(iv[0]) and _finite(iv[1])):
            return False
        lo, hi = min(iv), max(iv)
        return not (lo <= central <= hi)

    new_ci90 = new_ci50 = None
    if _needs_recenter(ci90):
        new_ci90 = _recentered_band(ci90, central, lo_b=lo_b, hi_b=hi_b)
        if new_ci90 is not None:
            fixes.append(f"recentered ci90 on central tendency {central}")
    if _needs_recenter(ci50):
        new_ci50 = _recentered_band(ci50, central, lo_b=lo_b, hi_b=hi_b)
        if new_ci50 is not None:
            fixes.append(f"recentered ci50 on central tendency {central}")

    if not fixes:
        return payload, []

    # Use the recentered bands where we moved them, otherwise the (already-consistent)
    # originals, so re-nesting reasons over the final shape.
    eff_ci90 = new_ci90 if new_ci90 is not None else (list(ci90) if (ci90 and _finite(ci90[0]) and _finite(ci90[1])) else None)
    eff_ci50 = new_ci50 if new_ci50 is not None else (list(ci50) if (ci50 and _finite(ci50[0]) and _finite(ci50[1])) else None)

    if eff_ci50 and eff_ci90 and (eff_ci50[0] < eff_ci90[0] or eff_ci50[1] > eff_ci90[1]):
        eff_ci50 = [max(eff_ci50[0], eff_ci90[0]), min(eff_ci50[1], eff_ci90[1])]
        if eff_ci50[0] > eff_ci50[1]:
            eff_ci50 = [eff_ci90[0], eff_ci90[1]]
        fixes.append("re-nested ci50 inside ci90")

    if eff_ci90 is not None:
        fixed["interval_90_low"], fixed["interval_90_high"] = eff_ci90[0], eff_ci90[1]
    if eff_ci50 is not None:
        fixed["interval_50_low"], fixed["interval_50_high"] = eff_ci50[0], eff_ci50[1]
    return fixed, fixes
