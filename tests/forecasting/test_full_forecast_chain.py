"""Slice S3 — the autonomous entry point.

A lazy prompter's single sentence should yield a complete, committed forecast:
`forecast onboard --auto` / the `full_forecast` tool action / the cron bootstrap all
chain research -> base_rate -> update through ONE shared orchestration helper
(`forecasting.application.pipeline.run_forecast_chain`). The LLM stages can't run in a test, so we stub
`agent.forecast_stage.run_stage` (the execution adapter every path reuses) and assert the wiring:
the chain commits at each stage, a gate that refuses the update still blocks (no
fabricated snapshot), and the CLI flag parses + runs the chain.
"""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting.cli import register_cli, run_forecast_chain
from tools.forecasting_tool import forecast_ledger_tool


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "chain.db"))
    ledger.initialize_schema()
    return ledger


def _question(ledger, **over):
    defaults = dict(
        title="Will CPI YoY be below 3.0% for the July 2026 release?",
        resolution_criteria="Resolves yes if BLS CPI-U YoY for the July 2026 release is below 3.0%; otherwise no.",
    )
    defaults.update(over)
    return ledger.create_question(**defaults)


def _stage_side_effects(ledger, qid, stage):
    """The artifacts each pipeline stage would land, so the pipeline gate unlocks."""
    if stage == "research":
        # Land ADEQUATE research (>=3 distinct, fresh sources with a disconfirming
        # stance) so the chain's VOI research-adequacy loop passes on the first audit
        # and adds no extra research pass — the stage sequence stays as authored.
        from datetime import datetime, timezone
        _fresh = datetime.now(timezone.utc).isoformat()
        ledger.add_evidence(question_id=qid, source_or_note="BLS prior prints", source_name="bls", available_at=_fresh, stance="supports")
        ledger.add_evidence(question_id=qid, source_or_note="skeptic take", source_name="analyst-b", available_at=_fresh, stance="opposes")
        ledger.add_evidence(question_id=qid, source_or_note="market read", source_name="market-c", available_at=_fresh, stance="context")
    elif stage == "base_rate":
        ledger.add_reference_class(question_id=qid, name="recent CPI prints", inclusion_criteria="last 12 prints", base_rate=0.4)
    elif stage == "update":
        ledger.create_snapshot(question_id=qid, probability_or_distribution=0.42, rationale="committed forecast", require_panel=False)


# ── run_forecast_chain ────────────────────────────────────────────────────────


def test_chain_happy_path_commits_at_each_stage(tmp_path, monkeypatch):
    import forecasting.cli as cli
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} done"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    result = run_forecast_chain(ledger, q.id, max_iterations=3)

    assert seen == ["research", "base_rate", "update"]
    assert result["committed"] is True
    assert result["snapshot"]["probability_or_distribution"] == 0.42
    assert result["update_ready"] is True
    # only the update stage lands a snapshot; earlier stages report ran/uncommitted
    by_stage = {s["stage"]: s for s in result["stages"]}
    assert by_stage["research"]["committed"] is False
    assert by_stage["update"]["committed"] is True


def test_chain_gate_blocks_when_update_violates_a_gate(tmp_path, monkeypatch):
    import forecasting.cli as cli
    ledger = _ledger(tmp_path)
    # high-impact question: the update stage's create_snapshot(require_panel=True)
    # hits the deliberative-panel gate and REFUSES — orchestration must surface the
    # block honestly (no snapshot, committed False), never fabricate a number.
    q = _question(ledger, impact="high")

    def fake_agent(led, qid, *, stage="update", **kw):
        if stage == "research":
            led.add_evidence(question_id=qid, source_or_note="prior prints", available_at="2026-01-01T00:00:00Z")
        elif stage == "base_rate":
            led.add_reference_class(question_id=qid, name="recent", inclusion_criteria="last 12", base_rate=0.4)
        elif stage == "update":
            # the REAL gate fires here and raises — the chain must not swallow it into a commit
            led.create_snapshot(question_id=qid, probability_or_distribution=0.42, rationale="x", require_panel=True)
        return {}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    result = run_forecast_chain(ledger, q.id, max_iterations=3)

    assert result["committed"] is False
    assert result["snapshot"] is None
    update_outcome = next(s for s in result["stages"] if s["stage"] == "update")
    assert update_outcome["status"] == "error"
    assert ledger.get_current_snapshot(q.id) is None


