"""Tests for the multi-perspective forecast panel."""

from __future__ import annotations

import argparse
import json
import math

import pytest

from forecasting import ForecastLedger
from forecasting.bayes_toolkit import log_odds_pool
from forecasting.cli import register_cli
from forecasting.models import ValidationError
from forecasting.panel import (
    DEFAULT_PANEL_PERSPECTIVES,
    PANEL_AGGREGATION_METHODS,
    PANEL_PERSPECTIVES,
    PanelAggregation,
    aggregate_panel_estimates,
    build_perspective_prompts,
    should_run_panel,
)
from tools.forecasting_tool import FORECAST_LEDGER_SCHEMA, forecast_ledger_tool


# ── helpers ─────────────────────────────────────────────────────────────────


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "panel.db"))
    ledger.initialize_schema()
    return ledger


def _question(ledger, **overrides):
    defaults = dict(
        title="Will inflation cool by July 2026?",
        resolution_criteria="BLS CPI YoY less than 3.0% for July 2026 release.",
    )
    defaults.update(overrides)
    return ledger.create_question(**defaults)


def _five_estimates():
    return [
        {"perspective": "outside", "probability": 0.4, "rationale": "base rate"},
        {"perspective": "inside", "probability": 0.6, "rationale": "mechanism"},
        {"perspective": "market", "probability": 0.55, "rationale": "markets"},
        {"perspective": "red_team", "probability": 0.2, "rationale": "red team"},
        {"perspective": "sanity", "probability": 0.5, "rationale": "gut"},
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def _run(parser: argparse.ArgumentParser, argv: list[str]) -> None:
    args = parser.parse_args(argv)
    args.func(args)


# ── PANEL_PERSPECTIVES catalog ──────────────────────────────────────────────


def test_default_perspectives_are_named():
    assert set(DEFAULT_PANEL_PERSPECTIVES) == {
        "outside",
        "inside",
        "market",
        "red_team",
        "sanity",
    }


def test_panel_perspectives_catalog_has_each_expected_perspective():
    for name in DEFAULT_PANEL_PERSPECTIVES:
        assert name in PANEL_PERSPECTIVES
        assert PANEL_PERSPECTIVES[name]["label"]
        assert PANEL_PERSPECTIVES[name]["system"]
        assert PANEL_PERSPECTIVES[name]["instruction"]


def test_perspectives_describe_their_constraint():
    assert "OUTSIDE VIEW" in PANEL_PERSPECTIVES["outside"]["system"]
    assert "INSIDE VIEW" in PANEL_PERSPECTIVES["inside"]["system"]
    assert "MARKET" in PANEL_PERSPECTIVES["market"]["system"].upper()
    assert "RED-TEAM" in PANEL_PERSPECTIVES["red_team"]["system"]
    assert "SANITY" in PANEL_PERSPECTIVES["sanity"]["system"]


# ── aggregate_panel_estimates ───────────────────────────────────────────────


def test_aggregate_panel_estimates_default_uses_trim_one():
    aggregation = aggregate_panel_estimates(_five_estimates())
    assert aggregation.method == "trimmed_geomean_odds"
    assert aggregation.trim == 1
    # Two extremes trimmed (0.2 and 0.6 in this set).
    trimmed = [e for e in aggregation.estimates if e["trimmed"]]
    assert {e["perspective"] for e in trimmed} == {"red_team", "inside"}


def test_aggregate_panel_estimates_returns_log_odds_pool_after_trim():
    aggregation = aggregate_panel_estimates(_five_estimates(), trim=1)
    kept = [e["probability"] for e in aggregation.estimates if not e["trimmed"]]
    expected = log_odds_pool(kept, [1.0] * len(kept))
    assert aggregation.aggregate_probability == pytest.approx(expected, abs=1e-9)


def test_aggregate_panel_estimates_no_trim_includes_everyone():
    aggregation = aggregate_panel_estimates(_five_estimates(), trim=0)
    assert aggregation.trim == 0
    assert all(not e["trimmed"] for e in aggregation.estimates)
    expected = log_odds_pool([e["probability"] for e in _five_estimates()], [1.0] * 5)
    assert aggregation.aggregate_probability == pytest.approx(expected, abs=1e-9)


def test_aggregate_panel_estimates_median_method():
    aggregation = aggregate_panel_estimates(_five_estimates(), method="median", trim=0)
    # Sorted probabilities: 0.2, 0.4, 0.5, 0.55, 0.6 -> median 0.5.
    assert aggregation.aggregate_probability == pytest.approx(0.5)


def test_aggregate_panel_estimates_spread_summary_captures_disagreement():
    aggregation = aggregate_panel_estimates(_five_estimates(), trim=0)
    spread = aggregation.spread
    assert spread["min"] == pytest.approx(0.2)
    assert spread["max"] == pytest.approx(0.6)
    assert spread["median"] == pytest.approx(0.5)
    assert spread["count"] == pytest.approx(5)
    assert spread["range"] == pytest.approx(0.4)


def test_aggregate_panel_estimates_requires_at_least_one_estimate():
    with pytest.raises(ValidationError):
        aggregate_panel_estimates([], method="trimmed_geomean_odds")


def test_aggregate_panel_estimates_rejects_unknown_method():
    with pytest.raises(ValidationError):
        aggregate_panel_estimates(_five_estimates(), method="not-a-method")


def test_aggregate_panel_estimates_rejects_invalid_probability():
    with pytest.raises(ValidationError):
        aggregate_panel_estimates([{"perspective": "x", "probability": 1.5}])


def test_aggregate_panel_estimates_rejects_negative_weight():
    with pytest.raises(ValidationError):
        aggregate_panel_estimates([{"perspective": "x", "probability": 0.5, "weight": -1}])


def test_aggregate_panel_estimates_validates_confidence_bounds():
    with pytest.raises(ValidationError):
        aggregate_panel_estimates(
            [
                {
                    "perspective": "x",
                    "probability": 0.5,
                    "confidence_low": 0.7,
                    "confidence_high": 0.3,
                }
            ]
        )


def test_aggregate_panel_estimates_falls_back_when_trim_overflows():
    """Trim that would leave nothing falls back to no trim (forgiving by design)."""

    aggregation = aggregate_panel_estimates(_five_estimates(), trim=3)
    assert aggregation.trim == 3
    assert all(not e["trimmed"] for e in aggregation.estimates)
    expected = log_odds_pool([e["probability"] for e in _five_estimates()], [1.0] * 5)
    assert aggregation.aggregate_probability == pytest.approx(expected, abs=1e-9)


def test_aggregate_panel_estimates_string_reasons_become_lists():
    aggregation = aggregate_panel_estimates(
        [
            {
                "perspective": "x",
                "probability": 0.5,
                "reasons_up": "alpha\nbeta",
                "reasons_down": ["gamma"],
            }
        ]
    )
    assert aggregation.estimates[0]["reasons_up"] == ["alpha", "beta"]
    assert aggregation.estimates[0]["reasons_down"] == ["gamma"]


def test_panel_aggregation_to_dict_is_serializable():
    aggregation = aggregate_panel_estimates(_five_estimates(), trim=1)
    payload = aggregation.to_dict()
    json.dumps(payload)
    assert payload["method"] == "trimmed_geomean_odds"
    assert payload["trim"] == 1
    assert payload["estimates"][0]["perspective"]


def test_panel_aggregation_methods_set_is_stable():
    assert PANEL_AGGREGATION_METHODS == frozenset(
        {"trimmed_geomean_odds", "log_odds_pool", "median"}
    )


# ── gating heuristic ────────────────────────────────────────────────────────


def test_should_run_panel_runs_on_high_impact_question():
    assert should_run_panel(impact="high", has_prior_snapshot=True) is True


def test_should_run_panel_runs_on_first_forecast():
    assert should_run_panel(impact=None, has_prior_snapshot=False) is True


def test_should_run_panel_skips_routine_refresh():
    assert should_run_panel(impact="low", has_prior_snapshot=True) is False


def test_should_run_panel_force_overrides_everything():
    assert should_run_panel(impact="low", has_prior_snapshot=True, force=True) is True
    assert should_run_panel(impact="high", has_prior_snapshot=False, force=False) is False


# ── prompt builder ──────────────────────────────────────────────────────────


def test_build_perspective_prompts_returns_one_per_perspective():
    prompts = build_perspective_prompts(
        question_title="Q",
        resolution_criteria="R",
        context_packet="C",
    )
    assert set(prompts) == set(DEFAULT_PANEL_PERSPECTIVES)
    for name, prompt in prompts.items():
        assert "OUTSIDE" in prompt["system"] or "INSIDE" in prompt["system"] or "MARKET" in prompt["system"].upper() or "RED" in prompt["system"] or "SANITY" in prompt["system"]
        assert "JSON object" in prompt["user"]
        assert "probability" in prompt["user"]


def test_build_perspective_prompts_rejects_unknown_perspective():
    with pytest.raises(ValidationError):
        build_perspective_prompts(
            question_title="Q",
            resolution_criteria="R",
            context_packet="C",
            perspectives=["outside", "unknown"],
        )


# ── ledger persistence ─────────────────────────────────────────────────────


def test_record_panel_run_stores_aggregate_and_estimates(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    record = ledger.record_panel_run(
        question_id=q.id,
        estimates=_five_estimates(),
        trim=1,
        triggered_by="first_forecast",
    )
    assert record["id"].startswith("pr_")
    assert record["aggregation_method"] == "trimmed_geomean_odds"
    assert record["trim"] == 1
    assert record["aggregate_probability"] == pytest.approx(
        aggregate_panel_estimates(_five_estimates(), trim=1).aggregate_probability,
        abs=1e-9,
    )
    assert len(record["estimates"]) == 5
    assert record["triggered_by"] == "first_forecast"


def test_record_panel_run_is_round_trippable(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    record = ledger.record_panel_run(question_id=q.id, estimates=_five_estimates())
    fetched = ledger.get_panel_run(record["id"])
    assert fetched["aggregate_probability"] == record["aggregate_probability"]
    assert fetched["spread_summary"]["range"] == record["spread_summary"]["range"]


def test_attach_panel_to_snapshot(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    record = ledger.record_panel_run(question_id=q.id, estimates=_five_estimates())
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=record["aggregate_probability"],
        rationale="Panel-aggregated forecast",
    )
    attached = ledger.attach_panel_to_snapshot(record["id"], snap.forecast_id)
    assert attached["snapshot_id"] == snap.forecast_id


def test_list_panel_runs_filters_by_question(tmp_path):
    ledger = _ledger(tmp_path)
    q1 = _question(ledger, title="Q1?")
    q2 = _question(ledger, title="Q2?")
    ledger.record_panel_run(question_id=q1.id, estimates=_five_estimates())
    ledger.record_panel_run(question_id=q2.id, estimates=_five_estimates())
    rows = ledger.list_panel_runs(question_id=q1.id)
    assert len(rows) == 1
    assert rows[0]["question_id"] == q1.id


# ── CLI: forecast panel aggregate / show / record / perspectives ───────────


def test_cli_panel_aggregate_prints_aggregate_and_spread(capsys):
    parser = _parser()
    _run(
        parser,
        [
            "forecast",
            "panel",
            "aggregate",
            "--input",
            json.dumps(_five_estimates()),
            "--trim",
            "1",
        ],
    )
    out = capsys.readouterr().out
    assert "method: trimmed_geomean_odds" in out
    assert "aggregate:" in out
    assert "spread:" in out
    assert "× " in out  # at least one trimmed estimate marker


def test_cli_panel_aggregate_json_output(capsys):
    parser = _parser()
    _run(
        parser,
        [
            "forecast",
            "panel",
            "aggregate",
            "--input",
            json.dumps(_five_estimates()),
            "--trim",
            "0",
            "--json",
        ],
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "trimmed_geomean_odds"
    assert payload["trim"] == 0
    assert len(payload["estimates"]) == 5


def test_cli_panel_record_saves_to_ledger(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "panel.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will inflation cool by July 2026?",
            "--resolution-criteria",
            "BLS CPI YoY less than 3.0% for the July 2026 release.",
        ],
    )
    import re

    qid = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "panel",
            "record",
            qid,
            "--input",
            json.dumps(_five_estimates()),
            "--triggered-by",
            "first_forecast",
        ],
    )
    out = capsys.readouterr().out
    assert "panel_run:" in out
    ledger = ForecastLedger(db_path=db)
    runs = ledger.list_panel_runs(question_id=qid)
    assert len(runs) == 1
    assert runs[0]["triggered_by"] == "first_forecast"


def test_cli_panel_perspectives_prints_all_five(capsys):
    parser = _parser()
    _run(parser, ["forecast", "panel", "perspectives"])
    out = capsys.readouterr().out
    for name in DEFAULT_PANEL_PERSPECTIVES:
        assert f"=== {name}" in out


def test_cli_panel_perspectives_json_output(capsys):
    parser = _parser()
    _run(parser, ["forecast", "panel", "perspectives", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == set(DEFAULT_PANEL_PERSPECTIVES)
    for prompt in payload.values():
        assert "system" in prompt
        assert "user" in prompt


# ── CLI: forecast update --panel-estimates-json ────────────────────────────


def test_cli_update_with_panel_estimates_aggregates_and_attaches(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "panel.db")
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "new",
            "Will inflation cool by July 2026?",
            "--resolution-criteria",
            "BLS CPI YoY less than 3.0% for the July 2026 release.",
        ],
    )
    import re

    qid = re.search(r"created forecast question (fq_[a-f0-9]+)", capsys.readouterr().out).group(1)
    _run(
        parser,
        [
            "forecast",
            "--db",
            db,
            "update",
            qid,
            "--rationale",
            "Aggregated panel of five perspectives",
            "--panel-estimates-json",
            json.dumps(_five_estimates()),
            "--panel-trim",
            "1",
            "--panel-triggered-by",
            "first_forecast",
        ],
    )
    out = capsys.readouterr().out
    assert "created forecast snapshot" in out
    assert "panel_run:" in out
    assert "aggregate:" in out

    ledger = ForecastLedger(db_path=db)
    snap = ledger.get_current_snapshot(qid)
    expected = aggregate_panel_estimates(_five_estimates(), trim=1).aggregate_probability
    assert snap.probability_or_distribution == pytest.approx(expected, abs=1e-3)
    runs = ledger.list_panel_runs(question_id=qid)
    assert runs[0]["snapshot_id"] == snap.forecast_id


# ── agent tool ──────────────────────────────────────────────────────────────


def test_tool_panel_perspectives_returns_prompts():
    out = json.loads(forecast_ledger_tool({"action": "panel_perspectives"}))
    assert out["success"] is True
    assert set(out["perspectives"]) == set(DEFAULT_PANEL_PERSPECTIVES)
    assert out["catalog"]["outside"]


def test_tool_aggregate_panel():
    out = json.loads(
        forecast_ledger_tool(
            {
                "action": "aggregate_panel",
                "estimates": _five_estimates(),
                "trim": 1,
            }
        )
    )
    assert out["success"] is True
    # The tool serializes via to_dict() which rounds to 6 places.
    assert out["aggregate_probability"] == pytest.approx(
        aggregate_panel_estimates(_five_estimates(), trim=1).aggregate_probability,
        abs=1e-5,
    )


def test_tool_aggregate_panel_requires_estimates():
    out = json.loads(forecast_ledger_tool({"action": "aggregate_panel"}))
    assert out["success"] is False


def test_tool_record_panel_saves(tmp_path):
    db = str(tmp_path / "panel.db")
    create = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will the bill pass in 2026?",
                "resolution_criteria": "Vote tally from the official Senate record.",
            }
        )
    )
    qid = create["question"]["id"]
    out = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_panel",
                "question_id": qid,
                "estimates": _five_estimates(),
                "trim": 1,
                "triggered_by": "first_forecast",
            }
        )
    )
    assert out["success"] is True
    assert out["panel_run"]["aggregate_probability"] == pytest.approx(
        aggregate_panel_estimates(_five_estimates(), trim=1).aggregate_probability,
        abs=1e-5,
    )


def test_tool_show_and_list_panel(tmp_path):
    db = str(tmp_path / "panel.db")
    create = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will it rain on 2026-06-20?",
                "resolution_criteria": "Meteo France observation for 2026-06-20.",
            }
        )
    )
    qid = create["question"]["id"]
    rec = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_panel",
                "question_id": qid,
                "estimates": _five_estimates(),
            }
        )
    )
    pr_id = rec["panel_run"]["id"]
    show = json.loads(
        forecast_ledger_tool({"db": db, "action": "show_panel", "panel_run_id": pr_id})
    )
    assert show["panel_run"]["id"] == pr_id
    listed = json.loads(
        forecast_ledger_tool({"db": db, "action": "list_panel", "question_id": qid})
    )
    assert len(listed["panel_runs"]) == 1


def test_tool_schema_advertises_panel_properties():
    props = FORECAST_LEDGER_SCHEMA["parameters"]["properties"]
    for name in (
        "panel_run_id",
        "estimates",
        "perspectives",
        "trim",
        "method",
        "triggered_by",
    ):
        assert name in props, f"missing schema field: {name}"
    actions = props["action"]["enum"]
    for name in ("record_panel", "aggregate_panel", "show_panel", "list_panel", "panel_perspectives"):
        assert name in actions
