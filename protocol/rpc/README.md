# RPC declarations

Declares request and response contracts for sessions, configuration, forecasting and other host operations.

## Ownership and boundaries

Keep execution in gateway/application handlers. Version incompatible changes and validate requests at the protocol boundary.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                                                                                                          |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | RPC request/response model families (one module per RPC family).                                                                                                        |
| [agents.py](agents.py)     | Wire models for the `agents.*` / `delegation.*` / `subagent.*` / `spawn_tree.*` RPCs and the shared `SubagentEventPayload` (Arc A4 — the plan's named "agents" family). |
| [commands.py](commands.py) | Wire models for the command-catalog / completion / slash RPCs (Arc A4).                                                                                                 |
| [config.py](config.py)     | Wire models for the `config.*` + `setup.status` RPCs (Arc A4).                                                                                                          |
| [forecast.py](forecast.py) | Wire models for the `forecast.*` RPC family (Arc A3) — the biggest family.                                                                                              |
| [host.py](host.py)         | Host compatibility admission, shared by local and remote transports.                                                                                                    |
| [interact.py](interact.py) | interact.                                                                                                                                                               |
| [jobs.py](jobs.py)         | Wire models for the `jobs.*` detached-job-runtime RPCs (Arc B on Arc A).                                                                                                |

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
