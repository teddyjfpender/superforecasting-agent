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


def _q(lg, *, profile=None):
    meta = {"forecast_hooks": {"profile": profile}} if profile else None
    return lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
        metadata=meta,
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
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
        method="m", require_panel=False, enforce_resolved_hooks=True,
    )
    assert snap is not None  # evidence present -> require_evidence satisfied


# ── (b) STRICT profile actually blocks a rule it PROMOTES (was observe-only) ─────
def test_strict_profile_blocks_promoted_outside_view_anchor(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg, profile="strict")
    # Clear the evidence floor so the FIRST strict-only promotion (require_outside_view_anchor,
    # WARN in standard -> ERROR in strict) is what blocks — proving the strict severity is real.
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
