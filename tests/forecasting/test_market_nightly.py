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
    CONTEMPORANEOUS_THRESHOLD_SECONDS,
    MARKET_BASELINE_TYPE,
    MARKET_NIGHTLY_ORIGIN,
    MarketNightlyRun,
    baseline_is_contemporaneous,
    default_market_devig,
    market_id,
    market_nightly_report,
    market_price_asof,
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


# ── BOUNDED PARALLELISM over the per-market forecaster (max_workers > 1) ────────
#
# The forecaster is the slow seam (~75s search-agent calls); record_pending can
# fan it out across a ThreadPoolExecutor while keeping every ledger write
# serialized. These tests MOCK the forecaster (no live agent) and prove:
#   * max_workers=4 records the SAME set as max_workers=1 (order-independent),
#   * ledger writes are not corrupted under concurrency (one clean snapshot +
#     market baseline per recorded market, correct agent/market numbers),
#   * a forecaster that returns None for some markets still SKIPS exactly those,
#   * the strictly-future-close foreknowledge filter STILL applies in parallel.


def _future_markets(n, *, base_yes=0.6):
    # All close strictly after AS_OF -> all admissible. Distinct yes prices so a
    # per-market mix-up under concurrency would show up in the stored baselines.
    return [
        _market(f"m{i}", close="2026-07-01T00:00:00Z", yes=round(base_yes - 0.01 * i, 4))
        for i in range(n)
    ]


def _recorded_index(run):
    """market_id -> recorded row (so assertions are order-independent)."""
    return {row["market_id"]: row for row in run.recorded}


def test_parallel_records_same_set_as_sequential(tmp_path):
    markets = _future_markets(8)
    # A per-market forecast keyed off the market id so we can verify each market's
    # OWN number landed on its OWN snapshot (no cross-thread bleed).
    def forecaster(m):
        return 0.10 + 0.05 * int(market_id(m)[1:])

    seq_ledger = ForecastLedger(tmp_path / "seq.db")
    seq = record_pending(seq_ledger, markets, AS_OF, forecaster, max_workers=1)

    par_ledger = ForecastLedger(tmp_path / "par.db")
    par = record_pending(par_ledger, markets, AS_OF, forecaster, max_workers=4)

    assert par.n_recorded == seq.n_recorded == 8
    # Same SET of markets recorded (order-independent), with identical numbers.
    seq_by = _recorded_index(seq)
    par_by = _recorded_index(par)
    assert set(par_by) == set(seq_by) == {f"m{i}" for i in range(8)}
    for mid, row in par_by.items():
        assert row["agent_forecast"] == pytest.approx(seq_by[mid]["agent_forecast"])
        assert row["market_devig_probability"] == pytest.approx(seq_by[mid]["market_devig_probability"])
    # Deterministic RECORDED order: the parallel run still records in input order.
    assert [r["market_id"] for r in par.recorded] == [f"m{i}" for i in range(8)]
    assert [r["market_id"] for r in seq.recorded] == [f"m{i}" for i in range(8)]


def test_parallel_ledger_writes_are_not_corrupted(tmp_path):
    markets = _future_markets(6)
    def forecaster(m):
        # A distinct agent prob per market; its OWN market price comes from the dict.
        return 0.20 + 0.05 * int(market_id(m)[1:])

    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, markets, AS_OF, forecaster, max_workers=4)
    assert run.n_recorded == 6

    market_by_id = {m["id"]: m for m in markets}
    for row in run.recorded:
        qid = row["question_id"]
        snaps = ledger.list_snapshots(qid)
        # EXACTLY one snapshot per recorded question (no double-write race).
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.forecast_origin == MARKET_NIGHTLY_ORIGIN
        # The agent number on the snapshot is THIS market's number, not another's.
        expected_agent = 0.20 + 0.05 * int(row["market_id"][1:])
        assert snap.probability_or_distribution == pytest.approx(expected_agent)
        # Exactly one market-price baseline, carrying THIS market's de-vigged price.
        market_bl = [
            b for b in ledger.list_baseline_comparisons(qid)
            if b["baseline_type"] == MARKET_BASELINE_TYPE
        ]
        assert len(market_bl) == 1
        assert market_bl[0]["probability_or_distribution"] == pytest.approx(
            market_by_id[row["market_id"]]["probability"]
        )
    # One question per market id — no duplicates created under concurrency.
    mn_qids = [
        (getattr(q, "metadata", {}) or {}).get("market_id")
        for q in ledger.list_questions()
    ]
    assert sorted(mn_qids) == sorted(m["id"] for m in markets)


