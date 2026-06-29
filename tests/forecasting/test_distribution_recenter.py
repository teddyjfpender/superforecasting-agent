"""SLICE 5 (c): the recenter assist — a real fix path for a central-in-band warning.

The central-in-band invariant fires when the central tendency lies OUTSIDE its own
band (the disconnected-band bug). ``recenter_distribution`` re-estimates the band
centered on the central tendency (half-width preserved) so the point sits back
inside. It is NOT auto-applied — the dispatcher keeps central-in-band NO_AUTO /
surfaced — but it makes the warning resolvable instead of unresolvable.
"""

from __future__ import annotations

from forecasting.distribution import recenter_distribution, would_recenter
from forecasting.hooks.distribution import assess_distribution
from forecasting.warnings import plan_alert, resolve_alert
from forecasting.warnings import ResolutionRunners, classify_warning, ResolutionKind
from forecasting.models import AlertEvent


# ── the recenter helper ──────────────────────────────────────────────────────


def test_recenter_translates_disconnected_band_onto_central_tendency():
    # mean 44.7 with ci90 [-4.7, 5] — the canonical disconnected-band bug.
    payload = {"mean": 44.7, "interval_90_low": -4.7, "interval_90_high": 5.0}
    fixed, fixes = recenter_distribution(payload)

    assert fixes, "a disconnected band must be recentered"
    lo, hi = fixed["interval_90_low"], fixed["interval_90_high"]
    # central now lies inside the recentered band...
    assert lo <= 44.7 <= hi
    # ...and the half-width (uncertainty) is preserved: (5 - -4.7)/2 = 4.85.
    assert abs((hi - lo) / 2 - 4.85) < 1e-9
    assert abs(hi - lo - (5.0 - -4.7)) < 1e-9


def test_recenter_is_noop_on_consistent_distribution():
    payload = {"mean": 3.0, "interval_90_low": 2.0, "interval_90_high": 4.0}
    fixed, fixes = recenter_distribution(payload)
    assert fixes == []
    assert fixed is payload  # original returned unchanged
    assert not would_recenter(payload)


def test_recenter_result_satisfies_central_in_band_invariant():
    payload = {"mean": 44.7, "interval_90_low": -4.7, "interval_90_high": 5.0}
    before = assess_distribution(payload, outcome_type="distribution")
    assert before is not None and before.central_within is False

    fixed, fixes = recenter_distribution(payload)
    assert fixes
    after = assess_distribution(fixed, outcome_type="distribution")
    assert after is not None
    assert after.central_within is True
    assert after.well_formed


def test_recenter_clamps_to_bounds_and_keeps_central_inside():
    # central just below the upper bound; band would otherwise spill past it.
    payload = {"mean": 0.95, "interval_90_low": 0.0, "interval_90_high": 0.2}
    fixed, fixes = recenter_distribution(payload, bounds=[0.0, 1.0])
    assert fixes
    lo, hi = fixed["interval_90_low"], fixed["interval_90_high"]
    assert 0.0 <= lo <= hi <= 1.0
    assert lo <= 0.95 <= hi


def test_recenter_renests_ci50_inside_ci90():
    payload = {
        "mean": 44.7,
        "interval_90_low": -4.7,
        "interval_90_high": 5.0,
        "interval_50_low": -2.0,
        "interval_50_high": 2.0,
    }
    fixed, fixes = recenter_distribution(payload)
    assert fixes
    lo90, hi90 = fixed["interval_90_low"], fixed["interval_90_high"]
    lo50, hi50 = fixed["interval_50_low"], fixed["interval_50_high"]
    assert lo90 <= lo50 <= hi50 <= hi90
    assert lo50 <= 44.7 <= hi50


def test_recenter_ignores_binary_and_pmf_payloads():
    # a bare scalar / non-dict is not a continuous distribution
    assert recenter_distribution(0.6) == (0.6, [])
    # a candidate-share PMF has no continuous band to recenter
    pmf = {"alice": 0.55, "bob": 0.45}
    fixed, fixes = recenter_distribution(pmf)
    assert fixes == []
    assert fixed is pmf


# ── dispatcher integration: central-in-band stays NO_AUTO / surfaced ─────────


def _alert(reason: str) -> AlertEvent:
    return AlertEvent(
        id="al_test",
        created_at="2026-06-29T00:00:00Z",
        severity="warning",
        scope_type="question",
        scope_ref="fq_test",
        reason=reason,
        recommended_action="",
        acknowledged_at=None,
    )


def test_central_in_band_classified_no_auto():
    assert classify_warning("central_in_band:fq_test") is ResolutionKind.NO_AUTO


def test_central_in_band_surfaced_not_acked_but_names_recenter_fix():
    alert = _alert("central_in_band:fq_test")
    runners = ResolutionRunners()

    class _Ledger:
        def acknowledge_alert(self, *a, **k):  # must NEVER be called for NO_AUTO
            raise AssertionError("NO_AUTO alert must not be acknowledged")

    result = resolve_alert(_Ledger(), alert, runners=runners)
    assert result["status"] == "surfaced"
    assert result["acknowledged"] is False
    assert "recenter" in result["detail"].lower()

    plan = plan_alert(alert, runners)
    assert plan["planned"] == "surfaced"
    assert "recenter" in plan["detail"].lower()
