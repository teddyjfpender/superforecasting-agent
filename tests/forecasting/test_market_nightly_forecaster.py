"""AIA P2.1 — the LIVE search-enabled informed forecaster + the market-nightly CLI.

These tests prove the FORWARD, foreknowledge-proof path end to end WITHOUT any live
call: the agent is always MOCKED. Covered:

  * build_informed_market_forecaster returns a float in [0,1] for a market dict when
    the agent emits a JSON forecast, and None when the agent ERRORS or returns
    non-JSON (so record_pending then SKIPS the market),
  * the agent is built with a SEARCH-ENABLED toolset (web is present — this is the
    legitimate live path, NOT closed-book),
  * the CLI `run` path samples (with a mocked source adapter) + records pending with
    BOTH the agent forecast and the de-vigged market price as the baseline,
  * `score` / `report` round-trip on a real (tmp) ledger after a market resolves.

NOTHING here reaches a live market API or a live LLM — the source adapter and the
agent factory are injected/patched.
"""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting import cli
from forecasting import market_nightly_forecaster as mnf
from forecasting.market_nightly import MARKET_BASELINE_TYPE, MARKET_NIGHTLY_ORIGIN


# ── a mock agent: run_conversation returns whatever final_response we hand it ───


class _MockAgent:
    def __init__(self, *, response=None, raises=False, **kwargs):
        self.kwargs = kwargs
        self._response = response
        self._raises = raises
        self.calls = 0

    def run_conversation(self, user_message, system_message=None):
        self.calls += 1
        if self._raises:
            raise RuntimeError("agent blew up")
        return {"final_response": self._response}


def _factory_returning(agent):
    def factory(**kwargs):
        agent.kwargs.update(kwargs)
        return agent

    return factory


def _open_market(mid="m1", *, yes=0.40, close="2030-01-01T00:00:00Z"):
    return {
        "id": mid,
        "source": "manifold",
        "question": f"Will {mid} happen?",
        "resolution_criteria": "Resolves YES if it happens.",
        "probability": yes,
        "close_time": close,
    }


# ── 1. the forecaster: float on JSON, None on error / non-JSON ─────────────────


def test_forecaster_returns_float_when_agent_emits_json():
    agent = _MockAgent(response=json.dumps({"probability": 0.73, "rationale": "fresh search"}))
    forecaster = mnf.build_informed_market_forecaster(
        model="test-model", agent_factory=_factory_returning(agent), discover=False
    )
    p = forecaster(_open_market())
    assert isinstance(p, float)
    assert p == pytest.approx(0.73)
    assert agent.calls == 1


def test_forecaster_search_toolset_includes_web_and_is_not_closed_book():
    # The whole point of the LIVE path: the agent CAN search. "web" MUST be present.
    agent = _MockAgent(response=json.dumps({"probability": 0.5}))
    forecaster = mnf.build_informed_market_forecaster(
        model="test-model", agent_factory=_factory_returning(agent), discover=False
    )
    forecaster(_open_market())
    assert "web" in agent.kwargs["enabled_toolsets"]
    assert agent.kwargs["enabled_toolsets"]  # non-empty (closed-book would be [])


def test_forecaster_returns_none_when_agent_errors():
    agent = _MockAgent(raises=True)
    forecaster = mnf.build_informed_market_forecaster(
        model="m", agent_factory=_factory_returning(agent), discover=False
    )
    assert forecaster(_open_market()) is None


def test_forecaster_returns_none_on_non_json():
    agent = _MockAgent(response="I think it is fairly likely but cannot say.")
    forecaster = mnf.build_informed_market_forecaster(
        model="m", agent_factory=_factory_returning(agent), discover=False
    )
    assert forecaster(_open_market()) is None


def test_forecaster_none_lets_record_pending_skip_the_market(tmp_path):
    from forecasting.market_nightly import record_pending

    ledger = ForecastLedger(tmp_path / "mn.db")
    agent = _MockAgent(raises=True)  # -> forecaster returns None
    forecaster = mnf.build_informed_market_forecaster(
        model="m", agent_factory=_factory_returning(agent), discover=False
    )
    run = record_pending(ledger, [_open_market("skipme")], "2026-06-01T00:00:00Z", forecaster)
    assert run.n_recorded == 0
    assert "skipme" in run.skipped_ids


# ── 2. the CLI run path: sample (mocked source) + record agent_p AND market_p ──


def _run_args(tmp_path, **overrides):
    ns = argparse.Namespace(
        db=str(tmp_path / "mn.db"),
        count=2,
        source="manifold",
        model="test-model",
        rng_seed=0,
        max_iterations=None,
        json=False,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_cli_run_samples_and_records_agent_and_market(tmp_path, monkeypatch):
    markets = [_open_market("a", yes=0.30), _open_market("b", yes=0.80)]

    # Mock the SOURCE adapter (no live API) and the forecaster build (no live agent).
    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.load_open_markets",
        lambda source, *, limit: markets,
    )
    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.build_informed_market_forecaster",
        lambda **kwargs: (lambda market: 0.65),
    )

    cli._cmd_market_nightly_run(_run_args(tmp_path))

    ledger = ForecastLedger(tmp_path / "mn.db")
    questions = [
        q for q in ledger.list_questions()
        if (getattr(q, "metadata", {}) or {}).get("market_nightly")
    ]
    assert len(questions) == 2
    for q in questions:
        snaps = ledger.list_snapshots(q.id)
        assert snaps[0].forecast_origin == MARKET_NIGHTLY_ORIGIN
        assert snaps[0].probability_or_distribution == pytest.approx(0.65)  # agent forecast
        assert snaps[0].calibration_eligible is False  # segregated
        baselines = [
            b for b in ledger.list_baseline_comparisons(q.id)
            if b["baseline_type"] == MARKET_BASELINE_TYPE
        ]
        assert len(baselines) == 1  # de-vigged market price recorded as the baseline


