"""Tests for the quorum (model-diverse panel) core module."""

from __future__ import annotations

import json

import pytest

from forecasting.models import ValidationError
from forecasting.quorum import (
    _POOL_SHRINK_C,
    _POOL_SHRINK_CALM_VAR,
    _POOL_SHRINK_FLOOR,
    QUORUM_PRESETS,
    _split_provider_model,
    apply_market_anchor_discipline,
    build_panelist_prompt,
    build_reconcile_block,
    cap_trials_by_calls,
    disagreement_signal,
    estimate_quorum_calls,
    make_aiagent_runner,
    parse_judge_response,
    parse_panelist_response,
    resolve_configured_panel,
    resolve_connected_panel,
    resolve_models,
    resolve_trial_count,
    run_quorum,
    shrink_pool_toward_anchor,
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


def test_resolve_panelist_toolsets_live_is_research_only(web_backend_available):
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


def test_make_aiagent_runner_threads_cutoff_into_panelist_toolset(monkeypatch, web_backend_available):
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


# ── BLF A1 — linguistic belief state (the trajectory) ─────────────────────────


def test_belief_trajectory_records_the_flip_and_commits_last_belief():
    # BLF A1: the panelist re-emits its belief after each evidence step; the
    # trajectory captures (step, p_t, moved_by), and the FINAL belief is the commit —
    # even when a decoy top-level probability disagrees.
    resp = "```json\n" + json.dumps(
        {
            "probability": 0.30,  # DECOY: the last belief must win over this
            "rationale": "walked the evidence",
            "reasons_up": ["u"],
            "reasons_down": ["d"],
            "change_my_mind": ["c"],
            "crux": "the crux",
            "belief_trajectory": [
                {
                    "step": 1,
                    "probability": 0.55,
                    "moved_by": "prior — reference-class base rate",
                    "confidence": "low",
                    "open_questions": ["turnout?"],
                },
                {"step": 2, "probability": 0.58, "moved_by": "a fresh poll nudged it up"},
                {
                    "step": 3,
                    "probability": 0.18,
                    "moved_by": "the incumbent withdrew — flips the base case",
                    "confidence": "high",
                },
            ],
        }
    ) + "\n```"
    f = parse_panelist_response(resp, "x/y")
    # The trajectory is captured, in order, with the mover on the flip step.
    assert [s["step"] for s in f.belief_trajectory] == [1, 2, 3]
    flip = f.belief_trajectory[2]
    assert flip["probability"] == 0.18 and "withdrew" in flip["moved_by"]
    assert f.belief_trajectory[0]["open_questions"] == ["turnout?"]
    # The final belief IS the commit — the decoy 0.30 loses.
    assert f.probability == 0.18
    # It rides the estimate metadata (the durable panel_estimates.metadata column).
    assert f.to_estimate()["metadata"]["belief_trajectory"] == f.belief_trajectory


def test_absent_trajectory_leaves_commit_and_metadata_backward_compatible():
    # A legacy/stub response with no belief_trajectory: the committed number is the
    # top-level probability and the trajectory metadata is an empty list.
    f = parse_panelist_response(_panelist_json(0.42), "x/y")
    assert f.probability == 0.42
    assert f.belief_trajectory == []
    meta = f.to_estimate()["metadata"]
    assert meta["belief_trajectory"] == [] and meta["trials"] == []
    assert meta["trial_shrinkage"] is None


def test_blind_belief_trajectory_is_anchor_free_reconcile_adds_anchor_step():
    # BLF A1 orthogonality: the belief state is requested in the blind prompt with NO
    # anchor anywhere; the anchor step is introduced only by the reconcile block.
    blind = build_panelist_prompt(
        question_title="Q", resolution_criteria="R", context_packet="", market_anchor=None
    )
    assert "belief_trajectory" in blind["user"]
    assert "anchor" not in blind["user"].lower() and "market" not in blind["user"].lower()
    # A blind response's trajectory carries only evidence movers — never the anchor.
    blind_resp = json.dumps(
        {
            "probability": 0.6,
            "belief_trajectory": [
                {"step": 1, "probability": 0.5, "moved_by": "prior"},
                {"step": 2, "probability": 0.6, "moved_by": "a fresh poll"},
            ],
        }
    )
    bf = parse_panelist_response(blind_resp, "x/y")
    assert all("market" not in (s["moved_by"] or "").lower() for s in bf.belief_trajectory)
    # The reconcile block (phase 2) asks to APPEND an anchor step and re-emit.
    block = build_reconcile_block(blind_probability=0.6, market_anchor=0.2, threshold_pp=10.0)
    assert "belief_trajectory" in block and "anchor" in block.lower()


# ── BLF A2 — multi-trial per panelist (variance-shrunk logit pool) ────────────


def _trial_varying_runner(reconciled_by_trial, *, blind_p=0.75):
    """A stub whose per-model RECONCILE turn returns a rotating value across trials
    (so a seat's K draws diverge), each with a one-step belief trajectory; the blind
    turn returns a constant. Judge (if any) is non-overriding."""

    import threading

    lock = threading.Lock()
    counts: dict[str, int] = {}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {"probability": 0.5, "rationale": "j", "market_deviation_justification": ""}
            )
        if "Market Reconciliation" in user:
            with lock:
                n = counts.get(model, 0)
                counts[model] = n + 1
            p = reconciled_by_trial[n % len(reconciled_by_trial)]
            return json.dumps(
                {
                    "probability": p,
                    "rationale": "reconciled",
                    "reconcile_reason": "converged",
                    "belief_trajectory": [
                        {"step": 1, "probability": p, "moved_by": "outside-view anchor"}
                    ],
                }
            )
        return json.dumps({"probability": blind_p, "rationale": "blind"})

    return runner


