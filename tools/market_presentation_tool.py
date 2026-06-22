"""Agent tool: emit the final Market Model presentation.

The agent calls ``emit_market_presentation`` once when the analysis is ready,
passing the assembled Presentation (typed blocks) plus a re-runnable ``spec``.
We validate against the schema and stash it on a thread-local so the build
orchestrator (forecasting.market_model) can retrieve it after the run. Invalid
presentations are still stashed but the tool returns the errors so the agent can
self-repair within its budget.
"""

from __future__ import annotations

import threading
from typing import Any

from forecasting import presentation as P
from tools.registry import registry, tool_error, tool_result

# Per-thread stash: each build runs in its own thread (gateway pool / async
# delegation worker), so a thread-local can't collide across concurrent builds.
_STASH = threading.local()


def _items() -> list:
    if not hasattr(_STASH, "items"):
        _STASH.items = []
    return _STASH.items


def reset_emitted() -> None:
    """Clear the stash before a build run (called by the orchestrator)."""
    _items().clear()


def take_emitted() -> dict | None:
    """Return the last emitted {presentation, spec} and clear the stash."""
    items = _items()
    out = items[-1] if items else None
    items.clear()
    return out


EMIT_MARKET_PRESENTATION_SCHEMA = {
    "name": "emit_market_presentation",
    "description": (
        "Emit the FINAL Market Model presentation. Call this exactly once, at the "
        "end, with the fully assembled presentation built from the standardized "
        "block library, plus a re-runnable spec. If it reports validation errors, "
        "fix them and call again."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "presentation": {
                "type": "object",
                "description": (
                    "The presentation: {title, summary, status?, blocks:[...]} where each block has a "
                    "type (narrative, finding, metric, timeseries, scatter, regression, bars, table, "
                    "fan, scenario, assumptions, sources, heatmap, distribution, candles, depth, sparkgrid) and its fields. "
                    "heatmap {matrix:[[..]], rowLabels?, colLabels?, diverging?} → truecolor correlation/matrix heatmap; "
                    "fan may include paths:[[..]] (simulated trajectories) → Monte-Carlo cone; "
                    "distribution {support, pdf, cdf?, mean?, median?, intervals?} → density + CDF + interval bands; "
                    "candles {candles:[{o,h,l,c}], volume?, ma?} → OHLC; depth {bids:[{price,size}], asks, mid?} → order-book depth; "
                    "sparkgrid {cells:[{label, values?, value?, delta?}], columns?} → mini-chart dashboard."
                ),
            },
            "spec": {
                "type": "object",
                "description": (
                    "Re-runnable recipe so the model can refresh on live data: "
                    "{series:[{name, source_type, source, unit?, limit?}], "
                    "compute:[{block_id, model_type, payload}]} where a payload input may reference a "
                    'series as {"series": "<name>", "field": "x|y"}.'
                ),
            },
        },
        "required": ["presentation"],
    },
}


def emit_market_presentation_tool(args: dict[str, Any]) -> str:
    pres = args.get("presentation")
    spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
    if not isinstance(pres, dict):
        return tool_error("presentation must be an object with a title and a blocks list")
    ok, errors = P.validate_presentation(pres)
    _items().append({"presentation": pres, "spec": spec})
    if not ok:
        return tool_result(
            accepted=True,
            valid=False,
            errors=errors[:8],
            note="Presentation stored but has validation issues; fix them and call emit_market_presentation again.",
        )
    return tool_result(accepted=True, valid=True, blocks=len(pres.get("blocks", [])))


registry.register(
    name="emit_market_presentation",
    toolset="market-models",
    schema=EMIT_MARKET_PRESENTATION_SCHEMA,
    handler=lambda args, **kw: emit_market_presentation_tool(args),
    emoji="P",
)
