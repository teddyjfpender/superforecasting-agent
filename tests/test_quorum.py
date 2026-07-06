"""Tests for the quorum (model-diverse panel) core module."""

from __future__ import annotations

import json

import pytest

from forecasting.models import ValidationError
from forecasting.quorum import (
    QUORUM_PRESETS,
    _split_provider_model,
    apply_market_anchor_discipline,
    disagreement_signal,
    make_aiagent_runner,
    parse_judge_response,
    parse_panelist_response,
    resolve_configured_panel,
    resolve_connected_panel,
    resolve_models,
    run_quorum,
    validate_panel_models,
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


# ── adapter fixes: honest error surfacing + reasoning-trace salvage ───────────


class _FakeAgent:
    def __init__(self, result):
        self._result = result

    def run_conversation(self, user, system_message=None):
        return self._result


def _install_fake_agent(monkeypatch, result):
    import agent.agent_factory as af

    monkeypatch.setattr(af, "build_agent", lambda **_kw: _FakeAgent(result))


def test_runner_surfaces_real_agent_error(monkeypatch):
    # A non-retryable API failure (copilot 400 / gemini 429) sets failed/error and
    # leaves final_response empty; the runner must raise the REAL reason, not let it
    # be masked downstream as "agent protocol response is empty".
    _install_fake_agent(
        monkeypatch,
        {"final_response": None, "failed": True, "error": "HTTP 400: The requested model is not supported."},
    )
    runner = make_aiagent_runner(toolsets=())
    with pytest.raises(RuntimeError) as exc:
        runner("copilot:gpt-5.4", "sys", "user")
    assert "400" in str(exc.value) and "not supported" in str(exc.value)


def test_runner_salvages_json_from_reasoning_trace(monkeypatch):
    # A reasoning model emits the structured answer inside its thinking trace and
    # leaves the visible message as prose; the runner falls back to last_reasoning.
    _install_fake_agent(
        monkeypatch,
        {
            "final_response": "On balance I judge it fairly likely.",
            "last_reasoning": 'weighing paths… {"probability": 0.61, "crux": "turnout"}',
        },
    )
    runner = make_aiagent_runner(toolsets=())
    text = runner("gemini:gemini-2.5-flash", "sys", "user")
    forecast = parse_panelist_response(text, "gemini:gemini-2.5-flash")
    assert abs(forecast.probability - 0.61) < 1e-9


def test_runner_genuinely_empty_still_errors_honestly(monkeypatch):
    # No visible content AND no reasoning JSON → the runner returns "" and the parse
    # errors honestly. It must NEVER fabricate a number.
    _install_fake_agent(monkeypatch, {"final_response": "", "last_reasoning": ""})
    runner = make_aiagent_runner(toolsets=())
    text = runner("x:y", "sys", "user")
    assert text == ""
    with pytest.raises(ValidationError):
        parse_panelist_response(text, "x:y")


# ── configurable panel (QUORUM_PANEL_MODELS / QUORUM_JUDGE_MODEL) ─────────────


def test_configured_panel_resolves_and_validates():
    provs = [{"id": "openai-codex"}, {"id": "gemini"}]
    got = resolve_configured_panel(
        providers=provs,
        panel_models="openai-codex:gpt-5.5, gemini:gemini-2.5-flash",
        judge_model="openai-codex:gpt-5.5",
    )
    assert got == {
        "models": ["openai-codex:gpt-5.5", "gemini:gemini-2.5-flash"],
        "judge": "openai-codex:gpt-5.5",
    }
    # Unset key → None so the caller falls through to preset/connected resolution.
    assert resolve_configured_panel(providers=provs, panel_models=None, judge_model=None) is None


def test_configured_panel_names_non_callable_entry():
    provs = [{"id": "openai-codex"}]
    with pytest.raises(ValidationError) as exc:
        resolve_configured_panel(
            providers=provs,
            panel_models="openai-codex:gpt-5.5, copilot:gpt-5.4",
            judge_model=None,
        )
    assert "copilot:gpt-5.4" in str(exc.value)


def test_configured_panel_validates_the_judge_too():
    provs = [{"id": "openai-codex"}]
    with pytest.raises(ValidationError) as exc:
        resolve_configured_panel(
            providers=provs, panel_models="openai-codex:gpt-5.5", judge_model="copilot:gpt-5.4"
        )
    assert "copilot:gpt-5.4" in str(exc.value)


def test_configured_panel_fail_open_on_unknown_providers():
    # Detection unavailable → cannot prove non-callability → accept (fail open).
    got = resolve_configured_panel(providers=None, panel_models="anything:x", judge_model=None)
    assert got is not None and got["models"] == ["anything:x"]


def test_validate_panel_models_aggregator_serves_all():
    # An OpenRouter key serves any id, so every pinned entry passes.
    validate_panel_models(
        ["anthropic:claude-opus-4-8", "foo:bar"], providers=[{"id": "openrouter"}]
    )


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


def _make_concurrency_probe_runner():
    """Return (runner, get_max) where the runner records peak parallelism."""
    import threading
    import time

    lock = threading.Lock()
    state = {"live": 0, "max": 0}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.5, "rationale": "ok"})
        with lock:
            state["live"] += 1
            state["max"] = max(state["max"], state["live"])
        # Hold the slot long enough that genuinely-parallel dispatch overlaps.
        time.sleep(0.05)
        with lock:
            state["live"] -= 1
        return json.dumps({"probability": 0.4, "rationale": "r"})

    return runner, (lambda: state["max"])


