"""Benchmark scoreboard section (carved from ``dashboard.py``).

The Wave-4 §W3.b ``scoreboard`` section: ``build_bench_scoreboard`` and its
Brier / binary-outcome / market-baseline helpers — the closed-book benchmark
tallies. Imported back into :mod:`forecasting.dashboard.core` for the façade's
public surface and re-exported unchanged, so ``from forecasting.dashboard import
build_bench_scoreboard`` is byte-for-byte unchanged.
"""
from __future__ import annotations

from typing import Any

from forecasting.branding import PRODUCT_NAME
from forecasting.ledger import ForecastLedger
from forecasting.models import utc_now_iso
from forecasting.dashboard.core import format_probability

def _bench_binary_prob_yes(payload: Any, choices: list[str] | None) -> float | None:
    """Pull the P(yes) scalar out of a binary forecast/baseline payload.

    Binary snapshots and ForecastBench market baselines store a bare float that is
    already P(first-choice) — the "yes" leg — so a scalar is returned verbatim. A
    dict payload (defensive: a {"yes": .., "no": ..} categorical) is read by the
    first choice label. Anything else → None (uncomputable, never faked)."""

    if isinstance(payload, bool):  # bool is an int subclass — reject before float
        return None
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        keys = [str(choices[0])] if choices else []
        keys += ["yes", "y", "true"]
        lowered = {str(k).lower(): v for k, v in payload.items()}
        for key in keys:
            value = lowered.get(str(key).lower())
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _bench_outcome_binary(outcome: Any, choices: list[str] | None) -> float | None:
    """Map a confirmed binary resolution label to the 0.0/1.0 the brier uses.

    Mirrors ``ledger._brier_score``'s yes/no convention: the first outcome-space
    choice (or a yes/true/1 synonym) → 1.0, else 0.0. Unrecognized → None."""

    if outcome is None:
        return None
    if isinstance(outcome, bool):
        return 1.0 if outcome else 0.0
    if isinstance(outcome, (int, float)):
        if abs(float(outcome) - 1.0) < 1e-9:
            return 1.0
        if abs(float(outcome) - 0.0) < 1e-9:
            return 0.0
        return None
    label = str(outcome).strip().lower()
    yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
    no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
    first_choice = str(choices[0]).lower() if choices else "yes"
    if label in yes_labels or label == first_choice:
        return 1.0
    if label in no_labels or (choices and len(choices) > 1 and label == str(choices[1]).lower()):
        return 0.0
    return None


def _bench_brier(prob_yes: float | None, outcome_binary: float | None) -> float | None:
    """Pure binary Brier = (p − y)². Read-only: never touches the ledger / scoring."""

    if prob_yes is None or outcome_binary is None:
        return None
    return round((float(prob_yes) - float(outcome_binary)) ** 2, 6)


def _bench_market_baseline(ledger: ForecastLedger, question_id: str) -> dict[str, Any] | None:
    """The de-vigged market freeze baseline for a bench question (read-only).

    Prefers the ``market`` baseline_type (the ForecastBench freeze_datetime_value
    carried by ``forecastbench.build_forecastbench_case``); the most recent one
    wins when several exist. Returns the raw comparison dict or None."""

    market: dict[str, Any] | None = None
    for comparison in ledger.list_baseline_comparisons(question_id):
        if str(comparison.get("baseline_type") or "") == "market":
            market = comparison  # list is as_of ASC → last assignment is newest
    return market