def test_parallel_skips_markets_whose_forecaster_returns_none(tmp_path):
    markets = _future_markets(6)
    # The forecaster declines (None) for the odd-indexed markets.
    def forecaster(m):
        i = int(market_id(m)[1:])
        return None if i % 2 == 1 else 0.5

    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, markets, AS_OF, forecaster, max_workers=4)

    recorded_ids = {r["market_id"] for r in run.recorded}
    assert recorded_ids == {"m0", "m2", "m4"}  # only the non-None forecasts
    assert set(run.skipped_ids) == {"m1", "m3", "m5"}
    # A None forecast must NOT have written a question/snapshot for that market.
    stored_mids = {
        (getattr(q, "metadata", {}) or {}).get("market_id")
        for q in ledger.list_questions()
    }
    assert stored_mids == {"m0", "m2", "m4"}


def test_parallel_still_applies_strictly_future_close_filter(tmp_path):
    # A mix: future-close (admissible) + at/before as_of (must be rejected even
    # under parallelism — the foreknowledge gate runs BEFORE any forecaster call).
    markets = [
        _market("future1", close="2026-07-01T00:00:00Z"),
        _market("exact", close=AS_OF),                    # exactly at -> rejected
        _market("future2", close="2026-08-01T00:00:00Z"),
        _market("past", close="2026-05-01T00:00:00Z"),    # before -> rejected
        _market("future3", close="2026-09-01T00:00:00Z"),
    ]
    seen = []
    def forecaster(m):
        seen.append(market_id(m))  # records which markets the agent was asked about
        return 0.6

    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, markets, AS_OF, forecaster, max_workers=4)

    assert {r["market_id"] for r in run.recorded} == {"future1", "future2", "future3"}
    assert set(run.rejected_ids) == {"exact", "past"}
    # The rejected markets were never even handed to the (parallel) forecaster.
    assert set(seen) == {"future1", "future2", "future3"}


def test_parallel_a_raising_forecaster_skips_only_that_market(tmp_path):
    # A forecaster that RAISES on one market (not just returns None) must not abort
    # the sweep — that one market is skipped, the rest record cleanly.
    markets = _future_markets(5)
    def forecaster(m):
        if market_id(m) == "m2":
            raise RuntimeError("boom")
        return 0.5

    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, markets, AS_OF, forecaster, max_workers=4)

    assert {r["market_id"] for r in run.recorded} == {"m0", "m1", "m3", "m4"}
    assert "m2" in run.skipped_ids


def test_fresh_agent_per_call_builds_a_new_agent_each_forecast():
    # The CLI uses fresh_agent_per_call=True under parallelism so concurrent
    # workers never share one (non-thread-safe) agent. Prove the factory is
    # invoked once PER market when fresh, and only ONCE total when reused.
    from forecasting import market_nightly_forecaster as mnf

    class _FakeAgent:
        def run_conversation(self, *_a, **_k):
            return '{"probability": 0.5}'

    builds = {"n": 0}

    def fake_factory(**_kwargs):
        builds["n"] += 1
        return _FakeAgent()

    markets = _future_markets(3)

    fresh = mnf.build_informed_market_forecaster(
        model="x", agent_factory=fake_factory, fresh_agent_per_call=True
    )
    for m in markets:
        assert fresh(m) == pytest.approx(0.5)
    assert builds["n"] == 3  # one agent per call

    builds["n"] = 0
    reused = mnf.build_informed_market_forecaster(
        model="x", agent_factory=fake_factory
    )
    for m in markets:
        assert reused(m) == pytest.approx(0.5)
    assert builds["n"] == 1  # default: one agent, reused


