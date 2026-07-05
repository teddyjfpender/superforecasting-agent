"""Review, alert, warning and scheduled-review actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _infer_schedule_scope_ref, _infer_schedule_scope_type, _required, _review_row, _scheduled_result

def review(args: dict[str, Any], ledger) -> str:
    rows = ledger.review_questions(
        stale=bool(args.get("stale", False)),
        last_days=args.get("last_days") or 7,
        domain=args.get("domain"),
        topic=args.get("topic"),
        horizon=args.get("horizon"),
        confidence_below=args.get("confidence_below"),
        confidence_above=args.get("confidence_above"),
        large_delta_threshold=args.get("large_delta_threshold"),
        now=args.get("now"),
    )
    return tool_result(success=True, review=[_review_row(row) for row in rows])

def self_check(args: dict[str, Any], ledger) -> str:
    alerts = ledger.self_check(
        question_id=args.get("question_id"),
        domain=args.get("domain"),
        topic=args.get("topic"),
        horizon=args.get("horizon"),
        portfolio=args.get("portfolio"),
        stale_days=args.get("last_days") or 7,
        now=args.get("now"),
        confidence_below=args.get("confidence_below"),
        confidence_above=args.get("confidence_above"),
        large_delta_threshold=args.get("large_delta_threshold"),
        auto_score=bool(args.get("auto_score", False)),
        auto_postmortem=bool(args.get("auto_postmortem", False)),
    )
    return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])

def list_alerts(args: dict[str, Any], ledger) -> str:
    alerts = ledger.list_alerts(unresolved_only=bool(args.get("unresolved_only", True)))
    return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])

def acknowledge_alert(args: dict[str, Any], ledger) -> str:
    alert = ledger.acknowledge_alert(
        _required(args, "alert_id"),
        acknowledged_at=args.get("acknowledged_at"),
    )
    return tool_result(success=True, alert=alert.__dict__)

def resolve_warning(args: dict[str, Any], ledger) -> str:
    from forecasting import warnings as fwarn
    from forecasting.cron_runner import build_warning_runners

    ref = _required(args, "ref")
    now = args.get("now")
    runners = build_warning_runners(ledger, now=now)
    open_alerts = ledger.list_alerts(unresolved_only=True)
    if ref.startswith("al_"):
        selected = [a for a in open_alerts if a.id == ref]
    else:
        selected = [w.alert for w in fwarn.iter_warnings(ledger, scope=ref)]
    if not selected:
        return tool_result(success=False, error=f"no open alert for {ref}")
    results = [
        fwarn.resolve_alert(ledger, alert, runners=runners, now=now)
        for alert in selected
    ]
    return tool_result(success=True, results=results, count=len(results))

def run_warning_automode(args: dict[str, Any], ledger) -> str:
    from forecasting.cron_runner import run_warning_resolution

    summary = run_warning_resolution(
        ledger=ledger,
        now=args.get("now"),
        limit=int(args["limit"]) if args.get("limit") is not None else None,
        reason=args.get("reason"),
        scope=args.get("scope"),
        kinds=args.get("kinds"),
        tier=args.get("tier"),
        dry_run=bool(args.get("dry_run", False)),
        reconcile=bool(args.get("reconcile", True)),
    )
    return tool_result(success=True, **summary)

def schedule_review(args: dict[str, Any], ledger) -> str:
    schedule = ledger.schedule_review(
        scope_type=args.get("scope_type") or _infer_schedule_scope_type(args),
        scope_ref=args.get("scope_ref") or _infer_schedule_scope_ref(args),
        cadence=_required(args, "cadence"),
        next_run_at=args.get("next_run_at"),
        trigger_reason=args.get("trigger_reason") or "scheduled",
        enabled=bool(args.get("enabled", True)),
        auto_score=bool(args.get("auto_score", False)),
        auto_postmortem=bool(args.get("auto_postmortem", False)),
        stale_days=int(args.get("stale_days") or args.get("last_days") or 7),
        confidence_below=args.get("confidence_below"),
        confidence_above=args.get("confidence_above"),
        large_delta_threshold=args.get("large_delta_threshold"),
    )
    return tool_result(success=True, scheduled_review=schedule)

def list_scheduled_reviews(args: dict[str, Any], ledger) -> str:
    return tool_result(success=True, scheduled_reviews=ledger.list_scheduled_reviews())

def run_scheduled_reviews(args: dict[str, Any], ledger) -> str:
    results = ledger.run_due_scheduled_reviews(
        now=args.get("now"),
        auto_score=bool(args.get("auto_score", False)),
        auto_postmortem=bool(args.get("auto_postmortem", False)),
    )
    return tool_result(success=True, scheduled_review_results=[_scheduled_result(row) for row in results])

def check_update_triggers(args: dict[str, Any], ledger) -> str:
    observations = args.get("observations")
    if observations is not None and not isinstance(observations, dict):
        return tool_error(
            "observations must be an object mapping source_ref -> value",
            success=False,
        )
    alerts = ledger.check_update_triggers(
        question_id=_required(args, "question_id"),
        observations=observations or None,
        now=args.get("now"),
    )
    return tool_result(success=True, alerts=[alert.__dict__ for alert in alerts])


HANDLERS = {
    "review": review,
    "self_check": self_check,
    "list_alerts": list_alerts,
    "acknowledge_alert": acknowledge_alert,
    "resolve_warning": resolve_warning,
    "run_warning_automode": run_warning_automode,
    "schedule_review": schedule_review,
    "list_scheduled_reviews": list_scheduled_reviews,
    "run_scheduled_reviews": run_scheduled_reviews,
    "check_update_triggers": check_update_triggers,
}
