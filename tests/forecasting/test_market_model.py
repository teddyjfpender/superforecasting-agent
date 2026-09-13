"""Tests for Market Models orchestration (forecasting.market_model)."""

from __future__ import annotations

import json

import pytest

import forecasting.market_model as MM
from forecasting.ledger import ForecastLedger


@pytest.fixture()
def ledger(tmp_path):
    return ForecastLedger(db_path=tmp_path / "ledger.db")


def _good_presentation():
    return {
        "schema_version": "market-presentation-v1",
        "title": "GPU vs NVDA",
        "summary": "Compute growth explains revenue.",
        "status": "complete",
        "blocks": [
            {"type": "narrative", "id": "n1", "body": "Strong relationship."},
            {"type": "regression", "id": "reg1", "r2": 0.9,
             "coeffs": [{"name": "flops", "value": 1.2}], "y_label": "rev",
             "points": [{"x": 1, "y": 2}, {"x": 2, "y": 4}],
             "extrapolation": [{"x": 5, "y": 11}]},
        ],
    }


def _agent_result_with_emit(pres, spec=None):
    # Mirrors run_conversation's real shape: tool calls live inside messages as
    # assistant {tool_calls:[{function:{name, arguments(JSON string)}}]}.
    return {
        "final_response": "done",
        "model": "test-model",
        "api_calls": 4,
        "completed": True,
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "import_source_evidence", "arguments": "{}"}},
                    {"id": "t2", "function": {"name": "emit_market_presentation",
                                              "arguments": json.dumps({"presentation": pres, "spec": spec or {}})}},
                ],
            },
        ],
    }


def test_build_persists_model_and_presentation(ledger, monkeypatch):
    spec = {"series": [{"name": "rev", "source_type": "sec", "source": "NVDA"}],
            "compute": [{"block_id": "reg1", "model_type": "ols",
                         "payload": {"x": {"series": "rev", "field": "x"}, "y": {"series": "rev", "field": "y"}}}]}
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), spec))

    out = MM.build_market_model("how does compute drive NVDA revenue", {"depth": "deep"}, ledger=ledger)
    assert out["status"] == "complete"
    assert out["version"] == 1
    model = ledger.get_market_model(out["model_id"])
    assert model["depth"] == "deep"
    assert model["spec"]["series"][0]["source_type"] == "sec"
    # data series captured from the presentation
    assert ledger.list_market_data_series(out["model_id"])


def test_build_emit_via_fenced_json_fallback(ledger, monkeypatch):
    import json

    pres = _good_presentation()
    result = {"final_response": "Here it is:\n```json\n" + json.dumps({"presentation": pres}) + "\n```", "tool_calls": []}
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: result)
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "complete" and out["version"] == 1


def test_build_no_presentation_no_prose_is_failed_not_raised(ledger, monkeypatch):
    # No emit + empty final_response → truly nothing → failed (never raises).
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: {"final_response": "", "messages": [], "completed": True})
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "failed"
    assert ledger.get_market_presentation(out["model_id"])["status"] == "failed"


def test_html_error_is_not_dumped_as_narrative(ledger, monkeypatch):
    # Provider/tool returned an HTML error page → must NOT render as a prose
    # analysis; fail cleanly with no raw HTML in the presentation.
    html = "<!DOCTYPE html><html><head><title>503</title></head><body><h1>Service Unavailable</h1></body></html>"
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: {
        "final_response": html, "messages": [], "completed": False, "error": html, "api_calls": 1,
    })
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "failed"
    blob = json.dumps(out["presentation"])
    assert "<html" not in blob and "<body" not in blob and "<!DOCTYPE" not in blob


def test_build_prose_only_falls_back_to_partial(ledger, monkeypatch):
    # Agent answered in prose but didn't call emit → surface the prose as partial.
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: {
        "final_response": "GPU compute roughly doubled each generation and revenue tracked it closely.",
        "messages": [], "completed": True, "api_calls": 5,
    })
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "partial"
    blocks = out["presentation"]["blocks"]
    assert any(b["type"] == "narrative" for b in blocks)
    assert "did not call emit_market_presentation" in (out["presentation"]["diagnostics"].get("warnings") or [""])[0]


