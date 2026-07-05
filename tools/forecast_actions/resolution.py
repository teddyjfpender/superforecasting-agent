"""Resolution-rule, proposal and scoring actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

import os

from forecasting.models import ForecastingError
from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _required

def set_resolution_rule(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    if args.get("threshold") is None:
        raise ForecastingError("threshold is required for set_resolution_rule")
    rule = ledger.set_resolution_rule(
        question_id,
        field=_required(args, "field"),
        comparator=_required(args, "comparator"),
        threshold=float(args["threshold"]),
        resolver=args.get("resolver") or "metric_threshold",
        source_role=args.get("source_role") or "resolver",
    )
    return tool_result(success=True, question_id=question_id, resolution_rule=rule)

def propose_resolution(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    proposal = ledger.propose_resolution(question_id)
    return tool_result(success=True, question_id=question_id, resolution_proposal=proposal)

def propose_resolutions(args: dict[str, Any], ledger) -> str:
    from forecasting import resolution_detector as _rd

    dry_run = bool(args.get("dry_run"))
    horizon_days = int(args.get("horizon_days") or _rd.DEFAULT_HORIZON_DAYS)
    limit = args.get("limit")
    market_reader = None
    try:
        market_reader = _rd.build_market_outcome_reader()
    except Exception:
        market_reader = None

    classifier = None
    runner = None
    model = ""
    if args.get("use_llm"):
        # Opt-in paid tier: wire the bounded cheap-model runner (mirrors the
        # triage labeler) + the reference classifier. Only reached on an
        # explicit use_llm=true, so the default path spends nothing.
        from forecasting.quorum import DEFAULT_JUDGE_MODEL, make_aiagent_runner

        model = args.get("model") or os.getenv("FORECAST_RESOLUTION_MODEL") or DEFAULT_JUDGE_MODEL
        runner = make_aiagent_runner(toolsets=(), max_iterations=2, quiet=True, timeout=180)
        classifier = _rd.classify_resolution

    summary = _rd.propose_detected_resolutions(
        ledger,
        now=args.get("now"),
        horizon_days=horizon_days,
        market_reader=market_reader,
        classifier=classifier,
        runner=runner,
        model=model,
        limit=int(limit) if limit is not None else None,
        dry_run=dry_run,
    )
    return tool_result(success=True, **summary)

def list_resolution_proposals(args: dict[str, Any], ledger) -> str:
    from forecasting.ledger import alerts as _alerts

    proposals = []
    for alert in ledger.list_alerts(unresolved_only=True):
        if getattr(alert, "scope_type", None) != "question":
            continue
        outcome = _alerts.resolution_proposal_outcome(getattr(alert, "reason", ""))
        if not outcome:
            continue
        proposals.append({
            "alert_id": alert.id,
            "question_id": alert.scope_ref,
            "outcome": outcome,
            "reason": alert.reason,
            "confirm_command": alert.recommended_action,
            "created_at": alert.created_at,
        })
    return tool_result(success=True, count=len(proposals), proposals=proposals)

def resolve(args: dict[str, Any], ledger) -> str:
    resolution = ledger.resolve_question(
        question_id=_required(args, "question_id"),
        outcome=_required(args, "outcome"),
        resolution_source=args.get("resolution_source"),
        resolution_source_snapshot_ref=args.get("resolution_source_snapshot_ref"),
        resolver_type=args.get("resolver_type") or "manual",
        resolution_status=args.get("resolution_status") or "confirmed",
        criteria_satisfied=bool(args.get("criteria_satisfied", True)),
        confidence=args.get("confidence"),
        confirmed_by=args.get("confirmed_by"),
        resolver_notes=args.get("resolver_notes"),
        correction_ref=args.get("correction_ref"),
        trusted_policy_id=args.get("trusted_policy_id"),
        scoreable=bool(args.get("scoreable", True)),
        auto_score=bool(args.get("auto_score", True)),
    )
    try:
        if resolution.resolution_status == "confirmed" and resolution.criteria_satisfied:
            from forecasting.writeup import write_retrospective

            _qid = args.get("question_id")
            write_retrospective(ledger, _qid, score=ledger.get_current_score(_qid))
    except Exception:
        pass
    return tool_result(success=True, resolution=resolution.__dict__)

def score(args: dict[str, Any], ledger) -> str:
    score = ledger.score_question(_required(args, "question_id"))
    return tool_result(success=True, score=score.__dict__)

def list_scores(args: dict[str, Any], ledger) -> str:
    scores = ledger.list_scores(
        domain=args.get("domain"),
        forecast_origin=args.get("forecast_origin"),
        calibration_eligible=args.get("calibration_eligible"),
        horizon=args.get("horizon"),
        bucket=args.get("bucket"),
        include_invalidated=bool(args.get("include_invalidated", False)),
    )
    return tool_result(success=True, scores=[score.__dict__ for score in scores])


HANDLERS = {
    "set_resolution_rule": set_resolution_rule,
    "propose_resolution": propose_resolution,
    "propose_resolutions": propose_resolutions,
    "list_resolution_proposals": list_resolution_proposals,
    "resolve": resolve,
    "score": score,
    "list_scores": list_scores,
}
