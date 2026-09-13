# Forecast interface contracts

Provides command-facing interfaces for forecast operations shared by product adapters.

## Ownership and boundaries

Expose domain operations without introducing terminal rendering or messaging dependencies into the forecasting core.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                            |
| -------------------------- | ------------------------------------------------------------------------- |
| [**init**.py](__init__.py) | Product adapters for forecasting services; never imported by the domain.  |
| [commands.py](commands.py) | Shared command syntax and text presentation for CLI and Ink RPC adapters. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
