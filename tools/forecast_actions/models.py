"""Model-run, living-model and bayes-toolkit actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from forecasting.ensembles import linear_trend_projection
from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _MARKET_COMPUTE_MODEL_TYPES, _required

def record_model_run(args: dict[str, Any], ledger) -> str:
    model_type = _required(args, "model_type")
    inputs = args.get("inputs") or {}
    parameters = args.get("parameters") or {}
    output = args.get("output") or {}
    if model_type == "trend_projection":
        series = args.get("series") or inputs.get("series")
        if series:
            target_date = args.get("target_date") or parameters.get("target_date")
            target_x = args.get("target_x")
            if target_x is None:
                target_x = parameters.get("target_x")
            date_field = args.get("date_field") or parameters.get("date_field") or "date"
            value_field = args.get("value_field") or parameters.get("value_field") or "value"
            # ONE engine: linear_trend_projection now delegates its OLS fit +
            # prediction interval to forecasting.market_compute, so this and the
            # market_compute tool share a single audited least-squares path.
            projection = linear_trend_projection(
                series,
                target_date=target_date,
                target_x=target_x,
                date_field=date_field,
                value_field=value_field,
            )
            inputs.setdefault("series", series)
            parameters.setdefault("target_date", target_date)
            parameters.setdefault("target_x", target_x)
            parameters.setdefault("date_field", date_field)
            parameters.setdefault("value_field", value_field)
            for key, value in projection.items():
                output.setdefault(key, value)
    elif model_type in _MARKET_COMPUTE_MODEL_TYPES:
        # Route deterministic families (ols / loglinear / timeseries_trend /
        # montecarlo / correlation / arima / ...) through the SAME
        # market_compute engine the Market Model uses, and merge its summary
        # scalars (r2, projected endpoints, tail percentiles, ...) into the
        # stored output alongside whatever the caller passed. No-backend safe:
        # market_compute is pure-Python by default. Keys are ADDED, never
        # overwritten (setdefault), so existing outputs' shape is preserved.
        from forecasting import market_compute as _mc

        payload = args.get("payload")
        if not isinstance(payload, dict):
            payload = inputs.get("payload") if isinstance(inputs.get("payload"), dict) else inputs
        res = _mc.compute(model_type, payload or {})
        # When the caller passed the compute params directly in ``inputs``
        # (the fallback above sets ``payload is inputs``), snapshot them into
        # a fresh dict — folding ``inputs`` back into ``inputs['payload']``
        # would create a self-referential dict that json_dumps rejects.
        if payload is inputs:
            inputs.setdefault("payload", dict(inputs))
        else:
            inputs.setdefault("payload", payload or {})
        parameters.setdefault("backend", res.get("backend"))
        if res.get("degraded"):
            output.setdefault("degraded", True)
            output.setdefault("reason", res.get("reason"))
        for key, value in (res.get("summary") or {}).items():
            output.setdefault(key, value)
        if res.get("block") is not None:
            output.setdefault("compute_block", res["block"])
    model_run = ledger.record_model_run(
        question_id=_required(args, "question_id"),
        model_type=model_type,
        status=args.get("model_status") or "success",
        inputs=inputs,
        parameters=parameters,
        output=output,
        diagnostics=args.get("diagnostics") or {},
        code_ref=args.get("code_ref"),
        artifact_paths=args.get("artifact_paths") or [],
        model_version=args.get("model_version"),
        prompt_version=args.get("prompt_version"),
        data_version=args.get("data_version"),
        evidence_cutoff=args.get("evidence_cutoff"),
        market_model_id=args.get("market_model_id"),
    )
    return tool_result(success=True, model_run=model_run)

def build_model(args: dict[str, Any], ledger) -> str:
    from forecasting.application.model_build import build_model as execute_build

    return tool_result(**execute_build(args, ledger))


def list_model_runs(args: dict[str, Any], ledger) -> str:
    model_runs = ledger.list_model_runs(_required(args, "question_id"))
    return tool_result(success=True, model_runs=model_runs)

def component_track_record(args: dict[str, Any], ledger) -> str:
    origin = args.get("forecast_origin", "live")
    records = ledger.component_track_record(
        forecast_origin=None if origin in (None, "any") else origin,
        min_count=args.get("min_count"),
    )
    kind = args.get("kind")
    if kind in ("ensemble", "panel"):
        records = [row for row in records if row["kind"] == kind]
    return tool_result(
        success=True,
        components=records,
        note=(
            "edge > 0 = component beat the committed aggregate (paired Brier, "
            "resolved binary questions). Weights are ADVISORY and shrunk by "
            "sample size; apply to a panel via record_panel estimates' "
            "weight field, never silently."
        ),
    )

def bayes(args: dict[str, Any], ledger) -> str:
    from forecasting.bayes_toolkit import (
        BAYES_ACTIONS,
        ensure_industry_backends,
        run_bayes_action,
    )

    bayes_action = str(args.get("bayes_action") or "").strip()
    if not bayes_action:
        return tool_error(
            "bayes_action is required (one of: "
            + ", ".join(sorted(BAYES_ACTIONS))
            + ")",
            success=False,
        )
    # Load installed NumPy/SciPy; fall back to stdlib without installing.
    ensure_industry_backends()
    payload = args.get("bayes_payload") or {}
    if not isinstance(payload, dict):
        return tool_error("bayes_payload must be an object", success=False)
    if bayes_action == "sensitivity":
        if not isinstance(payload.get("components"), list):
            return tool_error("bayes sensitivity requires components as an array", success=False)
        if not isinstance(payload.get("parameter_ranges"), dict):
            return tool_error(
                "bayes sensitivity requires parameter_ranges as an object mapping component names to arrays",
                success=False,
            )
        invalid_ranges = [
            str(name)
            for name, values in payload["parameter_ranges"].items()
            if not isinstance(values, list) or not values
        ]
        if invalid_ranges:
            return tool_error(
                "bayes sensitivity parameter ranges must be non-empty arrays: "
                + ", ".join(invalid_ranges),
                success=False,
            )
    outcome = run_bayes_action(bayes_action, payload)
    return tool_result(
        success=True,
        bayes_action=outcome["action"],
        result=outcome["result"],
        rationale=outcome["rationale"],
    )


HANDLERS = {
    "record_model_run": record_model_run,
    "build_model": build_model,
    "list_model_runs": list_model_runs,
    "component_track_record": component_track_record,
    "bayes": bayes,
}