def _rotating_runner(values_by_model):
    """Non-market single-phase stub: each model's committed probability rotates
    across its trials so a seat's draws diverge."""

    import threading

    lock = threading.Lock()
    counts: dict[str, int] = {}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.5, "rationale": "j"})
        with lock:
            n = counts.get(model, 0)
            counts[model] = n + 1
        vals = values_by_model[model]
        return _panelist_json(vals[n % len(vals)])

    return runner


def test_multi_trial_variance_shrinks_pooled_toward_anchor():
    # BLF A2: K=3 divergent trials pool as a James–Stein shrunken logit mean toward
    # the anchor (α<1); measurably closer to the anchor than the unshrunk mean.
    from forecasting.bayes_toolkit import inv_logit, logit

    reconciled = [0.70, 0.80, 0.90]
    anchor = 0.20
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b"],
        runner=_trial_varying_runner(reconciled),
        judge_model=None,
        market_anchor=anchor,
        market_anchor_threshold_pp=100.0,  # keep the terminal discipline out of it
        trials=3,
    )
    seat = res.ok_forecasts[0]
    plain_mean = inv_logit(sum(logit(p) for p in reconciled) / len(reconciled))
    assert seat.trial_shrinkage["survivors"] == 3
    assert seat.trial_shrinkage["alpha"] < 1.0  # variance triggered the shrink
    # Pooled sits strictly between the trials' own mean and the anchor.
    assert anchor < seat.probability < plain_mean
    assert abs(seat.probability - anchor) < abs(plain_mean - anchor)


def test_zero_variance_trials_do_not_shrink_and_k1_is_identity():
    # Contrast: identical trials (s²=0) → α=1, no shrink toward the anchor; and K=1
    # is a strict passthrough with NO trial machinery (byte-identical to pre-A2).
    res3 = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b"],
        runner=_trial_varying_runner([0.80, 0.80, 0.80]),
        judge_model=None,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,
        trials=3,
    )
    seat3 = res3.ok_forecasts[0]
    assert seat3.trial_shrinkage["alpha"] == 1.0
    assert abs(seat3.probability - 0.80) < 1e-9  # unmoved by the anchor

    res1 = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b"],
        runner=_trial_varying_runner([0.70, 0.80, 0.90]),
        judge_model=None,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,
        trials=1,
    )
    seat1 = res1.ok_forecasts[0]
    assert seat1.trial_shrinkage is None and seat1.trials == []
    assert abs(seat1.probability - 0.70) < 1e-9  # the single draw, unpooled


def test_trial_divergence_widens_the_disagreement_index():
    # BLF A2: the FULL trial sample (not just the pooled seats) feeds the
    # disagreement index, so a divergent trial widens the measured spread.
    from forecasting.bayes_toolkit import inv_logit, logit

    vals = {"a/m": [0.10, 0.40, 0.70], "b/m": [0.30, 0.60, 0.90]}
    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["a/m", "b/m"],
        runner=_rotating_runner(vals),
        judge_model=None,
        trim=0,
        trials=3,
    )
    full = [p for seat in vals.values() for p in seat]
    assert (
        res.disagreement["disagreement_index"]
        == disagreement_signal(full)["disagreement_index"]
    )
    pooled = [
        inv_logit(sum(logit(p) for p in seat) / len(seat)) for seat in vals.values()
    ]
    assert (
        res.disagreement["disagreement_index"]
        > disagreement_signal(pooled)["disagreement_index"]
    )


