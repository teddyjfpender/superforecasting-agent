# Terminal gateway adapter

Serves the versioned protocol over local and remote transports and translates requests into shared backend operations.

## Ownership and boundaries

Python owns durable sessions and execution; Ink owns presentation. Do not import the classic CLI or restore slash-worker fallback. Reconnect state must agree with the durable turn journal.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility                                                            |
| ---------------------------------------- | ------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)               | init .                                                                    |
| [server.py](server.py)                   | server.                                                                   |
| [agents_rpc.py](agents_rpc.py)           | Gateway RPCs for the `agents.*` family — carved from server.py.           |
| [browser_rpc.py](browser_rpc.py)         | Gateway RPC for the browser-connect plane — carved from server.py.        |
| [command_routes.py](command_routes.py)   | Terminal command ownership shared by dispatch and consumer parity checks. |
| [commands_rpc.py](commands_rpc.py)       | Gateway RPCs for the command / CLI-exec family — carved from server.py.   |
| [completion_rpc.py](completion_rpc.py)   | Gateway RPCs for the completion family — carved from server.py.           |
| [cron_skills_rpc.py](cron_skills_rpc.py) | Gateway RPCs for the cron + skills family — carved from server.py.        |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tui_gateway/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

Interactive prompts share the correlated request owner in `server_requests.py`. See the [protocol and reconnect contract](../protocol/README.md) for capability negotiation, legacy adapters, cancellation, and reply ownership.


## Command host ownership

`commands_rpc.CommandContext` supplies the command family's typed capabilities.
Use `register_handlers(context, method=..., rpc_validated=...)` for independently
owned hosts. Each registered handler captures its context and pins its runtime
host for one invocation. Admission and draining use that host's worker owner;
stopped hosts return the existing `5030` host-stopping error.

`register(server)` remains the singleton server composition adapter. Its callbacks
follow that server object's explicit reload behavior, without rebinding globals in
the command module or redirecting another registration. This does not make the
whole gateway multi-host: other RPC families and profile-dependent plugin/skill
services still have separate ownership work. Keep those limitations explicit.

An import contract forbids direct command-handler imports of `tui_gateway.server`.
Tests in `tests/tui_gateway/test_command_context.py` cover independent registration,
repeated shutdown, active-call draining and host replacement during a call.


`tools_rpc.ToolContext` similarly owns tool inspection, configuration access and
session reset callbacks. Inject profile-specific persistence and reset operations
for independent hosts; `register(server)` is only the singleton compatibility
composition. Configuration still reserves session replacement before saving and
resetting. `rpc_binding.bind_host_handler` is the shared command/tool admission
owner: it pins the runtime for each call and retains worker ownership until exit.
Tests in `test_tool_context.py` verify separate configuration/reset destinations
for hosts with identical session IDs. This family and the binding owner receive
complete strict checks and cannot directly import the singleton server.