def test_build_hard_failure_degrades(ledger, monkeypatch):
    def boom(**k):
        raise RuntimeError("no provider")

    monkeypatch.setattr(MM, "_run_market_agent", boom)
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "failed"


def test_invalid_presentation_is_repaired_to_partial(ledger, monkeypatch):
    bad = {"title": "t", "blocks": [{"type": "regression", "id": "r"}]}  # missing r2/coeffs
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(bad))
    out = MM.build_market_model("q", {}, ledger=ledger)
    assert out["status"] == "partial"
    blocks = out["presentation"]["blocks"]
    assert any(b.get("id") == "validation-note" for b in blocks)


def test_open_recomputes_when_spec_runnable(ledger, monkeypatch):
    spec = {"series": [{"name": "rev", "source_type": "sec", "source": "NVDA"}],
            "compute": [{"block_id": "reg1", "model_type": "ols",
                         "payload": {"x": {"series": "rev", "field": "x"}, "y": {"series": "rev", "field": "y"}}}]}
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), spec))
    out = MM.build_market_model("q", {}, ledger=ledger)
    mid = out["model_id"]

    # fresh data: y = 3x → slope should become 3 after re-pull.
    # _repull_series now returns (refreshed_series, reasons).
    monkeypatch.setattr(MM, "_repull_series", lambda spec: ([
        {"name": "rev", "source_type": "sec", "source": "NVDA",
         "points": [{"x": 1, "y": 3}, {"x": 2, "y": 6}, {"x": 3, "y": 9}], "as_of": "now"}
    ], []))
    opened = MM.open_market_model(mid, ledger=ledger)
    assert opened["refreshed"] is True
    reg = next(b for b in opened["presentation"]["blocks"] if b.get("id") == "reg1")
    assert reg["coeffs"][0]["value"] == pytest.approx(3.0, abs=1e-6)


def test_open_passthrough_when_not_runnable(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), {}))
    out = MM.build_market_model("q", {}, ledger=ledger)
    opened = MM.open_market_model(out["model_id"], ledger=ledger)
    assert opened["refreshed"] is False
    assert opened["presentation"]["blocks"]


def test_chat_appends_thread_and_versions(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), {}))
    out = MM.build_market_model("q", {}, ledger=ledger)
    mid = out["model_id"]

    pres2 = _good_presentation()
    pres2["summary"] = "Now extended to 2030."
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(pres2, {}))
    res = MM.chat_market_model(mid, "extend to 2030", ledger=ledger)
    assert res["version"] == 2
    msgs = ledger.list_market_messages(mid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_depth_presets_have_caps():
    for d, cfg in MM.DEPTH_PRESETS.items():
        assert cfg["max_iterations"] > 0
    assert MM.DEPTH_PRESETS["ultra"]["max_iterations"] >= MM.DEPTH_PRESETS["quick"]["max_iterations"]


def test_model_to_forecast_creates_linked_question(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), {}))
    out = MM.build_market_model("q", {}, ledger=ledger)
    res = MM.model_to_forecast(out["model_id"], ledger=ledger)
    assert res["seed"]["source_market_model"] == out["model_id"]
    # The forecast is actually created + cross-linked both ways (was a dead seed).
    qid = res["question_id"]
    assert qid
    q = ledger.get_question(qid)
    meta = getattr(q, "metadata", None) or (q.get("metadata") if isinstance(q, dict) else {})
    assert (meta or {}).get("source_market_model") == out["model_id"]
    assert (ledger.get_market_model(out["model_id"]).get("spec") or {}).get("forecast_question_id") == qid


class _FakeAgent:
    last_kwargs: dict = {}

    def __init__(self, **kw):
        _FakeAgent.last_kwargs = kw
        self.session_id = "sess-123"

    def run_conversation(self, user, system_message=None):
        return {"completed": True, "messages": [], "api_calls": 1}


