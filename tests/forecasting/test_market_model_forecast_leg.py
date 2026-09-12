"""Wave 5 Slice M — Market Models as a forecast leg (M1-M5).

Covers reachability (build_model action + CLI verb), numbers-not-prose
(model_to_forecast records a model_run + FK + reference class), one-engine
(trend_projection + market_compute routing, no-backend fallback), the model-type
recommender, and the scheduled refresh phase (alert on material move + dedupe).
"""

from __future__ import annotations

import argparse
import json

import pytest

import forecasting.market_model as MM
from forecasting import cron_runner as CR
from forecasting.ensembles import linear_trend_projection
from forecasting.ledger import ForecastLedger, allow_ledger_writes


@pytest.fixture()
def ledger(tmp_path):
    return ForecastLedger(db_path=tmp_path / "ledger.db")


def _regression_pres(proj_y=11.0, lo=9.0, hi=13.0, r2=0.9):
    return {
        "schema_version": "market-presentation-v1",
        "title": "Compute vs revenue",
        "summary": "Trend.",
        "status": "complete",
        "blocks": [
            {"type": "narrative", "id": "n1", "body": "Strong trend."},
            {"type": "regression", "id": "reg1", "method": "timeseries_trend", "r2": r2,
             "y_label": "revenue", "coeffs": [{"name": "t", "value": 1.2}],
             "points": [{"x": 1, "y": 2}, {"x": 2, "y": 4}],
             "extrapolation": [{"x": 5, "y": proj_y, "lo": lo, "hi": hi}]},
        ],
    }


def _prob_metric_pres(value=0.42):
    return {
        "schema_version": "market-presentation-v1",
        "title": "Base rate",
        "summary": "Rate.",
        "status": "complete",
        "blocks": [
            {"type": "metric", "id": "m1", "label": "historical base rate", "value": value, "unit": "probability"},
        ],
    }


def _agent_emit(pres, spec=None):
    return {
        "final_response": "done", "model": "test-model", "api_calls": 3, "completed": True,
        "messages": [{"role": "assistant", "tool_calls": [
            {"id": "t1", "function": {"name": "emit_market_presentation",
                                      "arguments": json.dumps({"presentation": pres, "spec": spec or {}})}},
        ]}],
    }


# ── M4: recommender ────────────────────────────────────────────────────────────


def test_recommender_maps_outcome_shapes():
    assert MM.recommend_model_family("binary", "will X happen")["model_type"] == "ols"
    assert MM.recommend_model_family("numeric", "project the level of GDP")["model_type"] == "timeseries_trend"
    assert MM.recommend_model_family("numeric", "annual growth rate / CAGR")["model_type"] == "loglinear"
    assert MM.recommend_model_family("numeric", "tail risk trajectory path")["model_type"] == "montecarlo"
    assert MM.recommend_model_family("numeric", "relationship between A and B")["model_type"] == "correlation"
    assert MM.recommend_model_family("vote_share", "share of the vote")["model_type"] == "montecarlo"
    assert MM.recommend_model_family("thesis", "macro thesis")["model_type"] == "correlation"
    # unknown outcome falls back to the numeric-level default
    assert MM.recommend_model_family(None, "some level")["model_type"] == "timeseries_trend"


def test_recommender_injected_into_build_prompt():
    prompt = MM._build_user_prompt("project the level of revenue", {"outcome_type": "numeric"}, MM.DEPTH_PRESETS["quick"])
    assert "Recommended primary model: timeseries_trend" in prompt
    # explicit analysis_type suppresses the recommender default
    pinned = MM._build_user_prompt("q", {"analysis_type": "montecarlo", "outcome_type": "numeric"}, MM.DEPTH_PRESETS["quick"])
    assert "Preferred analysis type: montecarlo" in pinned
    assert "Recommended primary model" not in pinned


# ── M2: numbers-not-prose (model_to_forecast) ──────────────────────────────────


