# Shared tool infrastructure

Owns tool selection, definitions, argument handling, dispatch support, cancellation and shared Skills Hub HTTP operations.

## Ownership and boundaries

Tool implementations consume this package. Carry cancellation through worker I/O and check it before publication; keep tool catalogs separate from transport and presentation.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility                                                          |
| ---------------------------------- | ----------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)         | Tool definition, argument, and dispatch support.                        |
| [runtime.py](runtime.py)           | Public orchestration API for tool discovery and dispatch.               |
| [arguments.py](arguments.py)       | Coerce model-produced arguments against registered tool schemas.        |
| [async_bridge.py](async_bridge.py) | Persistent event-loop ownership for synchronous tool dispatch.          |
| [background.py](background.py)     | Shared background inspection and stop operations over owned registries. |
| [definitions.py](definitions.py)   | Discover tools and build cached schemas for the active session.         |
| [dispatch.py](dispatch.py)         | Execute tool calls through registry, approvals, and plugin hooks.       |
| [errors.py](errors.py)             | Remove structural framing from tool error messages.                     |

## Subdirectories

- [catalogs/](catalogs/README.md) — Tool capability catalogs.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tooling/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