def test_chain_continues_past_a_failing_stage(tmp_path, monkeypatch):
    import forecasting.cli as cli
    ledger = _ledger(tmp_path)
    q = _question(ledger)

    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        if stage == "research":
            raise RuntimeError("search timed out")  # research lands no evidence
        if stage == "base_rate":
            _stage_side_effects(led, qid, stage)  # base_rate still runs
        # the update stage respects the still-open gate and declines to commit
        return {}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    result = run_forecast_chain(ledger, q.id, max_iterations=3)

    # research errored but the chain CONTINUED through base_rate and update; with no
    # evidence the update stage stayed gated, so nothing was fabricated. The VOI
    # adequacy loop re-ran research once (it also raised, landed nothing) before the
    # no-progress guard stopped it.
    assert seen == ["research", "research", "base_rate", "update"]
    research = next(s for s in result["stages"] if s["stage"] == "research")
    assert research["status"] == "error"
    assert result["committed"] is False
    assert "research" in result["update_blockers"]


# ── full_forecast tool action ─────────────────────────────────────────────────


def _casual_spec():
    return {
        "title": "Will the Fed cut in September 2026?",
        "resolution_criteria": "Resolves yes if the FOMC lowers the target rate at or before its September 2026 meeting; otherwise no.",
    }


def test_full_forecast_tool_commits_and_chains(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} done"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    out = json.loads(forecast_ledger_tool({
        "action": "full_forecast", "db": db, "spec": _casual_spec(),
    }))

    assert out["success"] is True
    assert out["question_id"]
    assert seen == ["research", "base_rate", "update"]
    assert out["committed"] is True
    assert out["snapshot"]["probability_or_distribution"] == 0.42
    assert out["applied_defaults"]  # accept-defaults filled the vague ask's gaps
    # the question actually exists in the ledger afterward
    shown = json.loads(forecast_ledger_tool({"action": "show_question", "db": db, "question_id": out["question_id"]}))
    assert shown["question"]["id"] == out["question_id"]


def test_full_forecast_tool_blocks_on_unscoreable_and_never_runs_agent(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    calls: list[str] = []
    monkeypatch.setattr("agent.forecast_stage.run_stage", lambda *a, **k: calls.append("x") or {})

    out = json.loads(forecast_ledger_tool({
        "action": "full_forecast", "db": db,
        "spec": {"title": "forecast", "resolution_criteria": "tbd"},
    }))
    assert out["success"] is False
    assert {e["field"] for e in out["issues"]} & {"title", "resolution_criteria"}
    assert calls == []  # nothing committed -> the chain never ran
    assert json.loads(forecast_ledger_tool({"action": "list_questions", "db": db}))["questions"] == []


# ── E1: duplicate routing on the laziest path ─────────────────────────────────


def _chain_agent(cli, monkeypatch):
    def fake_agent(led, qid, *, stage="update", **kw):
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} done"}
    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)


def test_full_forecast_routes_duplicate_to_existing(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)

    first = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": _casual_spec()}))
    assert first["success"] is True
    assert first["routed_to_existing"] is False

    # a second identical sentence must REFRESH the same question, not fork a rival
    second = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": _casual_spec()}))
    assert second["routed_to_existing"] is True
    assert second["question_id"] == first["question_id"]
    assert second["duplicate_of"]["id"] == first["question_id"]
    assert "refreshed that instead of forking a rival" in second["duplicate_note"]
    # the same stage chain still ran (onto the existing id), but no rival was created
    assert second["committed"] is True
    questions = json.loads(forecast_ledger_tool({"action": "list_questions", "db": db}))["questions"]
    assert len(questions) == 1


def test_full_forecast_allow_duplicate_forks_a_new_question(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)

    first = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": _casual_spec()}))
    # the escape hatch forces a NEW question, but the warning is surfaced either way
    second = json.loads(forecast_ledger_tool({
        "action": "full_forecast", "db": db, "spec": _casual_spec(), "allow_duplicate": True,
    }))
    assert second["routed_to_existing"] is False
    assert second["question_id"] != first["question_id"]
    assert "duplicate_warning" in second
    questions = json.loads(forecast_ledger_tool({"action": "list_questions", "db": db}))["questions"]
    assert len(questions) == 2


# ── E2: source-plan auto-apply on the auto path ───────────────────────────────


def test_full_forecast_auto_attaches_watches_when_none_given(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)

    out = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": _casual_spec()}))
    assert out["success"] is True
    # the spine feeds itself: watches attached so the scheduled refresh has sources
    assert out["watched_sources_attached"]
    assert len(out["watched_sources_attached"]) <= 3
    sources = json.loads(forecast_ledger_tool({
        "action": "list_watched_sources", "db": db, "scope_type": "question", "scope_ref": out["question_id"],
    }))
    assert len(sources["watched_sources"]) >= 1


