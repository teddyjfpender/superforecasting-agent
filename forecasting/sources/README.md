# Evidence source adapters and parsers

Acquires source records and parses measurements from supported public sources into evidence suitable for later semantic binding.

## Ownership and boundaries

Keep fetching, parsing, binding and ledger writes separate. Reject ambiguous identity, units, periods, publication times and revisions before settlement; successful JSON parsing is insufficient.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                   |
| -------------------------------- | ---------------------------------------------------------------- |
| [values.py](values.py)           | Shared source value handling.                                    |
| [nws.py](nws.py)                 | Weather source acquisition and observation handling.             |
| [usgs.py](usgs.py)               | USGS event acquisition and identity handling.                    |
| [bls.py](bls.py)                 | BLS acquisition and evidence observations.                       |
| [bls_parsing.py](bls_parsing.py) | Pure BLS parsing; observation periods are not publication dates. |
| [fred.py](fred.py)               | FRED series acquisition with source metadata.                    |
| [eia_parser.py](eia_parser.py)   | Pure EIA payload parsing.                                        |
| [sec_parsing.py](sec_parsing.py) | Pure SEC response parsing.                                       |

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

## Common request admission

`requests.py` validates shared acquisition options before dispatch: positive integer
limits/horizons, actual booleans, ISO dates or timezone-bearing timestamps, and HTTP
endpoint URLs. Explicit zero, numeric strings and string booleans are invalid; they
must not be coerced into plausible requests. Omitted fields use declared defaults.
Validation errors name fields without echoing endpoint credentials.

`dispatch.py` applies this check before provider I/O. Watched-source orchestration
passes original input types through admission and isolates per-source failures.
Provider-specific options still belong to their adapters; this common projection
is not a complete discriminated request schema or a settlement measurement contract.
Those stricter semantics remain separately required before ledger settlement.

Focused regressions: `tests/forecasting/test_source_request_admission.py` and
`tests/forecasting/test_source_dispatch.py`.
