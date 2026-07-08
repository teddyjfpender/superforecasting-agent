"""Per-member probability intervals — the EARNED-band source for a thesis event.

Locks: (a) the derivation follows the candidate-interval precedence (panel spread
> evidence-thinness default); (b) a wider component spread => a wider interval
(never a fabricated tightness); (c) the backfill stamps only competitive binary
members; (d) a stamped p_ci90 flows through _belief_record into the event band so
members_with_interval rises (the band is earned, not defaulted)."""

from __future__ import annotations

from forecasting import thesis as tm
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


# ── pure derivation ───────────────────────────────────────────────────────────
def test_panel_spread_source_when_enough_components():
    iv, prov = tm.derive_member_probability_interval(
        0.55, component_probs=[0.56, 0.54, 0.53, 0.58, 0.50], evidence_count=40,
    )
    assert prov["source"] == "panel"
    lo, hi = iv["p_ci90"]
    assert lo < 0.55 < hi and lo >= 0.0 and hi <= 1.0


def test_wider_spread_gives_wider_interval():
    tight, _ = tm.derive_member_probability_interval(0.5, component_probs=[0.49, 0.50, 0.51, 0.50, 0.49])
    wide, _ = tm.derive_member_probability_interval(0.5, component_probs=[0.30, 0.45, 0.50, 0.60, 0.72])
    tw = tight["p_ci90"][1] - tight["p_ci90"][0]
    ww = wide["p_ci90"][1] - wide["p_ci90"][0]
    assert ww > tw  # measured disagreement widens the band; agreement tightens it


def test_default_source_when_too_few_components():
    iv, prov = tm.derive_member_probability_interval(0.6, component_probs=[0.61], evidence_count=1)
    assert prov["source"] == "default"
    lo, hi = iv["p_ci90"]
    assert lo < 0.6 < hi


def test_default_widens_as_evidence_thins():
    thin, _ = tm.derive_member_probability_interval(0.5, component_probs=[], evidence_count=1)
    rich, _ = tm.derive_member_probability_interval(0.5, component_probs=[], evidence_count=25)
    assert (thin["p_ci90"][1] - thin["p_ci90"][0]) > (rich["p_ci90"][1] - rich["p_ci90"][0])


# ── backfill + belief-record forwarding + earned band ─────────────────────────
def _thesis_with_binary_member(lg, *, weight, comp_probs, p=0.6):
    q = lg.create_question(title=f"Will member {weight} resolve yes?",
                           resolution_criteria="Resolves yes if it happens; otherwise no.", impact="high")
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    components = {"components": [{"source": f"model:{i}", "probability": pp} for i, pp in enumerate(comp_probs)]}
    lg.create_snapshot(question_id=q.id, probability_or_distribution=p, rationale="r",
                       require_panel=False, ensemble_components=components, enforce_resolved_hooks=False)
    return q


def test_backfill_stamps_competitive_and_earns_band(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    lg = ForecastLedger(db_path=str(tmp_path / "mi.db"))
    lg.initialize_schema()
    thesis = lg.create_question(
        title="Joint threshold thesis tracker",
        resolution_criteria="Resolves to the count of member forecasts that resolve yes at their close dates.",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    heavy = _thesis_with_binary_member(lg, weight=2.5, comp_probs=[0.56, 0.54, 0.53, 0.58, 0.50], p=0.55)
    light = _thesis_with_binary_member(lg, weight=0.5, comp_probs=[0.7, 0.72, 0.68, 0.71, 0.69], p=0.70)
    lg.add_thesis_member(thesis.id, heavy.id, weight=2.5)
    lg.add_thesis_member(thesis.id, light.id, weight=0.5)
    lg.set_thesis_event(thesis.id, kind="count_threshold", threshold=1)

    dry = lg.backfill_thesis_member_intervals(thesis.id, weight_floor=1.5, apply=False)
    assert dry["competitive_members"] == 1 and dry["applied"] == 0  # only the heavy member

    applied = lg.backfill_thesis_member_intervals(thesis.id, weight_floor=1.5, apply=True)
    assert applied["applied"] == 1
    # The stamped p_ci90 forwards into the belief record.
    belief = lg._thesis_member_belief({"member_question_id": heavy.id, "weight": 2.5, "member_outcome_type": "binary"})
    assert "p_ci90" in belief and len(belief["p_ci90"]) == 2

    # And the event band now earns its width from that member.
    result = lg.aggregate_thesis(thesis.id, rho=0.4)
    band = (lg.get_current_snapshot(thesis.id).metadata or {}).get("event", {}).get("band", {})
    assert band.get("members_with_interval", 0) >= 1