def test_multi_trial_seat_labels_partial_survivors_like_a_degraded_panel():
    # BLF A2 honest-labeling: a 1-of-3-trials survivor seat still commits its
    # survivor's number but is LABELED degraded; the whole quorum is NOT degraded
    # because a second seat survived intact.
    import threading

    lock = threading.Lock()
    counts: dict[str, int] = {}

    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps({"probability": 0.5, "rationale": "j"})
        with lock:
            n = counts.get(model, 0)
            counts[model] = n + 1
        if model == "flaky/m" and n >= 1:  # trials 2 and 3 fail for this seat
            return "not json at all"
        return _panelist_json(0.4)

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=["good/m", "flaky/m"],
        runner=runner,
        judge_model=None,
        trim=0,
        trials=3,
    )
    seats = {f.model: f for f in res.ok_forecasts}
    flaky = seats["flaky/m"]
    assert flaky.error is None and abs(flaky.probability - 0.4) < 1e-9
    assert flaky.trial_shrinkage["n_trials"] == 3
    assert flaky.trial_shrinkage["survivors"] == 1
    assert flaky.trial_shrinkage["degraded"] is True
    # Two seats survived → the quorum itself is not degraded.
    assert res.degraded is False


def test_multi_trial_metadata_round_trips():
    # BLF A1+A2 schema round-trip: the pooled seat's belief trajectory + per-trial
    # provenance ride the estimate metadata and survive a JSON round-trip (the
    # panel_estimates.metadata column is a JSON blob — no schema migration).
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="Resolves YES if X.",
        models=["a/b"],
        runner=_trial_varying_runner([0.70, 0.80, 0.90]),
        judge_model=None,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,
        trials=3,
    )
    meta = res.panel_estimates()[0]["metadata"]
    assert meta["trial_shrinkage"]["n_trials"] == 3
    assert [t["trial"] for t in meta["trials"]] == [1, 2, 3]
    # The pooled seat's headline trajectory is the representative trial's.
    assert meta["belief_trajectory"] == res.ok_forecasts[0].belief_trajectory
    assert json.loads(json.dumps(meta)) == meta
    # The whole result still serialises for the run-status payload.
    json.dumps(res.to_dict())


# ── BLF A2 — trial-count resolution + cost bounding ──────────────────────────


def test_resolve_trial_count_is_impact_driven():
    class _Q:
        def __init__(self, impact):
            self.impact = impact

    assert resolve_trial_count(_Q("high"))[0] == 3
    assert resolve_trial_count(_Q("medium"))[0] == 1
    assert resolve_trial_count(_Q(None))[0] == 1
    # An explicit override wins over impact.
    assert resolve_trial_count(_Q("high"), override=2)[0] == 2
    # Configurable defaults.
    assert resolve_trial_count(_Q("high"), high_impact_trials=5)[0] == 5


def test_estimate_quorum_calls_scales_with_trials():
    # trials=1 is byte-identical; K multiplies only the panelist calls, not the judge.
    assert estimate_quorum_calls(model_count=3, delphi_rounds=0) == 4
    assert estimate_quorum_calls(model_count=3, delphi_rounds=0, trials=3) == 3 * 3 + 1
    assert (
        estimate_quorum_calls(model_count=2, delphi_rounds=1, trials=2)
        == (2 * 2 + 1) * 2
    )


def test_cap_trials_by_calls_bounds_to_budget():
    # frontier = 2 models + judge → 2k+1 calls. max_calls=8 fits k=3 (7), not k=4 (9).
    k, note = cap_trials_by_calls(
        preset="frontier", delphi_rounds=0, samples=3, trials=5, max_calls=8
    )
    assert k == 3 and note and "→3" in note
    # Already-fitting request is untouched (no note).
    k2, note2 = cap_trials_by_calls(
        preset="frontier", delphi_rounds=0, samples=3, trials=2, max_calls=8
    )
    assert k2 == 2 and note2 is None
    # Never drops below 1, even under a pathological cap.
    k3, _ = cap_trials_by_calls(
        preset="frontier", delphi_rounds=0, samples=3, trials=5, max_calls=1
    )
    assert k3 == 1


