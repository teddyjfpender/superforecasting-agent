"""JSON adapters for shared information-triage operations."""

from __future__ import annotations

from typing import Any

from forecasting.application.triage import execute_triage_action
from tools.registry import tool_result


def label_score(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "label_score"}, ledger))


def set_label_rubric(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "set_label_rubric"}, ledger))


def list_label_rubrics(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "list_label_rubrics"}, ledger))


def triage_label(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "triage_label"}, ledger))


def triage_contested(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "triage_contested"}, ledger))


def relabel_route(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "relabel_route"}, ledger))


def triage_trust(args: dict[str, Any], ledger) -> str:
    return tool_result(**execute_triage_action({**args, "action": "triage_trust"}, ledger))


HANDLERS = {
    "label_score": label_score,
    "set_label_rubric": set_label_rubric,
    "list_label_rubrics": list_label_rubrics,
    "triage_label": triage_label,
    "triage_contested": triage_contested,
    "relabel_route": relabel_route,
    "triage_trust": triage_trust,
}
