# Forecast configuration

Defines forecasting-specific configuration and quorum settings used by the domain services.

## Ownership and boundaries

Keep defaults and interpretation separate from persistence. Use the shared configuration updater for writes rather than serializing an expanded runtime configuration.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                            |
| -------------------------- | ------------------------------------------------------------------------- |
| [**init**.py](__init__.py) | Forecast configuration contracts and registry ownership.                  |
| [quorum.py](quorum.py)     | Quorum default-policy validation independent of command presentation.     |
| [registry.py](registry.py) | Data-only forecast setting contracts, defaults and compatibility aliases. |

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
