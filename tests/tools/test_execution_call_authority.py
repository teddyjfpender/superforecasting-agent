"""Real generated RPC clients retain session authority and deny empty selections."""

import contextvars
import json
from unittest.mock import patch

from superforecasting_agent.tooling import prompt_callbacks
from tools.code_execution_tool import execute_code


def test_explicit_empty_selection_cannot_call_default_tools(monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "local")
    with patch("superforecasting_agent.tooling.runtime.handle_function_call") as dispatch:
        result = json.loads(execute_code(
            'import json, forecast_tools\nprint(json.dumps(forecast_tools._call("terminal", {"command": "forbidden"})))',
            task_id="empty-selection", enabled_tools=[],
        ))
    assert result["status"] == "success"
    assert "not available" in result["output"]
    dispatch.assert_not_called()


def test_real_rpc_worker_uses_each_callers_context_and_callback(monkeypatch):
    monkeypatch.setenv("TERMINAL_ENV", "local")
    tenant = contextvars.ContextVar("rpc_tenant", default="missing")
    previous = prompt_callbacks.get_approval_callback()
    observed = []

    def dispatch(name, args, **kwargs):
        callback = prompt_callbacks.get_approval_callback()
        observed.append((tenant.get(), callback(), kwargs["task_id"]))
        return json.dumps({"output": "accepted", "exit_code": 0})

    try:
        with patch("superforecasting_agent.tooling.runtime.handle_function_call", side_effect=dispatch):
            for label in ("one", "two"):
                token = tenant.set(label)
                prompt_callbacks.set_approval_callback(lambda label=label: label)
                try:
                    result = json.loads(execute_code(
                        'from forecast_tools import terminal\nprint(terminal("echo harmless"))',
                        task_id=label, enabled_tools=["terminal"],
                    ))
                    assert result["status"] == "success"
                finally:
                    tenant.reset(token)
    finally:
        prompt_callbacks.set_approval_callback(previous)
    assert observed == [("one", "one", "one"), ("two", "two", "two")]
