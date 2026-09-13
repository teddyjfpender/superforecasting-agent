# Prediction-market integration

Fetches and aggregates prediction-market metadata, prices, history and stream updates across supported venues.

## Ownership and boundaries

Keep venue identity and price meaning explicit. A market price is evidence about beliefs, not authoritative proof of the eventual outcome.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                                                                                                           |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)     | Prediction-markets package: one Python implementation of Polymarket + Kalshi read-only market data, consumed by both the agent tool and the TUI gateway. |
| [\_http.py](_http.py)          | Bounded stdlib HTTP GET → parsed JSON. No third-party deps, no trading.                                                                                  |
| [aggregate.py](aggregate.py)   | Collapse a venue event into a discretised distribution (headline + sub-rows).                                                                            |
| [health.py](health.py)         | Prediction-market health snapshot for the `forecast doctor` fold-in.                                                                                     |
| [history.py](history.py)       | Normalise both venues' price history to `[{ts, p}]` + downsample.                                                                                        |
| [kalshi.py](kalshi.py)         | Kalshi read-only client + RSA-PSS signer helper.                                                                                                         |
| [model.py](model.py)           | Frozen data model for prediction-market events, markets, books, and history.                                                                             |
| [polymarket.py](polymarket.py) | Polymarket read-only client: Gamma discovery + CLOB pricing.                                                                                             |

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
