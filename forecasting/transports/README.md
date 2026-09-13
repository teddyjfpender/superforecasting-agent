# Forecast collaboration transports

Delivers forecasting collaboration through messaging services using transport-specific adapters.

## Ownership and boundaries

Keep delivery and formatting here; ledger mutation, consent and identity validation belong to the shared forecasting owners.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | Outbound message transports for the forecast-native notification surfaces.                              |
| [slack.py](slack.py)       | Slack transport shared by forecast collaboration, notifications and tools.                              |
| [telegram.py](telegram.py) | Stdlib Telegram Bot API client — the outbound/probe transport for the forecast-native Telegram surface. |

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
