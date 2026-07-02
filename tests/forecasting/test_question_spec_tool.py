"""Gateway action tests for propose_spec / commit_spec."""

from __future__ import annotations

import json

from tools.forecasting_tool import forecast_ledger_tool


def _good_spec_dict():
    return {
        "title": "US CPI YoY for the June 2026 print",
        "resolution_criteria": "Resolves yes if BLS June 2026 CPI YoY exceeds 3.0 percent.",
        "close_time": "2026-07-15T00:00:00Z",
        "decision_owner": "me",
        "action_threshold": ">=70% act",
        "update_triggers": [{"mechanism": "CPI print", "operator": ">", "threshold": 3.0, "source_ref": "fred:CPIAUCSL"}],
        "watched_sources": [{"source": "fred:CPIAUCSL", "source_type": "fred", "reliability_prior": 0.9, "confidence_weight": 2.0}],
        "reference_classes": [{"name": "recent CPI prints", "inclusion_criteria": "monthly CPI since 2015", "base_rate": 0.4}],
        "panel_by_default": True,
        "allow_evidence_gathering": False,
    }


def test_propose_spec_returns_issues_and_clarifications(tmp_path):
    db = str(tmp_path / "p.db")
    out = json.loads(forecast_ledger_tool({
        "action": "propose_spec", "db": db,
        "spec": {"title": "forecast", "resolution_criteria": "tbd"},
    }))
    assert out["success"] is True
    assert out["committable"] is False
    fields = {e["field"] for e in out["errors"]}
    assert "title" in fields and "resolution_criteria" in fields
    # recommended clarifications are ready to fire, each with <=4 base choices
    assert out["recommended_clarifications"]
    for c in out["recommended_clarifications"]:
        assert "question" in c and "choices" in c
        assert len(c["choices"]) <= 4


def test_commit_spec_refuses_unscoreable(tmp_path):
    db = str(tmp_path / "c.db")
    out = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db,
        "spec": {"title": "x", "resolution_criteria": "tbd"},
    }))
    assert out["success"] is False
    assert out.get("issues")
    assert json.loads(forecast_ledger_tool({"action": "list_questions", "db": db}))["questions"] == []


def test_commit_spec_creates_full_fanout(tmp_path):
    db = str(tmp_path / "ok.db")
    out = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": _good_spec_dict()}))
    assert out["success"] is True
    qid = out["question_id"]
    assert len(out["watched_sources"]) == 1
    assert len(out["reference_classes"]) == 1

    sources = json.loads(forecast_ledger_tool({
        "action": "list_watched_sources", "db": db, "scope_type": "question", "scope_ref": qid,
    }))
    src = sources["watched_sources"][0]
    assert src["metadata"]["reliability_prior"] == 0.9
    assert src["metadata"]["confidence_weight"] == 2.0


def test_propose_spec_reports_quality_and_suggested_rule(tmp_path):
    db = str(tmp_path / "q.db")
    out = json.loads(forecast_ledger_tool({"action": "propose_spec", "db": db, "spec": _good_spec_dict()}))
    assert out["spec_quality"]["score"] == 100
    # binary + watched source + executable trigger -> a rule is suggested
    assert out["suggested_resolution_rule"] is not None
    assert out["suggested_resolution_rule"]["comparator"] == ">"
    # nothing committed yet, so no duplicates
    assert out["possible_duplicates"] == []


def test_duplicate_detection_surfaces_and_warns(tmp_path):
    db = str(tmp_path / "dup.db")
    # commit the question once
    first = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": _good_spec_dict()}))
    assert first["success"] is True

    # proposing the same title surfaces the existing question as a possible duplicate
    proposed = json.loads(forecast_ledger_tool({"action": "propose_spec", "db": db, "spec": _good_spec_dict()}))
    dups = proposed["possible_duplicates"]
    assert dups and dups[0]["id"] == first["question_id"]

    # committing the near-identical question warns but does NOT block
    second = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": _good_spec_dict()}))
    assert second["success"] is True
    assert "duplicate_warning" in second
    assert first["question_id"] in second["duplicate_warning"]


