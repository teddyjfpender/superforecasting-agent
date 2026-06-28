"""AIA P2.1 — the MarketNightly foreknowledge-proof live benchmark.

Covers:
  * sample_open_markets keeps ONLY strictly-future-close markets (a market closing
    exactly AT, or just before, as_of is REJECTED — the foreknowledge invariant),
  * the sampler is seed-deterministic and respects n,
  * record_pending RE-ASSERTS the invariant: a non-future-close entry is rejected +
    counted, never stored,
  * a full lifecycle on a real (tmp) ledger + FAKE market source + FAKE forecaster:
    record_pending -> (time passes, market resolves) -> score_matured scores BOTH the
    agent and the market baseline against the binary outcome -> market_nightly_report
    surfaces n_scored + the paired agent-vs-market edge,
  * nothing calls a live API (the seams are injected callables; the offline default
    de-vig is pure),
  * a HARD GUARD that no existing default changed: market-nightly snapshots are
    segregated (origin tag, calibration_eligible=False) and the live calibration book
    is untouched.
"""

from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace
from forecasting.market_nightly import (
    MARKET_BASELINE_TYPE,
    MARKET_NIGHTLY_ORIGIN,
    MarketNightlyRun,
    default_market_devig,
    market_nightly_report,
    record_pending,
    sample_open_markets,
    score_matured,
)

AS_OF = "2026-06-01T00:00:00Z"


def _market(mid, *, close, yes=0.6, **extra):
    m = {"id": mid, "question": f"Will {mid} happen?", "probability": yes, "close_time": close}
    m.update(extra)
    return m


# ── 1. the pure foreknowledge-proof sampler ───────────────────────────────────


def test_sampler_keeps_only_strictly_future_close():
    markets = [
        _market("future", close="2026-07-01T00:00:00Z"),  # strictly after -> kept
        _market("exact", close=AS_OF),                     # exactly at -> REJECTED
        _market("past", close="2026-05-01T00:00:00Z"),     # before -> REJECTED
        _market("just_before", close="2026-05-31T23:59:59Z"),  # 1s before -> REJECTED
    ]
    res = sample_open_markets(markets, AS_OF, n=10)
    kept = {m["id"] for m in res["sampled"]}
    assert kept == {"future"}
    assert res["admissible"] == 1
    assert res["rejected"] == 3
    assert set(res["rejected_ids"]) == {"exact", "past", "just_before"}


def test_sampler_is_seed_deterministic_and_respects_n():
    markets = [_market(f"m{i}", close="2026-07-01T00:00:00Z") for i in range(20)]
    a = sample_open_markets(markets, AS_OF, n=5, rng_seed=42)
    b = sample_open_markets(markets, AS_OF, n=5, rng_seed=42)
    assert [m["id"] for m in a["sampled"]] == [m["id"] for m in b["sampled"]]
    assert len(a["sampled"]) == 5  # respects n
    # A different seed generally reorders the pick.
    c = sample_open_markets(markets, AS_OF, n=5, rng_seed=7)
    assert [m["id"] for m in c["sampled"]] != [m["id"] for m in a["sampled"]]
    # Order of the incoming list must not change the seeded pick.
    shuffled = list(reversed(markets))
    d = sample_open_markets(shuffled, AS_OF, n=5, rng_seed=42)
    assert {m["id"] for m in d["sampled"]} == {m["id"] for m in a["sampled"]}


def test_sampler_missing_close_is_rejected():
    markets = [{"id": "no_close", "probability": 0.5}]
    res = sample_open_markets(markets, AS_OF, n=10)
    assert res["sampled"] == []
    assert res["rejected"] == 1


def test_offline_devig_is_pure_and_handles_quotes():
    # Single YES price de-vigs to itself.
    assert default_market_devig(_market("x", close="2026-07-01T00:00:00Z", yes=0.4)) == pytest.approx(0.4)
    # Paired bid/ask de-vigs (removes the overround).
    m = {"id": "y", "bid_yes": 0.50, "ask_yes": 0.54, "bid_no": 0.50, "ask_no": 0.54}
    assert default_market_devig(m) == pytest.approx(0.5, abs=1e-9)


# ── 2. record_pending invariant ────────────────────────────────────────────────


