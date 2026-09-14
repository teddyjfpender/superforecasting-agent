# Built-in tool implementations

Implements the tools exposed to agent conversations, including forecasting, files, execution, sources and optional integrations.

## Ownership and boundaries

Register built-in tools through the registry and catalog. Put common policy in tooling owners and forecasting mutations in application/ledger services; tool handlers must preserve structured errors.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                 | Responsibility                                                             |
| ---------------------------------------------------- | -------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                           | Tools package namespace.                                                   |
| [ansi_strip.py](ansi_strip.py)                       | Strip ANSI escape sequences from subprocess output.                        |
| [approval.py](approval.py)                           | Dangerous command approval -- detection, prompting, and per-session state. |
| [async_delegation.py](async_delegation.py)           | Async (background) delegation registry.                                    |
| [binary_extensions.py](binary_extensions.py)         | Binary file extensions to skip for text-based operations.                  |
| [browser_camofox.py](browser_camofox.py)             | Camofox browser backend — local anti-detection browser via REST API.       |
| [browser_camofox_state.py](browser_camofox_state.py) | Superforecasting Agent-managed Camofox state helpers.                      |
| [browser_cdp_tool.py](browser_cdp_tool.py)           | Raw Chrome DevTools Protocol (CDP) passthrough tool.                       |

## Subdirectories

- [computer_use/](computer_use/README.md) — Computer-use tool backend.
- [environments/](environments/README.md) — Execution environments.
- [forecast_actions/](forecast_actions/README.md) — Forecast tool actions.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tools/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

## Code execution RPC

[code_execution_tool.py](code_execution_tool.py) selects the execution environment
and owns script lifetime. [code_kernel_runner.py](code_kernel_runner.py) provides
the standalone persistent cell protocol under development: retained variables,
bounded Python output, ordered calculation hashes and owner-pipe shutdown. It is
not yet selected by the public execution tool; host lifecycle and RPC integration
must land before enabling persistent sessions. [code_execution_rpc.py](code_execution_rpc.py) owns the
shared authenticated request pipeline for local sockets and remote files. Both
transports validate request shape and size, preserve the selected tool allow-list
and forecast commit policy, and charge the call budget before dispatch.

Local children receive an ephemeral token. Remote tokens are generated in a
private directory and read from a private file; their values never appear in shell
arguments. A remote response-delivery failure retains the result for delivery
retry, so polling cannot repeat the tool effect. These receipts last for the
execution call; they do not promise exactly-once external effects after host death.

Worker output suppression is context-scoped through the agent output owner;
accepted sockets and borrowed terminal streams have separate disposal owners.
