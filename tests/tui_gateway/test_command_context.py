"""Independent command registrations retain their host and callback ownership."""

import threading
from concurrent.futures import ThreadPoolExecutor

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.commands_rpc import CommandContext, register_handlers


def command_host(label):
    host = RuntimeHost()
    handlers = {}
    config = {
        "quick_commands": {"owned": {"type": "alias", "target": f"model {label}"}}
    }
    context = CommandContext(
        host=lambda: host,
        load_config=lambda: config,
        save_config=lambda value: config.update(value),
        database=lambda: None,
        database_error=lambda rid, *, code: {"error": {"code": code}},
        ok=lambda rid, result: {"result": result},
        error=lambda rid, code, message: {"error": {"code": code, "message": message}},
        handoff=lambda rid, message, dispatch="command.dispatch": {
            "error": {"message": message}
        },
        block=lambda event, sid, payload: "No",
        background_output=lambda session, name: label,
        enabled_toolsets=lambda: [],
        methods=handlers,
        extra_commands=(),
        hidden_commands=frozenset(),
    )

    def register(name):
        def install(handler):
            handlers[name] = handler
            return handler

        return install

    register_handlers(context, method=register, rpc_validated=register)
    return host, context, handlers


def test_registration_and_repeated_shutdown_do_not_redirect_another_host():
    first, _, a = command_host("first")
    second, _, b = command_host("second")
    args = {"name": "owned", "arg": ""}
    assert a["command.dispatch"](1, args)["result"]["target"] == "model first"
    assert b["command.dispatch"](1, args)["result"]["target"] == "model second"
    shutdown = dict(
        stop_services=lambda: None,
        release_prompts=lambda sid, session: None,
        interrupt_delegations=lambda: None,
        close_session=lambda sid, session, db: None,
    )
    assert first.shutdown(0, **shutdown)
    assert first.shutdown(0, **shutdown)
    assert a["command.dispatch"](1, args)["error"]["code"] == 5030
    assert b["command.dispatch"](1, args)["result"]["target"] == "model second"
    assert second.shutdown(0, **shutdown)


def test_active_handler_remains_owned_until_it_exits():
    from dataclasses import replace

    host, context, handlers = command_host("first")
    entered, release = threading.Event(), threading.Event()

    def config():
        entered.set()
        assert release.wait(5)
        return {}

    context = replace(context, load_config=config)

    def register(name):
        def install(handler):
            handlers[name] = handler
            return handler

        return install

    register_handlers(context, method=register, rpc_validated=register)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            handlers["command.dispatch"], 1, {"name": "queue", "arg": "note"}
        )
        try:
            assert entered.wait(5)
            host.workers.stop()
            assert not host.workers.drain(0)
            assert (
                handlers["command.resolve"](2, {"name": "help"})["error"]["code"]
                == 5030
            )
        finally:
            release.set()
        assert pending.result(timeout=5)["result"]["message"] == "note"
    assert host.workers.drain(0)


def test_handler_pins_host_for_its_entire_invocation():
    from dataclasses import replace

    first, context, handlers = command_host("first")
    second = RuntimeHost()
    first.configuration.last_error = "original host configuration unavailable"
    current = [first]

    def config():
        current[0] = second
        return {}

    context = replace(context, host=lambda: current[0], load_config=config)

    def register(name):
        def install(handler):
            handlers[name] = handler
            return handler

        return install

    register_handlers(context, method=register, rpc_validated=register)
    response = handlers["command.dispatch"](1, {"name": "codex-runtime", "arg": ""})
    assert response["error"]["message"] == "original host configuration unavailable"
    first.workers.stop()
    second.workers.stop()
    assert first.workers.drain(0)
    assert second.workers.drain(0)
