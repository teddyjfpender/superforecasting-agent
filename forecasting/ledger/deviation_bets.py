"""Deviation-bet domain (UPGRADE 2 — the deviation ledger).

A *deviation bet* is the desk's honest, pre-registered mini-bet AGAINST the market:
on a LIVE market-linked quorum where the reconciled verdict deviates from the
de-vigged market price by more than the discipline threshold WITH a named edge (a
justified conviction deviation, not one that was pulled back to the price), we
record a bet — ``(market_price, blind_pool, reconciled_verdict, deviation_pp,
named_edge, threshold_pp)``. When the question resolves, the bet is scored:
``Brier_ours`` (the reconciled verdict) vs ``Brier_market`` (the market price)
against the realized outcome. The verdict is simply: *did the named edge beat the
market?* This is the live-edge study (docs/research/live-edge-study.md) made a
first-class, continuously-accruing ledger instead of a hand-run script.

This leaf mirrors :mod:`forecasting.ledger.panels`: the gated write
``record_deviation_bet`` reaches ``_enforce_write_gate`` straight from
:mod:`forecasting.ledger.gate` (deviation_bets is a gated forecast-producing
table); every read + the resolution-time scorer resolve through the ``ledger``
INSTANCE (``get_question`` / ``_score_forecast_payload`` / ``_paired_bootstrap``).
It NEVER creates a bet on a backtest — creation is foreknowledge-gated by the
caller (a LIVE evidence cutoff only), so a resolved-question replay can never
manufacture a fake edge.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

from forecasting.ledger.gate import _enforce_write_gate
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso

logger = logging.getLogger(__name__)

# Below this scored-bet count the edge is reported honestly as an insufficient
# sample: no CI, no recommendation to move the threshold — just "accrue more".
EDGE_MIN_SAMPLE = 10


def record_deviation_bet(
    ledger,
    *,
    question_id: str,
    market_price: float,
    reconciled_verdict: float,
    deviation_pp: float,
    threshold_pp: float,
    panel_run_id: str | None = None,
    blind_pool: float | None = None,
    named_edge: str | None = None,
    forecast_origin: str | None = "live",
) -> dict[str, Any]:
    """Persist one deviation bet (gated forecast-producing write).

    Records the desk's named-edge deviation from the market at forecast time; the
    scored fields (``outcome`` / ``brier_ours`` / ``brier_market`` / ``brier_delta``
    / ``resolution_id`` / ``scored_at``) stay NULL until :func:`score_deviation_bets`
    fills them at resolution. The caller is responsible for the foreknowledge gate
    (LIVE runs only) and for opening the ``allow_ledger_writes`` commit context —
    exactly like ``record_panel_run``.
    """

    _enforce_write_gate("record_deviation_bet")
    ledger.get_question(question_id)  # validate the FK target exists
    bet_id = f"db_{uuid.uuid4().hex[:12]}"
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO deviation_bets (
                id, question_id, panel_run_id, created_at, market_price,
                blind_pool, reconciled_verdict, deviation_pp, named_edge,
                threshold_pp, forecast_origin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bet_id,
                question_id,
                panel_run_id,
                now,
                float(market_price),
                float(blind_pool) if blind_pool is not None else None,
                float(reconciled_verdict),
                float(deviation_pp),
                (str(named_edge).strip() or None) if named_edge else None,
                float(threshold_pp),
                forecast_origin,
            ),
        )
    return ledger.get_deviation_bet(bet_id)


def get_deviation_bet(ledger, bet_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM deviation_bets WHERE id = ?", (bet_id,)
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"deviation bet not found: {bet_id}")
    return _deviation_bet_dict(row)


def list_deviation_bets(
    ledger,
    question_id: str | None = None,
    *,
    only_open: bool = False,
    only_scored: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if only_open:
        clauses.append("outcome IS NULL")
    if only_scored:
        clauses.append("outcome IS NOT NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM deviation_bets {where} ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_deviation_bet_dict(row) for row in rows]


def score_deviation_bets(
    ledger,
    question_id: str,
    outcome: Any,
    *,
    resolution_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """RESOLUTION HOOK — score every OPEN bet on a just-resolved question.

    For each open bet, compute ``Brier_ours`` (the reconciled verdict) and
    ``Brier_market`` (the market price) against the realized ``outcome`` and set
    ``brier_delta = Brier_market - Brier_ours`` (POSITIVE ⇒ our named edge beat the
    market). Only binary questions are scored (a market bet is a binary YES/NO
    proposition); anything else is skipped, never fabricated. Best-effort and
    idempotent: an already-scored bet (``outcome`` set) is left untouched, and any
    per-bet failure is logged and skipped so a scoring hiccup can never break the
    resolution. Returns ``{scored, agent_wins, market_wins, ties}``.
    """

    summary = {"scored": 0, "agent_wins": 0, "market_wins": 0, "ties": 0}
    open_bets = list_deviation_bets(ledger, question_id, only_open=True)
    if not open_bets:
        return summary
    try:
        outcome_space = ledger.get_question(question_id).outcome_space
    except LedgerNotFoundError:
        return summary
    if getattr(outcome_space, "type", None) != "binary":
        return summary  # Brier-vs-market only meaningful for a binary market bet.
    stamp = now or utc_now_iso()

    def _brier(probability: float) -> float | None:
        try:
            payload = ledger._score_forecast_payload(
                float(probability), outcome, outcome_space
            )
        except (TypeError, ValueError, ValidationError):
            return None
        value = payload.get("brier_score")
        return float(value) if isinstance(value, (int, float)) else None

    for bet in open_bets:
        brier_ours = _brier(bet["reconciled_verdict"])
        brier_market = _brier(bet["market_price"])
        if brier_ours is None or brier_market is None:
            continue
        delta = brier_market - brier_ours
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE deviation_bets
                SET outcome = ?, brier_ours = ?, brier_market = ?, brier_delta = ?,
                    resolution_id = ?, scored_at = ?
                WHERE id = ?
                """,
                (
                    str(outcome),
                    brier_ours,
                    brier_market,
                    delta,
                    resolution_id,
                    stamp,
                    bet["id"],
                ),
            )
        summary["scored"] += 1
        if brier_ours < brier_market:
            summary["agent_wins"] += 1
        elif brier_ours > brier_market:
            summary["market_wins"] += 1
        else:
            summary["ties"] += 1
    return summary


