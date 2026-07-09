"""BLF gate-wiring — the three rules that make the harvest INGRAINED, not bolted-on.

belief_trajectory_present (A1), pool_shrinkage_recorded (A3), and
specialist_seat_considered (A5) each REQUIRE or VALIDATE machinery the harvest
shipped. The load-bearing property tested here is RETROACTIVITY: every rule gates
its applies() on ``panel_ran_post_harvest`` (the panel-run process marker), so a
panel that predates the machinery is never judged for it — which is what keeps the
live-board fire count at ~0.
"""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.blf_signals import (
    PANEL_PROCESS_VERSION,
    belief_trajectory_signals,
    panel_ran_post_harvest,
    pool_shrinkage_signals,
    specialist_seat_signals,
    validate_pool_shrinkage_alpha,
)
from forecasting.hooks.profiles import profile_severities
from forecasting.hooks.spec import HookContext, Severity


def _ctx(**kw) -> HookContext:
    base = dict(
        question_id="fq", event="update", forecast_origin="live",
        is_thesis_or_factor=False, outcome_type="numeric",
        panel_ran_post_harvest=True,
    )
    base.update(kw)
    return HookContext(**base)


def _verdict(ctx, rule_id, *, profile="standard"):
    policy = dict(profile_severities(profile))
    report = run_hooks(ctx, policy)
    return next((v for v in report.verdicts if v.rule_id == rule_id), None)


# ══ retroactivity marker (the whole guard) ════════════════════════════════════
def test_panel_marker_reads_post_harvest():
    assert panel_ran_post_harvest({"spread_summary": {"process_version": PANEL_PROCESS_VERSION}}) is True


def test_panel_without_marker_is_pre_harvest():
    assert panel_ran_post_harvest({"spread_summary": {}}) is False
    assert panel_ran_post_harvest({}) is False
    assert panel_ran_post_harvest(None) is False


def test_every_blf_rule_is_inert_pre_harvest():
    # A pre-harvest context (no marker) fires NONE of the three rules, even with a
    # payload that would otherwise fail each — the retroactivity guarantee.
    ctx = _ctx(
        panel_ran_post_harvest=False,
        belief_trajectory_ok=False, belief_trajectory_offenders=("gpt-5.5",),
        is_quorum=True, pool_shrinkage_present=True, pool_shrinkage_valid=False,
        specialist_offerable=True, specialist_seat_present=False,
    )
    for rid in ("belief_trajectory_present", "pool_shrinkage_recorded", "specialist_seat_considered"):
        assert _verdict(ctx, rid) is None, rid


# ══ A1 · belief_trajectory_present ════════════════════════════════════════════
def test_belief_trajectory_fires_on_missing_steps():
    # PROMOTED 2026-07-09: belief_trajectory_present is ERROR in standard now (was WARN);
    # the check stays inert unless the linked panel is post-harvest, so this only bites
    # a post-harvest panel that recorded no trajectory.
    v = _verdict(_ctx(belief_trajectory_ok=False, belief_trajectory_offenders=("gpt-5.5", "opus")), "belief_trajectory_present")
    assert v is not None and v.passed is False and v.severity is Severity.ERROR
    assert "gpt-5.5" in v.message and "belief_trajectory" in v.message


def test_belief_trajectory_passes_when_ok():
    assert _verdict(_ctx(belief_trajectory_ok=True), "belief_trajectory_present").passed is True


def test_belief_trajectory_blocks_in_strict():
    v = _verdict(_ctx(belief_trajectory_ok=False, belief_trajectory_offenders=("m",)), "belief_trajectory_present", profile="strict")
    assert v.severity is Severity.ERROR and v.passed is False


def test_belief_trajectory_off_in_exploratory():
    assert _verdict(_ctx(belief_trajectory_ok=False), "belief_trajectory_present", profile="exploratory-lenient") is None


def test_belief_trajectory_not_applied_to_thesis():
    assert _verdict(_ctx(is_thesis_or_factor=True, belief_trajectory_ok=False), "belief_trajectory_present") is None


