"""Connect scoped tool disclosure to the existing agent invocation boundary."""

from typing import Any

from superforecasting_agent.tooling.disclosure import BRIDGE_NAMES, ToolCatalog
from tools.registry import tool_error


def catalog_for(agent: Any) -> ToolCatalog | None:
    config = getattr(agent, "tool_discovery_config", None)
    if not isinstance(config, dict) or config.get("enabled", True) is False:
        return None
    if type(config.get("enabled", True)) is not bool:
        raise ValueError("tool_discovery.enabled must be a boolean")
    direct = config.get("direct_tools", [])
    if not isinstance(direct, list) or any(
        not isinstance(name, str) for name in direct
    ):
        raise ValueError("tool_discovery.direct_tools must be a list of tool names")
    return ToolCatalog.selected(agent.tools or [], direct)


def wire_tools(agent: Any, *, register: bool = True) -> list[dict] | None:
    catalog = catalog_for(agent)
    if catalog is None or not catalog.optional:
        if register and isinstance(getattr(agent, "valid_tool_names", None), set):
            agent.valid_tool_names.difference_update(BRIDGE_NAMES)
        return agent.tools
    budget = agent.tool_discovery_config.get("listing_chars", 8000)
    if type(budget) is not int or not 0 <= budget <= 24000:
        raise ValueError(
            "tool_discovery.listing_chars must be an integer from 0 to 24000"
        )
    if register:
        agent.valid_tool_names.update(BRIDGE_NAMES)
    return catalog.wire_tools(listing_chars=budget)


def execute_discovery(
    agent: Any,
    name: str,
    args: dict,
    task_id: str,
    call_id: str | None,
    messages: list | None,
) -> str:
    """Revalidate selection at dispatch; execute via existing hooks and tool owners."""
    import json

    from agent.display import _detect_tool_failure

    try:
        catalog = catalog_for(agent)
        if catalog is None or not catalog.optional:
            raise ValueError("Optional tool discovery is not enabled for this session")
        if name == "tool_search":
            if set(args) - {"queries", "limit"}:
                raise ValueError("tool_search accepts queries and limit only")
            return json.dumps(
                {"results": catalog.search(args.get("queries"), args.get("limit", 5))},
                ensure_ascii=False,
            )
        if name == "tool_describe":
            if set(args) != {"names"}:
                raise ValueError("tool_describe requires names")
            return json.dumps(
                {"tools": catalog.describe(args["names"])}, ensure_ascii=False
            )
        if name != "tool_call" or set(args) != {"calls"}:
            raise ValueError("tool_call requires calls")
        calls = catalog.calls(args["calls"])
    except ValueError as exc:
        return tool_error(str(exc))
    results = []
    for index, (target, arguments) in enumerate(calls):
        if getattr(agent, "_interrupt_requested", False) is True:
            return json.dumps({
                "success": False,
                "results": results,
                "error": "Tool batch interrupted; remaining calls were not executed",
            })
        # Config/tool selection can change while an earlier call is running.
        # Recheck before each effect; the initial whole-batch validation still
        # guarantees an invalid later argument cannot cause partial execution.
        try:
            current = catalog_for(agent)
            if current is None or target not in current.optional:
                raise ValueError(
                    "Tool selection changed; remaining calls were not executed"
                )
            current.calls([{"name": target, "arguments": arguments}])
        except ValueError as exc:
            return json.dumps({"success": False, "results": results, "error": str(exc)})
        decision = agent._tool_guardrails.before_call(target, arguments)
        if not decision.allows_execution:
            result = agent._guardrail_block_result(decision)
        else:
            try:
                result = agent._invoke_tool(
                    target,
                    arguments,
                    task_id,
                    tool_call_id=f"{call_id or 'discovery'}:{index}",
                    messages=messages,
                )
            except InterruptedError:
                return json.dumps({
                    "success": False,
                    "results": results,
                    "error": "Tool batch interrupted during execution",
                })
            except Exception as exc:
                from agent.redact import redact_sensitive_text

                result = tool_error(redact_sensitive_text(str(exc), force=True))
            failed, _ = _detect_tool_failure(target, result)
            result = agent._append_guardrail_observation(
                target, arguments, result, failed=failed
            )
        failed, _ = _detect_tool_failure(target, result)
        results.append({"name": target, "success": not failed, "result": result})
        if (
            decision.should_halt
            or getattr(agent, "_tool_guardrail_halt_decision", None) is not None
        ):
            return json.dumps({
                "success": False,
                "results": results,
                "error": "Tool guardrail halted the batch",
            })
    return json.dumps(
        {"success": all(item["success"] for item in results), "results": results},
        ensure_ascii=False,
    )