def build_bench_scoreboard(
    *,
    ledger: ForecastLedger | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Assemble the READ-ONLY ForecastBench backtest scoreboard.

    For every question with ``domain == "forecastbench"`` (or tag ``bench`` /
    ``forecastbench`` as a fallback) this reads — never mutates — the question's
    current agent snapshot, its de-vigged market freeze baseline, its confirmed
    resolution, and the recorded agent score, and emits one row carrying the
    agent probability, the market freeze price, the resolved 0/1 outcome, and the
    agent vs market Brier. The aggregate is the mean agent Brier vs the mean
    market Brier over the rows where BOTH are computable, plus the paired count.

    Pure: uses only ``list_questions`` / ``list_snapshots`` /
    ``get_latest_resolution`` / ``list_baseline_comparisons`` / ``get_current_score``.
    The agent Brier comes from the already-recorded ``ScoreRecord`` when present
    (force=False, so no scoring is triggered); the market Brier is computed in
    Python from the stored baseline probability + the resolved outcome, so a
    scoreboard renders even before baselines have been separately scored."""

    ledger = ledger or ForecastLedger()

    # Domain isolation is the primary selector (forecastbench.py sets it on every
    # ingested case); the tag fallback catches any hand-built bench question that
    # carries "bench"/"forecastbench" tags but a different domain. De-duplicated by id.
    questions = list(ledger.list_questions(domain="forecastbench"))
    seen = {q.id for q in questions}
    for question in ledger.list_questions():
        if question.id in seen:
            continue
        tags = {str(tag).lower() for tag in (question.tags or [])}
        if tags & {"bench", "forecastbench"}:
            questions.append(question)
            seen.add(question.id)

    rows: list[dict[str, Any]] = []
    for question in questions:
        snapshots = ledger.list_snapshots(question.id)
        # The agent forecast is the most recent NON-baseline snapshot (a scored
        # baseline rides as an imported_baseline snapshot on the same question).
        agent_snapshot = next(
            (s for s in reversed(snapshots) if s.forecast_origin != "imported_baseline"),
            None,
        )
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        choices = list(question.outcome_space.choices or [])

        agent_prob = (
            _bench_binary_prob_yes(agent_snapshot.probability_or_distribution, choices)
            if agent_snapshot
            else None
        )
        market_comparison = _bench_market_baseline(ledger, question.id)
        market_prob = (
            _bench_binary_prob_yes(market_comparison.get("probability_or_distribution"), choices)
            if market_comparison
            else None
        )
        outcome_label = resolution.outcome if resolution else None
        outcome_binary = _bench_outcome_binary(outcome_label, choices)

        # The agent Brier: prefer the recorded ScoreRecord (no rescoring); fall
        # back to the pure formula so a row scores even if scoring hasn't run.
        recorded = ledger.get_current_score(question.id)
        agent_brier = recorded.brier_score if recorded and recorded.brier_score is not None else None
        if agent_brier is None:
            agent_brier = _bench_brier(agent_prob, outcome_binary)
        market_brier = _bench_brier(market_prob, outcome_binary)

        source = (
            (question.metadata or {}).get("forecastbench_source")
            or (question.topics[0] if question.topics else None)
        )

        rows.append(
            {
                "id": question.id,
                "title": question.title,
                "source": source,
                "domain": question.domain,
                "topics": list(question.topics or []),
                "as_of": agent_snapshot.as_of if agent_snapshot else None,
                "resolved_at": resolution.resolved_at if resolution else None,
                "agent_probability": agent_prob,
                "agent_probability_display": format_probability(agent_prob) if agent_prob is not None else "-",
                "market_probability": market_prob,
                "market_probability_display": format_probability(market_prob) if market_prob is not None else "-",
                "outcome": outcome_binary,
                "outcome_label": str(outcome_label) if outcome_label is not None else None,
                "resolved": outcome_binary is not None,
                "agent_brier": agent_brier,
                "market_brier": market_brier,
                # Per-row edge: positive = agent beat the market freeze on Brier.
                "brier_edge": (
                    round(market_brier - agent_brier, 6)
                    if agent_brier is not None and market_brier is not None
                    else None
                ),
            }
        )

    # Newest-resolved first, then newest-forecast, so the freshest backtests lead.
    rows.sort(key=lambda r: (r.get("resolved_at") or "", r.get("as_of") or ""), reverse=True)
    if limit is not None and limit >= 0:
        rows = rows[:limit]

    paired = [
        r for r in rows if r.get("agent_brier") is not None and r.get("market_brier") is not None
    ]
    mean_agent = (
        round(sum(r["agent_brier"] for r in paired) / len(paired), 6) if paired else None
    )
    mean_market = (
        round(sum(r["market_brier"] for r in paired) / len(paired), 6) if paired else None
    )
    resolved_count = sum(1 for r in rows if r.get("resolved"))

    return {
        "product": PRODUCT_NAME,
        "generated_at": utc_now_iso(),
        "count": len(rows),
        "resolved_count": resolved_count,
        "rows": rows,
        "aggregate": {
            "n": len(paired),
            "mean_agent_brier": mean_agent,
            "mean_market_brier": mean_market,
            # Positive = the agent's mean Brier is lower than the market freeze's
            # (lower Brier is better), i.e. the agent beat the honest baseline.
            "mean_brier_edge": (
                round(mean_market - mean_agent, 6)
                if mean_agent is not None and mean_market is not None
                else None
            ),
        },
    }