def test_model_to_forecast_records_model_run_with_fk(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres()))
    built = MM.build_market_model("compute vs revenue", {"depth": "quick"}, ledger=ledger)
    model_id = built["model_id"]

    out = MM.model_to_forecast(model_id, ledger=ledger)
    qid = out["question_id"]
    assert qid and out["model_run_id"]
    runs = ledger.list_model_runs(qid)
    assert len(runs) == 1
    run = runs[0]
    # FK column is written (was never populated before)
    assert run["market_model_id"] == model_id
    assert run["model_type"] == "timeseries_trend"
    # the computed numbers survive as structured output, not just prose
    assert run["output"]["projected_value"] == 11.0
    assert run["output"]["lo"] == 9.0 and run["output"]["hi"] == 13.0
    assert run["output"]["r2"] == 0.9
    # a plain numeric level is NOT turned into a reference class
    assert out["reference_class_id"] is None
    # the spec carries the spawned question id back (link both ways)
    assert ledger.get_market_model(model_id)["spec"]["forecast_question_id"] == qid
    assert ledger.get_question(qid).metadata.get("source_market_model") == model_id


def test_model_to_forecast_adds_reference_class_for_base_rate(ledger, monkeypatch):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_prob_metric_pres(0.42)))
    built = MM.build_market_model("base rate of X", {"depth": "quick"}, ledger=ledger)
    out = MM.model_to_forecast(built["model_id"], ledger=ledger)
    qid = out["question_id"]
    assert out["reference_class_id"]
    rcs = ledger.list_reference_classes(qid)
    assert len(rcs) == 1
    assert abs(rcs[0]["base_rate"] - 0.42) < 1e-9
    assert built["model_id"] in rcs[0]["source_refs"]


# ── M1: build_model action + CLI verb ──────────────────────────────────────────


def test_build_model_action_links_existing_question(ledger, tmp_path, monkeypatch):
    from tools.forecasting_tool import forecast_ledger_tool

    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres()))
    with allow_ledger_writes(reason="test"):
        q = ledger.create_question(
            title="Will 2027 revenue exceed 20B",
            resolution_criteria="Resolves YES if reported 2027 revenue is above 20 billion USD.",
            description="Compute-driven revenue.",
        )
    out = json.loads(forecast_ledger_tool({
        "action": "build_model", "db": str(tmp_path / "ledger.db"), "question_id": q.id, "depth": "quick",
    }))
    assert out["success"] is True
    assert out["model_id"] and out["question_id"] == q.id
    assert out["recommended_model"]["model_type"] == "ols"  # binary question
    # linked both ways
    model = ledger.get_market_model(out["model_id"])
    assert model["spec"]["forecast_question_id"] == q.id
    assert ledger.get_question(q.id).metadata.get("source_market_model") == out["model_id"]


def test_build_model_action_freetext_no_question(ledger, tmp_path, monkeypatch):
    from tools.forecasting_tool import forecast_ledger_tool

    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres()))
    out = json.loads(forecast_ledger_tool({
        "action": "build_model", "db": str(tmp_path / "ledger.db"),
        "question": "project NVDA revenue to 2027", "outcome_type": "numeric",
    }))
    assert out["success"] is True and out["model_id"]
    assert out["question_id"] is None
    assert out["recommended_model"]["model_type"] == "timeseries_trend"


def test_build_model_action_requires_question():
    from tools.forecasting_tool import forecast_ledger_tool

    out = json.loads(forecast_ledger_tool({"action": "build_model"}))
    assert out.get("success") is False


def test_cli_model_build_verb(ledger, tmp_path, monkeypatch, capsys):
    from forecasting import cli

    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres()))
    with allow_ledger_writes(reason="test"):
        q = ledger.create_question(
            title="Will 2027 revenue exceed 20B",
            resolution_criteria="Resolves YES if reported 2027 revenue is above 20 billion USD.",
            description="",
        )
    args = argparse.Namespace(
        db=str(tmp_path / "ledger.db"), id="build", build_question=q.id,
        depth="quick", analysis_type=None,
    )
    cli._cmd_model_build(args)
    out = capsys.readouterr().out
    assert "model build:" in out
    assert f"linked to question: {q.id}" in out
    assert "recommended:" in out