# ── CONTEMPORANEOUS-vs-FROZEN baseline distinguisher (the live-edge fix) ────────
#
# The headline "agent beats the market" edge must count ONLY markets whose market
# price is a CONTEMPORANEOUS baseline (sampled at the forecast instant). A FROZEN
# ForecastBench freeze price (stamped weeks before the run) is still scored, but
# QUARANTINED from the headline edge so it cannot contaminate the claim.


def _frozen_market(mid, *, close, yes=0.6, price_asof, **extra):
    """A frozen-baseline market: its price_asof is a stale vintage (weeks-old)."""
    return _market(mid, close=close, yes=yes, source="manifold",
                   price_asof=price_asof, baseline_is_frozen=True, **extra)


def _live_market(mid, *, close, yes=0.6, **extra):
    """A contemporaneous (live-fetch) market: price_asof == the forecast instant."""
    return _market(mid, close=close, yes=yes, source="manifold",
                   price_asof=AS_OF, baseline_is_frozen=False, **extra)


def test_classifier_priority_flag_then_lag_then_id_fallback():
    # 1. explicit recorded contemporaneous flag wins.
    assert baseline_is_contemporaneous(metadata={"contemporaneous": True}) is True
    assert baseline_is_contemporaneous(metadata={"contemporaneous": False}) is False
    # 2. baseline_is_frozen flag.
    assert baseline_is_contemporaneous(metadata={"baseline_is_frozen": True}) is False
    assert baseline_is_contemporaneous(metadata={"baseline_is_frozen": False}) is True
    # 3. price_asof vs forecast_as_of GAP under the threshold -> contemporaneous.
    near = baseline_is_contemporaneous(
        metadata={"price_asof": "2026-06-01T00:00:00Z", "forecast_as_of": "2026-06-01T06:00:00Z"}
    )
    assert near is True  # 6h gap < 48h
    far = baseline_is_contemporaneous(
        metadata={"price_asof": "2026-06-01T00:00:00Z", "forecast_as_of": "2026-06-20T00:00:00Z"}
    )
    assert far is False  # 19 days >> 48h
    # 4. LEGACY fallback for rows with no provenance: a forecastbench id is FROZEN,
    #    any other (direct live) market is contemporaneous. The legacy fallback must
    #    NOT trust an equal as_of (the pre-fix bug stamped frozen prices that way).
    assert baseline_is_contemporaneous(metadata={}, market_id_str="forecastbench:abc") is False
    assert baseline_is_contemporaneous(metadata={}, source="forecastbench") is False
    assert baseline_is_contemporaneous(metadata={}, market_id_str="manifold:xyz") is True


def test_threshold_boundary_is_inclusive():
    fa = "2026-06-03T00:00:00Z"  # exactly THRESHOLD seconds after price_asof
    pa = "2026-06-01T00:00:00Z"
    assert (CONTEMPORANEOUS_THRESHOLD_SECONDS) == 48 * 3600
    assert baseline_is_contemporaneous(metadata={"price_asof": pa, "forecast_as_of": fa}) is True


def test_market_price_asof_prefers_explicit_else_forecast_instant():
    # Explicit price_asof is used as the true vintage.
    m = _market("m", close="2026-07-01T00:00:00Z", price_asof="2026-05-01T00:00:00Z")
    assert market_price_asof(m, forecast_as_of=AS_OF) == "2026-05-01T00:00:00Z"
    # No price_asof -> falls back to the forecast instant (the live-source default).
    m2 = _market("m2", close="2026-07-01T00:00:00Z")
    assert market_price_asof(m2, forecast_as_of=AS_OF) == AS_OF


