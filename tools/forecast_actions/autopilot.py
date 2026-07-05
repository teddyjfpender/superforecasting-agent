"""Autopilot and forecast-update-proposal actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _plain, _required, _tool_autopilot_guardrail_policy, _tool_autopilot_materiality_policy, _tool_autopilot_notification_policy, _tool_autopilot_required_sources, _tool_autopilot_sources, _tool_proposed_probability
from tools import forecasting_tool as _ft

def autopilot_readiness(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    readiness = ledger.autopilot_readiness(
        question_id,
        sources=_tool_autopilot_sources(args, required=False),
        allow_missing_resolution_source=bool(args.get("allow_missing_resolution_source", False)),
    )
    return tool_result(success=True, readiness=readiness)

def enable_autopilot(args: dict[str, Any], ledger) -> str:
    result = ledger.enable_autopilot(
        question_id=_required(args, "question_id"),
        sources=_tool_autopilot_sources(args, required=True) or [],
        cadence=_required(args, "cadence"),
        mode=args.get("mode") or "propose",
        materiality_policy=_tool_autopilot_materiality_policy(args),
        guardrail_policy=_tool_autopilot_guardrail_policy(args),
        notification_policy=_tool_autopilot_notification_policy(args),
        required_sources=_tool_autopilot_required_sources(args),
        next_run_at=args.get("next_run_at"),
        created_by=args.get("created_by"),
        allow_missing_resolution_source=bool(args.get("allow_missing_resolution_source", False)),
    )
    return tool_result(success=True, **_plain(result))

def disable_autopilot(args: dict[str, Any], ledger) -> str:
    policy = ledger.disable_autopilot(_required(args, "question_id"))
    return tool_result(success=True, autopilot_policy=policy)

def autopilot_status(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    policies = ledger.list_autopilot_policies(question_id=question_id, enabled_only=False)
    watches = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    runs = ledger.list_autopilot_runs(
        question_id=question_id,
        limit=int(args.get("limit") or 5),
    )
    proposals = ledger.list_forecast_update_proposals(
        question_id=question_id,
        status=None,
        limit=int(args.get("limit") or 20),
    )
    return tool_result(
        success=True,
        question_id=question_id,
        active_policy=next((row for row in policies if row.get("enabled")), None),
        autopilot_policies=policies,
        watched_sources=watches,
        autopilot_runs=runs,
        forecast_update_proposals=proposals,
        pending_proposal_count=len([row for row in proposals if row.get("status") == "pending"]),
    )

def run_autopilot(args: dict[str, Any], ledger) -> str:
    result = ledger.run_autopilot(
        _required(args, "question_id"),
        now=args.get("now"),
        trigger_reason=args.get("trigger_reason") or "manual",
        proposed_probability_or_distribution=_tool_proposed_probability(args),
        rationale=args.get("rationale"),
    )
    return tool_result(success=True, **_plain(result))

def refresh_forecast(args: dict[str, Any], ledger) -> str:
    _concurrency = int(args.get("concurrency") or 4)
    result = ledger.refresh_forecast(
        _required(args, "question_id"),
        fetcher=lambda specs: _ft.fetch_watched_source_payloads(specs, concurrency=_concurrency),
        now=args.get("now"),
        re_estimate=args.get("re_estimate") or "deterministic",
        extremize=float(args.get("extremize") or 1.0),
        correlation=args.get("correlation"),
        dry_run=bool(args.get("dry_run", False)),
        commit=bool(args.get("commit", True)),
        trigger_reason=args.get("trigger_reason") or "tool_refresh",
    )
    return tool_result(success=True, **_plain(result))

def list_autopilot_policies(args: dict[str, Any], ledger) -> str:
    policies = ledger.list_autopilot_policies(
        question_id=args.get("question_id"),
        enabled_only=not bool(args.get("include_inactive", False)),
    )
    return tool_result(success=True, autopilot_policies=policies)

def list_autopilot_runs(args: dict[str, Any], ledger) -> str:
    runs = ledger.list_autopilot_runs(
        question_id=args.get("question_id"),
        policy_id=args.get("policy_id"),
        limit=int(args.get("limit") or 20),
    )
    return tool_result(success=True, autopilot_runs=runs)

def list_forecast_update_proposals(args: dict[str, Any], ledger) -> str:
    proposal_status = args.get("proposal_status", args.get("status", "pending"))
    proposals = ledger.list_forecast_update_proposals(
        question_id=args.get("question_id"),
        status=None if args.get("include_reviewed") else proposal_status,
        limit=int(args.get("limit") or 20),
    )
    return tool_result(success=True, forecast_update_proposals=proposals)

def approve_forecast_update_proposal(args: dict[str, Any], ledger) -> str:
    proposal_id = _required(args, "proposal_id")
    snapshot = ledger.approve_forecast_update_proposal(
        proposal_id,
        reviewed_by=args.get("reviewed_by"),
    )
    return tool_result(
        success=True,
        forecast_snapshot=snapshot.__dict__,
        forecast_update_proposal=ledger.get_forecast_update_proposal(proposal_id),
    )

def reject_forecast_update_proposal(args: dict[str, Any], ledger) -> str:
    proposal = ledger.reject_forecast_update_proposal(
        _required(args, "proposal_id"),
        reviewed_by=args.get("reviewed_by"),
    )
    return tool_result(success=True, forecast_update_proposal=proposal)


HANDLERS = {
    "autopilot_readiness": autopilot_readiness,
    "enable_autopilot": enable_autopilot,
    "disable_autopilot": disable_autopilot,
    "autopilot_status": autopilot_status,
    "run_autopilot": run_autopilot,
    "refresh_forecast": refresh_forecast,
    "list_autopilot_policies": list_autopilot_policies,
    "list_autopilot_runs": list_autopilot_runs,
    "list_forecast_update_proposals": list_forecast_update_proposals,
    "approve_forecast_update_proposal": approve_forecast_update_proposal,
    "reject_forecast_update_proposal": reject_forecast_update_proposal,
}