def test_record_pending_rejects_non_future_close(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    sampled = [
        _market("ok", close="2026-07-01T00:00:00Z"),
        _market("stale", close="2026-05-01T00:00:00Z"),  # close <= as_of -> must be rejected
        _market("exact", close=AS_OF),                   # exactly at as_of -> must be rejected
    ]
    run = record_pending(ledger, sampled, AS_OF, lambda m: 0.7)
    assert isinstance(run, MarketNightlyRun)
    assert run.n_recorded == 1
    assert set(run.rejected_ids) == {"stale", "exact"}
    # Only the admissible market produced a stored question/snapshot.
    assert run.recorded[0]["market_id"] == "ok"
    assert ledger.list_snapshots(run.recorded[0]["question_id"])[0].forecast_origin == MARKET_NIGHTLY_ORIGIN


def test_record_pending_stores_agent_and_market_baseline(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger,
        [_market("m", close="2026-07-01T00:00:00Z", yes=0.62)],
        AS_OF,
        lambda m: 0.71,
    )
    qid = run.recorded[0]["question_id"]
    snap = ledger.list_snapshots(qid)[0]
    assert snap.probability_or_distribution == pytest.approx(0.71)  # agent forecast stored
    assert snap.calibration_eligible is False  # segregated from the live calibration book
    baselines = ledger.list_baseline_comparisons(qid)
    market_bl = [b for b in baselines if b["baseline_type"] == MARKET_BASELINE_TYPE]
    assert len(market_bl) == 1
    assert market_bl[0]["probability_or_distribution"] == pytest.approx(0.62)  # de-vigged market price


def test_record_pending_is_idempotent_per_market(tmp_path):
    # Re-sampling the SAME still-open market on a later night must NOT duplicate it.
    ledger = ForecastLedger(tmp_path / "mn.db")
    market = _market("repeat", close="2026-07-01T00:00:00Z")
    first = record_pending(ledger, [market], AS_OF, lambda m: 0.7)
    assert first.n_recorded == 1
    second = record_pending(ledger, [market], "2026-06-02T00:00:00Z", lambda m: 0.7)
    assert second.n_recorded == 0           # already has an entry -> not stored again
    assert "repeat" in second.skipped_ids
    mn_questions = [
        q for q in ledger.list_questions()
        if (getattr(q, "metadata", {}) or {}).get("market_id") == "repeat"
    ]
    assert len(mn_questions) == 1           # exactly ONE question for this market id


def test_malformed_close_is_rejected_without_crashing_the_sweep(tmp_path):
    # A single market with a garbage close timestamp must be REJECTED, never raise
    # (one bad market must not abort the whole sweep).
    markets = [
        _market("good", close="2026-07-01T00:00:00Z"),
        _market("garbage", close="not-a-timestamp"),
    ]
    res = sample_open_markets(markets, AS_OF, n=10)  # must not raise
    assert {m["id"] for m in res["sampled"]} == {"good"}
    assert "garbage" in res["rejected_ids"]
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, markets, AS_OF, lambda m: 0.7)  # must not raise
    assert run.n_recorded == 1
    assert run.recorded[0]["market_id"] == "good"


# ── 3 + 4. full lifecycle: record -> resolve -> score -> report ────────────────


def _resolve_yes(ledger, qid):
    ledger.resolve_question(question_id=qid, outcome="yes", resolution_source="https://example.test/settle")