def test_run_quorum_default_dispatches_whole_panel_in_one_wave():
    # Wave-5 P3: with no explicit max_concurrency an 8-model panel should fire
    # all 8 at once (capped at 8), not serialise into 4-wide waves.
    runner, get_max = _make_concurrency_probe_runner()
    models = [f"m/{i}" for i in range(8)]
    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=models,
        runner=runner,
        judge_model=None,
        trim=0,
    )
    assert len(res.ok_forecasts) == 8
    assert get_max() == 8  # == min(len(models), 8)


def test_run_quorum_auto_concurrency_caps_at_eight():
    # A panel wider than the cap must not exceed 8 concurrent workers.
    runner, get_max = _make_concurrency_probe_runner()
    models = [f"m/{i}" for i in range(12)]
    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=models,
        runner=runner,
        judge_model=None,
        trim=0,
    )
    assert len(res.ok_forecasts) == 12
    assert get_max() == 8


def test_run_quorum_explicit_max_concurrency_still_honoured():
    # An explicit override (incl. the sequential branch) is preserved.
    runner, get_max = _make_concurrency_probe_runner()
    models = [f"m/{i}" for i in range(8)]
    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=models,
        runner=runner,
        judge_model=None,
        trim=0,
        max_concurrency=1,
    )
    assert len(res.ok_forecasts) == 8
    assert get_max() == 1  # sequential branch — never overlaps


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
    # The QUORUM call path (jobs.types.quorum.execute) builds the runner with
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


# ── DELPHI: anonymous reveal → private second round (v1: 0 or 1 rounds) ─────────


def test_run_quorum_delphi_zero_matches_existing_path():
    # delphi_rounds=0 is the default un-delphi path: no delphi_audit rounds and a
    # committed number byte-identical to a run that never mentions delphi at all.
    table = {"a/b": 0.30, "c/d": 0.55, "e/f": 0.62}
    common = dict(
        question_title="Will X happen by 2027?",
        resolution_criteria="Resolves YES if X.",
        models=list(table),
        runner=_stub_runner(table),
        judge_model="anthropic/claude-opus-4-8",
        pool_method="trimmed_geomean_odds",
        trim=1,
    )
    baseline = run_quorum(**common)
    zero = run_quorum(**common, delphi_rounds=0)
    assert zero.delphi_rounds == 0
    assert zero.delphi_audit == {}
    assert "rounds" not in zero.delphi_audit
    assert zero.final_probability == baseline.final_probability


def test_run_quorum_delphi_runs_second_private_round():
    # Panelists forecast one number in the sealed round and a DIFFERENT number once
    # the anonymous "Delphi Revision Context" reveal is appended to their prompt.
    r1 = {"a/b": 0.30, "c/d": 0.40, "e/f": 0.50}
    r2 = {"a/b": 0.60, "c/d": 0.65, "e/f": 0.70}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {
                    "probability": 0.5,
                    "rationale": "judge synthesis",
                    "consensus": ["panel agrees X"],
                    "contradictions": ["A says hot, B says cold"],
                    "reasons_up": ["u"],
                    "reasons_down": ["d"],
                    "change_my_mind": ["cmm"],
                    "blind_spots": ["regime change unpriced"],
                }
            )
        if "Delphi Revision Context" in user:
            return _panelist_json(r2[model])
        return _panelist_json(r1[model])

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=list(r1),
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        trim=1,
        delphi_rounds=1,
    )
    assert res.delphi_rounds == 1
    # The FINAL forecasts are the revision (round-2) estimates, not the sealed ones.
    assert all(f.round_index == 2 for f in res.forecasts)
    assert sorted(round(f.probability, 3) for f in res.forecasts) == sorted(r2.values())
    # Each revision seat carries its own sealed-round prior.
    for f in res.forecasts:
        assert f.prior_probability == pytest.approx(r1[f.model], abs=1e-9)
    # The sealed round-1 estimates are preserved in the audit trail.
    rounds = res.delphi_audit["rounds"]
    assert rounds[0]["round_index"] == 1
    assert sorted(round(fc["probability"], 3) for fc in rounds[0]["forecasts"]) == sorted(
        r1.values()
    )
    assert rounds[1]["round_index"] == 2