# ── M3: one engine ──────────────────────────────────────────────────────────────


def test_trend_projection_backward_compatible_keys():
    series = [{"x": 0, "value": 1}, {"x": 1, "value": 2}, {"x": 2, "value": 3}]
    r = linear_trend_projection(series, target_x=4)
    # all the historical keys still present + identical math
    for key in ("count", "intercept", "slope", "slope_unit", "r_squared", "residual_std",
                "latest_x", "latest_value", "target_x", "target_date", "projected_value"):
        assert key in r
    assert r["slope"] == 1.0 and r["intercept"] == 1.0
    assert r["projected_value"] == 5.0
    # richer fields added alongside
    assert "projected_lo" in r and "projected_hi" in r


def test_trend_projection_no_scipy_fallback(monkeypatch):
    # Force the no-scipy path in market_compute's t-quantile (normal approx) — the
    # engine must still produce a projection + interval.
    from forecasting import market_compute as MC

    monkeypatch.setattr(MC, "_scipy_stats", None, raising=False)
    monkeypatch.setattr(MC, "_scipy_stats_probed", True, raising=False)
    series = [{"x": 0, "value": 1}, {"x": 1, "value": 3}, {"x": 2, "value": 4}, {"x": 3, "value": 6}]
    r = linear_trend_projection(series, target_x=5)
    assert r["projected_lo"] <= r["projected_value"] <= r["projected_hi"]


def test_record_model_run_routes_ols_through_market_compute(ledger, tmp_path):
    from tools.forecasting_tool import forecast_ledger_tool

    with allow_ledger_writes(reason="test"):
        q = ledger.create_question(
            title="Will 2027 revenue exceed 20B",
            resolution_criteria="Resolves YES if reported 2027 revenue is above 20 billion USD.",
            description="",
        )
    out = json.loads(forecast_ledger_tool({
        "action": "record_model_run", "db": str(tmp_path / "ledger.db"), "question_id": q.id,
        "model_type": "ols", "payload": {"x": [0, 1, 2], "y": [1, 3, 5]},
        "market_model_id": "mm_abc",
    }))
    assert out["success"] is True
    run = out["model_run"]
    # market_compute summary merged in + block attached; FK stored
    assert run["output"]["slope"] == 2.0
    assert run["output"]["compute_block"]["type"] == "regression"
    assert run["market_model_id"] == "mm_abc"


def test_market_compute_multivariate_no_numpy_fallback(monkeypatch):
    # No-backend path: multivariate solves via the pure-Python normal equations.
    from forecasting import market_compute as MC

    monkeypatch.setattr(MC, "_np", None, raising=False)
    res = MC.compute("multivariate", {"X": [[1.0], [2.0], [3.0]], "y": [2.0, 4.0, 6.0], "x_labels": ["a"]})
    assert res["ok"] is True
    assert abs(res["summary"]["coeffs"][1] - 2.0) < 1e-6


# ── M5: scheduled refresh phase ─────────────────────────────────────────────────


def _build_linked_model(ledger, monkeypatch, proj_y=11.0):
    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres(proj_y=proj_y)))
    built = MM.build_market_model("revenue", {"depth": "quick"}, ledger=ledger)
    model_id = built["model_id"]
    out = MM.model_to_forecast(model_id, ledger=ledger)
    return model_id, out["question_id"]


