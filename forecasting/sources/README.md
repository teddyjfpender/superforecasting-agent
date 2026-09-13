# Evidence source adapters and parsers

Acquires source records and parses measurements from supported public sources into evidence suitable for later semantic binding.

## Ownership and boundaries

Keep fetching, parsing, binding and ledger writes separate. Reject ambiguous identity, units, periods, publication times and revisions before settlement; successful JSON parsing is insufficient.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                            |
| -------------------------------- | ------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)       | Domain records and parsing components for forecasting evidence sources.   |
| [arxiv.py](arxiv.py)             | Load scholarly papers from the arXiv Atom API.                            |
| [bls.py](bls.py)                 | Load U.S. Bureau of Labor Statistics evidence observations.               |
| [bls_parsing.py](bls_parsing.py) | Pure BLS response parsing; observation periods are not publication dates. |
| [bluesky.py](bluesky.py)         | Load bluesky public-attention evidence.                                   |
| [census.py](census.py)           | Load U.S. Census demographic and regional evidence records.               |
| [cisa_kev.py](cisa_kev.py)       | Load cisa_kev vulnerability records as forecasting evidence.              |
| [ckan.py](ckan.py)               | Load CKAN open-data evidence records.                                     |

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