def test_full_forecast_respects_evidence_gathering_off(tmp_path, monkeypatch):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)

    spec = dict(_casual_spec(), allow_evidence_gathering=False)
    out = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": spec}))
    assert out["success"] is True
    assert out["watched_sources_attached"] == []  # opt-out honored
    sources = json.loads(forecast_ledger_tool({
        "action": "list_watched_sources", "db": db, "scope_type": "question", "scope_ref": out["question_id"],
    }))
    assert sources["watched_sources"] == []


def test_full_forecast_watch_attach_failure_is_fail_open(tmp_path, monkeypatch):
    import forecasting.cli as cli
    import tools.forecasting_tool as ft
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("planner down")

    monkeypatch.setattr(ft, "plan_sources_for_question", boom)
    out = json.loads(forecast_ledger_tool({"action": "full_forecast", "db": db, "spec": _casual_spec()}))
    # a planner error never blocks the forecast — the chain still ran + committed
    assert out["success"] is True
    assert out["committed"] is True
    assert out["watched_sources_attached"] == []


# ── CLI: forecast onboard --auto ──────────────────────────────────────────────


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def test_cli_onboard_auto_parses_commits_and_chains(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(_casual_spec()), encoding="utf-8")
    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto"])
    args.func(args)

    out = capsys.readouterr().out
    assert "created forecast question" in out
    assert "committed forecast" in out
    assert seen == ["research", "base_rate", "update"]
    # a real committed snapshot landed
    ledger = ForecastLedger(db_path=db)
    q = ledger.list_questions()[0]
    assert ledger.get_current_snapshot(q.id) is not None


def test_cli_onboard_auto_refuses_unscoreable_prompt(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    calls: list[str] = []
    monkeypatch.setattr("agent.forecast_stage.run_stage", lambda *a, **k: calls.append("x") or {})
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", db, "onboard", "a vague wish with no criteria", "--auto"])
    with pytest.raises(SystemExit):
        args.func(args)
    err = capsys.readouterr().out
    assert "cannot auto-forecast" in err
    assert calls == []  # the gate refused before any stage ran


def test_cli_onboard_auto_routes_duplicate_to_existing(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(_casual_spec()), encoding="utf-8")

    def fake_agent(led, qid, *, stage="update", **kw):
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    parser = _parser()

    first = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto"])
    first.func(first)
    capsys.readouterr()  # drain

    # a second identical run must route onto the existing question, not fork a rival
    second = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto"])
    second.func(second)
    out = capsys.readouterr().out
    assert "routed to existing forecast" in out
    ledger = ForecastLedger(db_path=db)
    assert len(ledger.list_questions()) == 1  # no rival forked


def test_cli_onboard_auto_force_new_forks_a_rival(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(_casual_spec()), encoding="utf-8")

    def fake_agent(led, qid, *, stage="update", **kw):
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    parser = _parser()

    first = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto"])
    first.func(first)
    capsys.readouterr()

    second = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto", "--force-new"])
    second.func(second)
    out = capsys.readouterr().out
    assert "committing a new rival question anyway" in out
    ledger = ForecastLedger(db_path=db)
    assert len(ledger.list_questions()) == 2  # the escape hatch forked a new one


def test_cli_onboard_auto_attaches_watches(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(_casual_spec()), encoding="utf-8")

    def fake_agent(led, qid, *, stage="update", **kw):
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", db, "onboard", "--spec", str(spec_file), "--auto"])
    args.func(args)

    out = capsys.readouterr().out
    assert "attached" in out and "refreshes itself" in out
    ledger = ForecastLedger(db_path=db)
    q = ledger.list_questions()[0]
    assert ledger.list_watched_sources(scope_type="question", scope_ref=q.id, status=None)


# ── stage 0: the --auto criteria draft (one sentence in, a forecast out) ──────


def test_cli_onboard_auto_drafts_criteria_from_a_bare_sentence(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)
    monkeypatch.setattr(
        cli,
        "_draft_resolution_criteria",
        lambda spec, **kw: (
            "Resolves YES if the FOMC lowers the federal funds target range per the "
            "Federal Reserve's official statement on or before 2026-09-30; otherwise NO."
        ),
    )
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", db, "onboard", "Will the Fed cut rates by September?", "--auto"])
    args.func(args)

    out = capsys.readouterr().out
    assert "drafted resolution criteria" in out
    assert "created forecast question" in out
    assert "committed forecast" in out
    ledger = ForecastLedger(db_path=db)
    q = ledger.list_questions()[0]
    assert "FOMC" in q.resolution_criteria
    # the criteria-implied September deadline upgraded the end-of-year fallback
    assert (q.close_time or "").startswith("2026-09")


def test_cli_onboard_auto_criteria_flag_pins_without_drafting(tmp_path, monkeypatch, capsys):
    import forecasting.cli as cli
    db = str(tmp_path / "chain.db")
    _chain_agent(cli, monkeypatch)
    monkeypatch.setattr(
        cli, "_draft_resolution_criteria",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not draft when --criteria is given")),
    )
    parser = _parser()
    args = parser.parse_args([
        "forecast", "--db", db, "onboard", "Will CPI YoY fall below 3%?", "--auto",
        "--criteria", "Resolves YES if BLS CPI-U YoY is below 3.0% in any release on or before 2026-12-31; otherwise NO.",
    ])
    args.func(args)
    out = capsys.readouterr().out
    assert "drafted resolution criteria" not in out
    assert "created forecast question" in out


def test_draft_resolution_criteria_sanitizes_and_rejects_junk(monkeypatch):
    import forecasting.cli as cli
    import forecasting.quorum as quorum_mod
    from types import SimpleNamespace

    import superforecasting_agent.runtime.config as cfgmod

    monkeypatch.setattr(cfgmod, "load_config", lambda: {"model": {"default": "openai/gpt-5.5"}})
    spec = SimpleNamespace(title="Will X happen?", close_time="2026-09-30")

    def _factory(reply):
        def make(**kw):
            assert kw.get("toolsets") == (), "criteria draft must be tool-less"
            return lambda model, system, user: reply
        return make

    good = '"Resolves YES if X is confirmed per the official register on or before 2026-09-30; otherwise NO."\nextra line'
    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _factory(good))
    drafted = cli._draft_resolution_criteria(spec)
    assert drafted.startswith("Resolves YES if X")
    assert "extra line" not in drafted and '"' not in drafted[:1]

    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _factory("I cannot help with that."))
    assert cli._draft_resolution_criteria(spec) is None

    monkeypatch.setattr(quorum_mod, "make_aiagent_runner", _factory(""))
    assert cli._draft_resolution_criteria(spec) is None


