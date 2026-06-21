"""Agent tool: read a forecasting Desk forecast as a Market Model input.

Lets a Market Model cite the Desk: pull a question's current probability + recent
history by id, or search by title/topic. Read-only.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import registry, tool_error, tool_result

READ_DESK_FORECAST_SCHEMA = {
    "name": "read_desk_forecast",
    "description": (
        "Read a forecasting Desk forecast to use as a model input: its current "
        "probability and recent forecast history. Pass a question_id, or a query "
        "to search by title/topic first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question_id": {"type": "string", "description": "The forecast question id (e.g. q_...)."},
            "query": {"type": "string", "description": "Search text if you don't have an id."},
        },
    },
}


def read_desk_forecast_tool(args: dict[str, Any]) -> str:
    from forecasting.ledger import ForecastLedger

    qid = (args.get("question_id") or "").strip()
    query = (args.get("query") or "").strip()
    try:
        ledger = ForecastLedger()
        if not qid:
            if not query:
                return tool_error("provide question_id or query")
            rows = ledger.list_questions() if hasattr(ledger, "list_questions") else []
            ql = query.lower()
            matches = [
                {"id": getattr(r, "id", None) or (r.get("id") if isinstance(r, dict) else None),
                 "title": getattr(r, "title", None) or (r.get("title") if isinstance(r, dict) else "")}
                for r in rows
                if ql in str(getattr(r, "title", "") or (r.get("title") if isinstance(r, dict) else "")).lower()
            ][:8]
            return tool_result(matches=matches, note="Re-call with a question_id from matches.")

        packet = json.loads(ledger.export_question(qid, fmt="json"))
        history = packet.get("forecast_history") or []
        latest = history[-1] if history else None
        return tool_result(
            question={"id": qid, "title": (packet.get("question") or {}).get("title")},
            latest=latest,
            recent_history=history[-8:],
        )
    except Exception as e:
        return tool_error(f"read_desk_forecast failed: {e}")


registry.register(
    name="read_desk_forecast",
    toolset="market-models",
    schema=READ_DESK_FORECAST_SCHEMA,
    handler=lambda args, **kw: read_desk_forecast_tool(args),
    emoji="D",
)
