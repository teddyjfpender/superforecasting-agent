"""Tool configuration uses only the selected host's persistence and reset capabilities."""

from copy import deepcopy

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.tools_rpc import ToolContext, register_handlers


def tool_host():
    host = RuntimeHost()
    host.sessions["shared-id"] = {"history": [], "session_key": "owned"}
    durable = {"platform_toolsets": {"cli": ["web", "memory"]}}
    writes, resets, handlers = [], [], {}

    def save(cfg):
        writes.append(deepcopy(cfg))
        durable.clear()
        durable.update(deepcopy(cfg))

    def reset(sid, session, *, reserved=False):
        assert session is host.sessions[sid]
        assert reserved and session["_replacing"]
        resets.append(sid)
        return {}

    context = ToolContext(
        host=lambda: host,
        enabled_toolsets=lambda: durable["platform_toolsets"]["cli"],
        load_config=lambda: deepcopy(durable),
        save_config=save,
        reset_session=reset,
        ok=lambda rid, result: {"result": result},
        error=lambda rid, code, message: {"error": {"code": code, "message": message}},
    )

    def register(name):
        def install(handler):
            handlers[name] = handler
            return handler

        return install

    register_handlers(context, method=register, rpc_validated=register)
    return host, durable, writes, resets, handlers


def test_configure_and_stop_one_host_leave_other_unchanged(monkeypatch):
    monkeypatch.setattr(
        "superforecasting_agent.tooling.selection._get_plugin_toolset_keys",
        lambda: set(),
    )
    first, config_a, writes_a, resets_a, a = tool_host()
    second, config_b, writes_b, resets_b, b = tool_host()
    params = {"session_id": "shared-id", "action": "disable", "names": ["memory"]}
    response = a["tools.configure"](1, params)
    assert response["result"]["reset"]
    assert config_a["platform_toolsets"]["cli"] == ["web"]
    assert config_b["platform_toolsets"]["cli"] == ["web", "memory"]
    assert len(writes_a) == 1 and resets_a == ["shared-id"]
    assert writes_b == [] and resets_b == []
    first.workers.stop()
    assert first.workers.drain(0)
    assert a["tools.configure"](2, params)["error"]["code"] == 5030
    assert b["tools.configure"](3, params)["result"]["reset"]
    assert len(writes_b) == 1 and resets_b == ["shared-id"]
    assert len(writes_a) == 1 and resets_a == ["shared-id"]
    second.workers.stop()
    assert second.workers.drain(0)