def test_set_and_propose_resolution_rule_actions(tmp_path):
    db = str(tmp_path / "rule.db")
    committed = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": _good_spec_dict()}))
    qid = committed["question_id"]

    rule_out = json.loads(forecast_ledger_tool({
        "action": "set_resolution_rule", "db": db, "question_id": qid,
        "field": "yoy_percent", "comparator": ">=", "threshold": 3.0, "source_role": "resolver",
    }))
    assert rule_out["success"] is True
    assert rule_out["resolution_rule"]["field"] == "yoy_percent"

    # no ingested value yet -> an explicit UNDETERMINED proposal, never fabricated
    proposal = json.loads(forecast_ledger_tool({
        "action": "propose_resolution", "db": db, "question_id": qid,
    }))
    assert proposal["success"] is True
    assert proposal["resolution_proposal"]["determinable"] is False


def test_set_resolution_rule_requires_threshold(tmp_path):
    db = str(tmp_path / "rule2.db")
    committed = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": _good_spec_dict()}))
    qid = committed["question_id"]
    out = json.loads(forecast_ledger_tool({
        "action": "set_resolution_rule", "db": db, "question_id": qid,
        "field": "v", "comparator": ">=",
    }))
    assert out["success"] is False


# ── accept-defaults onboarding (one-shot for a vague ask) ──────────────────────
def _casual_spec_dict():
    # A lazy prompter's sentence: binary defaults, an auditable condition, but no
    # deadline / owner / action threshold — every one has a recommended default.
    return {
        "title": "Will the Fed cut in September 2026?",
        "resolution_criteria": "Resolves yes if the FOMC lowers the target rate at or before its September 2026 meeting; otherwise no.",
    }


def test_accept_defaults_proposes_and_commits_in_one_shot(tmp_path):
    db = str(tmp_path / "accept.db")

    # propose_spec with accept_defaults fills the gaps and reports them.
    proposed = json.loads(forecast_ledger_tool({
        "action": "propose_spec", "db": db, "spec": _casual_spec_dict(), "accept_defaults": True,
    }))
    assert proposed["success"] is True
    assert proposed["accept_defaults"] is True
    applied_fields = {a["field"] for a in proposed["applied_defaults"]}
    assert {"close_time", "decision_owner", "action_threshold"} <= applied_fields
    # gaps with a recommended default are closed; committable regardless (gaps never block).
    assert proposed["committable"] is True
    remaining_gaps = {g["field"] for g in proposed["readiness_gaps"]}
    assert not ({"close_time", "decision_owner", "action_threshold"} & remaining_gaps)

    # commit_spec with accept_defaults commits the enriched spec in one shot.
    committed = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db, "spec": _casual_spec_dict(), "accept_defaults": True,
    }))
    assert committed["success"] is True
    assert committed["applied_defaults"]
    q = json.loads(forecast_ledger_tool({"action": "show_question", "db": db, "question_id": committed["question_id"]}))
    assert q["question"]["close_time"]  # a concrete deadline was recorded
    # the auto-applied answers are persisted under metadata.onboarding for audit
    onboarding = q["question"]["metadata"]["onboarding"]
    assert any(c.get("auto_default") for c in onboarding["clarifications"])


def test_accept_defaults_still_blocks_on_error_severity(tmp_path):
    db = str(tmp_path / "accept_block.db")
    # An unscoreable criteria is an error with no recommended default — accept_defaults
    # must NOT fabricate past it; the commit is still refused, nothing is written.
    out = json.loads(forecast_ledger_tool({
        "action": "commit_spec", "db": db,
        "spec": {"title": "forecast", "resolution_criteria": "tbd"},
        "accept_defaults": True,
    }))
    assert out["success"] is False
    assert {e["field"] for e in out["issues"]} & {"title", "resolution_criteria"}
    assert json.loads(forecast_ledger_tool({"action": "list_questions", "db": db}))["questions"] == []


def test_full_autonomy_implies_accept_defaults(tmp_path):
    db = str(tmp_path / "autonomy.db")
    spec = dict(_casual_spec_dict(), autonomy="full")
    # No explicit accept_defaults flag — 'full' autonomy alone triggers the fast path.
    proposed = json.loads(forecast_ledger_tool({"action": "propose_spec", "db": db, "spec": spec}))
    assert proposed["accept_defaults"] is True
    assert proposed["applied_defaults"]
    assert proposed["committable"] is True

    committed = json.loads(forecast_ledger_tool({"action": "commit_spec", "db": db, "spec": spec}))
    assert committed["success"] is True
    assert committed["accept_defaults"] is True
