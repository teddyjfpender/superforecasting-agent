"""Source planning and watched-source actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from forecasting.source_search import capture_watched_text_candidates, search_watched_text_sources
from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _apply_source_plan_watches, _required, _tool_watch_metadata
from tools import forecasting_tool as _ft

def source_plan(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    question = ledger.get_question(question_id)
    recommendations = _ft.plan_sources_for_question(
        question,
        limit=int(args["limit"]) if args.get("limit") is not None else None,
    )
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if args.get("apply_watch"):
        created, skipped_recommendations = _apply_source_plan_watches(
            ledger,
            question_id,
            recommendations,
        )
        skipped = [item.to_dict() for item in skipped_recommendations]
    return tool_result(
        success=True,
        question_id=question_id,
        title=question.title,
        source_plan=[item.to_dict() for item in recommendations],
        applied_watched_sources=created,
        skipped_source_plan=skipped,
        no_silent_probability_mutation=True,
    )

def source_search(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    result = search_watched_text_sources(
        ledger,
        question_id,
        query=args.get("query"),
        limit=int(args["limit"]) if args.get("limit") is not None else 20,
        since=args.get("since"),
    )
    captured = (
        capture_watched_text_candidates(
            ledger,
            question_id,
            result.candidates,
            limit=int(args["limit"]) if args.get("limit") is not None else None,
        )
        if args.get("capture_candidates")
        else []
    )
    payload = result.to_dict()
    return tool_result(
        success=True,
        **payload,
        captured_candidates=[item.to_dict() for item in captured],
    )

def add_watched_source(args: dict[str, Any], ledger) -> str:
    watch = ledger.add_watched_source(
        scope_type=args.get("scope_type") or ("question" if args.get("question_id") else ""),
        scope_ref=args.get("scope_ref") or args.get("question_id"),
        source=_required(args, "source"),
        source_type=args.get("source_type"),
        metadata=_tool_watch_metadata(args),
    )
    return tool_result(success=True, watched_source=watch)

def add_watched_sources(args: dict[str, Any], ledger) -> str:
    entries = args.get("watches")
    if not isinstance(entries, list) or not entries:
        raise ValueError("add_watched_sources requires a non-empty watches array")
    if len(entries) > 400:
        raise ValueError("add_watched_sources caps at 400 watches per call")
    results: list[dict[str, Any]] = []
    added = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            results.append({"index": index, "success": False, "error": "entry must be an object"})
            continue
        try:
            watch = ledger.add_watched_source(
                scope_type=entry.get("scope_type") or ("question" if entry.get("question_id") else ""),
                scope_ref=entry.get("scope_ref") or entry.get("question_id"),
                source=str(entry.get("source") or "").strip(),
                source_type=entry.get("source_type"),
                metadata=_tool_watch_metadata(entry),
            )
            added += 1
            results.append({"index": index, "success": True, "watched_source": watch})
        except Exception as exc:  # per-row isolation: one bad row never kills the batch
            results.append({"index": index, "success": False, "error": str(exc)})
    return tool_result(
        success=added > 0,
        added=added,
        failed=len(results) - added,
        results=results,
        note=(
            "bulk watch add: per-row results above; failed rows carry their "
            "error and can be resubmitted alone"
        ),
    )

def list_watched_sources(args: dict[str, Any], ledger) -> str:
    watches = ledger.list_watched_sources(
        scope_type=args.get("scope_type"),
        scope_ref=args.get("scope_ref") or args.get("question_id"),
        status=None if args.get("include_inactive") else "active",
    )
    return tool_result(success=True, watched_sources=watches)

def check_watched_sources(args: dict[str, Any], ledger) -> str:
    alerts = ledger.check_watched_sources(
        scope_type=args.get("scope_type"),
        scope_ref=args.get("scope_ref") or args.get("question_id"),
    )
    return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])


HANDLERS = {
    "source_plan": source_plan,
    "source_search": source_search,
    "add_watched_source": add_watched_source,
    "add_watched_sources": add_watched_sources,
    "list_watched_sources": list_watched_sources,
    "check_watched_sources": check_watched_sources,
}
