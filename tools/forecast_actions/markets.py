"""Market-quality, prediction-market and research-audit actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _market_data_service, _market_query_refs, _pm_service, _required

def market_quality(args: dict[str, Any], ledger) -> str:
    from forecasting.market_quality import (
        MarketReading,
        age_days_from_timestamp,
        classify_market,
        reading_from_evidence,
    )

    markets = args.get("markets")
    if not isinstance(markets, list) or not markets:
        return tool_error(
            "market_quality requires a `markets` array of "
            "{source, volume?, updated_at?|age_days?, probability?} objects",
            success=False,
        )
    results = []
    for row in markets:
        if not isinstance(row, dict):
            continue
        if "age_days" in row and row.get("age_days") is not None:
            reading = MarketReading(
                source=str(row.get("source") or "market"),
                probability=row.get("probability"),
                volume=row.get("volume"),
                age_days=row.get("age_days"),
            )
        else:
            reading = reading_from_evidence(row, now=args.get("now"))
        results.append(classify_market(reading).to_dict())
    return tool_result(
        success=True,
        markets=results,
        note=(
            "weight is an ADVISORY pooling multiplier in [0,1]: stale or thin markets "
            "are discounted so a price nobody is defending can't inflate a tail. Multiply "
            "it into the market component's `weight` in ensemble_components on update_forecast "
            "(e.g. a liquid market weight 2 stays 2; a stale one at 0.25 becomes 0.5). Never "
            "drop a market silently — record the discounted weight."
        ),
    )

def pm_query(args: dict[str, Any], ledger) -> str:
    pm_mode = str(args.get("pm_mode") or args.get("mode") or "").strip().lower()
    venue = args.get("venue") or None
    svc = _pm_service()
    if pm_mode == "search":
        try:
            pm_limit = int(args.get("limit") or 20)
        except (TypeError, ValueError):
            pm_limit = 20
        pm_limit = max(1, min(pm_limit, 100))
        pairs = svc.list_events(
            venue=str(venue) if venue else None,
            query=args.get("query") or None,
            tag=args.get("tag") or None,
            limit=pm_limit,
        )
        events = [
            {"event": ev.to_dict(), "distribution": dist.to_dict()}
            for ev, dist in pairs
        ]
        return tool_result(
            success=True,
            mode="search",
            count=len(events),
            events=events,
            note=(
                "Market priors across Polymarket + Kalshi. Each distribution is "
                "de-vigged (normalized=true) or left raw when the outcome set isn't a "
                "guaranteed mutually-exclusive partition — read `normalized` before "
                "trusting sum-to-1. Drill into one with mode='event'."
            ),
        )
    if pm_mode == "event":
        if not venue or not args.get("event_id"):
            return tool_error(
                "pm_query mode='event' requires venue and event_id", success=False
            )
        event, dist = svc.event_detail(str(venue), str(args.get("event_id")))
        return tool_result(
            success=True,
            mode="event",
            event=event.to_dict(),
            distribution=dist.to_dict(),
            note=(
                "Full de-vigged outcome distribution. `outcomes[].raw_prob` is the "
                "pre-devig YES mid; `outcomes[].prob` is normalized. Feed prob into a "
                "market component; discount thin/zero-liquidity outcomes (liquid=false)."
            ),
        )
    if pm_mode == "book":
        if not venue or not args.get("market_id"):
            return tool_error(
                "pm_query mode='book' requires venue and market_id", success=False
            )
        book = svc.orderbook(str(venue), str(args.get("market_id")))
        return tool_result(
            success=True,
            mode="book",
            book=book.to_dict(),
            note=(
                "YES-oriented order book. Bid/ask depth is a liquidity signal: a wide "
                "spread or thin size means the mid is weakly defended — discount the "
                "market prior's weight accordingly (see market_quality)."
            ),
        )
    if pm_mode == "history":
        if not venue or not args.get("market_id"):
            return tool_error(
                "pm_query mode='history' requires venue and market_id", success=False
            )
        series_ticker = args.get("series_ticker") or None
        points = svc.history(
            str(venue),
            str(args.get("market_id")),
            series_ticker=str(series_ticker) if series_ticker else None,
            interval=str(args.get("range") or args.get("interval") or "1w"),
        )
        return tool_result(
            success=True,
            mode="history",
            count=len(points),
            points=[p.to_dict() for p in points],
            note=(
                "Price-probability time series on a [0,1] scale. Use it for the market's "
                "trajectory/status-quo anchor, not just the latest mid."
            ),
        )
    return tool_error(
        "pm_query requires pm_mode in {search, event, book, history}", success=False
    )

def market_query(args: dict[str, Any], ledger) -> str:
    refs = _market_query_refs(args)
    if not refs:
        return tool_error(
            "market_query requires `market_series` (refs) or `symbols` + `provider(s)`; "
            "e.g. providers=['frankfurter'], symbols=['EUR','JPY'] or "
            "market_series=[{'provider':'bea','symbol':'T20305'}]",
            success=False,
        )
    quotes = _market_data_service().quotes(refs)
    return tool_result(
        success=True,
        count=len(quotes),
        quotes=[q.to_dict() for q in quotes],
        note=(
            "Server-side market readings with the honesty law enforced: a missing "
            "value is null ('—'), never 0. `change`/`changePct` are the day (FX) or "
            "quarter (BEA) delta vs the prior close; `history` is the recent series for "
            "a trend/status-quo anchor. Keyed providers (BEA) return nothing without a "
            "key — set it with `forecast api-key set bea <key>`."
        ),
    )

def research_plan(args: dict[str, Any], ledger) -> str:
    from forecasting.research_audit import build_research_plan

    question = ledger.get_question(_required(args, "question_id"))
    snapshot = ledger.get_current_snapshot(question.id)
    plan = build_research_plan(question, snapshot=snapshot)
    return tool_result(
        success=True,
        plan=plan,
        note=(
            "Work the VOI angles FIRST — update_trigger / change_my_mind / outcome_path "
            "angles hunt for exactly what would move THIS forecast, not the topic in "
            "general. Import material findings with import_source_evidence, then call "
            "action='research_audit' before you finish to close any gaps."
        ),
    )

def research_audit(args: dict[str, Any], ledger) -> str:
    from forecasting.research_audit import audit_research

    question = ledger.get_question(_required(args, "question_id"))
    # Opt-in LLM change_my_mind-coverage check: only when a model is passed
    # (deterministic checks always run and are cheap). Fail-open — a runner
    # that errors simply drops that one check.
    runner = None
    audit_model = args.get("model")
    if audit_model:
        try:
            from forecasting.quorum import make_aiagent_runner

            runner = make_aiagent_runner(
                max_iterations=1, toolsets=(), quiet=True, timeout=120
            )
        except Exception:
            runner = None
    audit = audit_research(
        ledger, question, runner=runner, model=audit_model
    )
    return tool_result(
        success=True,
        audit=audit,
        note=(
            "adequate=false means the research is thin on a lever that matters — close the "
            "listed gaps (import evidence for the suggested_queries, add a reference class, "
            "or watch an executable trigger's source) and re-audit. The deterministic checks "
            "always run; a model= arg adds an advisory change_my_mind-coverage check."
        ),
    )


HANDLERS = {
    "market_quality": market_quality,
    "pm_query": pm_query,
    "market_query": market_query,
    "research_plan": research_plan,
    "research_audit": research_audit,
}
