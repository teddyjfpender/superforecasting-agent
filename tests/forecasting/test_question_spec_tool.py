"""Gateway action tests for propose_spec / commit_spec."""

from __future__ import annotations

import json

from tools.forecasting_tool import forecast_ledger_tool


def _good_spec_dict():
    return {
        "title": "US CPI YoY for the June 2026 print",
        "resolution_criteria": "Resolves yes if BLS June 2026 CPI YoY exceeds 3.0 percent.",
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
