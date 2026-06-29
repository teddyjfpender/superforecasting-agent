"""Tests for the quorum (model-diverse panel) core module."""

from __future__ import annotations

import json

import pytest

from forecasting.models import ValidationError
from forecasting.quorum import (
    QUORUM_PRESETS,
    disagreement_signal,
    parse_judge_response,
    parse_panelist_response,
    resolve_models,
    run_quorum,
)


def test_disagreement_bands():
    assert disagreement_signal([0.50, 0.52, 0.49])["disagreement_band"] == "calm"
    assert disagreement_signal([0.20, 0.80])["disagreement_band"] == "high"
    assert disagreement_signal([0.02, 0.97])["disagreement_band"] == "severe"
    single = disagreement_signal([0.4])
    assert single["disagreement_index"] == 0.0


def test_disagreement_logit_space_symmetry():
    # An order-of-magnitude split low in the range registers like one mid-range.
    low = disagreement_signal([0.01, 0.10])["sd_logit"]
    mid = disagreement_signal([0.30, 0.82])["sd_logit"]
    assert abs(low - mid) < 0.25


def test_resolve_models_presets_and_overrides():
    assert resolve_models(None, ["a/b", "c/d"]) == (["a/b", "c/d"], None)
    frontier, judge = resolve_models("frontier", None)
    assert len(frontier) == 2 and judge
    selfm, sjudge = resolve_models("self", None, active_model="x/y")
    assert selfm == ["x/y", "x/y", "x/y"] and sjudge == "x/y"
    with pytest.raises(ValidationError):
        resolve_models("self", None)  # no active model
    with pytest.raises(ValidationError):
        resolve_models("nope", None)


def _panelist_json(p: float) -> str:
    return "```json\n" + json.dumps(
        {
            "probability": p,
            "confidence_low": max(0.0, p - 0.15),
            "confidence_high": min(1.0, p + 0.15),
            "rationale": "because reasons",
            "reasons_up": ["a path up"],
            "reasons_down": ["a path down"],
            "change_my_mind": ["a load-bearing fact"],
            "crux": "the single biggest uncertainty",
        }
    ) + "\n```"


def test_parse_panelist_handles_fenced_json():
    f = parse_panelist_response(_panelist_json(0.37), "openai/gpt-5.5")
    assert f.probability == 0.37
    assert f.crux and f.reasons_up == ["a path up"]
    assert f.error is None


def test_parse_judge_response():
    raw = json.dumps(
        {
            "probability": 0.42,
            "rationale": "synthesis",
            "consensus": ["c"],
            "contradictions": ["x vs y"],
            "reasons_up": ["u"],
            "reasons_down": ["d"],
            "change_my_mind": ["cmm"],
            "blind_spots": ["nobody checked Z"],
        }
    )
    j = parse_judge_response(raw, "anthropic/claude-opus-4-8")
    assert j.probability == 0.42
    assert j.blind_spots == ["nobody checked Z"]
    assert j.judge_model == "anthropic/claude-opus-4-8"


def _stub_runner(table):
    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {
                    "probability": 0.41,
                    "rationale": "judge synthesis",
                    "consensus": ["panel agrees X"],
                    "contradictions": ["A says hot, B says cold"],
                    "reasons_up": ["u"],
                    "reasons_down": ["d"],
                    "change_my_mind": ["cmm"],
                    "blind_spots": ["regime change unpriced"],
                }
            )
        return _panelist_json(table.get(model, 0.5))

    return runner


def test_run_quorum_end_to_end():
    table = {"a/b": 0.30, "c/d": 0.55, "e/f": 0.62}
    res = run_quorum(
        question_title="Will X happen by 2027?",
        resolution_criteria="Resolves YES if X.",
        models=list(table),
        runner=_stub_runner(table),
        judge_model="anthropic/claude-opus-4-8",
        pool_method="trimmed_geomean_odds",
        trim=1,
    )
    assert 0.0 < res.aggregate_probability < 1.0
    assert res.disagreement["disagreement_band"] in {"calm", "moderate", "high", "severe"}
    assert res.judge and res.judge.probability == 0.41
    assert res.judge.blind_spots == ["regime change unpriced"]
    assert len(res.panel_estimates()) == 3
    # Round-trips to a JSON-serialisable dict (for the run-status payload).
    json.dumps(res.to_dict())


def test_run_quorum_tolerates_a_failed_panelist():
    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.5, "rationale": "ok"})
        if model == "bad/model":
            return "not json at all"
        return _panelist_json(0.4)

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["good/a", "bad/model", "good/b"],
        runner=runner,
        judge_model=None,
        trim=0,
    )
    errored = [f for f in res.forecasts if f.error]
    assert len(errored) == 1 and errored[0].model == "bad/model"
    assert len(res.ok_forecasts) == 2


