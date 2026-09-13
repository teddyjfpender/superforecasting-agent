# Computer-use tool backend

Defines computer-use schemas, backend interfaces and the adapter that performs desktop operations.

## Ownership and boundaries

Keep interaction capability checks and resource ownership explicit. Do not conflate a failed UI action with successful completion.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                      |
| -------------------------------- | ------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)       | Computer use toolset — universal (any-model) macOS desktop control. |
| [backend.py](backend.py)         | Abstract backend interface for computer use.                        |
| [cua_backend.py](cua_backend.py) | Cua-driver backend (macOS only).                                    |
| [schema.py](schema.py)           | Schema for the generic `computer_use` tool.                         |
| [tool.py](tool.py)               | Entry point for the `computer_use` tool.                            |

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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