def deviation_bet_edge_report(ledger) -> dict[str, Any]:
    """READ-ONLY roll-up: did the desk's named-edge deviations beat the market?

    Over every SCORED bet: n, win-rate vs the market, the mean paired Brier delta
    (POSITIVE ⇒ ours better), and the seeded paired-bootstrap 95% CI + p-value
    (AIA P0.2 — reuses :meth:`ForecastLedger._paired_bootstrap`, the same machinery
    the market-nightly and backtest edge tests use). Below :data:`EDGE_MIN_SAMPLE`
    scored bets the sample is honestly labeled ``insufficient_sample`` and NO
    threshold move is recommended. The RECOMMENDATION line is advisory only — the
    operator acts on it via the ``quorum.market_anchor_deviation_pp`` appconfig key;
    it is NEVER auto-applied.
    """

    scored = [
        bet
        for bet in list_deviation_bets(ledger, only_scored=True)
        if isinstance(bet.get("brier_ours"), (int, float))
        and isinstance(bet.get("brier_market"), (int, float))
    ]
    n = len(scored)
    n_open = len(list_deviation_bets(ledger, only_open=True))
    threshold_key = "quorum.market_anchor_deviation_pp"

    if n == 0:
        return {
            "n": 0,
            "n_open": n_open,
            "status": "insufficient_sample",
            "win_rate": None,
            "mean_brier_delta": None,
            "mean_brier_ours": None,
            "mean_brier_market": None,
            "ci95_low": None,
            "ci95_high": None,
            "p_value": None,
            "agent_wins": 0,
            "market_wins": 0,
            "ties": 0,
            "min_sample": EDGE_MIN_SAMPLE,
            "threshold_config_key": threshold_key,
            "recommendation": (
                "HOLD — no scored deviation bets yet; accrue live named-edge bets "
                f"before adjusting {threshold_key}."
            ),
        }

    deltas = [float(bet["brier_delta"]) for bet in scored]
    ours = [float(bet["brier_ours"]) for bet in scored]
    market = [float(bet["brier_market"]) for bet in scored]
    agent_wins = sum(1 for bet in scored if bet["brier_ours"] < bet["brier_market"])
    market_wins = sum(1 for bet in scored if bet["brier_ours"] > bet["brier_market"])
    ties = n - agent_wins - market_wins
    mean_delta = sum(deltas) / n
    win_rate = agent_wins / n
    # AIA P0.2 seeded paired bootstrap over the per-bet Brier deltas.
    bootstrap = ledger._paired_bootstrap(deltas, mean_delta)
    ci_low = bootstrap.get("ci_low")
    ci_high = bootstrap.get("ci_high")
    p_value = bootstrap.get("p_value")

    if n < EDGE_MIN_SAMPLE:
        status = "insufficient_sample"
        recommendation = (
            f"HOLD — insufficient sample (n={n} < {EDGE_MIN_SAMPLE}); the edge is "
            f"not yet estimable. Accrue more live named-edge bets before touching "
            f"{threshold_key}."
        )
    else:
        beats = (
            isinstance(ci_low, (int, float))
            and ci_low > 0
            and win_rate > 0.5
        )
        loses = isinstance(ci_high, (int, float)) and ci_high < 0
        if beats:
            status = "beats_market"
            recommendation = (
                "LOOSEN — the desk's named-edge bets beat the market (mean Brier "
                f"delta {mean_delta:+.4f}, 95% CI excludes 0, win-rate "
                f"{win_rate:.0%}). Consider RAISING {threshold_key} so the desk holds "
                "its conviction deviations more readily."
            )
        elif loses:
            status = "loses_to_market"
            recommendation = (
                "TIGHTEN — the desk's named-edge bets UNDERPERFORM the market (mean "
                f"Brier delta {mean_delta:+.4f}, 95% CI below 0). Consider LOWERING "
                f"{threshold_key} so more deviations are pulled back to the price."
            )
        else:
            status = "inconclusive"
            recommendation = (
                f"HOLD — the edge (mean Brier delta {mean_delta:+.4f}) is not "
                f"statistically distinguishable from the market at n={n}. Keep "
                f"{threshold_key} as-is and accrue more bets."
            )

    return {
        "n": n,
        "n_open": n_open,
        "status": status,
        "win_rate": win_rate,
        "mean_brier_delta": mean_delta,
        "mean_brier_ours": sum(ours) / n,
        "mean_brier_market": sum(market) / n,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "p_value": p_value,
        "agent_wins": agent_wins,
        "market_wins": market_wins,
        "ties": ties,
        "min_sample": EDGE_MIN_SAMPLE,
        "threshold_config_key": threshold_key,
        "recommendation": recommendation,
    }


def _deviation_bet_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
