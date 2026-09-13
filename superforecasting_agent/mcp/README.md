# Forecast MCP server

Exposes forecast data, conversation and event operations through the MCP server interface.

## Ownership and boundaries

Translate protocol requests into shared operations and return protocol-safe results. Keep ledger validation authoritative and do not expose unrestricted persistence through a new tool.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                           | Responsibility                                                  |
| ---------------------------------------------- | --------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                     | MCP servers supporting the forecasting runtime.                 |
| [server.py](server.py)                         | Create and run the Superforecasting Agent messaging MCP server. |
| [conversation_tools.py](conversation_tools.py) | MCP tool registration for conversation data.                    |
| [data.py](data.py)                             | Session discovery and message conversion for the MCP bridge.    |
| [event_tools.py](event_tools.py)               | MCP tool registration for events and messaging actions.         |
| [events.py](events.py)                         | Queued messaging events and the session database poller.        |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