def test_refresh_market_models_alerts_on_material_move_and_dedupes(ledger, monkeypatch):
    model_id, qid = _build_linked_model(ledger, monkeypatch, proj_y=11.0)

    # open_market_model returns a refreshed presentation whose projection MOVED a lot.
    moved = {"model_id": model_id, "presentation": _regression_pres(proj_y=20.0, lo=18.0, hi=22.0),
             "refreshed": True, "refresh_note": None}
    monkeypatch.setattr(MM, "open_market_model", lambda mid, *, ledger: moved)
    renarrated = {"calls": 0}
    def _fake_renarrate(mid, *, ledger, **kw):
        renarrated["calls"] += 1
        return {"model_id": mid, "version": 2, "status": "complete"}
    monkeypatch.setattr(MM, "renarrate_market_model", _fake_renarrate)

    with allow_ledger_writes(reason="test"):
        res = CR.refresh_market_models(ledger)
    assert res["checked"] == 1 and res["refreshed"] == 1 and res["moved"] == 1
    assert res["alerted"] == [qid]
    assert renarrated["calls"] == 1
    open_alerts = [a for a in ledger.list_alerts(unresolved_only=True) if a.reason == CR._MARKET_MODEL_MOVE_ALERT_REASON]
    assert len(open_alerts) == 1

    # Second sweep: deduped — no new alert (same reason+scope already open).
    with allow_ledger_writes(reason="test"):
        res2 = CR.refresh_market_models(ledger)
    assert res2["alerted"] == []
    open_alerts2 = [a for a in ledger.list_alerts(unresolved_only=True) if a.reason == CR._MARKET_MODEL_MOVE_ALERT_REASON]
    assert len(open_alerts2) == 1


def test_refresh_market_models_no_alert_when_stable(ledger, monkeypatch):
    model_id, qid = _build_linked_model(ledger, monkeypatch, proj_y=11.0)
    stable = {"model_id": model_id, "presentation": _regression_pres(proj_y=11.2, lo=9.0, hi=13.0),
              "refreshed": True, "refresh_note": None}
    monkeypatch.setattr(MM, "open_market_model", lambda mid, *, ledger: stable)
    monkeypatch.setattr(MM, "renarrate_market_model", lambda mid, *, ledger, **kw: None)
    with allow_ledger_writes(reason="test"):
        res = CR.refresh_market_models(ledger)
    assert res["moved"] == 0 and res["alerted"] == []


def test_refresh_market_models_skips_resolved_questions(ledger, monkeypatch):
    model_id, qid = _build_linked_model(ledger, monkeypatch, proj_y=11.0)
    with allow_ledger_writes(reason="test"):
        ledger.resolve_question(question_id=qid, outcome="yes")
    called = {"open": 0}
    def _open(mid, *, ledger):
        called["open"] += 1
        return {"model_id": mid, "presentation": {}, "refreshed": False}
    monkeypatch.setattr(MM, "open_market_model", _open)
    with allow_ledger_writes(reason="test"):
        res = CR.refresh_market_models(ledger)
    # resolved question is skipped before opening the model
    assert res["checked"] == 0 and called["open"] == 0


# ── Wave 5 fix regressions ──────────────────────────────────────────────────


def test_record_model_run_params_in_inputs_no_circular_ref(ledger, tmp_path):
    """The market-compute route must accept compute params passed directly in
    ``inputs`` (no separate ``payload``) without building a self-referential
    dict that json_dumps rejects."""
    from tools.forecasting_tool import forecast_ledger_tool

    with allow_ledger_writes(reason="test"):
        q = ledger.create_question(
            title="Will 2027 revenue exceed 20B",
            resolution_criteria="Resolves YES if reported 2027 revenue is above 20 billion USD.",
            description="",
        )
    out = json.loads(forecast_ledger_tool({
        "action": "record_model_run", "db": str(tmp_path / "ledger.db"), "question_id": q.id,
        "model_type": "ols", "inputs": {"x": [0, 1, 2], "y": [1, 3, 5]},
    }))
    assert out["success"] is True, out.get("error")
    run = out["model_run"]
    # compute still ran + merged its summary
    assert run["output"]["slope"] == 2.0
    # the payload was snapshotted, not folded back into itself
    assert run["inputs"]["payload"]["x"] == [0, 1, 2]
    assert run["inputs"]["payload"].get("payload") is None


def test_market_compute_backends_probes_scipy():
    """backends() must PROBE scipy (like bayes_toolkit.using_industry_libraries),
    not read the raw lazy sentinel — otherwise it under-reports scipy for
    compute paths (montecarlo/scenario) that never touch it."""
    from forecasting import market_compute as MC

    # Simulate a fresh, un-probed process.
    prev_stats, prev_probed = MC._scipy_stats, MC._scipy_stats_probed
    try:
        MC._scipy_stats = None
        MC._scipy_stats_probed = False
        result = MC.backends()
        # backends() should reflect the probe result, not the un-probed None.
        assert result["scipy"] == (MC._get_scipy_stats() is not None)
        # and it must have actually probed (sentinel flipped), not returned a
        # stale False.
        assert MC._scipy_stats_probed is True
    finally:
        MC._scipy_stats, MC._scipy_stats_probed = prev_stats, prev_probed


