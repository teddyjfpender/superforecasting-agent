"""Agent adapter for the shared forecast-card sharing operation."""
from __future__ import annotations

from typing import Any

from forecasting.application.sharing import execute_share as execute_share
from tools.registry import tool_error, tool_result


def share_forecast(args: dict[str, Any], ledger) -> str:
    """``share_forecast`` action: post the current snapshot as a peer forecast card."""

    outcome = execute_share(
        ledger,
        str(args.get("question_id") or ""),
        str(args.get("channel") or ""),
        thread_ts=args.get("thread_ts"),
        team_id=args.get("team_id"),
    )
    if not outcome.get("success") and outcome.get("error"):
        return tool_error(outcome["error"], **{k: v for k, v in outcome.items() if k != "error"})
    return tool_result(**outcome)


HANDLERS = {
    "share_forecast": share_forecast,
}
