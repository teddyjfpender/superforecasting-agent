"""Read-only ForecastBench backtest scoreboard tests.

``forecasting.dashboard.build_bench_scoreboard`` backs the gateway ``forecast.bench``
RPC + the ``forecast bench`` CLI + the desk's "Bench" lens. It assembles a per-row
agent-vs-market-freeze Brier scoreboard (and the paired aggregate) purely by READING
the ledger — it never scores, never mutates. These tests seed a fully-resolved,
scored forecastbench question + an UNRELATED live question and assert:

  * the bench row carries the right agent / market probability, resolved 0/1 outcome,
    and agent / market Brier (computed against the de-vigged market freeze baseline),
  * the aggregate is the mean agent Brier vs mean market Brier over the paired rows,
  * the non-bench question is EXCLUDED from the scoreboard,
  * the call leaves the ledger byte-for-byte unchanged (read-only invariant).
"""

from __future__ import annotations

import pytest

from forecasting.dashboard import build_bench_scoreboard
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


def _seed_bench_question(
    ledger: ForecastLedger,
    *,
    qid_suffix: str,
    agent_prob: float,
    market_prob: float,
    outcome: str,
    source: str = "manifold",
) -> str:
    """Seed one resolved + scored forecastbench question and return its id."""

    question = ledger.create_question(
        title=f"Will bench event {qid_suffix} happen?",
        resolution_criteria="Resolves YES per the linked ForecastBench source.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        close_time="2099-03-01T00:00:00Z",
        resolution_time="2099-02-15T00:00:00Z",
        domain="forecastbench",
        tags=["bench", "forecastbench", source],
        topics=[source],
        metadata={"forecastbench_source": source},
    )
    # The agent's closed-book forecast at the freeze instant.
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=agent_prob,
        rationale="Closed-book bench forecast.",
        as_of="2099-01-01T00:00:00Z",
        forecast_origin="backtest",
    )
    # The de-vigged market freeze price as a baseline comparison.
    ledger.add_baseline_comparison(
        question_id=question.id,
        source=source,
        baseline_type="market",
        probability_or_distribution=market_prob,
        as_of="2099-01-01T00:00:00Z",
    )
    # A naive 0.5 baseline rides alongside (must be ignored by the scoreboard).
    ledger.add_baseline_comparison(
        question_id=question.id,
        source="auto",
        baseline_type="naive_0_5",
        probability_or_distribution=0.5,
        as_of="2099-01-01T00:00:00Z",
    )
    # Confirm the resolution + auto-score the agent snapshot.
    ledger.resolve_question(question_id=question.id, outcome=outcome)
    return question.id


def test_scoreboard_row_and_aggregate(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))

    # Two bench questions: one resolved YES, one resolved NO.
    qid_yes = _seed_bench_question(
        ledger, qid_suffix="A", agent_prob=0.70, market_prob=0.60, outcome="yes", source="manifold"
    )
    qid_no = _seed_bench_question(
        ledger, qid_suffix="B", agent_prob=0.30, market_prob=0.45, outcome="no", source="metaculus"
    )

    # An UNRELATED live forecast in a different domain — must be excluded.
    live = ledger.create_question(
        title="Will an unrelated live event happen?",
        resolution_criteria="Resolves YES on the live desk.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        domain="politics",
        topics=["elections"],
    )
    ledger.create_snapshot(
        question_id=live.id,
        probability_or_distribution=0.55,
        rationale="Live desk forecast.",
        as_of="2026-01-01T00:00:00Z",
        forecast_origin="live",
    )

    board = build_bench_scoreboard(ledger=ledger)

    # The non-bench question is excluded.
    ids = {row["id"] for row in board["rows"]}
    assert ids == {qid_yes, qid_no}
    assert live.id not in ids
    assert board["count"] == 2
    assert board["resolved_count"] == 2

    rows = {row["id"]: row for row in board["rows"]}

    # YES row: agent 0.70 vs outcome 1.0 → Brier 0.09; market 0.60 → Brier 0.16.
    yes = rows[qid_yes]
    assert yes["source"] == "manifold"
    assert yes["agent_probability"] == pytest.approx(0.70)
    assert yes["market_probability"] == pytest.approx(0.60)
    assert yes["outcome"] == pytest.approx(1.0)
    assert yes["resolved"] is True
    assert yes["agent_brier"] == pytest.approx(0.09)
    assert yes["market_brier"] == pytest.approx(0.16)
    # Positive edge = agent beat the market freeze (lower Brier).
    assert yes["brier_edge"] == pytest.approx(0.07)

    # NO row: agent 0.30 vs outcome 0.0 → Brier 0.09; market 0.45 → Brier 0.2025.
    no = rows[qid_no]
    assert no["source"] == "metaculus"
    assert no["outcome"] == pytest.approx(0.0)
    assert no["agent_brier"] == pytest.approx(0.09)
    assert no["market_brier"] == pytest.approx(0.2025)

    # Aggregate over both paired rows.
    agg = board["aggregate"]
    assert agg["n"] == 2
    assert agg["mean_agent_brier"] == pytest.approx((0.09 + 0.09) / 2)
    assert agg["mean_market_brier"] == pytest.approx((0.16 + 0.2025) / 2)
    assert agg["mean_brier_edge"] == pytest.approx(
        agg["mean_market_brier"] - agg["mean_agent_brier"]
    )