def test_delphi_summary_is_anonymous():
    from forecasting.quorum import (
        JudgeSynthesis,
        ModelForecast,
        aggregate_panel_estimates,
        build_delphi_summary,
        disagreement_signal,
    )

    models = ("openai/gpt-5.5", "anthropic/claude-opus-4-8", "google/gemini-3")
    forecasts = [
        ModelForecast(
            model=models[0],
            probability=0.30,
            reasons_up=["rate cuts land"],
            reasons_down=["supply glut"],
            participant_id="p01",
        ),
        ModelForecast(
            model=models[1],
            probability=0.55,
            reasons_up=["demand shock"],
            reasons_down=["inventory overhang"],
            participant_id="p02",
        ),
        ModelForecast(
            model=models[2],
            probability=0.62,
            reasons_up=["policy tailwind"],
            reasons_down=["seasonality"],
            participant_id="p03",
        ),
    ]
    aggregation = aggregate_panel_estimates(
        [f.to_estimate() for f in forecasts], method="trimmed_geomean_odds", trim=0
    )
    disagreement = disagreement_signal([f.probability for f in forecasts])
    judge = JudgeSynthesis(
        probability=0.48,
        rationale="synthesis",
        contradictions=["p-high vs p-low on supply"],
        blind_spots=["nobody priced a regime change"],
    )
    summary = build_delphi_summary(
        forecasts=forecasts,
        aggregation=aggregation,
        disagreement=disagreement,
        judge=judge,
        supervisor_evidence=[],
    )
    # NO model identity leaks into the anonymous reveal.
    for model in models:
        assert model not in summary
    low = summary.lower()
    for fragment in ("gpt", "claude", "opus", "gemini", "openai", "anthropic", "google"):
        assert fragment not in low, fragment
    # It DOES carry the distribution summary, contradictions, and shared blind spots.
    assert "probability distribution" in summary
    assert "contradictions:" in summary
    assert "p-high vs p-low on supply" in summary
    assert "shared blind spots:" in summary
    assert "nobody priced a regime change" in summary


def test_self_fusion_delphi_uses_participant_ids_not_model_ids():
    # The `self` preset repeats a single model id, so the panel SEAT (p01..) must be
    # the stable identity and each seat's own round-1 prior must map into ITS revision
    # prompt (a model-keyed map would collapse all three seats into one).
    import re

    r1_by_seat = {1: 0.20, 2: 0.50, 3: 0.80}
    revision_prompts: list[str] = []

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {
                    "probability": 0.5,
                    "rationale": "s",
                    "contradictions": ["x"],
                    "blind_spots": ["y"],
                }
            )
        if "Delphi Revision Context" in user:
            revision_prompts.append(user)
            return _panelist_json(0.55)
        seat = int(re.search(r"Independent draft #(\d+)", user).group(1))
        return _panelist_json(r1_by_seat[seat])

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["x/y", "x/y", "x/y"],
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        self_fusion=True,
        trim=0,
        delphi_rounds=1,
        max_concurrency=1,
    )
    assert res.delphi_rounds == 1
    # Seats are the identity; the model id is shared across all three.
    assert [f.participant_id for f in res.forecasts] == ["p01", "p02", "p03"]
    assert {f.model for f in res.forecasts} == {"x/y"}
    # All three distinct sealed-round priors survive (proves seat-keyed, not model-keyed).
    assert sorted(round(f.prior_probability, 4) for f in res.forecasts) == [0.20, 0.50, 0.80]
    # Each prior is rendered as the panelist's own prior inside its revision prompt.
    assert len(revision_prompts) == 3
    joined = "\n".join(revision_prompts)
    for p in (0.20, 0.50, 0.80):
        assert f"probability: {p:.4f}" in joined


