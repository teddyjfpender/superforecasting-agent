# Market-data service

Defines market-data requests and observations, provider selection and service-level acquisition.

## Ownership and boundaries

An available quote is not automatically a valid settlement observation. Preserve units, series identity, timestamps and provider provenance for semantic admission.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                            |
| -------------------------- | ------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | Server-side market-data plane (Arc C).                                    |
| [keys.py](keys.py)         | Server-side API-key resolution for market-data providers.                 |
| [model.py](model.py)       | Domain model for the server-side market-data plane.                       |
| [provider.py](provider.py) | The `Provider` protocol + a shared HTTP getter for market-data providers. |
| [service.py](service.py)   | MarketDataService — one facade over every market-data provider.           |

## Subdirectories

- [providers/](providers/README.md) — Market-data provider adapters.

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