def test_belief_trajectory_signals_search_requires_two_steps():
    run = {
        "spread_summary": {"supervisor_search": True},
        "estimates": [
            {"agent_model": "a", "metadata": {"belief_trajectory": [{"probability": 0.4}, {"probability": 0.5}]}},
            {"agent_model": "b", "metadata": {"belief_trajectory": [{"probability": 0.5}]}},  # lone step, no reason
        ],
    }
    ok, offenders, search = belief_trajectory_signals(run)
    assert search is True and ok is False and offenders == ("b",)


def test_belief_trajectory_single_step_with_reason_passes():
    run = {
        "spread_summary": {"supervisor_search": True},
        "estimates": [{"agent_model": "a", "metadata": {"belief_trajectory": [{"probability": 0.5, "moved_by": "the CPI print"}]}}],
    }
    assert belief_trajectory_signals(run)[0] is True


def test_belief_trajectory_non_search_single_step_ok():
    run = {
        "spread_summary": {"supervisor_search": False},
        "estimates": [{"agent_model": "a", "metadata": {"belief_trajectory": [{"probability": 0.5}]}}],
    }
    assert belief_trajectory_signals(run)[0] is True


def test_belief_trajectory_specialist_exempt():
    # A deterministic specialist seat has no linguistic belief state — never an offender.
    run = {
        "spread_summary": {"supervisor_search": True},
        "estimates": [{"agent_model": "model:climatology_knn", "metadata": {"belief_trajectory": []}}],
    }
    assert belief_trajectory_signals(run)[0] is True


# ══ A3 · pool_shrinkage_recorded ══════════════════════════════════════════════
_GOOD_PROV = {
    "alpha": 1.0, "var_logit": 0.05, "anchor": None, "floor": 0.5, "c": 0.5,
    "calm_var": 0.0914, "shrunk": False,
}


def test_alpha_validator_accepts_identity_anchorless():
    assert validate_pool_shrinkage_alpha(_GOOD_PROV) is True


def test_alpha_validator_accepts_reconstructable_shrink():
    var = 0.4
    calm, floor, c = 0.0914, 0.5, 0.5
    expected = max(floor, 1.0 - c * max(0.0, var - calm))
    prov = {"alpha": round(expected, 6), "var_logit": var, "anchor": 0.3, "floor": floor, "c": c, "calm_var": calm, "shrunk": True}
    assert validate_pool_shrinkage_alpha(prov) is True


def test_alpha_validator_rejects_garbage():
    prov = {**_GOOD_PROV, "anchor": 0.3, "alpha": 0.99, "var_logit": 0.9, "shrunk": True}  # α not reconstructable
    assert validate_pool_shrinkage_alpha(prov) is False
    assert validate_pool_shrinkage_alpha({"alpha": "x"}) is False
    assert validate_pool_shrinkage_alpha({}) is False


def test_pool_shrinkage_signals_present_valid():
    run = {"spread_summary": {"pool_shrinkage": _GOOD_PROV, "disagreement_band": "calm"}}
    present, valid, non_calm = pool_shrinkage_signals(run)
    assert present is True and valid is True and non_calm is False


def test_pool_shrinkage_garbage_fires_error_class():
    v = _verdict(_ctx(is_quorum=True, pool_shrinkage_present=True, pool_shrinkage_valid=False), "pool_shrinkage_recorded")
    assert v.passed is False and v.facts.get("fault") == "garbage"


def test_pool_shrinkage_absent_on_noncalm_market_warns():
    v = _verdict(_ctx(is_quorum=True, pool_shrinkage_present=False, pool_non_calm=True, has_linked_market=True), "pool_shrinkage_recorded")
    assert v.passed is False and v.facts.get("fault") == "absent"


def test_pool_shrinkage_anchorless_absence_passes():
    # Non-calm but NO market link (anchorless) — nothing to shrink toward, so PASS.
    v = _verdict(_ctx(is_quorum=True, pool_shrinkage_present=False, pool_non_calm=True, has_linked_market=False), "pool_shrinkage_recorded")
    assert v.passed is True


def test_pool_shrinkage_only_applies_to_quorum():
    assert _verdict(_ctx(is_quorum=False, pool_shrinkage_present=True, pool_shrinkage_valid=False), "pool_shrinkage_recorded") is None


