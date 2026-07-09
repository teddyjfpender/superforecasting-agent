"""Phase 2 tests: the style gate (block vs programmatic auto-fix) and the
interactive ``saturation_block`` directive the update_forecast tool returns."""

from __future__ import annotations

import json

import pytest

from forecasting import ForecastLedger
from forecasting.hooks import SaturationBlocked
from forecasting.models import OutcomeSpace
from tools.forecasting_tool import forecast_ledger_tool


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "hooks.db"))
    lg.initialize_schema()
    return lg


def _q(lg):
    return lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.",
    )


def _components():
    return {"components": [
        {"name": "base_rate", "probability": 0.4, "weight": 2},
        {"name": "mkt", "source": "manifold:x", "probability": 0.6, "weight": 3},
    ]}


def test_style_gate_blocks_em_dash_on_agent_path(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    with pytest.raises(SaturationBlocked) as ei:
        lg.create_snapshot(
            question_id=q.id, probability_or_distribution=0.5,
            rationale="rates rose — sharply this quarter", method="m",
            ensemble_components=_components(), reasons_up=["a"], reasons_down=["b"],
            change_my_mind=["c"], require_panel=False,
        )
    assert "house style" in str(ei.value)
    assert ei.value.report.blocking_failures()[0].rule_id == "style_clean"


def test_style_autofix_sanitizes_for_programmatic_path(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5,
        rationale="rates rose — sharply this quarter", method="m",
        ensemble_components=_components(), reasons_up=["a"], reasons_down=["b"],
        change_my_mind=["c"], require_panel=False, style_autofix=True,
    )
    assert "—" not in snap.rationale  # mechanically cleaned, not blocked
    assert "rates rose" in snap.rationale


def test_clean_prose_commits_normally(tmp_path):
    lg = _ledger(tmp_path)
    q = _q(lg)
    # A properly-formed live forecast now carries BOTH a hard evidence record
    # (require_evidence ERROR) and an outside-view anchor (require_outside_view_anchor)
    # — attach both so the clean-prose commit passes saturation as before.
    lg.add_evidence(question_id=q.id, source_or_note="quarterly rates report", claim="rates rose sharply")
    lg.add_reference_class(
        question_id=q.id,
        name="historical quarter-over-quarter rate moves",
        inclusion_criteria="comparable rate regimes",
        base_rate=0.5,
    )
    snap = lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5,
        rationale="rates rose sharply this quarter", method="m",
        ensemble_components=_components(), reasons_up=["a"], reasons_down=["b"],
        change_my_mind=["c"], require_panel=False,
    )
    assert (snap.metadata or {}).get("saturation", {}).get("passed") is True


def test_update_forecast_returns_saturation_block_directive(tmp_path):
    db = str(tmp_path / "tool.db")
    qid = json.loads(forecast_ledger_tool({
        "action": "create_question", "db": db,
        "title": "Will the indicator exceed target by close?",
        "resolution_criteria": "Resolves yes if the indicator exceeds target by close; otherwise no.",
    }))["question"]["id"]
    # Commit with NO ensemble_components -> blocked by require_components (default True),
    # and the tool returns a structured remediation directive instead of a bare error.
    out = json.loads(forecast_ledger_tool({
        "action": "update_forecast", "db": db, "question_id": qid,
        "probability": 0.5, "rationale": "first read", "method": "m",
        "reasons_up": ["a"], "reasons_down": ["b"], "change_my_mind": ["c"],
    }))
    assert out["success"] is False
    block = out["saturation_block"]
    assert block["blocked"] is True
    assert any(r["rule_id"] == "require_components" for r in block["failing_rules"])
    assert "decompose" in block["next_actions"]
    assert "own saturating it" in block["guidance"]


def _commit_clean(lg, q):
    return lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="rates rose sharply",
        method="m", ensemble_components=_components(), reasons_up=["a"], reasons_down=["b"],
        change_my_mind=["c"], require_panel=False, evidence_refs=[],
    )


def test_lint_forecast_scores_committed_snapshot(tmp_path):
    from forecasting.hooks import lint_forecast
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit_clean(lg, q)
    rep = lint_forecast(lg, q.id)
    assert rep is not None
    assert 0 <= rep.score <= 100
    assert any(v.rule_id == "style_clean" and v.passed for v in rep.verdicts)


def test_lint_none_without_snapshot(tmp_path):
    from forecasting.hooks import lint_forecast
    lg = _ledger(tmp_path)
    q = _q(lg)
    assert lint_forecast(lg, q.id) is None


def test_finish_sweep_dedupes_and_summarizes(tmp_path):
    from forecasting.hooks import finish_sweep
    lg = _ledger(tmp_path)
    q = _q(lg)
    _commit_clean(lg, q)
    summary = finish_sweep(lg, [q.id, q.id, "nonexistent"])
    assert summary["checked"] == 1  # deduped + skipped the missing one
    assert summary["clean"] + len(summary["under_saturated"]) == 1


def test_cli_lint_handler_emits_json(tmp_path, capsys):
    import argparse
    from forecasting.cli import _cmd_lint
    db = str(tmp_path / "lint.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    q = _q(lg)
    _commit_clean(lg, q)
    _cmd_lint(argparse.Namespace(db=db, question_id=q.id, ids=[], thesis_members=[], all=False, by_rule=False, json=True))
    out = capsys.readouterr().out
    assert '"score"' in out and '"verdicts"' in out and '"metrics"' in out


def test_cli_lint_ids_json_includes_metrics_and_warns(tmp_path, capsys):
    import argparse
    from forecasting.cli import _cmd_lint

    db = str(tmp_path / "lint_ids.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    q = _q(lg)
    for i in range(4):
        lg.add_evidence(question_id=q.id, source_or_note=f"report {i}", claim="rates rose")
    _commit_clean(lg, q)

    _cmd_lint(argparse.Namespace(db=db, question_id=None, ids=[q.id], thesis_members=[], all=False, by_rule=False, json=True))
    payload = json.loads(capsys.readouterr().out)
    row = payload["results"][0]
    assert row["question_id"] == q.id
    assert row["metrics"]["evidence_count"] == 4
    assert row["metrics"]["source_count"] == 0
    assert row["metrics"]["readiness_floor"] == 80
    assert "evidence_depth" in row["failed"]


def test_cli_lint_thesis_members_expands_members(tmp_path, capsys):
    import argparse
    from forecasting.cli import _cmd_lint

    db = str(tmp_path / "lint_thesis.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    thesis = lg.create_question(
        title="Will the thesis hold?",
        resolution_criteria="Aggregate health of member forecasts.",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    a = _q(lg)
    b = _q(lg)
    _commit_clean(lg, a)
    _commit_clean(lg, b)
    lg.add_thesis_member(thesis.id, a.id)
    lg.add_thesis_member(thesis.id, b.id)

    _cmd_lint(argparse.Namespace(db=db, question_id=None, ids=[], thesis_members=[thesis.id], all=False, by_rule=False, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert {row["question_id"] for row in payload["results"]} == {a.id, b.id}
