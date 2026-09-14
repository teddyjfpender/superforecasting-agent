# Market-data provider adapters

Adapts economic, currency, equity and crypto sources to the market-data provider interface.

## Ownership and boundaries

Reject wrong-series fallback and ambiguous units or periods. Do not fabricate publication times from fetch times or silently treat revisions as first releases.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------- |
| [bea.py](bea.py) | BEA NIPA observations with quarterly/annual dated history. |
| [bls.py](bls.py) | BLS exact-series parsing shared with source ingestion. |
| [coingecko.py](coingecko.py) | Spot prices, source timestamps and absolute changes. |
| [frankfurter.py](frankfurter.py) | FX history with independent dates per currency. |
| [fred.py](fred.py) | FRED observations, including dated monthly/quarterly/annual periods. |
| [stooq.py](stooq.py) | Daily OHLC CSV. |
| [yahoo.py](yahoo.py) | Quotes, dated history and symbol discovery. |

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

## Global and regional measurements

| Adapter | Contract |
| --- | --- |
| [country_indicators.py](country_indicators.py) | Existing World Bank/IMF parsers; annual periods and explicit estimate semantics. IMF access remains unqualified. |
| [europe.py](europe.py) | Eurostat JSON-stat dimensions and ECB series identity, currency, and multiplier. |
| [sdmx.py](sdmx.py) | ABS, BIS, and OECD CSV with pinned flow version, dimensions, units, and base period. |
| [regional_statistics.py](regional_statistics.py) | SingStat table/row/unit binding and IBGE territory/variable/unit binding. |
| [bcb.py](bcb.py) | BCB SGS dates and numeric values; future-effective values excluded from current observations. |
| [weather.py](weather.py) | Existing Open-Meteo forecast, air quality, and reanalysis parsers with location/unit checks. |
| [nws.py](nws.py) | Actual NWS alerts with area checks, duplicate detection, and explicit truncation. |

Shared transport bounds bodies before parsing, spaces requests per host, and
honors quota cooldowns. Authentication errors, rate limits, invalid measurements,
and unavailable sources remain distinguishable. Do not log raw request exceptions:
some upstream URLs contain credentials.
