"""The REFRESH job type: the operator's Desk "Update now" (``U`` / mass-``U``) on
the one detached-job runtime (Arc B) — the runtime's FIRST net-new capability, the
Arc-B payoff proof.

``U`` used to fan ``forecast refresh <id> --json`` client-side, one gateway request
per row, with the progress + the remaining queue living in React component state.
Navigating away from the Desk killed the progress heuristic, and mass-``U``'s
un-run tail was unrecoverable on return. This type lifts that loop server-side onto
the shared runtime: ONE durable, re-attachable job over the whole batch, with an
honest per-question tally — so a live ``U`` sweep resumes exactly where it left off
when the operator comes back to the Desk.

:func:`execute` runs the SAME deterministic re-pool the CLI ``forecast refresh
<id>`` invokes — :meth:`forecasting.ledger.ForecastLedger.refresh_forecast` with the
injected :func:`forecasting.sources.watched.fetch_watched_source_payloads` fetcher — PER
QUESTION SEQUENTIALLY, fail-open per question (one bad question never kills the
batch). It opens the ledger write gate exactly the way ``cmd_forecast`` does
(``allow_ledger_writes(reason="forecast_cli")``), so ``create_snapshot``'s
panel / style / saturation / distribution gates fire UNCHANGED — nothing is
weakened. There is NO agent/LLM call here: this is the DETERMINISTIC arm (the ``A``
agent-run REFORECAST type is the LLM arm). The analyst-brief write-up the single-row
CLI refresh appends is deliberately skipped — it is an LLM call, and the mass
deterministic sweep stays LLM-free by contract.

The honest tally + the per-question outcome classification (``refreshed`` /
``unchanged`` / ``no_sources`` / ``error``) is the SERVER-SIDE port of the desk's
old client-side ``classifyRefresh`` — the desk now renders the tally the job
computed instead of classifying each response itself.
"""

from __future__ import annotations

from typing import Any

from forecasting.jobs.types import JobType, register

# Mirrors the CLI ``forecast refresh`` default (``--concurrency 4``): the fetcher's
# thread-pool width when re-pulling a question's watched sources.
DEFAULT_CONCURRENCY = 4

# The four honest per-question outcomes (the tally keys). ``refreshed`` = a live
# re-pool committed a new snapshot; ``unchanged`` = nothing moved; ``no_sources`` =
# the question has no active watched sources (NOT a completed update); ``error`` =
# the deterministic refresh raised (fail-open per question).
OUTCOMES = ("refreshed", "needs_estimation", "unchanged", "no_sources", "error")


def classify_refresh_status(status: Any) -> str:
    """Map a :meth:`refresh_forecast` result ``status`` onto one of the honest
    outcomes — the server-side port of the desk's old client ``classifyRefresh``.

    ``no_watched_sources`` → ``no_sources``; ``no_change`` → ``unchanged``; every
    other status (``committed`` for a persisted re-pool, and defensively any
    ``re_pooled`` / ``carry_forward`` preview status) → ``refreshed``. An exception
    is handled by the caller as ``error``."""

    if status == "no_watched_sources":
        return "no_sources"
    if status == "no_change":
        return "unchanged"
    if status == "needs_estimation":
        return "needs_estimation"
    return "refreshed"


