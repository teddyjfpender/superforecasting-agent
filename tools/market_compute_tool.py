"""Agent tool: deterministic quant computation for Market Models.

Wraps ``forecasting.market_compute.compute`` so the agent routes EVERY number
(regression, correlation, trend, simulation, econometrics) through auditable,
reproducible math instead of narrating it. Returns a ready-to-use presentation
block plus key scalars.
"""

from __future__ import annotations

from typing import Any

from forecasting import market_compute as MC
from tools.registry import registry, tool_error, tool_result

MARKET_COMPUTE_SCHEMA = {
    "name": "market_compute",
    "description": (
        "Deterministically compute a quantitative statistic or model for a Market "
        "Model. Use this for EVERY number you present (slopes, R^2, correlations, "
        "trend projections, Monte-Carlo percentiles, cointegration, event-study, "
        "ARIMA, backtests) — never hand-derive them. Returns a ready-to-render "
        "presentation block plus the key scalars."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model_type": {
                "type": "string",
                "enum": sorted(MC.MODEL_TYPES),
                "description": "Which computation to run.",
            },
            "payload": {
                "type": "object",
                "description": (
                    "Inputs, by model_type: ols/loglinear → {x:[..], y:[..], x_label?, y_label?, "
                    "extrapolate_to?:[..]}; multivariate → {X:[[..]], y:[..], x_labels:[..], y_label?}; "
                    "timeseries_trend/arima → {values:[..], horizon?}; correlation/cointegration → "
                    "{a:[..], b:[..]}; montecarlo → {start, drift, vol, steps, n_paths, seed, bands?}; "
                    "event_study → {returns:[..], event_index, window}; backtest → {returns:[..], signal?:[..]}; "
                    "scenario → {scenarios:[{name, outcome, ...}]}."
                ),
            },
        },
        "required": ["model_type", "payload"],
    },
}


def market_compute_tool(args: dict[str, Any]) -> str:
    model_type = args.get("model_type")
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    if not model_type:
        return tool_error("model_type is required")
    try:
        res = MC.compute(str(model_type), payload)
    except Exception as e:  # never crash the agent loop
        return tool_error(f"market_compute failed: {e}")
    return tool_result(
        ok=res.get("ok"),
        degraded=res.get("degraded"),
        reason=res.get("reason"),
        block=res.get("block"),
        summary=res.get("summary"),
        backend=res.get("backend"),
    )


registry.register(
    name="market_compute",
    toolset="market-models",
    schema=MARKET_COMPUTE_SCHEMA,
    handler=lambda args, **kw: market_compute_tool(args),
    emoji="C",
)
