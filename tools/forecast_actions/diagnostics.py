"""Doctor/pilot reports, exports, protocol and pipeline actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

import json

from forecasting import PRODUCT_NAME
from forecasting.models import utc_now_iso
from forecasting.protocol import build_protocol_messages
from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _forecast_operational_status, _forecast_readiness_payload, _required, _safe_templated_batches, _workflow_report_payload

def evidence_readiness(args: dict[str, Any], ledger) -> str:
    benchmarks_ran = None
    if bool(args.get("run_safe_benchmarks")):
        # Advance readiness OFFLINE — run the builtin benchmark suite (no
        # network / no paid LLM) before evaluating.
        from forecasting.application.benchmarks import run_safe_benchmarks

        source = args.get("probability_source") or "forecast-engine"
        if source not in ("forecast-engine", "baseline-ensemble"):
            return tool_result(success=False, error="run_safe_benchmarks is OFFLINE only (forecast-engine / baseline-ensemble); agent-protocol needs an LLM runner.")
        try:
            benchmarks_ran = run_safe_benchmarks(ledger, source)
        except Exception as exc:  # a mid-suite failure must not raise uncaught
            return tool_result(success=False, error=f"safe benchmark run failed: {exc}")
    rows, summaries, evidence_status, _last = _forecast_readiness_payload(ledger, args)
    return tool_result(
        success=True,
        evidence_status=evidence_status,
        backtest_summaries=summaries,
        inspected_backtest_run_ids=[row["id"] for row in rows],
        benchmarks_ran=benchmarks_ran,
    )

def doctor_report(args: dict[str, Any], ledger) -> str:
    rows, summaries, evidence_status, last = _forecast_readiness_payload(ledger, args)
    pilot_report = ledger.pilot_report(
        min_questions=int(args.get("min_questions", 3) or 0),
        min_structured_source_questions=int(
            args.get("min_structured_source_questions", 1) or 0
        ),
        min_scores=int(args.get("min_scores", 1) or 0),
        min_postmortems=int(args.get("min_postmortems", 1) or 0),
        min_scheduled_reviews=int(args.get("min_scheduled_reviews", 1) or 0),
        min_scheduled_review_runs=int(args.get("min_scheduled_review_runs", 1) or 0),
    )
    pilot_ready = pilot_report["passed_checks"] == pilot_report["total_checks"]
    readiness_gaps = bool(evidence_status.get("gaps"))
    if not pilot_ready:
        doctor_status = "needs_tester_pilot_artifacts"
    elif readiness_gaps:
        doctor_status = "tester_handoff_ready_live_claim_unproven"
    else:
        doctor_status = "benchmark_evidence_ready_live_claim_unproven"

    operational_status = _forecast_operational_status(ledger, pilot_report)
    from forecasting.protocol import PROCESS_VERSION

    return tool_result(
        success=True,
        product=PRODUCT_NAME,
        process_version=PROCESS_VERSION,
        generated_at=utc_now_iso(),
        doctor_status=doctor_status,
        tester_handoff_ready=pilot_ready,
        claim_live_superforecasting=evidence_status.get("can_claim_live_superforecasting"),
        status=operational_status,
        operational_status=operational_status,
        pilot_report=pilot_report,
        readiness={
            "last": last,
            "dataset_filter": args.get("dataset"),
            "run_count": len(summaries),
            "inspected_backtest_run_ids": [row["id"] for row in rows],
            "evidence_status": evidence_status,
        },
        evidence_status=evidence_status,
        backtest_summaries=summaries,
        inspected_backtest_run_ids=[row["id"] for row in rows],
        required_exit_gates={
            "pilot_ready_required": False,
            "readiness_required": False,
            "pilot_ready": pilot_ready,
            "readiness_gaps": readiness_gaps,
        },
        templated_batches=_safe_templated_batches(ledger),
    )

def pilot_report(args: dict[str, Any], ledger) -> str:
    return tool_result(
        success=True,
        pilot_report=ledger.pilot_report(
            min_questions=int(args.get("min_questions", 3) or 0),
            min_structured_source_questions=int(
                args.get("min_structured_source_questions", 1) or 0
            ),
            min_scores=int(args.get("min_scores", 1) or 0),
            min_postmortems=int(args.get("min_postmortems", 1) or 0),
            min_scheduled_reviews=int(args.get("min_scheduled_reviews", 1) or 0),
            min_scheduled_review_runs=int(args.get("min_scheduled_review_runs", 1) or 0),
        ),
    )

def detect_templated_batches(args: dict[str, Any], ledger) -> str:
    return tool_result(
        success=True,
        templated_batches=ledger.detect_templated_batches(
            window_days=int(args.get("window_days", 7) or 7),
            min_cluster=int(args.get("min_cluster", 3) or 3),
        ),
    )

def forecast_complementarity(args: dict[str, Any], ledger) -> str:
    from forecasting.market_ensemble import complementarity_report

    report = complementarity_report(
        ledger,
        forecast_origin=args.get("forecast_origin") or "live",
        min_sample=int(args.get("min_sample", 30) or 30),
    )
    return tool_result(success=True, forecast_complementarity=report)

def thesis_dashboard(args: dict[str, Any], ledger) -> str:
    from forecasting.application.aggregate_summaries import build_factor_summary, build_thesis_summary

    return tool_result(
        success=True,
        theses=build_thesis_summary(ledger=ledger),
        factors=build_factor_summary(ledger=ledger),
    )

def tail_audit(args: dict[str, Any], ledger) -> str:
    from forecasting.tail_audit import (
        audit_outcomes,
        outcome_paths_from_inputs,
        render_audit_table,
    )

    distribution = args.get("distribution")
    if not isinstance(distribution, dict) or not distribution:
        return tool_error(
            "tail_audit requires a categorical `distribution` object "
            "{outcome: probability}",
            success=False,
        )
    try:
        dist = {str(k): float(v) for k, v in distribution.items()}
    except (TypeError, ValueError):
        return tool_error("distribution probabilities must be numeric", success=False)
    audit = audit_outcomes(
        outcome_paths_from_inputs(dist, args.get("outcome_paths"))
    )
    return tool_result(
        success=True,
        audit=audit.to_dict(),
        table=render_audit_table(audit),
        note=(
            "Every material outcome (>=0.5%) must route through a named path; "
            "mass with no mechanism is UNEARNED tail mass — name the path or "
            "compress it onto outcomes with a live mechanism. Pass these same "
            "outcome_paths to update_forecast with require_outcome_paths=true to "
            "enforce it on the committed snapshot."
        ),
    )

def workflow_report(args: dict[str, Any], ledger) -> str:
    return _workflow_report_payload(ledger, args)

def export_question(args: dict[str, Any], ledger) -> str:
    fmt = args.get("format") or "json"
    exported = ledger.export_question(_required(args, "question_id"), fmt=fmt)
    if fmt == "json":
        return tool_result(success=True, format=fmt, packet=json.loads(exported))
    return tool_result(success=True, format=fmt, export=exported)

def export_all(args: dict[str, Any], ledger) -> str:
    fmt = args.get("format") or "json"
    exported = ledger.export_all(fmt=fmt)
    if fmt == "json":
        return tool_result(success=True, format=fmt, packet=json.loads(exported))
    return tool_result(success=True, format=fmt, export=exported)

def import_packet(args: dict[str, Any], ledger) -> str:
    packet = args.get("packet")
    if not isinstance(packet, dict):
        return tool_error("import_packet requires a packet object", success=False)
    summary = ledger.import_packet(packet, conflict=args.get("conflict") or "error")
    return tool_result(success=True, import_summary=summary)

def protocol(args: dict[str, Any], ledger) -> str:
    messages = build_protocol_messages(
        ledger,
        _required(args, "question_id"),
        stage=args.get("stage") or "update",
    )
    return tool_result(success=True, messages=[message.__dict__ for message in messages])

def pipeline(args: dict[str, Any], ledger) -> str:
    from forecasting.protocol import build_pipeline_status, pipeline_advance_block

    question_id = _required(args, "question_id")
    status = build_pipeline_status(ledger, question_id)
    stage = args.get("stage")
    if stage:
        block = pipeline_advance_block(status, stage)
        if block and not bool(args.get("force", False)):
            return tool_error(block, success=False)
        messages = build_protocol_messages(ledger, question_id, stage=stage)
        return tool_result(
            success=True,
            stage=stage,
            pipeline=status,
            messages=[message.__dict__ for message in messages],
        )
    return tool_result(success=True, pipeline=status)


HANDLERS = {
    "evidence_readiness": evidence_readiness,
    "doctor_report": doctor_report,
    "pilot_report": pilot_report,
    "detect_templated_batches": detect_templated_batches,
    "forecast_complementarity": forecast_complementarity,
    "thesis_dashboard": thesis_dashboard,
    "tail_audit": tail_audit,
    "workflow_report": workflow_report,
    "export_question": export_question,
    "export_all": export_all,
    "import_packet": import_packet,
    "protocol": protocol,
    "pipeline": pipeline,
}