def test_delphi_rounds_rejects_more_than_one_for_v1():
    # v1 supports only 0 or 1 revision rounds; anything else is rejected up front.
    with pytest.raises(ValidationError):
        run_quorum(
            question_title="Q",
            resolution_criteria="R",
            models=["a/b"],
            runner=_stub_runner({"a/b": 0.4}),
            judge_model=None,
            delphi_rounds=2,
        )


# ── FIX A: preset resolution to ACTUALLY-connected providers ──────────────────


def _providers(*slugs, authed=True):
    return [{"id": s, "authenticated": authed} for s in slugs]


def test_resolve_connected_panel_multi_provider():
    # Two authed native providers with no OpenRouter -> a multi-model panel built
    # from each provider's own default model, addressed as provider:model.
    panel = resolve_connected_panel(
        "frontier",
        active_model="anthropic:claude-opus-4-7",
        active_provider="anthropic",
        providers=_providers("anthropic", "gemini"),
    )
    assert panel["rebuilt"] is True and panel["self_fusion"] is False
    assert len(panel["models"]) == 2
    # Every model is provider-qualified and callable — never a bare OpenRouter id.
    for m in panel["models"]:
        prov, bare = _split_provider_model(m)
        assert prov is not None and bare
    assert "anthropic" in panel["label"] and "gemini" in panel["label"]
    # The active provider seats the judge.
    assert panel["judge"].startswith("anthropic:")


def test_resolve_connected_panel_single_provider_self_fusion():
    # Exactly one native provider -> honest self-fusion labeling, never a fake panel.
    panel = resolve_connected_panel(
        "frontier",
        active_model="anthropic:claude-opus-4-7",
        active_provider="anthropic",
        providers=_providers("anthropic"),
        samples=3,
    )
    assert panel["rebuilt"] is True and panel["self_fusion"] is True
    assert panel["models"] == ["anthropic:claude-opus-4-7"] * 3
    assert "self-fusion" in panel["label"] and "second provider" in panel["label"]


def test_resolve_connected_panel_aggregator_keeps_preset():
    # An OpenRouter key can serve the hardcoded preset ids -> no rebuild.
    panel = resolve_connected_panel(
        "frontier",
        active_model="x/y",
        providers=_providers("openrouter", "anthropic"),
    )
    assert panel["rebuilt"] is False and panel["models"] is None
    # Detection unavailable (None) fails OPEN -> keep the preset verbatim.
    none_panel = resolve_connected_panel(
        "frontier", active_model="x/y", providers=None
    )
    # providers=None triggers live detection; in a sandbox that returns None or a
    # real picture. Either way the shape is well-formed and never crashes.
    assert "rebuilt" in none_panel


def test_resolve_connected_panel_no_key_failure_mode_impossible():
    # The reproduced live bug: 2 native providers, no OpenRouter, preset ids all
    # unreachable. After the fix every panelist id is provider-routable.
    panel = resolve_connected_panel(
        "budget",
        active_model="anthropic:claude-opus-4-7",
        providers=_providers("anthropic", "gemini", "deepseek"),
    )
    assert panel["rebuilt"] is True and panel["self_fusion"] is False
    assert len(panel["models"]) >= 2
    for m in panel["models"] + [panel["judge"]]:
        prov, _bare = _split_provider_model(m)
        assert prov is not None, f"{m} must resolve to a connected provider"


def test_split_provider_model():
    assert _split_provider_model("anthropic:claude-opus-4-7") == (
        "anthropic",
        "claude-opus-4-7",
    )
    # A bare id, or one whose colon is inside the model name, is NOT split.
    assert _split_provider_model("gpt-5.4") == (None, "gpt-5.4")
    assert _split_provider_model("anthropic/claude-3.5-sonnet:beta") == (
        None,
        "anthropic/claude-3.5-sonnet:beta",
    )


# ── FIX B: market-anchor discipline ───────────────────────────────────────────