def test_cli_run_resolves_model_with_quorum_logic(tmp_path, monkeypatch):
    # When --model is omitted, the run resolves config["model"] (a dict) with the
    # SAME _resolve_active_model_id logic the quorum uses.
    captured: dict = {}
    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.load_open_markets",
        lambda source, *, limit: [_open_market("a")],
    )

    def fake_build(**kwargs):
        captured.update(kwargs)
        return lambda market: 0.5

    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.build_informed_market_forecaster", fake_build
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"model": {"default": "openrouter/some-model", "provider": "openrouter"}},
    )

    cli._cmd_market_nightly_run(_run_args(tmp_path, model=None))
    assert captured["model"] == "openrouter/some-model"


# ── 3. score / report round-trip on a real tmp ledger (agent mocked upstream) ──


def _seed_recorded(tmp_path):
    from forecasting.market_nightly import record_pending

    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger,
        [_open_market("rt", yes=0.40, close="2026-06-15T00:00:00Z")],
        "2026-06-01T00:00:00Z",
        lambda m: 0.85,  # mocked agent forecast
    )
    assert run.n_recorded == 1
    return ledger, run


def test_cli_score_and_report_round_trip(tmp_path, capsys):
    ledger, run = _seed_recorded(tmp_path)
    qid = run.recorded[0]["question_id"]
    ledger.resolve_question(question_id=qid, outcome="yes", resolution_source="https://x.test/s")

    score_args = argparse.Namespace(db=str(tmp_path / "mn.db"), now=None, json=True)
    cli._cmd_market_nightly_score(score_args)
    score_out = json.loads(capsys.readouterr().out.strip())
    assert score_out["n_scored"] == 1
    assert score_out["scored"][0]["agent_brier"] is not None
    assert score_out["scored"][0]["market_brier"] is not None

    report_args = argparse.Namespace(db=str(tmp_path / "mn.db"), json=True)
    cli._cmd_market_nightly_report(report_args)
    report_out = json.loads(capsys.readouterr().out.strip())
    assert report_out["n_scored"] == 1
    assert report_out["n_pending"] == 0
    # agent (0.85) beats market (0.40 de-vigged) on a YES outcome -> positive edge.
    assert report_out["mean_agent_brier"] < report_out["mean_market_brier"]
    assert report_out["paired_agent_edge_mean_brier"] > 0


def test_cli_run_path_makes_no_live_call(tmp_path, monkeypatch):
    # Belt-and-suspenders: if the source adapter were ever reached it would raise;
    # the mocked source proves the CLI never touches the network in tests.
    def explode(*a, **k):
        raise AssertionError("LIVE network call attempted in a test")

    monkeypatch.setattr("forecasting.source_adapters._read_json_endpoint", explode)
    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.load_open_markets",
        lambda source, *, limit: [_open_market("a")],
    )
    monkeypatch.setattr(
        "forecasting.market_nightly_forecaster.build_informed_market_forecaster",
        lambda **kwargs: (lambda market: 0.5),
    )
    cli._cmd_market_nightly_run(_run_args(tmp_path, count=1))
    ledger = ForecastLedger(tmp_path / "mn.db")
    assert any(
        (getattr(q, "metadata", {}) or {}).get("market_nightly")
        for q in ledger.list_questions()
    )


def test_live_prompt_is_forward_and_encourages_search_not_backtest():
    # Review MAJOR: the live forecaster must NOT reuse the backtest prompt (which says
    # "historical backtest / use only supplied data / do not infer from later info")
    # — that would suppress the fresh search this experiment exists to measure. The
    # forward prompt frames the question as OPEN/future and instructs the agent to search.
    from forecasting.market_nightly_forecaster import build_live_market_messages

    msgs = build_live_market_messages(
        {
            "question": "Will X happen by 2027?",
            "resolution_criteria": "Resolves YES if X occurs.",
            "close_time": "2027-01-01T00:00:00Z",
            "market_source": "manifold",
        }
    )
    blob = " ".join(m["content"].lower() for m in msgs)
    assert "web search" in blob and "open" in blob and "future" in blob  # forward-framed
    assert "historical backtest" not in blob  # NOT the backtest framing
    assert "use only" not in blob
    assert "do not infer from later" not in blob
    assert "probability" in blob  # keeps the JSON schema parse_agent_protocol_response needs
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"


def test_looks_personal_heuristic_excludes_self_referential_markets():
    # Quality gate: Manifold's tail is personal/meta markets that are not researchable
    # skill tests; the study samples only objective real-world questions.
    from forecasting.market_nightly_forecaster import _looks_personal

    for q in [
        "Will I go to the gym this week?",
        "Will my novel be published by mid-2027?",
        "Will this market get 20 unique traders by June 29?",
        "Will we hit our team OKR?",
    ]:
        assert _looks_personal(q), q
    for q in [
        "Will Canada qualify for the round of 16?",
        "Will WTI crude be above $76 on June 30?",
        "Will Serena Williams play singles at Wimbledon 2026?",
    ]:
        assert not _looks_personal(q), q
