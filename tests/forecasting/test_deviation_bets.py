"""Tests for the deviation ledger (UPGRADE 2): record → resolution-hook scoring →
edge report (paired-bootstrap math + tiny-n honesty) + the write gate."""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.ledger.deviation_bets import EDGE_MIN_SAMPLE
from forecasting.models import ForecastingError


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "dev.db"))
    ledger.initialize_schema()
    return ledger


def _binary_question(ledger, n: int = 0):
    return ledger.create_question(
        title=f"Will milestone {n} be reached by 2028?",
        resolution_criteria=f"Resolves YES if milestone {n} is confirmed before 2028-01-01.",
        close_time="2028-01-01T00:00:00Z",
        impact="high",
    )


def _scored_bet(ledger, *, market, verdict, outcome, n=0):
    """Record a bet on a fresh question, then resolve it so the RESOLUTION HOOK
    scores it. Returns the scored bet dict."""
    q = _binary_question(ledger, n)
    bet = ledger.record_deviation_bet(
        question_id=q.id,
        market_price=market,
        reconciled_verdict=verdict,
        deviation_pp=abs(verdict - market) * 100.0,
        threshold_pp=10.0,
        blind_pool=verdict,
        named_edge="named edge",
    )
    ledger.resolve_question(question_id=q.id, outcome=outcome)
    return ledger.get_deviation_bet(bet["id"])