def test_apply_market_anchor_discipline_pull_and_justify():
    # Unjustified over-deviation is pulled toward the market via the log-odds pool.
    pulled = apply_market_anchor_discipline(
        0.55, market_anchor=0.20, justification=None, threshold_pp=10.0
    )
    assert pulled["pull_applied"] is True
    assert 0.20 < pulled["probability"] < 0.55  # pulled toward the market
    assert "pulled toward market" in pulled["justification"]
    # A named edge justifies the deviation — no pull.
    kept = apply_market_anchor_discipline(
        0.55, market_anchor=0.20, justification="private supply-shock signal", threshold_pp=10.0
    )
    assert kept["pull_applied"] is False and kept["probability"] == 0.55
    # Within the threshold — no pull, no justification needed.
    small = apply_market_anchor_discipline(
        0.27, market_anchor=0.20, justification=None, threshold_pp=10.0
    )
    assert small["pull_applied"] is False and small["probability"] == 0.27
    # No anchor -> pass through untouched.
    none = apply_market_anchor_discipline(
        0.55, market_anchor=None, justification=None
    )
    assert none["probability"] == 0.55 and none["deviation_pp"] is None


def _anchor_runner(panel_prob, *, justification=None):
    def runner(model, system, user):
        if "JUDGE" in system:
            payload = {"probability": 0.5, "rationale": "j", "directional_confidence": "medium"}
            if justification is not None:
                payload["market_deviation_justification"] = justification
            return json.dumps(payload)
        return _panelist_json(panel_prob)

    return runner


def test_run_quorum_market_anchor_pull_unjustified():
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d", "e/f"],
        runner=_anchor_runner(0.55),  # panel ~0.55, market 0.20 -> 35pp, no justification
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    assert res.market_price == 0.20
    assert res.market_pull_applied is True
    assert res.committed_probability < 0.55  # verdict pulled back toward the market
    assert "pulled toward market" in (res.market_justification or "")
    json.dumps(res.to_dict())


def test_run_quorum_market_anchor_justified_no_pull():
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d", "e/f"],
        runner=_anchor_runner(0.55, justification="named edge the market has not priced"),
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    assert res.market_pull_applied is False
    assert res.market_justification == "named edge the market has not priced"


def test_run_quorum_self_fusion_pseudo_diversity_caveat():
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["x/y", "x/y", "x/y"],
        runner=_stub_runner({"x/y": 0.4}),
        judge_model=None,
        self_fusion=True,
    )
    assert res.pseudo_diversity_caveat and "pseudo-diversity" in res.pseudo_diversity_caveat
    assert res.to_dict()["pseudo_diversity_caveat"] == res.pseudo_diversity_caveat


def test_judge_prompt_carries_market_anchor_requirement():
    # The judge prompt names the market and requires an explicit justification key.
    captured = {}

    def runner(model, system, user):
        if "JUDGE" in system:
            captured["user"] = user
            return json.dumps({"probability": 0.5, "rationale": "j"})
        return _panelist_json(0.5)

    run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d"],
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.30,
        market_anchor_threshold_pp=10.0,
    )
    assert "market_deviation_justification" in captured["user"]
    assert "0.30" in captured["user"] or "0.3000" in captured["user"]


def test_resolve_connected_panel_zero_providers_fails_open():
    """Zero usable providers -> rebuilt=False (preset verbatim), never a
    self-fusion claiming '1 provider connected' (the deep-review catch)."""
    from forecasting.quorum import resolve_connected_panel

    res = resolve_connected_panel("budget", active_model="gpt-5.5", providers=[])
    assert res["rebuilt"] is False
    assert res["label"] is None
    assert res["models"] is None


# ── UPGRADE 1 — blind-then-reconcile panelist protocol ────────────────────────


def _blind_reconcile_runner(blind_p, reconciled_p, *, justification="named edge", capture=None):
    """A stub whose panelist RECONCILE turn (message carries '## Market
    Reconciliation') returns ``reconciled_p`` and whose BLIND turn returns
    ``blind_p``. Records every blind-turn user message into ``capture`` so a test
    can prove the anchor never reached phase 1."""

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {
                    "probability": 0.5,
                    "rationale": "j",
                    "directional_confidence": "medium",
                    "market_deviation_justification": justification,
                }
            )
        if "Market Reconciliation" in user:
            return json.dumps(
                {
                    "probability": reconciled_p,
                    "rationale": "reconciled",
                    "reconcile_reason": "converged toward the market",
                }
            )
        if capture is not None:
            capture.append(user)
        return json.dumps({"probability": blind_p, "rationale": "blind"})

    return runner


def test_blind_phase_never_sees_the_anchor():
    # UPGRADE 1: the anchor must PROVABLY never reach the blind (phase-1) prompt.
    blind_users: list[str] = []
    run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d", "e/f"],
        runner=_blind_reconcile_runner(0.60, 0.45, capture=blind_users),
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    assert blind_users, "expected at least one blind-turn prompt"
    for user in blind_users:
        assert "0.20" not in user and "0.2000" not in user
        assert "Outside-View Anchor" not in user
        assert "Market Reconciliation" not in user
        assert "market" not in user.lower() or "the market" not in user.lower()