# ── BLF A3 — variance-adaptive cross-model pool shrinkage ─────────────────────
#
# A3 shrinks the DEFAULT cross-model pool (the aggregate AFTER A2's per-panelist
# trial pooling) toward the outside-view anchor as a continuous function of
# CROSS-PANELIST disagreement: the noisier the panel, the harder it leans on the
# anchor. It mirrors A2's James–Stein family (α=max(f,1−c·s²)) one layer up — one
# shrinkage philosophy at both layers — with a calm dead-zone so a calm panel (and
# an anchorless question) is a STRICT no-op, which is the default-ON safety case.


def test_shrink_pool_toward_anchor_helper_noops_and_engages():
    # The pure helper: no anchor → strict no-op; calm variance → strict no-op;
    # noisy variance → shrink toward the anchor with α<1, full provenance recorded.
    from forecasting.bayes_toolkit import inv_logit, logit

    noop = shrink_pool_toward_anchor(0.70, anchor=None, var_logit=5.0)
    assert noop["probability"] == 0.70 and noop["alpha"] == 1.0 and noop["shrunk"] is False

    calm = shrink_pool_toward_anchor(0.70, anchor=0.20, var_logit=_POOL_SHRINK_CALM_VAR)
    assert calm["probability"] == 0.70 and calm["alpha"] == 1.0 and calm["shrunk"] is False

    s2 = _POOL_SHRINK_CALM_VAR + 1.0
    noisy = shrink_pool_toward_anchor(0.70, anchor=0.20, var_logit=s2)
    expect_alpha = max(_POOL_SHRINK_FLOOR, 1.0 - _POOL_SHRINK_C * (s2 - _POOL_SHRINK_CALM_VAR))
    assert abs(noisy["alpha"] - expect_alpha) < 1e-12 and noisy["shrunk"] is True
    expect_p = inv_logit(expect_alpha * logit(0.70) + (1.0 - expect_alpha) * logit(0.20))
    assert abs(noisy["probability"] - expect_p) < 1e-12
    assert 0.20 < noisy["probability"] < 0.70  # strictly between anchor and pool


def test_shrink_pool_is_continuous_at_the_calm_edge():
    # NO CLIFF: just below the calm-band edge is a strict no-op; nudging just above
    # engages but moves the pool by an infinitesimal amount, not a jump.
    pool, anchor = 0.70, 0.20
    below = shrink_pool_toward_anchor(pool, anchor=anchor, var_logit=_POOL_SHRINK_CALM_VAR - 1e-9)
    at = shrink_pool_toward_anchor(pool, anchor=anchor, var_logit=_POOL_SHRINK_CALM_VAR)
    above = shrink_pool_toward_anchor(pool, anchor=anchor, var_logit=_POOL_SHRINK_CALM_VAR + 1e-6)
    assert below["probability"] == pool and below["alpha"] == 1.0
    assert at["probability"] == pool and at["alpha"] == 1.0
    assert above["alpha"] < 1.0  # engages just past the edge
    assert abs(above["probability"] - pool) < 1e-3  # continuous, not a cliff


def test_pool_shrinks_toward_anchor_on_contested_panel():
    # THE PAYOFF: a contested market panel commits measurably CLOSER to the anchor
    # than today's (pre-A3) pool, and α<1 with full provenance.
    table = {"a/b": 0.90, "c/d": 0.60}
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="R",
        models=list(table),
        runner=_stub_runner(table),
        judge_model=None,
        trim=0,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,  # isolate A3 from the discipline pull
    )
    ps = res.pool_shrinkage
    assert ps is not None and ps["shrunk"] is True and ps["alpha"] < 1.0
    assert ps["anchor_source"] == "market" and ps["anchor"] == 0.20
    pre = res.aggregation.aggregate_probability  # the pre-A3 pool
    assert 0.20 < res.committed_probability < pre
    assert abs(res.committed_probability - 0.20) < abs(pre - 0.20)
    json.dumps(res.to_dict())


def test_calm_panel_pool_shrink_is_strict_noop():
    # THE SAFETY CASE: a CALM panel (disagreement below the calm-band edge) with an
    # anchor is a strict no-op — α≡1, committed bit-identical to the pre-A3 pool.
    table = {"a/b": 0.55, "c/d": 0.56, "e/f": 0.54}  # tight cluster → calm
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="R",
        models=list(table),
        runner=_stub_runner(table),
        judge_model=None,
        trim=0,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,
    )
    assert res.disagreement["disagreement_band"] == "calm"
    ps = res.pool_shrinkage
    assert ps["alpha"] == 1.0 and ps["shrunk"] is False
    # Bit-identical to the pre-A3 pool: A3 did not move a calm number.
    assert res.committed_probability == res.aggregation.aggregate_probability