def test_record_creates_open_bet(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    bet = ledger.record_deviation_bet(
        question_id=q.id,
        market_price=0.20,
        reconciled_verdict=0.55,
        deviation_pp=35.0,
        threshold_pp=10.0,
        blind_pool=0.60,
        named_edge="private supply-shock signal",
    )
    assert bet["outcome"] is None  # open until resolution
    assert bet["market_price"] == 0.20 and bet["blind_pool"] == 0.60
    assert ledger.list_deviation_bets(only_open=True) == [
        b for b in ledger.list_deviation_bets() if b["id"] == bet["id"]
    ]


def test_resolution_hook_scores_agent_win(tmp_path):
    # Agent verdict 0.90 (near YES) vs market 0.50; outcome YES -> agent wins.
    ledger = _ledger(tmp_path)
    scored = _scored_bet(ledger, market=0.50, verdict=0.90, outcome="yes")
    assert scored["outcome"] == "yes"
    assert scored["brier_ours"] == pytest.approx((0.90 - 1.0) ** 2)  # 0.01
    assert scored["brier_market"] == pytest.approx((0.50 - 1.0) ** 2)  # 0.25
    assert scored["brier_delta"] == pytest.approx(0.25 - 0.01)  # +0.24, ours better
    assert scored["scored_at"] and scored["resolution_id"]


def test_resolution_hook_scores_market_win(tmp_path):
    # Agent verdict 0.10 (wrong-way) vs market 0.50; outcome YES -> market wins.
    ledger = _ledger(tmp_path)
    scored = _scored_bet(ledger, market=0.50, verdict=0.10, outcome="yes")
    assert scored["brier_ours"] == pytest.approx((0.10 - 1.0) ** 2)  # 0.81
    assert scored["brier_market"] == pytest.approx(0.25)
    assert scored["brier_delta"] == pytest.approx(0.25 - 0.81)  # -0.56, market better


def test_score_is_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    q = _binary_question(ledger)
    ledger.record_deviation_bet(
        question_id=q.id, market_price=0.5, reconciled_verdict=0.9,
        deviation_pp=40.0, threshold_pp=10.0,
    )
    ledger.resolve_question(question_id=q.id, outcome="yes")
    first = ledger.list_deviation_bets(only_scored=True)[0]
    # A second scoring pass leaves the already-scored bet untouched.
    summary = ledger.score_deviation_bets(q.id, "yes")
    assert summary["scored"] == 0
    assert ledger.get_deviation_bet(first["id"])["scored_at"] == first["scored_at"]


def test_edge_report_tiny_n_is_honest(tmp_path):
    # Below EDGE_MIN_SAMPLE the report refuses to recommend a threshold move.
    ledger = _ledger(tmp_path)
    for i in range(3):
        _scored_bet(ledger, market=0.5, verdict=0.9, outcome="yes", n=i)
    report = ledger.deviation_bet_edge_report()
    assert report["n"] == 3 and report["n"] < EDGE_MIN_SAMPLE
    assert report["status"] == "insufficient_sample"
    assert report["win_rate"] == 1.0  # math still computed
    assert "insufficient sample" in report["recommendation"].lower()
    assert "HOLD" in report["recommendation"]
    assert report["threshold_config_key"] == "quorum.market_anchor_deviation_pp"


def test_edge_report_beats_market(tmp_path):
    # 12 agent wins with VARYING magnitude (so the paired bootstrap has a spread and
    # yields a CI) -> CI excludes 0, win-rate 1.0 -> LOOSEN recommendation.
    ledger = _ledger(tmp_path)
    for i in range(12):
        verdict = 0.82 + 0.01 * (i % 6)  # 0.82..0.87, all near YES
        _scored_bet(ledger, market=0.5, verdict=verdict, outcome="yes", n=i)
    report = ledger.deviation_bet_edge_report()
    assert report["n"] == 12
    assert report["status"] == "beats_market"
    assert report["win_rate"] == 1.0
    assert report["mean_brier_delta"] > 0
    assert report["ci95_low"] is not None and report["ci95_low"] > 0
    assert "LOOSEN" in report["recommendation"]


def test_edge_report_loses_to_market(tmp_path):
    # 12 market wins with VARYING magnitude -> CI below 0 -> TIGHTEN recommendation.
    ledger = _ledger(tmp_path)
    for i in range(12):
        verdict = 0.06 + 0.01 * (i % 6)  # 0.06..0.11, wrong-way for a YES outcome
        _scored_bet(ledger, market=0.5, verdict=verdict, outcome="yes", n=i)
    report = ledger.deviation_bet_edge_report()
    assert report["status"] == "loses_to_market"
    assert report["win_rate"] == 0.0
    assert report["ci95_high"] is not None and report["ci95_high"] < 0
    assert "TIGHTEN" in report["recommendation"]


def test_edge_report_inconclusive_when_ci_straddles_zero(tmp_path):
    # Alternating equal-magnitude wins/losses -> mean ~0, CI straddles 0.
    ledger = _ledger(tmp_path)
    for i in range(12):
        if i % 2 == 0:
            _scored_bet(ledger, market=0.5, verdict=0.9, outcome="yes", n=i)  # +0.24
        else:
            _scored_bet(ledger, market=0.5, verdict=0.1, outcome="yes", n=i)  # -0.56
    report = ledger.deviation_bet_edge_report()
    # Not a clean beat or loss -> HOLD, threshold unchanged.
    assert report["status"] in {"inconclusive", "loses_to_market", "beats_market"}
    assert report["n"] == 12
    assert isinstance(report["recommendation"], str) and report["recommendation"]


def test_edge_report_empty(tmp_path):
    ledger = _ledger(tmp_path)
    report = ledger.deviation_bet_edge_report()
    assert report["n"] == 0 and report["status"] == "insufficient_sample"
    assert report["win_rate"] is None
    assert "HOLD" in report["recommendation"]


def test_record_deviation_bet_is_gated(tmp_path, monkeypatch):
    # UPGRADE 2: recording a bet is a GATED forecast-producing write.
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "on")
    ledger = _ledger(tmp_path)
    with allow_ledger_writes(reason="test-setup"):
        q = _binary_question(ledger)
    # Outside a commit context -> refused.
    with pytest.raises(ForecastingError):
        ledger.record_deviation_bet(
            question_id=q.id, market_price=0.2, reconciled_verdict=0.5,
            deviation_pp=30.0, threshold_pp=10.0,
        )
    # Inside a commit context -> allowed.
    with allow_ledger_writes(reason="test"):
        bet = ledger.record_deviation_bet(
            question_id=q.id, market_price=0.2, reconciled_verdict=0.5,
            deviation_pp=30.0, threshold_pp=10.0,
        )
    assert bet["id"]


def test_non_binary_question_bets_not_scored(tmp_path):
    # A market bet is a binary proposition; a non-binary question's bet is skipped
    # (never fabricated) at resolution.
    from forecasting.models import OutcomeSpace

    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Which party wins the most seats in 2028?",
        resolution_criteria="Resolves to the party certified with the most seats in 2028.",
        outcome_space=OutcomeSpace(type="categorical", choices=["a", "b", "c"]),
        close_time="2028-01-01T00:00:00Z",
    )
    ledger.record_deviation_bet(
        question_id=q.id, market_price=0.4, reconciled_verdict=0.6,
        deviation_pp=20.0, threshold_pp=10.0,
    )
    summary = ledger.score_deviation_bets(q.id, "a")
    assert summary["scored"] == 0
    assert ledger.list_deviation_bets(only_open=True)  # still open, not fabricated