def test_pool_shrinkage_blocks_in_strict():
    v = _verdict(_ctx(is_quorum=True, pool_shrinkage_present=True, pool_shrinkage_valid=False), "pool_shrinkage_recorded", profile="strict")
    assert v.severity is Severity.ERROR


# ══ A5 · specialist_seat_considered ═══════════════════════════════════════════
def test_specialist_seat_warns_when_offerable_and_absent():
    v = _verdict(_ctx(specialist_offerable=True, specialist_seat_present=False, specialist_series="berlin_temp"), "specialist_seat_considered")
    assert v.passed is False and v.severity is Severity.WARN and "berlin_temp" in v.message


def test_specialist_seat_passes_when_present():
    assert _verdict(_ctx(specialist_offerable=True, specialist_seat_present=True), "specialist_seat_considered").passed is True


def test_specialist_seat_passes_when_declined():
    assert _verdict(_ctx(specialist_offerable=True, specialist_declined=True), "specialist_seat_considered").passed is True


def test_specialist_seat_never_offerable_no_apply():
    assert _verdict(_ctx(specialist_offerable=False), "specialist_seat_considered") is None


def test_specialist_seat_warn_forever_even_strict():
    assert profile_severities("strict")["specialist_seat_considered"] is Severity.WARN


def test_specialist_signals_reads_estimates_and_declines():
    ran = {"estimates": [{"agent_model": "model:seasonal_naive"}], "spread_summary": {}}
    assert specialist_seat_signals(ran) == (True, False)
    declined = {"estimates": [], "spread_summary": {"specialist_seats": {"declined": [{"seat": "model:climatology_knn"}]}}}
    assert specialist_seat_signals(declined) == (False, True)


# ══ end-to-end: commit through the ledger with a real post-harvest panel run ═══
import pytest  # noqa: E402

from forecasting import ForecastLedger  # noqa: E402


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "blf.db"))
    lg.initialize_schema()
    return lg


def _estimate(model, *, traj, prob=0.5):
    return {
        "perspective": model, "agent_model": model, "probability": prob, "weight": 1.0,
        "reasons_up": [], "reasons_down": [], "change_my_mind": [], "crux": None,
        "metadata": {"belief_trajectory": traj},
    }


def _record_run(lg, qid, *, estimates, supervisor_search=True, triggered_by="quorum", **kw):
    from forecasting.ledger.core import allow_ledger_writes

    with allow_ledger_writes(reason="test"):
        return lg.record_panel_run(
            question_id=qid, estimates=estimates, triggered_by=triggered_by,
            supervisor_search_enabled=supervisor_search, **kw,
        )


def _verdicts(snap):
    return {v["rule_id"]: v for v in (snap.metadata.get("saturation") or {}).get("verdicts", [])}


def _commit(lg, qid, ref):
    return lg.create_snapshot(
        question_id=qid, probability_or_distribution=0.5, rationale="clean prose here",
        method="quorum", panel_run_ref=ref, set_current=True,
    )