def test_build_panelist_prompt_blind_omits_anchor():
    # Direct prompt-content assertion: with no anchor the blind prompt is anchor-free.
    from forecasting.quorum import build_panelist_prompt

    blind = build_panelist_prompt(
        question_title="Q", resolution_criteria="R", context_packet="", market_anchor=None
    )
    assert "Outside-View Anchor" not in blind["user"]
    # And the reconcile block DOES carry the anchor (phase 2 only).
    from forecasting.quorum import build_reconcile_block

    block = build_reconcile_block(blind_probability=0.6, market_anchor=0.2, threshold_pp=10.0)
    assert "0.2000" in block and "Market Reconciliation" in block and "reconcile_reason" in block


def test_blind_and_reconciled_numbers_both_recorded():
    # UPGRADE 1: BOTH numbers per panelist are recorded (blind + reconciled + reason).
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d", "e/f"],
        runner=_blind_reconcile_runner(0.60, 0.45),
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    for f in res.ok_forecasts:
        assert f.blind_probability == 0.60
        assert f.reconciled_probability == 0.45
        assert f.probability == 0.45  # committed == reconciled
        assert f.reconcile_reason == "converged toward the market"
    # The estimate metadata carries both, so the durable panel_run is honest.
    meta = res.panel_estimates()[0]["metadata"]
    assert meta["blind_probability"] == 0.60 and meta["reconciled_probability"] == 0.45


def test_reconciled_pool_routes_to_commit_blind_pool_is_independent():
    # UPGRADE 1: the pool/judge/commit operate on RECONCILED; the BLIND pool is
    # recorded alongside as the market-independent (orthogonality) signal.
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d", "e/f"],
        runner=_blind_reconcile_runner(0.60, 0.45),
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    assert round(res.reconciled_pool, 4) == 0.45  # reconciled numbers pooled
    assert round(res.blind_pool, 4) == 0.60  # blind numbers pooled, independently
    assert res.reconciled_pool == res.aggregation.aggregate_probability
    # blind_pool != reconciled_pool -> the orthogonality signal is computable.
    assert abs(res.blind_pool - res.market_price) > abs(res.reconciled_pool - res.market_price)
    d = res.to_dict()
    assert d["blind_pool"] == 0.6 and d["reconciled_pool"] == 0.45


def test_non_market_is_single_phase_unchanged():
    # UPGRADE 1: a non-market question (no anchor) pays for NO reconcile turn — one
    # runner call per panelist — and blind/reconciled pools stay None.
    calls: dict[str, int] = {}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.5, "rationale": "j"})
        assert "Market Reconciliation" not in user  # never a reconcile turn
        calls[model] = calls.get(model, 0) + 1
        return _panelist_json(0.4)

    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b", "c/d"],
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=None,  # non-market
    )
    assert calls == {"a/b": 1, "c/d": 1}  # exactly one call per panelist
    assert res.blind_pool is None and res.reconciled_pool is None
    assert res.to_dict()["blind_pool"] is None


def test_two_turn_single_session_seam_used_when_present():
    # UPGRADE 1: a runner exposing `.two_turn` gets the single-session path (one
    # blind turn, one reconcile turn) — the anchor enters ONLY via the follow-up.
    seen = {"blind_user": None, "reconcile_user": None}

    def runner(model, system, user):  # single-turn (judge + fallback)
        return json.dumps({"probability": 0.5, "rationale": "j", "market_deviation_justification": "edge"})

    def two_turn(model, system, blind_user, build_reconcile):
        seen["blind_user"] = blind_user
        blind_text = json.dumps({"probability": 0.7, "rationale": "blind"})
        reconcile_user = build_reconcile(blind_text)  # anchor introduced HERE
        seen["reconcile_user"] = reconcile_user
        return blind_text, json.dumps({"probability": 0.5, "rationale": "rec", "reconcile_reason": "held"})

    runner.two_turn = two_turn
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b"],
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        market_anchor=0.30,
        market_anchor_threshold_pp=10.0,
    )
    assert "Outside-View Anchor" not in seen["blind_user"]
    assert "0.3000" in seen["reconcile_user"] and "0.7000" in seen["reconcile_user"]
    assert res.ok_forecasts[0].blind_probability == 0.7
    assert res.ok_forecasts[0].reconciled_probability == 0.5
