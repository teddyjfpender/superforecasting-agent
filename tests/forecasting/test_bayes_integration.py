"""Integration tests: Bayesian toolkit wired into the CLI, agent tool, the
native forecast-update pooling path, and the forecast protocol guidance."""

from __future__ import annotations

import argparse
import json
import re

import pytest

from forecasting.cli import register_cli
from forecasting.protocol import build_protocol_messages
from forecasting.ledger import ForecastLedger
from tools.forecasting_tool import forecast_ledger_tool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    subparsers = parser.add_subparsers(dest="command")
    register_cli(subparsers)
    return parser


def _run(parser: argparse.ArgumentParser, argv: list[str]) -> None:
    # Legacy fixtures predate the default-on structured-reasoning formality for
    # live forecasts; opt live update commands carrying a payload out at the
    # harness so they keep testing their actual concern.
    _payload = (
        "--probability", "--numeric-value", "--distribution-json",
        "--panel-estimates-json", "--component", "--component-json", "--method",
    )
    if (
        "update" in argv
        and any(f in argv for f in _payload)
        and "--reason-up" not in argv
        and "--require-structured-reasoning" not in argv
        and "--no-require-structured-reasoning" not in argv
        and "exploratory" not in argv
    ):
        argv = [*argv, "--no-require-structured-reasoning"]
    args = parser.parse_args(argv)
    args.func(args)


# ── CLI: forecast bayes ──────────────────────────────────────────────────────


def test_cli_bayes_lists_actions(capsys):
    _run(_parser(), ["forecast", "bayes"])
    out = capsys.readouterr().out
    assert "Bayesian scratchpad actions" in out
    assert "lr_update" in out
    assert "combine" in out
    assert "forecast_diff" in out


def test_cli_bayes_lr_update_rationale(capsys):
    _run(_parser(), ["forecast", "bayes", "lr_update", "--input", '{"prior_p":0.62,"lrs":[0.85,0.70,1.25]}'])
    out = capsys.readouterr().out
    assert "posterior" in out
    assert "implied LR" in out


