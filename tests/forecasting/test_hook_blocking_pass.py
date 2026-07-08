"""Slice H3 — the RESOLVED-POLICY blocking pass in create_snapshot.

These are BEHAVIORAL tests (they commit through the ledger / agent tool and assert
what actually blocks), the counterpart to test_hook_config.py's severity-MAP tests.
They pin:
  * require_evidence becomes a real floor for an agent commit under the standard
    profile (soft-spot a);
  * the strict profile actually blocks the non-inline rules it promotes (soft-spot b);
  * exploratory + programmatic (autofix) + non-opted-in direct callers commit exactly
    as before (the preserved contracts);
  * the FORECAST_DISABLE_HOOK_BLOCKING kill-switch disables the pass.
"""

from __future__ import annotations

import json

import pytest

from forecasting import ForecastLedger
from forecasting.hooks import SaturationBlocked
from tools.forecasting_tool import forecast_ledger_tool


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "block.db"))
    lg.initialize_schema()
    return lg


def _q(lg, *, profile=None, impact=None):
    meta = {"forecast_hooks": {"profile": profile}} if profile else None
    return lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
        metadata=meta,
        impact=impact,
    )


# ── (a) require_evidence is a real floor for an agent commit under STANDARD ──────
def test_standard_agent_commit_blocks_on_missing_evidence(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)  # default (standard) profile
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(
            question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
            method="m", require_panel=False, enforce_resolved_hooks=True,
        )
    assert ei.value.report.blocking_failures()[0].rule_id == "require_evidence"
    assert "NO evidence attached" in str(ei.value)


def test_standard_agent_commit_passes_evidence_floor_with_one_record(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    lg.add_evidence(question_id=q.id, source_or_note="quarterly report", claim="rates rose")
    # G3: a FIRST commit now requires a linked outside-view anchor, so link one.
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False, reference_class_refs=[rc["id"]],
        enforce_resolved_hooks=True,
    )
    assert snap is not None  # evidence present + anchor linked -> commits


# ── (b) STRICT profile actually blocks a rule it PROMOTES (was observe-only) ─────
def test_strict_profile_blocks_promoted_outside_view_anchor(tmp_path):
    lg = _ledger(tmp_path)
    # impact="high" makes it a SERIOUS forecast so the (serious-scoped) anchor rule fires.
    q = _q(lg, profile="strict", impact="high")
    # Clear the evidence floor so the strict-only promotion (require_outside_view_anchor,
    # ERROR) is what blocks — proving the strict severity is real.
    lg.add_evidence(question_id=q.id, source_or_note="report", claim="rates rose")
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(
            question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
            method="m", require_panel=False, enforce_resolved_hooks=True,
        )
    assert ei.value.report.blocking_failures()[0].rule_id == "require_outside_view_anchor"


def test_strict_profile_bare_forecast_blocks_with_a_resolved_rule_message(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg, profile="strict")
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(
            question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
            method="m", require_panel=False, enforce_resolved_hooks=True,
        )
    # A bare strict commit blocks on the first applicable resolved-ERROR rule with no
    # inline gate. require_evidence (ERROR) precedes the outside-view anchor in builtin order.
    blocker = ei.value.report.blocking_failures()[0]
    assert blocker.rule_id == "require_evidence"
    assert str(ei.value) == blocker.message  # SaturationBlocked message == the resolved rule's


# ── (c) preserved contracts: exploratory / programmatic / non-opted-in ──────────
def test_exploratory_agent_commit_is_exempt_even_when_opted_in(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="scratch thinking",
        method="m", require_panel=False, forecast_origin="exploratory",
        enforce_resolved_hooks=True,
    )
    assert snap is not None and snap.forecast_origin == "exploratory"


def test_programmatic_autofix_path_is_exempt_from_blocking(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)  # no evidence
    # A programmatic path passes style_autofix / distribution_autofix; it keeps observe +
    # autofix leniency and is NEVER hard-blocked, even if it also opts in.
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="auto prose",
        method="m", require_panel=False, style_autofix=True, distribution_autofix=True,
        enforce_resolved_hooks=True,
    )
    assert snap is not None


def test_direct_ledger_commit_without_optin_is_unchanged(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)  # no evidence, standard profile
    # A raw create_snapshot (operator seed / migration / internal recompute) does NOT opt
    # into the blocking pass, so the evidence-free live commit succeeds exactly as before.
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False,
    )
    assert snap is not None
    # observe-mode still records the report (require_evidence shows as a blocking rule there).
    assert "require_evidence" in (snap.metadata or {}).get("saturation", {}).get("blocking", [])


# ── (e) kill-switch disables the pass (observe still records) ────────────────────
def test_kill_switch_disables_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_DISABLE_HOOK_BLOCKING", "1")
    lg = _ledger(tmp_path)
    q = _q(lg, profile="strict")  # strict + no evidence would normally block
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False, enforce_resolved_hooks=True,
    )
    assert snap is not None


