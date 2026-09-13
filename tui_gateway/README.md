# Terminal gateway adapter

Serves the versioned protocol over local and remote transports and translates requests into shared backend operations.

## Ownership and boundaries

Python owns durable sessions and execution; Ink owns presentation. Do not import the classic CLI or restore slash-worker fallback. Reconnect state must agree with the durable turn journal.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility                                                            |
| ---------------------------------------- | ------------------------------------------------------------------------- |
| [**init**.py](__init__.py)               | init .                                                                    |
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