def test_record_pending_stamps_baseline_with_price_asof_not_forecast_time(tmp_path):
    # The FIX: a frozen baseline's as_of must be its TRUE price vintage, NOT the
    # forecast time (the old bug stamped the forecast time, hiding the staleness).
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger,
        [_frozen_market("frozen", close="2026-07-01T00:00:00Z", price_asof="2026-05-01T00:00:00Z")],
        AS_OF,
        lambda m: 0.7,
    )
    qid = run.recorded[0]["question_id"]
    bl = [b for b in ledger.list_baseline_comparisons(qid) if b["baseline_type"] == MARKET_BASELINE_TYPE][0]
    # Baseline as_of is the PRICE vintage (2026-05-01), not the forecast AS_OF (2026-06-01).
    assert bl["as_of"] == "2026-05-01T00:00:00Z"
    assert bl["as_of"] != AS_OF
    meta = bl["metadata"]
    assert meta["price_asof"] == "2026-05-01T00:00:00Z"
    assert meta["forecast_as_of"] == AS_OF
    assert meta["contemporaneous"] is False
    assert meta["baseline_is_frozen"] is True
    assert meta["baseline_lag_seconds"] > CONTEMPORANEOUS_THRESHOLD_SECONDS
    # The agent snapshot still carries the FORECAST instant (unchanged).
    snap = ledger.list_snapshots(qid)[0]
    assert snap.as_of == AS_OF
    # And the recorded row surfaces the flag.
    assert run.recorded[0]["contemporaneous"] is False


def test_live_market_records_a_contemporaneous_baseline(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger, [_live_market("live", close="2026-07-01T00:00:00Z")], AS_OF, lambda m: 0.7
    )
    qid = run.recorded[0]["question_id"]
    bl = [b for b in ledger.list_baseline_comparisons(qid) if b["baseline_type"] == MARKET_BASELINE_TYPE][0]
    assert bl["as_of"] == AS_OF  # live fetch == forecast instant
    assert bl["metadata"]["contemporaneous"] is True
    assert run.recorded[0]["contemporaneous"] is True


def _resolve_no(ledger, qid):
    ledger.resolve_question(question_id=qid, outcome="no", resolution_source="https://example.test/settle")


def test_report_excludes_frozen_baseline_from_headline_edge_but_still_scores_it(tmp_path):
    """The core live-edge fix: a FROZEN-baseline market is scored + reported, but it is
    EXCLUDED from the headline agent-vs-market edge; a CONTEMPORANEOUS market is the
    only one that enters the claim; the counts are surfaced (no silent drop)."""
    ledger = ForecastLedger(tmp_path / "mn.db")

    # One contemporaneous (live) market + two frozen (stale) ForecastBench-style markets.
    sampled = [
        _live_market("live", close="2026-06-15T00:00:00Z", yes=0.50),
        _frozen_market("frozenA", close="2026-06-16T00:00:00Z", yes=0.05, price_asof="2026-05-01T00:00:00Z"),
        _frozen_market("frozenB", close="2026-06-17T00:00:00Z", yes=0.05, price_asof="2026-05-02T00:00:00Z"),
    ]
    # Agent is confident YES everywhere; outcomes resolve YES, so the agent trivially
    # "beats" the STALE/wrong frozen 0.05 priors — exactly the contamination we must
    # quarantine from the headline edge.
    run = record_pending(ledger, sampled, AS_OF, lambda m: 0.80)
    assert run.n_recorded == 3
    for row in run.recorded:
        _resolve_yes(ledger, row["question_id"])

    matured = score_matured(ledger, now="2026-07-01T00:00:00Z")
    # The resolver scores ALL THREE (both arms) — its job is maturity + Brier.
    assert matured["n_scored"] == 3
    assert matured["n_contemporaneous"] == 1
    assert matured["n_frozen_excluded"] == 2
    flag_by = {s["market_id"]: s["contemporaneous"] for s in matured["scored"]}
    assert flag_by == {"live": True, "frozenA": False, "frozenB": False}

    report = market_nightly_report(ledger)
    # Counts surfaced — frozen is NOT silently dropped.
    assert report["n_scored"] == 3           # full scored set (both arms)
    assert report["n_contemporaneous"] == 1
    assert report["n_frozen_excluded"] == 2
    # HEADLINE edge counts ONLY the contemporaneous market (1 win), NOT the 3 frozen wins.
    assert report["paired_agent_wins"] == 1
    assert report["paired_baseline_wins"] == 0
    assert report["paired_ties"] == 0
    # The frozen markets live in the diagnostic bucket (still scored), never the headline.
    assert report["frozen_diagnostic"]["n_scored"] == 2
    assert report["full_set"]["n_scored"] == 3
    # Full-set edge would have counted all 3 wins — proving the headline is the SUBSET.
    assert report["full_set"]["paired_agent_wins"] == 3