def test_run_market_agent_wires_runtime_knobs(monkeypatch):
    monkeypatch.setattr("run_agent.AIAgent", _FakeAgent)
    rt = {
        "model": "m", "provider": "p",
        "fallback_model": [{"provider": "x", "model": "y"}],
        "parent_session_id": "sid-1",
    }
    res = MM._run_market_agent(
        system="s", user="u", max_iterations=55, model="m", provider="p",
        depth="deep", preset=MM.DEPTH_PRESETS["deep"], runtime=rt,
    )
    kw = _FakeAgent.last_kwargs
    assert kw["fallback_model"] == [{"provider": "x", "model": "y"}]
    assert kw["max_tokens"] == MM.DEPTH_PRESETS["deep"]["max_tokens"]
    assert kw["reasoning_config"] == {"enabled": True, "effort": "medium"}
    assert kw["save_trajectories"] is True and kw["checkpoints_enabled"] is True
    assert kw["parent_session_id"] == "sid-1"
    assert kw["enabled_toolsets"] == ["market-models"]
    assert res["_market_runtime"]["fallback"] is True
    assert res["_market_runtime"]["timeout_override"] == 600.0
    assert res["_market_runtime"]["trajectory_session_id"] == "sess-123"


def test_run_market_agent_quick_disables_reasoning(monkeypatch):
    monkeypatch.setattr("run_agent.AIAgent", _FakeAgent)
    MM._run_market_agent(system="s", user="u", max_iterations=18, model="m", provider="p",
                         depth="quick", preset=MM.DEPTH_PRESETS["quick"], runtime={"model": "m"})
    kw = _FakeAgent.last_kwargs
    assert kw["reasoning_config"] == {"enabled": False}
    assert "save_trajectories" not in kw  # not a deep run


def test_run_market_agent_interactive_toolset(monkeypatch):
    monkeypatch.setattr("run_agent.AIAgent", _FakeAgent)
    MM._run_market_agent(system="s", user="u", max_iterations=32, model="m", provider="p",
                         depth="standard", preset=MM.DEPTH_PRESETS["standard"], runtime={"model": "m", "interactive": True})
    assert _FakeAgent.last_kwargs["enabled_toolsets"] == ["market-models-interactive"]


def test_repull_series_reports_reasons():
    refreshed, reasons = MM._repull_series({"series": [{"name": "rev", "points": [{"x": 1, "y": 2}]}]})
    assert refreshed == []
    assert any("source_type" in r for r in reasons)  # explains WHY it can't refresh


def test_renarrate_keeps_prior_when_aux_empty(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_result_with_emit(_good_presentation(), {}))
    out = MM.build_market_model("q", {}, ledger=ledger)
    monkeypatch.setattr(MM, "_aux_llm", lambda *a, **k: "")  # aux yields nothing usable
    res = MM.renarrate_market_model(out["model_id"], ledger=ledger)
    assert res.get("renarrated") is False
    assert res["presentation"]["blocks"]  # prior presentation kept intact


@pytest.mark.parametrize('failure', [None, 'construction', 'conversation'])
def test_interactive_build_restores_prior_approval_callback(monkeypatch, failure):
    from tools.terminal_tool import _get_approval_callback, set_approval_callback

    previous = _get_approval_callback()
    parent = lambda *args, **kwargs: 'deny'
    class Agent(_FakeAgent):
        def __init__(self, **kwargs):
            assert _get_approval_callback()('command', 'description') == 'session'
            if failure == 'construction':
                raise RuntimeError('construction failed')
            super().__init__(**kwargs)
        def run_conversation(self, *args, **kwargs):
            assert _get_approval_callback()('command', 'description') == 'session'
            if failure == 'conversation':
                raise RuntimeError('conversation failed')
            return super().run_conversation(*args, **kwargs)
    monkeypatch.setattr('run_agent.AIAgent', Agent)
    set_approval_callback(parent)
    try:
        def build():
            return MM._run_market_agent(system='s', user='u', max_iterations=3,
                                        model='m', provider='p', runtime={'interactive': True})
        if failure:
            with pytest.raises(RuntimeError, match=failure):
                build()
        else:
            build()
        assert _get_approval_callback() is parent
    finally:
        set_approval_callback(previous)
