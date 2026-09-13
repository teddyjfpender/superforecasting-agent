# Credential services

Discovers and resolves provider credentials, with focused provider adapters and OAuth services.

## Ownership and boundaries

Keep interactive login in the runtime presentation layer. Respect borrowed-secret ownership and avoid logging or returning secret material in diagnostics.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                                  |
| -------------------------------- | ------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)       | Credential discovery, refresh and persistence independent of command rendering. |
| [anthropic.py](anthropic.py)     | Anthropic credential files and token refresh without inference construction.    |
| [auth.py](auth.py)               | Multi-provider authentication system for Superforecasting Agent.                |
| [azure.py](azure.py)             | Entra configuration and SDK presence without client construction.               |
| [catalog.py](catalog.py)         | Credential availability inventory shared by forecasting and product adapters.   |
| [copilot.py](copilot.py)         | GitHub Copilot authentication utilities.                                        |
| [environment.py](environment.py) | Profile-bound credential reads without CLI initialization or mutation.          |

## Subdirectories

- [oauth/](oauth/README.md) — OAuth credential lifecycle.

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