def test_no_anchor_pool_shrink_is_noop():
    # No market link and no recorded prior → no anchor → strict no-op, and
    # pool_shrinkage is None (byte-compatible run-status payload). The panel is
    # contested, proving it is the ABSENT anchor — not calm — that no-ops A3.
    table = {"a/b": 0.90, "c/d": 0.60}
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="R",
        models=list(table),
        runner=_stub_runner(table),
        judge_model=None,
        trim=0,
    )
    assert res.pool_shrinkage is None
    assert res.committed_probability == res.aggregation.aggregate_probability


def test_outside_view_prior_is_the_anchor_when_no_market():
    # anchor = market where linked, ELSE the recorded outside-view prior. A contested
    # NON-market panel with a recorded prior shrinks toward that prior; and when a
    # market IS present it takes precedence over the prior.
    table = {"a/b": 0.90, "c/d": 0.60}
    common = dict(
        question_title="Will X?",
        resolution_criteria="R",
        models=list(table),
        runner=_stub_runner(table),
        judge_model=None,
        trim=0,
        market_anchor_threshold_pp=100.0,
    )
    prior_only = run_quorum(**common, outside_view_prior=0.20)
    ps = prior_only.pool_shrinkage
    assert ps["anchor_source"] == "outside_view_prior" and ps["anchor"] == 0.20
    assert ps["shrunk"] is True
    pre = prior_only.aggregation.aggregate_probability
    assert abs(prior_only.committed_probability - 0.20) < abs(pre - 0.20)

    # Market wins when both are supplied.
    both = run_quorum(**common, market_anchor=0.35, outside_view_prior=0.20)
    assert both.pool_shrinkage["anchor_source"] == "market"
    assert both.pool_shrinkage["anchor"] == 0.35


def test_pool_shrink_alpha_matches_the_documented_formula():
    # Provenance rigor: the recorded α and s² match the documented functional form
    # exactly, and the committed number is the logit-space blend at that α.
    from forecasting.bayes_toolkit import inv_logit, logit

    table = {"a/b": 0.90, "c/d": 0.60}
    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="R",
        models=list(table),
        runner=_stub_runner(table),
        judge_model=None,
        trim=0,
        market_anchor=0.20,
        market_anchor_threshold_pp=100.0,
    )
    ps = res.pool_shrinkage
    s2 = res.disagreement["sd_logit"] ** 2
    expect_alpha = max(
        _POOL_SHRINK_FLOOR, 1.0 - _POOL_SHRINK_C * max(0.0, s2 - _POOL_SHRINK_CALM_VAR)
    )
    assert abs(ps["alpha"] - expect_alpha) < 1e-6
    assert abs(ps["var_logit"] - s2) < 1e-6
    assert ps["pre_shrink_pool"] == round(res.aggregation.aggregate_probability, 6)
    pre = res.aggregation.aggregate_probability
    expect_p = inv_logit(expect_alpha * logit(pre) + (1.0 - expect_alpha) * logit(0.20))
    assert abs(res.committed_probability - expect_p) < 1e-6


def test_named_edge_judge_high_overrides_the_shrunk_pool():
    # A named edge STILL deviates: A3 shrinks the DEFAULT pool, but a high-confidence
    # judge with a distinct, justified number overrides the (shrunk) pool wholesale.
    def runner(model, system, user):
        if "JUDGE" in system:
            return json.dumps(
                {
                    "probability": 0.88,
                    "rationale": "decisive unpriced catalyst",
                    "directional_confidence": "high",
                    "market_deviation_justification": "a specific edge the market has not priced",
                }
            )
        return _panelist_json({"a/b": 0.90, "c/d": 0.60}.get(model, 0.5))

    res = run_quorum(
        question_title="Will X?",
        resolution_criteria="R",
        models=["a/b", "c/d"],
        runner=runner,
        judge_model="anthropic/claude-opus-4-8",
        trim=0,
        market_anchor=0.20,
        market_anchor_threshold_pp=10.0,
    )
    assert res.final_source == "judge_high"
    assert abs(res.committed_probability - 0.88) < 1e-9  # the named edge, not the shrunk pool
    assert res.market_pull_applied is False  # justified deviation kept
    # A3 still recorded its shrink of the DEFAULT pool, even though the edge escaped it.
    assert res.pool_shrinkage is not None and res.pool_shrinkage["shrunk"] is True
