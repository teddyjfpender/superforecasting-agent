"""Panel and quorum actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _required

def panel_perspectives(args: dict[str, Any], ledger) -> str:
    from forecasting.panel import (
        DEFAULT_PANEL_PERSPECTIVES,
        PANEL_PERSPECTIVES,
        build_perspective_prompts,
    )
    from forecasting.protocol import build_context_packet

    perspectives = args.get("perspectives") or list(DEFAULT_PANEL_PERSPECTIVES)
    if args.get("question_id"):
        question = ledger.get_question(args["question_id"])
        snapshot = ledger.get_current_snapshot(question.id)
        context = build_context_packet(ledger, question, snapshot)
        prompts = build_perspective_prompts(
            question_title=question.title,
            resolution_criteria=question.resolution_criteria,
            context_packet=context,
            perspectives=perspectives,
        )
    else:
        prompts = build_perspective_prompts(
            question_title=str(args.get("question_title") or "<question>"),
            resolution_criteria=str(args.get("resolution_criteria") or "<criteria>"),
            context_packet=str(args.get("context") or ""),
            perspectives=perspectives,
        )
    return tool_result(
        success=True,
        perspectives=prompts,
        catalog={k: v["label"] for k, v in PANEL_PERSPECTIVES.items()},
    )

def aggregate_panel(args: dict[str, Any], ledger) -> str:
    from forecasting.panel import aggregate_panel_estimates

    estimates = args.get("estimates")
    if not estimates:
        return tool_error("aggregate_panel requires 'estimates'", success=False)
    aggregation = aggregate_panel_estimates(
        estimates,
        method=str(args.get("method") or "trimmed_geomean_odds"),
        trim=int(args.get("trim", 1)),
    )
    return tool_result(success=True, **aggregation.to_dict())

def record_panel(args: dict[str, Any], ledger) -> str:
    estimates = args.get("estimates")
    if not estimates:
        return tool_error("record_panel requires 'estimates'", success=False)
    record = ledger.record_panel_run(
        question_id=_required(args, "question_id"),
        estimates=estimates,
        aggregation_method=str(args.get("method") or "trimmed_geomean_odds"),
        trim=int(args.get("trim", 1)),
        snapshot_id=args.get("snapshot_id"),
        triggered_by=args.get("triggered_by"),
        perspectives=args.get("perspectives"),
        judge=args.get("judge"),
    )
    # Upfront quorum feedback: the quorum_participation gate wants >= 3 DISTINCT
    # perspectives OR >= 3 distinct models. Tell the agent NOW (not only at commit)
    # when this panel won't satisfy it — the agent reported being surprised by a
    # participation warning even though it had recorded a panel.
    _min = 3
    # Mirror the gate EXACTLY so the advisory can't fabricate or miss a warning:
    # the gate uses panel_perspective_count = len(stored perspectives) [raw, incl.
    # auto-named blanks/dupes] and quorum_model_count = distinct models.
    _persp = len(record.get("perspectives") or [])
    _models = len({(e.get("agent_model") or e.get("model") or "").strip() for e in estimates if (e.get("agent_model") or e.get("model") or "").strip()})
    advisory = None
    if _persp < _min and _models < _min:
        advisory = (
            f"This panel has {_persp} distinct perspective(s) and {_models} distinct model(s); the "
            f"quorum_participation gate wants >= {_min} of EITHER. It will WARN at commit unless you "
            "record a fuller perspective panel or a wider model quorum."
        )
    return tool_result(
        success=True,
        panel_run=record,
        distinct_perspectives=_persp,
        distinct_models=_models,
        quorum_advisory=advisory,
    )

def show_panel(args: dict[str, Any], ledger) -> str:
    record = ledger.get_panel_run(_required(args, "panel_run_id"))
    return tool_result(success=True, panel_run=record)

def list_panel(args: dict[str, Any], ledger) -> str:
    rows = ledger.list_panel_runs(
        question_id=args.get("question_id"),
        limit=int(args["limit"]) if args.get("limit") is not None else 20,
    )
    return tool_result(success=True, panel_runs=rows)

def start_quorum(args: dict[str, Any], ledger) -> str:
    from forecasting.jobs.types.quorum import read_job, start_job

    # Only forward keys the caller actually set: the quorum execute resolves its
    # own defaults from a MISSING key (e.g. int(spec.get("trim", 1)),
    # pool_method fallback, the supervisor_search config fallback), so
    # writing None here would clobber those defaults / break the run.
    spec: dict[str, Any] = {"question_id": _required(args, "question_id")}
    for _key in (
        "preset",
        "models",
        "judge",
        "pool_method",
        "trim",
        "delphi_rounds",
        "supervisor_search",
    ):
        if args.get(_key) is not None:
            spec[_key] = args.get(_key)
    wait = bool(args.get("wait"))
    run_id = start_job(spec, wait=wait)
    return tool_result(
        success=True,
        run_id=run_id,
        job=read_job(run_id) if wait else None,
    )

def show_quorum_status(args: dict[str, Any], ledger) -> str:
    from forecasting.jobs.types.quorum import read_job

    return tool_result(success=True, job=read_job(_required(args, "run_id")))


HANDLERS = {
    "panel_perspectives": panel_perspectives,
    "aggregate_panel": aggregate_panel,
    "record_panel": record_panel,
    "show_panel": show_panel,
    "list_panel": list_panel,
    "start_quorum": start_quorum,
    "show_quorum_status": show_quorum_status,
}