def test_maybe_base_rate_rejects_market_share():
    """A market/vote SHARE in [0,1] is a level, not a probability of the
    question resolving, so it must NOT be promoted to a reference-class base
    rate. A genuine probability/rate metric still is."""
    share = {"blocks": [{"type": "metric", "label": "projected 2030 EV market share",
                         "value": 0.35, "unit": "fraction"}]}
    p = MM._primary_projection(share)
    assert p is not None and "base_rate" not in p

    prob = {"blocks": [{"type": "metric", "label": "historical base rate",
                        "value": 0.2, "unit": "probability"}]}
    p2 = MM._primary_projection(prob)
    assert p2 is not None and p2["base_rate"] == 0.2


@pytest.mark.parametrize("failure", [RuntimeError("link interrupted"), KeyboardInterrupt()])
def test_build_model_link_failure_rolls_back_both_edges(ledger, tmp_path, monkeypatch, failure):
    from tools.forecasting_tool import forecast_ledger_tool

    monkeypatch.setattr(MM, "_run_market_agent", lambda **k: _agent_emit(_regression_pres()))
    with allow_ledger_writes(reason="test"):
        q = ledger.create_question(title="Revenue above 20B?", resolution_criteria="Reported revenue exceeds 20B USD.")
    original = ForecastLedger.link_question_market_model

    def interrupted(self, question_id, model_id):
        original(self, question_id, model_id)
        raise failure

    monkeypatch.setattr(ForecastLedger, "link_question_market_model", interrupted)
    args = {"action": "build_model", "db": str(tmp_path / "ledger.db"), "question_id": q.id}
    if isinstance(failure, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            forecast_ledger_tool(args)
    else:
        result = json.loads(forecast_ledger_tool(args))
        assert result["success"] is False
        assert result["model_id"]
        assert "link interrupted" in result["error"]
    models = ledger.list_market_models()
    assert len(models) == 1
    assert "forecast_question_id" not in models[0]["spec"]
    assert "source_market_model" not in ledger.get_question(q.id).metadata

    from forecasting.application.model_build import link_built_model

    monkeypatch.setattr(ForecastLedger, "link_question_market_model", original)
    link_built_model(ledger, q.id, models[0]["id"])
    link_built_model(ledger, q.id, models[0]["id"])
    assert len(ledger.list_market_models()) == 1
    assert ledger.get_market_model(models[0]["id"])["spec"]["forecast_question_id"] == q.id
    assert ledger.get_question(q.id).metadata["source_market_model"] == models[0]["id"]


@pytest.mark.parametrize("surface", ["application", "tool", "cli"])
def test_model_build_surfaces_share_parameters(tmp_path, monkeypatch, surface):
    from forecasting.application.model_build import build_model
    from tools.forecasting_tool import forecast_ledger_tool
    from forecasting import cli

    captured = []

    def build(question, params, **kwargs):
        captured.append((question, params))
        return {"model_id": "mm_test", "version": 1, "status": "complete"}

    monkeypatch.setattr(MM, "build_market_model", build)
    args = {"question": "project revenue", "depth": "quick", "analysis_type": "ols"}
    if surface == "application":
        build_model(args, ForecastLedger(tmp_path / "ledger.db"))
    elif surface == "tool":
        forecast_ledger_tool({**args, "action": "build_model", "db": str(tmp_path / "ledger.db")})
    else:
        cli._cmd_model_build(argparse.Namespace(db=str(tmp_path / "ledger.db"), build_question=args["question"], depth="quick", analysis_type="ols"))
    assert captured == [("project revenue", {"depth": "quick", "analysis_type": "ols"})]