def test_run_quorum_parallel_preserves_input_order():
    # Models finish in reverse order (later index returns faster), but results
    # must still line up with the input order.
    import time

    order = ["m/0", "m/1", "m/2", "m/3"]

    def runner(model, system, user):
        idx = int(model.split("/")[1])
        time.sleep((len(order) - idx) * 0.02)
        return json.dumps({"probability": 0.1 * (idx + 1), "rationale": "r"})

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=order,
        runner=runner,
        judge_model=None,
        trim=0,
        max_concurrency=4,
    )
    assert [f.model for f in res.forecasts] == order
    assert [round(f.probability, 3) for f in res.forecasts] == [0.1, 0.2, 0.3, 0.4]


def test_run_quorum_isolates_unexpected_panelist_error():
    # An unexpected error type (not just bad JSON) from one model must degrade
    # to an errored panelist, never abort the whole quorum.
    def runner(model, system, user):
        if model == "weird/model":
            raise KeyError("totally unexpected SDK error")
        return json.dumps({"probability": 0.4, "rationale": "r"})

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["weird/model", "good/model"],
        runner=runner,
        judge_model=None,
        trim=0,
    )
    errored = [f for f in res.forecasts if f.error]
    assert len(errored) == 1 and "KeyError" in errored[0].error
    assert len(res.ok_forecasts) == 1


def test_run_quorum_all_failed_raises():
    def runner(model, system, user):
        return "garbage"

    with pytest.raises(ValidationError):
        run_quorum(
            question_title="Q",
            resolution_criteria="R",
            models=["a/b"],
            runner=runner,
            judge_model=None,
        )


def test_presets_have_required_keys():
    for name, spec in QUORUM_PRESETS.items():
        assert "description" in spec
        assert "models" in spec


def test_disagreement_error_relationship_detects_positive_link():
    from forecasting.quorum_analysis import disagreement_error_relationship, pearson

    # Disagreement rises with error → positive correlation, interpretation flags it.
    pairs = [
        {"disagreement_index": 0.05, "brier": 0.02},
        {"disagreement_index": 0.20, "brier": 0.10},
        {"disagreement_index": 0.50, "brier": 0.18},
        {"disagreement_index": 0.80, "brier": 0.30},
    ]
    rel = disagreement_error_relationship(pairs)
    assert rel["n"] == 4
    assert rel["correlation"] > 0.9
    assert "calm" in rel["bands"] and "severe" in rel["bands"]
    assert "widen the band" in rel["interpretation"]
    assert pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) is None  # zero variance


def test_disagreement_error_relationship_empty():
    from forecasting.quorum_analysis import disagreement_error_relationship

    rel = disagreement_error_relationship([])
    assert rel["n"] == 0 and rel["correlation"] is None


def test_disagreement_band_agrees_with_index():
    # The stored index and band must never contradict — the desk recomputes the
    # band from the index, so a boundary case like [0.3, 0.7] must be stable.
    from forecasting.panel import _disagreement_band, disagreement_signal

    for ps in ([0.3, 0.7], [0.2, 0.8], [0.45, 0.55], [0.1, 0.9], [0.5, 0.5]):
        d = disagreement_signal(ps)
        assert d["disagreement_band"] == _disagreement_band(d["disagreement_index"])


def _install_fake_run_agent(monkeypatch, sleep_s, response="ok-response"):
    # make_aiagent_runner constructs panelists via agent.agent_factory.build_agent
    # (the single resolve->construct path), so patch that seam.
    import time

    class FakeAIAgent:
        def __init__(self, **kwargs):
            pass

        def run_conversation(self, user_message, system_message=None):
            time.sleep(sleep_s)
            return {"final_response": response}

    import agent.agent_factory as _af

    monkeypatch.setattr(_af, "build_agent", lambda **kwargs: FakeAIAgent())


def test_make_aiagent_runner_times_out_a_hung_model(monkeypatch):
    from forecasting.quorum import make_aiagent_runner

    _install_fake_run_agent(monkeypatch, sleep_s=2.0)
    runner = make_aiagent_runner(timeout=0.15)
    with pytest.raises(RuntimeError, match="timed out"):
        runner("slow/model", "system", "user")


def test_make_aiagent_runner_returns_within_timeout(monkeypatch):
    from forecasting.quorum import make_aiagent_runner

    _install_fake_run_agent(monkeypatch, sleep_s=0.0, response="fast")
    runner = make_aiagent_runner(timeout=5)
    assert runner("fast/model", "system", "user") == "fast"


def test_run_quorum_records_timed_out_panelist_as_error(monkeypatch):
    # A per-model timeout in the production runner surfaces as an errored
    # panelist, and the quorum still completes on the survivors.
    import json as _json

    from forecasting.quorum import run_quorum

    def runner(model, system, user):
        if model == "slow/model":
            raise RuntimeError("model slow/model timed out after 0.1s")
        return _json.dumps({"probability": 0.4, "rationale": "r"})

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["slow/model", "good/model"],
        runner=runner,
        judge_model=None,
        trim=0,
    )
    errored = [f for f in res.forecasts if f.error]
    assert len(errored) == 1 and "timed out" in errored[0].error
    assert len(res.ok_forecasts) == 1