# ── RDY machine-readiness enforcement (readiness_floor + no_watched_sources) ─────
def _well_provisioned_q(lg, *, profile=None):
    """A question whose machine-readiness clears the floor and carries a watched
    source, so neither new rule fires. (watches 20 + ref_class 12 + trigger 12 +
    close_time 6 + impact 6 + resolution 6 = 62 >= 60 floor.)"""
    meta = {"forecast_hooks": {"profile": profile}} if profile else None
    q = lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
        close_time="2030-01-01T00:00:00Z",
        impact="medium",
        update_triggers=[{"mechanism": "CPI print", "source_ref": "fred:CPIAUCSL", "operator": ">", "threshold": 3.0}],
        review_cadence="weekly",
        next_review_at="2030-01-01T00:00:00Z",
        metadata=meta,
    )
    lg.add_watched_source(scope_type="question", scope_ref=q.id, source="fred:CPIAUCSL")
    lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior indicator cases", base_rate=0.4)
    lg.add_evidence(question_id=q.id, source_or_note="quarterly report", claim="rates rose")
    return q


def test_strict_bare_commit_blocks_on_new_readiness_rules(tmp_path):
    """A live STRICT commit on a bare, zero-watched-source question raises
    SaturationBlocked citing BOTH new rules — proving the resolved-policy blocking
    pass evaluates them at ERROR and that their signals reach the commit context."""
    lg = _ledger(tmp_path)
    q = _q(lg, profile="strict")  # no watches, readiness far below floor, no evidence
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(
            question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
            method="m", require_panel=False, enforce_resolved_hooks=True,
        )
    blocking = {v.rule_id for v in ei.value.report.blocking_failures()}
    assert "no_watched_sources" in blocking
    assert "readiness_floor" in blocking


def test_standard_well_provisioned_commit_does_not_fire_new_rules(tmp_path):
    """THE PLUMBING PROOF: a well-provisioned question commits under standard and
    NEITHER new rule fires. If snapshots.py did not thread watched_source_count /
    readiness_score into the blocking-pass context, no_watched_sources would false-fire
    (count defaults to 0) — this pins that the real values arrive."""
    lg = _ledger(tmp_path)
    q = _well_provisioned_q(lg)  # standard profile, watches>0, readiness>=60, rc present
    # G3: link the already-present reference class so the FIRST-commit anchor clears.
    _rc_id = lg.list_reference_classes(q.id)[0]["id"]
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False, reference_class_refs=[_rc_id],
        enforce_resolved_hooks=True,
    )
    assert snap is not None
    sat = (snap.metadata or {}).get("saturation") or {}
    assert "no_watched_sources" not in sat.get("warnings", [])
    assert "no_watched_sources" not in sat.get("blocking", [])
    assert "readiness_floor" not in sat.get("warnings", [])
    assert "readiness_floor" not in sat.get("blocking", [])


def test_standard_bare_commit_warns_new_rules_without_blocking(tmp_path):
    """Contrast case: a bare question under standard commits (both rules are WARN,
    non-blocking) but BOTH new rules surface as observe-mode warnings — proving the
    signals reach the context and the rules are wired ON by default."""
    lg = _ledger(tmp_path)
    q = _q(lg)  # standard, no watches, low readiness
    lg.add_evidence(question_id=q.id, source_or_note="report", claim="x")  # clear the evidence floor
    # G3: link an anchor so the FIRST-commit anchor ERROR does not block (leaving the
    # WARN-only new rules to surface in the observe report, which is what this pins).
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False, reference_class_refs=[rc["id"]],
        enforce_resolved_hooks=True,
    )
    assert snap is not None
    warns = ((snap.metadata or {}).get("saturation") or {}).get("warnings", [])
    assert "no_watched_sources" in warns
    assert "readiness_floor" in warns


# ── the agent tool opts in: the block flows through the structured directive ─────
def test_agent_tool_evidence_floor_returns_saturation_block(tmp_path):
    db = str(tmp_path / "tool.db")
    qid = json.loads(forecast_ledger_tool({
        "action": "create_question", "db": db,
        "title": "Will the indicator exceed target by close?",
        "resolution_criteria": "Resolves yes if the indicator exceeds target by close; otherwise no.",
    }))["question"]["id"]
    # A fully-formed agent commit (reasons + components) with NO evidence is refused by the
    # require_evidence floor, and the tool hands back the structured remediation directive.
    out = json.loads(forecast_ledger_tool({
        "action": "update_forecast", "db": db, "question_id": qid,
        "probability": 0.5, "rationale": "clean prose", "method": "m",
        "require_panel": False,
        "reasons_up": ["a"], "reasons_down": ["b"], "change_my_mind": ["c"],
        "components": {"base_rate": {"probability": 0.4, "weight": 1},
                       "inside_view": {"probability": 0.6, "weight": 1}},
    }))
    assert out["success"] is False
    block = out["saturation_block"]
    assert block["blocked"] is True
    assert any(r["rule_id"] == "require_evidence" for r in block["failing_rules"])
