"""Market-hidden ForecastBench arm (Slice R3).

Covers the pieces layered on top of the already-shipped baseline-withholding:
the run-level ``arm`` label, and the scoring report (agent vs the WITHHELD market
baseline + the equal-weight log-odds POOL Brier + fitted-simplex complementarity)
computed from a single backtest run via
:func:`forecasting.market_ensemble.market_hidden_pool_report`.

The report math is checked on hand-computable synthetic cases so a regression in
the Brier / pool arithmetic is caught deterministically.
"""

from __future__ import annotations

import math

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.market_ensemble import (
    collect_backtest_market_llm_triples,
    market_hidden_pool_report,
)


def _case(cid: str, *, agent_p: float, market_p: float, outcome: str) -> dict:
    """A minimal scoreable backtest case: an agent forecast + a market baseline
    (marked hidden_from_agent, the arm marker) + a clean binary outcome."""

    as_of = "2099-01-01T00:00:00Z"
    return {
        "id": cid,
        "title": f"Will {cid} happen?",
        "description": "Background.",
        "resolution_criteria": f"Resolves YES if {cid} occurs.",
        "domain": "test",
        "as_of": as_of,
        "simulated_forecast_time": as_of,
        "evidence_cutoff": as_of,
        "resolution_time": "2099-02-01T00:00:00Z",
        "outcome": outcome,
        "probability": agent_p,
        "probability_source": "stub",
        "baselines": [
            {
                "source": "manifold",
                "baseline_type": "market",
                "probability": market_p,
                "as_of": as_of,
                "hidden_from_agent": True,
            }
        ],
    }


def _run(tmp_path) -> tuple[ForecastLedger, str]:
    ledger = ForecastLedger(db_path=str(tmp_path / "mh.db"))
    cases = [
        _case("event-a", agent_p=0.8, market_p=0.6, outcome="yes"),
        _case("event-b", agent_p=0.3, market_p=0.4, outcome="no"),
    ]
    run = ledger.run_backtest_dataset(
        dataset="test:market-hidden", cases=cases, arm="market_hidden"
    )
    return ledger, run["id"]


def test_arm_label_persisted_on_run(tmp_path):
    ledger, run_id = _run(tmp_path)
    run = ledger.get_backtest_run(run_id)
    assert run["result_summary"]["arm"] == "market_hidden"


def test_arm_label_absent_by_default_is_byte_stable(tmp_path):
    # A run with no arm carries NO "arm" key — existing backtest paths unchanged.
    ledger = ForecastLedger(db_path=str(tmp_path / "plain.db"))
    run = ledger.run_backtest_dataset(
        dataset="test:plain",
        cases=[_case("event-a", agent_p=0.8, market_p=0.6, outcome="yes")],
    )
    assert "arm" not in run["result_summary"]


def test_triples_collected_from_run(tmp_path):
    ledger, run_id = _run(tmp_path)
    collected = collect_backtest_market_llm_triples(ledger, run_id)
    assert collected["n"] == 2
    # market/agent/outcome align positionally per case (as_of-ASC == insertion).
    assert collected["sources"]["market"] == pytest.approx([0.6, 0.4])
    assert collected["sources"]["llm"] == pytest.approx([0.8, 0.3])
    assert collected["outcomes"] == pytest.approx([1.0, 0.0])


def test_pool_report_math_is_hand_checkable(tmp_path):
    ledger, run_id = _run(tmp_path)
    report = market_hidden_pool_report(ledger, run_id)

    assert report["n"] == 2
    # agent Brier = mean[(0.8-1)^2, (0.3-0)^2] = mean[0.04, 0.09] = 0.065
    assert report["agent_brier"] == pytest.approx(0.065)
    # market Brier = mean[(0.6-1)^2, (0.4-0)^2] = mean[0.16, 0.16] = 0.16
    assert report["market_brier"] == pytest.approx(0.16)
    # edge = market_brier - agent_brier (positive == agent beat the withheld price)
    assert report["agent_edge_vs_market"] == pytest.approx(0.095)
    # agent wins BOTH per-case Brier head-to-heads
    assert report["win_rate_vs_market"] == pytest.approx(1.0)

    # equal-weight log-odds pool, computed independently here.
    def _pool(m, a):
        lo = (math.log(m / (1 - m)) + math.log(a / (1 - a))) / 2.0
        return 1.0 / (1.0 + math.exp(-lo))

    p_a = _pool(0.6, 0.8)  # ~0.7102
    p_b = _pool(0.4, 0.3)  # ~0.3483
    expected_pool_brier = ((p_a - 1.0) ** 2 + (p_b - 0.0) ** 2) / 2.0
    assert report["pooled_brier"] == pytest.approx(expected_pool_brier, abs=1e-6)
    # the pool beats the market but NOT the (strong) agent -> not "beats both".
    assert report["pooled_brier"] < report["market_brier"]
    assert report["pooled_brier"] > report["agent_brier"]
    assert report["pool_beats_both"] is False


def test_pool_beats_both_when_sources_are_complementary(tmp_path):
    # Construct rows where agent and market each miss on DIFFERENT questions so the
    # pool (which splits the difference) beats both standalones.
    ledger = ForecastLedger(db_path=str(tmp_path / "comp.db"))
    cases = [
        # market confident-right, agent confident-wrong.
        _case("q1", agent_p=0.2, market_p=0.8, outcome="yes"),
        # agent confident-right, market confident-wrong.
        _case("q2", agent_p=0.8, market_p=0.2, outcome="yes"),
    ]
    run = ledger.run_backtest_dataset(dataset="test:comp", cases=cases, arm="market_hidden")
    report = market_hidden_pool_report(ledger, run["id"])
    # By symmetry each standalone Brier is (0.8-1)^2==0.04 averaged with (0.2-1)^2==0.64
    # -> 0.34; the equal-weight pool lands at 0.5 each -> Brier 0.25 < 0.34.
    assert report["agent_brier"] == pytest.approx(0.34)
    assert report["market_brier"] == pytest.approx(0.34)
    assert report["pooled_brier"] == pytest.approx(0.25)
    assert report["pool_beats_both"] is True


def test_cli_report_prints_comparison_table(tmp_path, capsys):
    from forecasting.cli import _print_market_hidden_report

    ledger, run_id = _run(tmp_path)
    _print_market_hidden_report(ledger, run_id)
    out = capsys.readouterr().out
    assert "market-hidden arm" in out
    assert "agent Brier" in out
    assert "market Brier" in out
    assert "win-rate vs market" in out
    assert "pooled (agent+market log-odds) Brier" in out
    # the fitted-simplex complementarity block always prints its LOO line (the
    # fitted-weights line only appears once n >= min_sample).
    assert "loo_ensemble_brier" in out
    assert "blend beats BOTH (LOO)" in out
    # the withheld market price never appears in the report either.
    assert "0.62" not in out


def test_report_ignores_unscored_and_nonmarket(tmp_path):
    # A run whose cases carry only a naive baseline yields no market triples.
    ledger = ForecastLedger(db_path=str(tmp_path / "nomkt.db"))
    case = _case("event-a", agent_p=0.8, market_p=0.6, outcome="yes")
    case["baselines"] = [
        {"source": "auto", "baseline_type": "naive_0_5", "probability": 0.5,
         "as_of": "2099-01-01T00:00:00Z"}
    ]
    run = ledger.run_backtest_dataset(dataset="test:nomkt", cases=[case])
    report = market_hidden_pool_report(ledger, run["id"])
    assert report["n"] == 0
    assert report["agent_brier"] is None
    assert report["market_brier"] is None
    assert report["pool_beats_both"] is False