# ── outcome-shape-aware chain: numeric questions get the model leg ────────────


def test_auto_stages_numeric_includes_model():
    from types import SimpleNamespace
    from forecasting.cli import AUTO_FORECAST_STAGES, auto_forecast_stages

    numeric = SimpleNamespace(outcome_space=SimpleNamespace(type="numeric"))
    binary = SimpleNamespace(outcome_space=SimpleNamespace(type="binary"))
    distribution = SimpleNamespace(outcome_space=SimpleNamespace(type="distribution"))
    weird = SimpleNamespace(outcome_space=None)

    assert auto_forecast_stages(numeric) == ("research", "base_rate", "model", "update")
    assert auto_forecast_stages(distribution) == ("research", "base_rate", "model", "update")
    assert auto_forecast_stages(binary) == AUTO_FORECAST_STAGES
    assert auto_forecast_stages(weird) == AUTO_FORECAST_STAGES


def test_chain_runs_model_stage_for_numeric_question(tmp_path, monkeypatch):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "chain.db"))
    from forecasting.models import OutcomeSpace

    q = ledger.create_question(
        title="What will May 2027 CPI-U YoY be?",
        resolution_criteria="Resolves to the BLS CPI-U YoY value in the May 2027 release.",
        outcome_space=OutcomeSpace(type="numeric", choices=[], units="percent YoY"),
    )
    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        _stage_side_effects(led, qid, stage)
        return {"final_response": f"{stage} ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    result = run_forecast_chain(ledger, q.id, max_iterations=3)
    assert seen == ["research", "base_rate", "model", "update"]
    assert [s["stage"] for s in result["stages"]] == ["research", "base_rate", "model", "update"]


def test_chain_explicit_stages_still_win(tmp_path, monkeypatch):
    import forecasting.cli as cli

    ledger = ForecastLedger(db_path=str(tmp_path / "chain.db"))
    from forecasting.models import OutcomeSpace

    q = ledger.create_question(
        title="What will Q3 2027 GDP growth be?",
        resolution_criteria="Resolves to the BEA advance estimate for Q3 2027 annualized growth.",
        outcome_space=OutcomeSpace(type="numeric", choices=[], units="percent"),
    )
    seen: list[str] = []

    def fake_agent(led, qid, *, stage="update", **kw):
        seen.append(stage)
        _stage_side_effects(led, qid, stage)  # research lands adequate evidence -> no adequacy re-run
        return {"final_response": "ok"}

    monkeypatch.setattr("agent.forecast_stage.run_stage", fake_agent)
    run_forecast_chain(ledger, q.id, max_iterations=3, stages=("research",))
    assert seen == ["research"], "an explicit stages argument must not be overridden"