def test_e2e_belief_trajectory_fires_on_post_harvest_commit(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will X exceed target?", resolution_criteria="Yes if X exceeds target.")
    run = _record_run(lg, q.id, estimates=[
        _estimate("opus", traj=[{"probability": 0.4, "moved_by": "a"}, {"probability": 0.5, "moved_by": "b"}]),
        _estimate("gpt-5.5", traj=[]),  # 0 steps on a search-enabled run → offender
    ])
    assert run["spread_summary"]["process_version"] >= PANEL_PROCESS_VERSION  # marker stamped
    snap = _commit(lg, q.id, run["id"])
    v = _verdicts(snap)["belief_trajectory_present"]
    assert v["passed"] is False and "gpt-5.5" in v["message"]


def test_e2e_belief_trajectory_inert_when_marker_stripped(tmp_path):
    # Simulate a PRE-harvest run: strip the process-version marker from the persisted
    # spread. The rule must go inert (proving the retroactivity guard) even though the
    # trajectories are missing.
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will Y exceed target?", resolution_criteria="Yes if Y exceeds target.")
    run = _record_run(lg, q.id, estimates=[_estimate("gpt-5.5", traj=[])])
    with lg._connect() as conn:
        row = conn.execute("SELECT spread_summary FROM panel_runs WHERE id = ?", (run["id"],)).fetchone()
        import json as _j
        spread = _j.loads(row[0]); spread.pop("process_version", None)
        conn.execute("UPDATE panel_runs SET spread_summary = ? WHERE id = ?", (_j.dumps(spread), run["id"]))
    snap = _commit(lg, q.id, run["id"])
    assert "belief_trajectory_present" not in _verdicts(snap)


def test_e2e_pool_shrinkage_garbage_fires(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will Z exceed target?", resolution_criteria="Yes if Z exceeds target.")
    garbage = {"alpha": 0.99, "var_logit": 0.9, "anchor": 0.3, "floor": 0.5, "c": 0.5, "calm_var": 0.0914, "shrunk": True}
    run = _record_run(lg, q.id, estimates=[
        _estimate("opus", traj=[{"probability": 0.4, "moved_by": "a"}, {"probability": 0.5, "moved_by": "b"}]),
        _estimate("gpt-5.5", traj=[{"probability": 0.6, "moved_by": "c"}, {"probability": 0.55, "moved_by": "d"}]),
    ], pool_shrinkage=garbage)
    snap = _commit(lg, q.id, run["id"])
    v = _verdicts(snap)["pool_shrinkage_recorded"]
    assert v["passed"] is False and v["facts"]["fault"] == "garbage"


def test_e2e_specialist_decline_recorded_passes(tmp_path):
    # A numeric question with a derivable threshold, a post-harvest panel whose specialist
    # seat DECLINED (recorded) — the gate passes on the honest decline.
    from forecasting.models import OutcomeSpace

    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="What will the reading be?",
        resolution_criteria="The measured reading at close.",
        outcome_space=OutcomeSpace(type="numeric", bounds=[0.0, 100.0], units="count"),
        metadata={"specialist": {"threshold": 50.0, "operator": ">="}},
    )
    run = _record_run(lg, q.id, estimates=[
        _estimate("opus", traj=[{"probability": 0.4, "moved_by": "a"}, {"probability": 0.5, "moved_by": "b"}]),
    ], specialist_summary={"ran": [], "declined": [{"seat": "model:climatology_knn", "reason": "series unreachable"}]})
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution={"mean": 40.0, "q05": 10.0, "q50": 40.0, "q95": 70.0},
        rationale="clean prose", method="quorum", panel_run_ref=run["id"], set_current=True,
    )
    v = _verdicts(snap).get("specialist_seat_considered")
    assert v is not None and v["passed"] is True


# ══ TUI surfacing: the desk panel modal 'what moved the number' line ═══════════
def test_belief_line_renders_arc_and_mover():
    from forecasting.dashboard import _belief_trajectory_line

    line = _belief_trajectory_line({"belief_trajectory": [
        {"probability": 0.40, "moved_by": "the base rate"},
        {"probability": 0.55, "moved_by": "the CPI print"},
    ]})
    assert line == "40%→55% · 2 steps · moved by: the CPI print"


def test_belief_line_none_without_trajectory():
    from forecasting.dashboard import _belief_trajectory_line

    assert _belief_trajectory_line({}) is None
    assert _belief_trajectory_line({"belief_trajectory": []}) is None
    assert _belief_trajectory_line(None) is None


def test_workspace_panel_carries_belief_line():
    from forecasting.dashboard import _workspace_panel

    run = {
        "id": "pr_1", "aggregate_probability": 0.5, "spread_summary": {},
        "estimates": [
            {"perspective": "opus", "probability": 0.5, "weight": 1.0, "trimmed": False,
             "metadata": {"belief_trajectory": [{"probability": 0.5, "moved_by": "x"}]}},
            {"perspective": "legacy", "probability": 0.5, "weight": 1.0, "trimmed": False, "metadata": {}},
        ],
    }
    panel = _workspace_panel(run)
    assert panel["estimates"][0]["belief"] and "moved by: x" in panel["estimates"][0]["belief"]
    assert panel["estimates"][1]["belief"] is None  # legacy estimate → no fabricated line