def test_tag_fallback_includes_non_forecastbench_domain(tmp_path):
    # A bench question tagged "bench"/"forecastbench" but in a different domain is
    # still picked up via the tag fallback.
    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))
    question = ledger.create_question(
        title="Tagged-but-off-domain bench question?",
        resolution_criteria="Resolves YES per bench source.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        domain="markets",  # NOT forecastbench
        tags=["bench", "forecastbench"],
        topics=["polymarket"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.8,
        rationale="x",
        as_of="2099-01-01T00:00:00Z",
        forecast_origin="backtest",
    )
    ledger.add_baseline_comparison(
        question_id=question.id,
        source="polymarket",
        baseline_type="market",
        probability_or_distribution=0.7,
        as_of="2099-01-01T00:00:00Z",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")

    board = build_bench_scoreboard(ledger=ledger)
    assert {row["id"] for row in board["rows"]} == {question.id}


def test_unresolved_bench_question_has_no_brier_but_still_listed(tmp_path):
    # A bench question with a forecast but no confirmed resolution lists with a
    # null outcome / null market Brier and does NOT enter the paired aggregate.
    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))
    question = ledger.create_question(
        title="Unresolved bench question?",
        resolution_criteria="Resolves YES if the bench event occurs before close.",
        outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        domain="forecastbench",
        tags=["bench", "forecastbench"],
        topics=["manifold"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.6,
        rationale="x",
        as_of="2099-01-01T00:00:00Z",
        forecast_origin="backtest",
    )
    ledger.add_baseline_comparison(
        question_id=question.id,
        source="manifold",
        baseline_type="market",
        probability_or_distribution=0.5,
        as_of="2099-01-01T00:00:00Z",
    )

    board = build_bench_scoreboard(ledger=ledger)
    rows = {row["id"]: row for row in board["rows"]}
    assert question.id in rows
    row = rows[question.id]
    assert row["resolved"] is False
    assert row["outcome"] is None
    assert row["agent_brier"] is None
    assert row["market_brier"] is None
    # No paired rows → the aggregate is empty (n == 0), not faked.
    assert board["aggregate"]["n"] == 0
    assert board["aggregate"]["mean_agent_brier"] is None
    assert board["resolved_count"] == 0


def test_empty_ledger_returns_empty_scoreboard(tmp_path):
    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))
    board = build_bench_scoreboard(ledger=ledger)
    assert board["count"] == 0
    assert board["rows"] == []
    assert board["aggregate"]["n"] == 0
    assert board["aggregate"]["mean_brier_edge"] is None


def test_scoreboard_is_read_only(tmp_path):
    # Building the scoreboard must not add/alter any ledger row (no scoring side
    # effect). Snapshot the row counts before + after.
    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))
    _seed_bench_question(
        ledger, qid_suffix="A", agent_prob=0.7, market_prob=0.6, outcome="yes"
    )

    def _counts() -> dict[str, int]:
        with ledger._connect() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "forecast_questions",
                    "forecast_snapshots",
                    "resolutions",
                    "score_records",
                    "baseline_comparisons",
                )
            }

    before = _counts()
    build_bench_scoreboard(ledger=ledger)
    build_bench_scoreboard(ledger=ledger)  # twice, to be sure it is idempotent
    after = _counts()
    assert before == after