def test_full_lifecycle_scores_agent_and_market_and_reports_paired_edge(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")

    # FAKE market source: a handful of currently-OPEN markets closing in the future.
    markets = [
        _market("a", close="2026-06-15T00:00:00Z", yes=0.55),
        _market("b", close="2026-06-20T00:00:00Z", yes=0.40),
        _market("c", close="2026-06-25T00:00:00Z", yes=0.70),
    ]
    picked = sample_open_markets(markets, AS_OF, n=3, rng_seed=1)
    assert len(picked["sampled"]) == 3

    # FAKE forecaster: the agent is sharper than the market toward YES on every market
    # (so the paired edge is well-defined and the agent wins).
    run = record_pending(ledger, picked["sampled"], picked["as_of"], lambda m: 0.85)
    assert run.n_recorded == 3

    # Before any market closes, NOTHING is scoreable (the markets resolve in the future).
    early = score_matured(ledger, now="2026-06-10T00:00:00Z")
    assert early["n_scored"] == 0
    assert early["n_still_pending"] == 3

    # Time passes; every market closes and resolves YES (the agent's directional call).
    for row in run.recorded:
        _resolve_yes(ledger, row["question_id"])

    matured = score_matured(ledger, now="2026-07-01T00:00:00Z")
    assert matured["n_scored"] == 3
    for row in matured["scored"]:
        assert row["agent_brier"] is not None
        assert row["market_brier"] is not None
        # Agent (0.85) beats the market on a YES outcome (lower Brier is better).
        assert row["agent_brier"] < row["market_brier"]

    report = market_nightly_report(ledger)
    assert report["n_scored"] == 3
    assert report["n_pending"] == 0
    assert report["mean_agent_brier"] < report["mean_market_brier"]
    # POSITIVE paired edge == agent better (delta = market_brier - agent_brier).
    assert report["paired_agent_edge_mean_brier"] > 0
    assert report["paired_agent_wins"] == 3
    assert report["paired_baseline_wins"] == 0

    # score_matured is idempotent — re-running scores nothing new.
    again = score_matured(ledger, now="2026-07-01T00:00:00Z")
    assert again["n_scored"] == 3  # still finds them (already-scored, but reports them)
    report_again = market_nightly_report(ledger)
    assert report_again["n_scored"] == 3


def test_report_treats_unresolved_entries_as_pending(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger,
        [_market("x", close="2026-06-15T00:00:00Z"), _market("y", close="2026-06-20T00:00:00Z")],
        AS_OF,
        lambda m: 0.6,
    )
    # Resolve only ONE; the other stays pending.
    _resolve_yes(ledger, run.recorded[0]["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")
    report = market_nightly_report(ledger)
    assert report["n_scored"] == 1
    assert report["n_pending"] == 1


# ── HARD GUARD: no live API, no existing default changed ───────────────────────


def test_market_nightly_does_not_pollute_the_live_calibration_book(tmp_path):
    """A live forecast committed alongside the benchmark keeps its OWN scoring path;
    the benchmark snapshots never enter the live (calibration-eligible) score set."""
    ledger = ForecastLedger(tmp_path / "mn.db")

    # A genuine LIVE question + resolved score (the curated book).
    live_q = ledger.create_question(
        title="Will the live indicator print above target?",
        resolution_criteria="Resolves to the official value on the close date.",
        outcome_space=OutcomeSpace(type="binary"),
        domain="macro",
    )
    ledger.create_snapshot(question_id=live_q.id, probability_or_distribution=0.6, rationale="live call")
    ledger.resolve_question(question_id=live_q.id, outcome="yes", resolution_source="https://example.test/live")
    live_scores_before = ledger.list_scores(forecast_origin="live", calibration_eligible=None)
    assert len(live_scores_before) == 1

    # Run the benchmark: record + resolve + score.
    run = record_pending(
        ledger, [_market("bench", close="2026-06-15T00:00:00Z")], AS_OF, lambda m: 0.8
    )
    _resolve_yes(ledger, run.recorded[0]["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")

    # The LIVE calibration-eligible score set is unchanged — the benchmark did not leak in.
    live_scores_after = ledger.list_scores(forecast_origin="live", calibration_eligible=None)
    assert len(live_scores_after) == 1
    # The benchmark scores live under the segregated origin only.
    mn_scores = ledger.list_scores(forecast_origin=MARKET_NIGHTLY_ORIGIN, calibration_eligible=None)
    assert len(mn_scores) == 1
    assert all(not s.calibration_eligible for s in mn_scores)


def test_record_pending_makes_no_network_call(tmp_path, monkeypatch):
    """The market source + forecaster are injected seams; record_pending must never
    open a socket. We hard-fail any socket creation to prove it offline."""
    import socket

    def _boom(*_a, **_k):
        raise AssertionError("market-nightly must not contact the network")

    monkeypatch.setattr(socket, "socket", _boom)
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger, [_market("offline", close="2026-07-01T00:00:00Z")], AS_OF, lambda m: 0.5
    )
    assert run.n_recorded == 1
    # The offline default de-vig is also pure (no socket).
    assert default_market_devig(_market("z", close="2026-07-01T00:00:00Z", yes=0.33)) == pytest.approx(0.33)
