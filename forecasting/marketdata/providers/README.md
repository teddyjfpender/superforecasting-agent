# Market-data provider adapters

Adapts economic, currency, equity and crypto sources to the market-data provider interface.

## Ownership and boundaries

Reject wrong-series fallback and ambiguous units or periods. Do not fabricate publication times from fetch times or silently treat revisions as first releases.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)       | Market-data providers, ported one-to-one from `ui-tui/src/lib/marketFetch.ts`.        |
| [bea.py](bea.py)                 | BEA (NIPA) provider — ported one-to-one from `marketFetch.ts`.                        |
| [bls.py](bls.py)                 | BLS (Bureau of Labor Statistics) provider — ported one-to-one from `marketFetch.ts`.  |
| [coingecko.py](coingecko.py)     | CoinGecko (crypto spot) provider — ported one-to-one from `marketFetch.ts`.           |
| [frankfurter.py](frankfurter.py) | Frankfurter (ECB) FX provider — ported one-to-one from `marketFetch.ts`.              |
| [fred.py](fred.py)               | FRED (St. Louis Fed) provider.                                                        |
| [stooq.py](stooq.py)             | Stooq (daily OHLC CSV) provider — a server-side data-plane provider.                  |
| [yahoo.py](yahoo.py)             | Yahoo Finance provider — ported ONE-TO-ONE from `marketFetch.ts` / `marketSearch.ts`. |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