def _detail_for(outcome: str, result: dict[str, Any] | None) -> str | None:
    """A short, honest per-question detail string for the results row — the
    committed forecast id + the probability move for a refresh, else the ledger's
    own message. Never fabricated."""

    if not isinstance(result, dict):
        return None
    if outcome == "refreshed":
        prior = result.get("prior_probability")
        proposed = result.get("proposed_probability")
        if isinstance(prior, (int, float)) and not isinstance(prior, bool) and isinstance(
            proposed, (int, float)
        ) and not isinstance(proposed, bool):
            return f"{float(prior):.4f}→{float(proposed):.4f}"
        return result.get("forecast_id") or "committed"
    # unchanged / no_sources both carry the ledger's own explanatory message.
    return result.get("message")


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run the deterministic re-pool for every question in ``spec`` SEQUENTIALLY,
    persisting per-question progress + an honest running tally as it goes.

    Fail-open PER QUESTION: any failure on one question is recorded as that
    question's ``error`` outcome and the batch CONTINUES. Cooperative cancel
    (``ctx.should_cancel``) stops the loop between questions and returns a graceful
    ``cancelled=True`` summary with the partial tally. A bad ``db`` raises out to the
    runtime (whole-job ``error``), matching the REFORECAST type's contract."""

    # Lazy adapters inject acquisition into the ledger; fetching owns no writes.
    from forecasting.ledger import ForecastLedger, allow_ledger_writes
    from forecasting.jobs.policy import ActionClass
    from forecasting.sources.watched import fetch_watched_source_payloads

    question_ids = [
        str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()
    ]

    # Arc-9 approval gate: the ONLY side effect of the deterministic re-pool is the
    # gated ledger commit (no LLM spend — this is the LLM-free arm by contract), so it
    # authorizes ``ledger_writes`` ONCE up front, before the loop. AUTO under every
    # default; an operator who sets ``policy.<mode>.ledger_writes`` to ask/never parks
    # or refuses the whole batch before anything is written.
    ctx.authorize(ActionClass.LEDGER_WRITES, f"deterministic re-pool of {len(question_ids)} question(s)")
    try:
        concurrency = int(spec.get("concurrency") or DEFAULT_CONCURRENCY)
    except (TypeError, ValueError):
        concurrency = DEFAULT_CONCURRENCY
    now = spec.get("now") or None
    total = len(question_ids)

    ledger = ForecastLedger(spec.get("db"))  # a bad db → runtime marks the job error

    def _fetcher(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return fetch_watched_source_payloads(specs, concurrency=concurrency)

    results: list[dict[str, Any]] = []
    tally: dict[str, int] = {outcome: 0 for outcome in OUTCOMES}
    cancelled = False

    def _save() -> None:
        """Persist the running results + tally + accounting onto the record
        UNCONDITIONALLY (annotate writes the whole record — no coalescing), so a
        mid-run ``jobs.status`` poll always reads honestly and the desk can drop the
        ⋯ marker off a completed row."""
        ctx.record.total = total
        ctx.record.done_count = len(results)
        ctx.record.annotations["results"] = results
        ctx.annotate("tally", tally)

    for qid in question_ids:
        if ctx.should_cancel():
            cancelled = True
            break

        # Emit the in-flight pointer FIRST so the desk paints the working-row
        # spinner on this question before the (potentially slow) fetch.
        ctx.progress(phase="refresh", done=len(results), total=total, current=qid)

        entry: dict[str, Any] = {"question_id": qid, "outcome": "error", "detail": None}
        try:
            # The SAME gated path the CLI ``forecast refresh`` runs: ``cmd_forecast``
            # opens ``allow_ledger_writes(reason="forecast_cli")`` around its handler,
            # so create_snapshot's gate permits the deterministic re-pool's commit.
            # Opening it here reproduces that environment on the gateway's worker
            # thread — it does NOT weaken the gate (every downstream validation still
            # fires); it only marks this as the recognised legitimate writer.
            with allow_ledger_writes(reason="forecast_cli"):
                result = ledger.refresh_forecast(
                    qid,
                    fetcher=_fetcher,
                    now=now,
                    re_estimate="deterministic",
                    extremize=1.0,
                    correlation=None,
                    dry_run=False,
                    commit=True,
                    trigger_reason="manual_refresh",
                )
            status = result.get("status") if isinstance(result, dict) else None
            outcome = classify_refresh_status(status)
            entry["outcome"] = outcome
            entry["detail"] = _detail_for(outcome, result if isinstance(result, dict) else None)
        except Exception as exc:  # noqa: BLE001 — one bad question must never kill the batch
            entry["outcome"] = "error"
            entry["detail"] = f"{type(exc).__name__}: {exc}"

        results.append(entry)
        tally[entry["outcome"]] += 1
        _save()
        ctx.progress(phase="question", done=len(results), total=total)

    return {
        "results": results,
        "tally": tally,
        "total": total,
        "done_count": len(results),
        "cancelled": cancelled,
    }


REFRESH = JobType(
    name="refresh",
    execute=execute,
    # Coarse progress (two events per question — a few dozen for a full batch, not a
    # storm). The phase alternates refresh↔question so every event is a phase-change
    # that passes the coalescer regardless; the accounting still lands each write.
    min_interval_s=0.0,
    # A NET-NEW capability — no legacy RPC family to alias, so no alias_namespace.
    alias_namespace=None,
    # Deterministic re-pool: no LLM spend (the agent arm is the REFORECAST type).
    spend_class="free",
)

register(REFRESH)

__all__ = [
    "DEFAULT_CONCURRENCY",
    "OUTCOMES",
    "REFRESH",
    "classify_refresh_status",
    "execute",
]
