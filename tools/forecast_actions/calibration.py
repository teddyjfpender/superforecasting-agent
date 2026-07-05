"""Calibration, operator, backtest, correction and lesson actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _required

def calibration_summary(args: dict[str, Any], ledger) -> str:
    summary = ledger.calibration_summary(
        domain=args.get("domain"),
        forecast_origin=args.get("forecast_origin"),
        horizon=args.get("horizon"),
        calibration_eligible=args.get("calibration_eligible"),
    )
    return tool_result(success=True, calibration=summary)

def record_operator_estimate(args: dict[str, Any], ledger) -> str:
    probability = args.get("probability")
    if probability is None:
        probability = args.get("probability_or_distribution")
    if probability is None:
        raise ValueError("probability is required")
    estimate = ledger.record_operator_estimate(
        _required(args, "question_id"),
        probability,
        note=args.get("note"),
        context=args.get("context") or "practice",
    )
    return tool_result(success=True, operator_estimate=estimate)

def operator_calibration(args: dict[str, Any], ledger) -> str:
    window_days = args.get("window_days")
    summary = ledger.operator_calibration_summary(
        window_days=int(window_days) if window_days is not None else None
    )
    return tool_result(success=True, operator_calibration=summary)

def list_domain_error_profiles(args: dict[str, Any], ledger) -> str:
    profiles = ledger.list_domain_error_profiles(
        domain=args.get("domain"),
        topic=args.get("topic"),
    )
    return tool_result(success=True, domain_error_profiles=profiles)

def run_backtest_dataset(args: dict[str, Any], ledger) -> str:
    run = ledger.run_backtest_dataset(
        dataset=_required(args, "dataset"),
        cases=args.get("cases") or [],
        default_forecast_time_cutoff=args.get("default_forecast_time_cutoff"),
        evidence_cutoff_policy=args.get("evidence_cutoff_policy") or "available_at_lte_cutoff",
        allow_calibration_memory=bool(args.get("allow_calibration_memory", False)),
    )
    return tool_result(success=True, backtest_run=run)

def list_backtest_runs(args: dict[str, Any], ledger) -> str:
    return tool_result(success=True, backtest_runs=ledger.list_backtest_runs())

def backtest_performance_report(args: dict[str, Any], ledger) -> str:
    report = ledger.backtest_performance_report(_required(args, "run_id"))
    return tool_result(success=True, backtest_performance=report)

def list_calibration_lessons(args: dict[str, Any], ledger) -> str:
    lessons = ledger.list_calibration_lessons(
        scope_type=args.get("scope_type"),
        scope_ref=args.get("scope_ref"),
        active_only=bool(args.get("active_only", False)),
    )
    return tool_result(success=True, calibration_lessons=lessons)

def update_calibration_lesson(args: dict[str, Any], ledger) -> str:
    lesson = ledger.update_calibration_lesson(
        _required(args, "lesson_id"),
        status=args.get("lesson_status"),
        confidence=args.get("confidence"),
    )
    return tool_result(success=True, calibration_lesson=lesson)

def postmortem(args: dict[str, Any], ledger) -> str:
    postmortem = ledger.create_postmortem(
        question_id=_required(args, "question_id"),
        summary=args.get("summary") or "",
        what_happened=args.get("what_happened") or "",
        what_was_expected=args.get("what_was_expected") or "",
        missed_evidence=args.get("missed_evidence") or "",
        overweighted_evidence=args.get("overweighted_evidence") or "",
        base_rate_error=args.get("base_rate_error") or "",
        inside_view_error=args.get("inside_view_error") or "",
        resolution_error=args.get("resolution_error") or "",
        lesson=args.get("lesson") or "",
        calibration_adjustment=args.get("calibration_adjustment") or {},
        failure_class=args.get("failure_class"),
    )
    return tool_result(success=True, postmortem=postmortem)

def list_postmortems(args: dict[str, Any], ledger) -> str:
    postmortems = ledger.list_postmortems(
        question_id=args.get("question_id"),
        include_invalidated=bool(args.get("include_invalidated", False)),
    )
    return tool_result(success=True, postmortems=postmortems)

def create_correction(args: dict[str, Any], ledger) -> str:
    correction = ledger.create_correction(
        target_type=_required(args, "target_type"),
        target_id=_required(args, "target_id"),
        reason=_required(args, "reason"),
        created_by=args.get("created_by"),
        old_value=args.get("old_value"),
        new_value=args.get("new_value"),
        patch=args.get("patch") or {},
        status=args.get("status") or "proposed",
    )
    return tool_result(success=True, correction=correction)

def list_corrections(args: dict[str, Any], ledger) -> str:
    corrections = ledger.list_corrections(
        target_type=args.get("target_type"),
        target_id=args.get("target_id"),
        status=args.get("status"),
    )
    return tool_result(success=True, corrections=corrections)


HANDLERS = {
    "calibration_summary": calibration_summary,
    "record_operator_estimate": record_operator_estimate,
    "operator_calibration": operator_calibration,
    "list_domain_error_profiles": list_domain_error_profiles,
    "run_backtest_dataset": run_backtest_dataset,
    "list_backtest_runs": list_backtest_runs,
    "backtest_performance_report": backtest_performance_report,
    "list_calibration_lessons": list_calibration_lessons,
    "update_calibration_lesson": update_calibration_lesson,
    "postmortem": postmortem,
    "list_postmortems": list_postmortems,
    "create_correction": create_correction,
    "list_corrections": list_corrections,
}