# ── FOREKNOWLEDGE GUARD: cutoff-gated panelist toolset (the leak fix) ───────────


def _tool_names_for(toolsets):
    """Resolve a toolset list to its concrete tool names via the real registry.

    Mirrors tests/forecasting/test_market_nightly_forecaster.py — the toolset the
    panelist is built with is only a leak guard if it RESOLVES to a registry with no
    web_search / forecast_ledger. So assert against get_tool_definitions, not the
    string list.
    """

    from model_tools import get_tool_definitions

    defs = get_tool_definitions(enabled_toolsets=list(toolsets), quiet_mode=True)
    names = set()
    for d in defs:
        if isinstance(d, dict):
            fn = d.get("function") if isinstance(d.get("function"), dict) else d
            name = fn.get("name")
            if name:
                names.add(name)
    return names


def test_resolve_panelist_toolsets_historical_is_closed_book():
    from forecasting.quorum import resolve_panelist_toolsets

    # A HISTORICAL evidence_cutoff (a backtest / replay snapshot well in the past)
    # must yield an EMPTY toolset: no web (no fresh post-cutoff search) and no
    # forecasting (no forecast_ledger.import_source_evidence fetch of the now-known
    # source value).
    ts = resolve_panelist_toolsets("2020-01-01T00:00:00Z")
    assert ts == ()
    names = _tool_names_for(ts)
    assert "web_search" not in names, names
    assert "web_extract" not in names, names
    assert "forecast_ledger" not in names, names
    for forbidden in ("import_source_evidence", "update_forecast", "create_question", "record_panel"):
        assert forbidden not in names, names


def test_resolve_panelist_toolsets_live_is_research_only():
    from forecasting.quorum import resolve_panelist_toolsets

    # A LIVE cutoff (None == no cutoff) must yield web research ONLY — web_search is
    # present so the panelist can research the open question, but forecast_ledger
    # (and thus import_source_evidence + every ledger-write action) is absent: the
    # quorum JOB aggregates + records, never the panelist.
    for cutoff in (None, ""):
        ts = resolve_panelist_toolsets(cutoff)
        assert ts == ("web",)
        names = _tool_names_for(ts)
        assert "web_search" in names, names
        assert "forecast_ledger" not in names, names
        for forbidden in ("import_source_evidence", "update_forecast", "create_question", "record_panel"):
            assert forbidden not in names, names


def test_make_aiagent_runner_threads_cutoff_into_panelist_toolset(monkeypatch):
    # The QUORUM call path (quorum_jobs.execute_job) builds the runner with
    # evidence_cutoff; assert that flows into the build_agent enabled_toolsets so the
    # leak guard is actually in force on the constructed panelist.
    from forecasting.quorum import make_aiagent_runner

    captured = {}

    class FakeAIAgent:
        def run_conversation(self, user_message, system_message=None):
            return {"final_response": json.dumps({"probability": 0.4, "rationale": "r"})}

    import agent.agent_factory as _af

    def _fake_build_agent(**kwargs):
        captured["enabled_toolsets"] = kwargs.get("enabled_toolsets")
        return FakeAIAgent()

    monkeypatch.setattr(_af, "build_agent", _fake_build_agent)

    # HISTORICAL cutoff -> empty (closed-book).
    runner = make_aiagent_runner(evidence_cutoff="2020-01-01T00:00:00Z")
    runner("m/x", "system", "user")
    assert captured["enabled_toolsets"] == []
    hist_names = _tool_names_for(captured["enabled_toolsets"])
    assert "web_search" not in hist_names and "forecast_ledger" not in hist_names

    # LIVE cutoff -> web-only research.
    runner = make_aiagent_runner(evidence_cutoff=None)
    runner("m/x", "system", "user")
    assert captured["enabled_toolsets"] == ["web"]
    live_names = _tool_names_for(captured["enabled_toolsets"])
    assert "web_search" in live_names and "forecast_ledger" not in live_names


def test_make_aiagent_runner_default_is_backward_safe(monkeypatch):
    # Without evidence_cutoff the historical default toolsets are preserved (no
    # behavior change for callers that do not pass the guard).
    from forecasting.quorum import make_aiagent_runner

    captured = {}

    class FakeAIAgent:
        def run_conversation(self, user_message, system_message=None):
            return {"final_response": json.dumps({"probability": 0.4, "rationale": "r"})}

    import agent.agent_factory as _af

    def _fake_build_agent(**kwargs):
        captured["enabled_toolsets"] = kwargs.get("enabled_toolsets")
        return FakeAIAgent()

    monkeypatch.setattr(_af, "build_agent", _fake_build_agent)

    runner = make_aiagent_runner()
    runner("m/x", "system", "user")
    assert captured["enabled_toolsets"] == ["forecasting", "web"]