def test_report_contemporaneous_only_when_all_live(tmp_path):
    # Sanity: with no frozen markets, the headline edge == the full set (back-compat).
    ledger = ForecastLedger(tmp_path / "mn.db")
    sampled = [
        _live_market("l1", close="2026-06-15T00:00:00Z", yes=0.40),
        _live_market("l2", close="2026-06-16T00:00:00Z", yes=0.45),
    ]
    run = record_pending(ledger, sampled, AS_OF, lambda m: 0.85)
    for row in run.recorded:
        _resolve_yes(ledger, row["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")
    report = market_nightly_report(ledger)
    assert report["n_contemporaneous"] == 2
    assert report["n_frozen_excluded"] == 0
    assert report["paired_agent_wins"] == 2
    assert report["full_set"]["paired_agent_wins"] == 2


def test_legacy_frozen_row_without_provenance_is_excluded(tmp_path):
    # A row written BEFORE the fix has no price_asof/contemporaneous metadata, and its
    # baseline as_of equals the forecast time (the old bug). It must STILL be excluded
    # from the headline via the forecastbench-id fallback.
    ledger = ForecastLedger(tmp_path / "mn.db")
    # market id carries the forecastbench prefix; NO price_asof / baseline_is_frozen.
    legacy = _market("forecastbench:legacy", close="2026-06-15T00:00:00Z", yes=0.95, source="manifold")
    live = _live_market("manifold:live", close="2026-06-16T00:00:00Z", yes=0.50)
    run = record_pending(ledger, [legacy, live], AS_OF, lambda m: 0.80)
    for row in run.recorded:
        _resolve_yes(ledger, row["question_id"])
    # SIMULATE a legacy row: strip the provenance metadata the fix now records, so the
    # report must fall back to the forecastbench-id proxy to classify it as frozen.
    with ledger._connect() as conn:
        for row in run.recorded:
            bl = [b for b in ledger.list_baseline_comparisons(row["question_id"])
                  if b["baseline_type"] == MARKET_BASELINE_TYPE][0]
            conn.execute(
                "UPDATE baseline_comparisons SET metadata = ? WHERE id = ?",
                ('{"market_nightly": true}', bl["id"]),
            )
    score_matured(ledger, now="2026-07-01T00:00:00Z")
    report = market_nightly_report(ledger)
    assert report["n_scored"] == 2
    # The forecastbench-id legacy row is classified FROZEN and excluded from the headline.
    assert report["n_contemporaneous"] == 1
    assert report["n_frozen_excluded"] == 1
    assert report["paired_agent_wins"] == 1


# ── A/B research arm tagging + paired voi-vs-plain scoreboard ───────────────────
#
# The market-hidden ForecastBench result proved the closed-book LLM has no intrinsic
# edge; the only path to edge is fresh information, provable only FORWARD. Arc 2
# shipped VOI-directed research but build_informed_market_forecaster used the plain
# packet, so the lift was INVISIBLE to the scoreboard. These tests prove the paired
# A/B: each arm is tagged, split by arm, and the voi-vs-plain Brier delta is computed
# via the SAME P0.2 paired-bootstrap machinery (reused, never reimplemented).


def _live(mid, *, close, yes=0.5):
    # A contemporaneous live market (price_asof == forecast instant) so it enters the
    # headline / per-arm agent-vs-market split without frozen-baseline quarantine.
    return _market(mid, close=close, yes=yes, source="manifold", price_asof=AS_OF,
                   baseline_is_frozen=False)


def test_record_pending_tags_arm_on_question_snapshot_and_row(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger, [_market("m", close="2026-07-01T00:00:00Z")], AS_OF, lambda m: 0.7, arm="voi"
    )
    assert run.arm == "voi"
    row = run.recorded[0]
    assert row["arm"] == "voi"
    q = [q for q in ledger.list_questions() if (getattr(q, "metadata", {}) or {}).get("market_id") == "m"][0]
    assert q.metadata.get("arm") == "voi"
    snap = ledger.list_snapshots(row["question_id"])[0]
    assert snap.metadata.get("arm") == "voi"


def test_record_pending_default_arm_is_plain(tmp_path):
    # Back-compat: the default arm is 'plain' (the existing accrued record).
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(ledger, [_market("m", close="2026-07-01T00:00:00Z")], AS_OF, lambda m: 0.7)
    assert run.arm == "plain"
    assert run.recorded[0]["arm"] == "plain"
    snap = ledger.list_snapshots(run.recorded[0]["question_id"])[0]
    assert snap.metadata.get("arm") == "plain"


def test_arm_aware_idempotence_allows_both_arms_but_not_a_duplicate_within_an_arm(tmp_path):
    # The SAME market may hold one plain AND one voi entry (the paired A/B), but never
    # two entries for the SAME arm.
    ledger = ForecastLedger(tmp_path / "mn.db")
    market = _market("dup", close="2026-07-01T00:00:00Z")
    first = record_pending(ledger, [market], AS_OF, lambda m: 0.6, arm="plain")
    assert first.n_recorded == 1
    # Re-running plain on the same still-open market is deduped.
    again = record_pending(ledger, [market], "2026-06-02T00:00:00Z", lambda m: 0.6, arm="plain")
    assert again.n_recorded == 0 and "dup" in again.skipped_ids
    # But the voi arm is a DIFFERENT key, so it records.
    voi = record_pending(ledger, [market], "2026-06-02T00:00:00Z", lambda m: 0.9, arm="voi")
    assert voi.n_recorded == 1
    # Exactly two questions for this market: one per arm.
    qs = [q for q in ledger.list_questions() if (getattr(q, "metadata", {}) or {}).get("market_id") == "dup"]
    assert sorted((getattr(q, "metadata", {}) or {}).get("arm") for q in qs) == ["plain", "voi"]


def test_score_matured_surfaces_arm_and_counts_by_arm(tmp_path):
    ledger = ForecastLedger(tmp_path / "mn.db")
    markets = [_live("a", close="2026-06-15T00:00:00Z"), _live("b", close="2026-06-16T00:00:00Z")]
    plain = record_pending(ledger, markets, AS_OF, lambda m: 0.6, arm="plain")
    voi = record_pending(ledger, markets, AS_OF, lambda m: 0.8, arm="voi")
    for run in (plain, voi):
        for row in run.recorded:
            _resolve_yes(ledger, row["question_id"])
    matured = score_matured(ledger, now="2026-07-01T00:00:00Z")
    assert matured["n_scored"] == 4
    assert matured["n_by_arm"] == {"plain": 2, "voi": 2}
    assert {s["arm"] for s in matured["scored"]} == {"plain", "voi"}


def test_report_paired_voi_vs_plain_delta_is_hand_checkable(tmp_path):
    # Two markets forecast by BOTH arms; both resolve YES. Hand-checkable Briers:
    #   market x: plain=0.5 -> (1-0.5)^2 = 0.25 ; voi=0.9 -> (1-0.9)^2 = 0.01 ; delta=0.24
    #   market y: plain=0.6 -> (1-0.6)^2 = 0.16 ; voi=0.8 -> (1-0.8)^2 = 0.04 ; delta=0.12
    # delta = plain_brier - voi_brier (POSITIVE = VOI better). mean = (0.24+0.12)/2 = 0.18.
    ledger = ForecastLedger(tmp_path / "mn.db")
    mx = _live("x", close="2026-06-15T00:00:00Z")
    my = _live("y", close="2026-06-16T00:00:00Z")

    def plain_forecaster(m):
        return {"x": 0.5, "y": 0.6}[market_id(m)]

    def voi_forecaster(m):
        return {"x": 0.9, "y": 0.8}[market_id(m)]

    plain = record_pending(ledger, [mx, my], AS_OF, plain_forecaster, arm="plain")
    voi = record_pending(ledger, [mx, my], AS_OF, voi_forecaster, arm="voi")
    for run in (plain, voi):
        for row in run.recorded:
            _resolve_yes(ledger, row["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")

    report = market_nightly_report(ledger)
    vp = report["paired_voi_vs_plain"]
    assert vp["n_paired"] == 2
    assert vp["delta_mean_brier"] == pytest.approx(0.18)
    assert vp["voi_wins"] == 2
    assert vp["plain_wins"] == 0
    assert vp["ties"] == 0
    # Non-degenerate spread (0.24 vs 0.12) -> the seeded bootstrap yields a real p + CI.
    assert isinstance(vp["p_value"], float) and 0.0 <= vp["p_value"] <= 1.0
    assert vp["ci95_low"] is not None and vp["ci95_high"] is not None


def test_report_by_arm_splits_agent_vs_market(tmp_path):
    # Per-arm agent-vs-market split (contemporaneous baselines). voi (0.85) is sharper
    # than plain (0.55) toward the realized YES, so voi's mean agent Brier is lower.
    ledger = ForecastLedger(tmp_path / "mn.db")
    markets = [_live("a", close="2026-06-15T00:00:00Z", yes=0.50),
               _live("b", close="2026-06-16T00:00:00Z", yes=0.45)]
    plain = record_pending(ledger, markets, AS_OF, lambda m: 0.55, arm="plain")
    voi = record_pending(ledger, markets, AS_OF, lambda m: 0.85, arm="voi")
    for run in (plain, voi):
        for row in run.recorded:
            _resolve_yes(ledger, row["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")

    report = market_nightly_report(ledger)
    by_arm = report["by_arm"]
    assert by_arm["plain"]["n_scored"] == 2
    assert by_arm["voi"]["n_scored"] == 2
    # voi mean agent Brier (0.85 on YES -> 0.0225) < plain (0.55 on YES -> 0.2025).
    assert by_arm["voi"]["mean_agent_brier"] == pytest.approx(0.0225)
    assert by_arm["plain"]["mean_agent_brier"] == pytest.approx(0.2025)
    # Both arms share the SAME market baseline mean (same markets, same de-vigged price).
    assert by_arm["voi"]["mean_market_brier"] == pytest.approx(by_arm["plain"]["mean_market_brier"])
    # voi's agent-vs-market edge is bigger than plain's (both positive, voi sharper).
    assert by_arm["voi"]["paired_agent_edge_mean_brier"] > by_arm["plain"]["paired_agent_edge_mean_brier"]


def test_report_paired_voi_vs_plain_empty_without_both_arms(tmp_path):
    # With only ONE arm recorded, there are no both-arm pairs -> n_paired == 0 and the
    # delta is None (the empty paired stub), never a fabricated number.
    ledger = ForecastLedger(tmp_path / "mn.db")
    run = record_pending(
        ledger, [_live("solo", close="2026-06-15T00:00:00Z")], AS_OF, lambda m: 0.7, arm="plain"
    )
    _resolve_yes(ledger, run.recorded[0]["question_id"])
    score_matured(ledger, now="2026-07-01T00:00:00Z")
    report = market_nightly_report(ledger)
    assert report["paired_voi_vs_plain"]["n_paired"] == 0
    assert report["paired_voi_vs_plain"]["delta_mean_brier"] is None
    # by_arm still surfaces the single arm; voi bucket is empty (not scored).
    assert report["by_arm"]["plain"]["n_scored"] == 1
    assert report["by_arm"]["voi"]["n_scored"] == 0
