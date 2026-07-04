# Data-Plane Providers

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: forecasting/marketdata/service.py + keys.py; forecasting/pm/{kalshi,polymarket}.py -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `forecasting/marketdata/service.py + keys.py; forecasting/pm/{kalshi,polymarket}.py`

The server-side data plane (Arc C) turns external numbers into structured quotes and de-vigged market distributions. Two registries: **market-data quote providers** (FX, econ series, crypto, equities) and **prediction-market venues** (order books + price history). Evidence-import adapters (FRED, GDELT, arXiv, …) are a separate, larger set driven by the CLI `import`/`sources` commands and the tool's `source_type` parameter.


## Market-data quote providers


**7 providers**, resolved by `MarketDataService`. `needs key` providers are skipped when no key resolves; the others degrade to a keyless path where noted in the source.

| id | needs key | env var | class |
| --- | --- | --- | --- |
| `bea` | yes | `BEA_API_KEY` | `BeaProvider` |
| `bls` | no | `BLS_API_KEY` | `BlsProvider` |
| `coingecko` | no | `—` | `CoingeckoProvider` |
| `frankfurter` | no | `—` | `FrankfurterProvider` |
| `fred` | no | `FRED_API_KEY` | `FredProvider` |
| `stooq` | no | `—` | `StooqProvider` |
| `yahoo` | no | `—` | `YahooProvider` |

## Prediction-market venues


**2 venues**, browsed read-only (no API keys on the data path). Served through `PMService` and the `pm.*` RPCs; also reachable from the agent via the tool's `pm_query` action.

| venue | aliases | REST base URLs |
| --- | --- | --- |
| `polymarket` | `poly`, `pm` | `https://gamma-api.polymarket.com`, `https://clob.polymarket.com` |
| `kalshi` | — | `https://api.elections.kalshi.com/trade-api/v2` |