def test_cli_bayes_combine_json(capsys):
    payload = json.dumps({
        "components": [
            {"name": "markets", "p": 0.555, "weight": 0.30},
            {"name": "base_rate", "p": 0.75, "weight": 0.25},
        ],
        "method": "log_odds_pool",
        "extremize": 1.05,
        "correlation_matrix": "estimate",
    })
    _run(_parser(), ["forecast", "bayes", "combine", "--input", payload, "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["action"] == "combine"
    assert 0.0 < data["result"]["probability"] < 1.0
    assert data["result"]["correlation_applied"] is True


def test_cli_bayes_invalid_json_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        _run(_parser(), ["forecast", "bayes", "lr_update", "--input", "{not json}"])
    assert exc.value.code == 2


# ── Agent tool: forecast_ledger action="bayes" ───────────────────────────────


def test_tool_bayes_combine():
    out = json.loads(forecast_ledger_tool({
        "action": "bayes",
        "bayes_action": "combine",
        "bayes_payload": {
            "components": [{"name": "m", "p": 0.55}, {"name": "b", "p": 0.75}],
            "correlation_matrix": "estimate",
        },
    }))
    assert out["success"] is True
    assert out["bayes_action"] == "combine"
    assert 0.0 < out["result"]["probability"] < 1.0
    assert "rationale" in out


def test_tool_bayes_requires_action():
    out = json.loads(forecast_ledger_tool({"action": "bayes"}))
    assert out["success"] is False
    assert "bayes_action is required" in out["error"]


def test_tool_bayes_missing_field_is_clean_error():
    out = json.loads(forecast_ledger_tool({
        "action": "bayes", "bayes_action": "lr_update", "bayes_payload": {},
    }))
    assert out["success"] is False
    assert "prior_p" in out["error"]


def test_tool_bayes_forecast_diff():
    out = json.loads(forecast_ledger_tool({
        "action": "bayes",
        "bayes_action": "forecast_diff",
        "bayes_payload": {
            "previous": 0.621, "current": 0.593,
            "components": [
                {"name": "polling", "delta_pts": -0.02},
                {"name": "markets", "delta_pts": 0.008},
            ],
        },
    }))
    assert out["success"] is True
    total = sum(d["contribution_pts"] for d in out["result"]["drivers"])
    assert total == pytest.approx(out["result"]["net_change"] * 100, abs=0.1)


# ── Native pooling in forecast update ────────────────────────────────────────


def _new_question(parser, db, capsys) -> str:
    _run(parser, [
        "forecast", "--db", db, "new", "Will candidate R win the race?",
        "--resolution-criteria",
        "Resolves yes if the Republican nominee is certified as the winner by the Secretary of State; otherwise no.",
        "--close-time", "2026-11-03T00:00:00Z", "--domain", "elections",
    ])
    out = capsys.readouterr().out
    return re.search(r"created forecast question (fq_[a-f0-9]+)", out).group(1)


_COMPONENTS = json.dumps({
    "components": [
        {"name": "markets", "probability": 0.555, "weight": 0.30},
        {"name": "polling", "probability": 0.49, "weight": 0.25},
        {"name": "ratings", "probability": 0.62, "weight": 0.20},
        {"name": "base_rate", "probability": 0.75, "weight": 0.25},
    ]
})


def _preview_probability(parser, db, qid, method_args, capsys) -> float:
    _run(parser, [
        "forecast", "--db", db, "update", qid, "--component-json", _COMPONENTS,
        "--rationale", "test", "--preview", *method_args,
    ])
    out = capsys.readouterr().out
    return float(re.search(r"proposed_probability: ([0-9.]+)", out).group(1))


def test_update_log_odds_pool_differs_from_linear(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "bayes.db")
    qid = _new_question(parser, db, capsys)

    linear = _preview_probability(parser, db, qid, ["--method", "weighted_ensemble"], capsys)
    log_odds = _preview_probability(
        parser, db, qid,
        ["--method", "log_odds_pool", "--extremize", "1.05", "--correlation", "estimate"],
        capsys,
    )
    # Linear weighted average of the components is ~0.60; log-odds pooling with
    # extremization lands slightly higher and is a distinct, auditable number.
    assert linear == pytest.approx(0.601, abs=0.01)
    assert log_odds != pytest.approx(linear, abs=1e-3)
    assert 0.0 < log_odds < 1.0


def test_update_log_odds_pool_persists_method(tmp_path, capsys):
    parser = _parser()
    db = str(tmp_path / "bayes2.db")
    qid = _new_question(parser, db, capsys)
    _run(parser, [
        "forecast", "--db", db, "update", qid, "--component-json", _COMPONENTS,
        "--method", "log_odds_pool", "--rationale", "pooled via bayes toolkit",
    ])
    assert "created forecast snapshot" in capsys.readouterr().out
    snapshot = ForecastLedger(db).get_current_snapshot(qid)
    assert snapshot.method == "log_odds_pool"


# ── Protocol guidance points at the toolkit ──────────────────────────────────


def test_protocol_update_stage_recommends_bayes(tmp_path):
    db = str(tmp_path / "proto.db")
    ledger = ForecastLedger(db)
    question = ledger.create_question(
        title="Will the measure pass?",
        resolution_criteria="Resolves yes if the measure is certified as passed; otherwise no.",
    )
    messages = build_protocol_messages(ledger, question.id, stage="update")
    text = "\n".join(m.content for m in messages)
    assert "log_odds_pool" in text
    assert "forecast_diff" in text


def test_cli_bayes_lists_conditional_chain(capsys):
    _run(_parser(), ["forecast", "bayes"])
    out = capsys.readouterr().out
    assert "conditional_chain" in out


def test_cli_bayes_conditional_chain_passes(capsys):
    payload = json.dumps({
        "target_name": "London hit by nuclear strike",
        "links": [
            {"name": "A", "condition": "Russia uses tac nuke", "probability": 0.05},
            {"name": "B|A", "probability": 0.4},
            {"name": "C|A,B", "probability": 0.1},
        ],
        "unconditional_estimate": 0.002,
        "tolerance": 2.0,
    })
    _run(_parser(), ["forecast", "bayes", "conditional_chain", "--input", payload])
    out = capsys.readouterr().out
    assert "Chain product" in out
    assert "Unconditional sanity-check" in out
    assert "passes" in out


def test_cli_bayes_conditional_chain_flags_divergence(capsys):
    payload = json.dumps({
        "links": [{"probability": 0.4}, {"probability": 0.5}],
        "unconditional_estimate": 0.02,
    })
    _run(_parser(), ["forecast", "bayes", "conditional_chain", "--input", payload])
    out = capsys.readouterr().out
    assert "FLAGGED" in out
    assert "above" in out


def test_cli_bayes_conditional_chain_json_output(capsys):
    payload = json.dumps({
        "links": [{"probability": 0.5}],
        "unconditional_estimate": 0.5,
    })
    _run(_parser(), ["forecast", "bayes", "conditional_chain", "--input", payload, "--json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["action"] == "conditional_chain"
    assert data["result"]["flagged"] is False
    assert data["result"]["chain_product"] == pytest.approx(0.5, rel=1e-9)


def test_tool_bayes_conditional_chain():
    out = json.loads(forecast_ledger_tool({
        "action": "bayes",
        "bayes_action": "conditional_chain",
        "bayes_payload": {
            "target_name": "Rare event X",
            "links": [{"probability": 0.5}, {"probability": 0.4}],
            "unconditional_estimate": 0.18,
        },
    }))
    assert out["success"] is True
    assert out["bayes_action"] == "conditional_chain"
    assert out["result"]["chain_product"] == pytest.approx(0.2, rel=1e-3)
    assert out["result"]["flagged"] is False
    assert "Chain product" in out["rationale"]


def test_tool_bayes_conditional_chain_requires_unconditional():
    out = json.loads(forecast_ledger_tool({
        "action": "bayes",
        "bayes_action": "conditional_chain",
        "bayes_payload": {"links": [{"probability": 0.5}]},
    }))
    assert out["success"] is False
    assert "unconditional_estimate" in out["error"]
