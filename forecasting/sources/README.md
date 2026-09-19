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

## Typed acquisition admission

`acquisition_requests.SourceAcquisitionRequest` discriminates FRED, BLS, Kalshi
and Polymarket by stable adapter ID. Typed requests reject unknown fields; economic
limits and BLS years are strict integers, and BLS year ranges must be ordered.
Market requests contain endpoint/identity fields rather than economic options.
Shared dispatch translates legacy combined tool options into these contracts,
keeping import policy such as ratings and watches out of provider arguments.
The direct BLS loader shares admission before credentials/network access.

Add provider-specific fields to the selected request model and test rejection
before I/O. Do not broaden another adapter's contract or stringify malformed
values. Error text must not echo secret-bearing endpoints. Remaining adapters
still use common admission; migration is incremental. Acquisition validation does
not certify publication timing, measurement meaning or settlement eligibility.

Focused checks: `tests/forecasting/test_acquisition_requests.py` and
`tests/forecasting/test_source_request_admission.py`.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. Push checks use the canonical bounded integration tier; full suites belong to
explicit qualification.

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


## Kalshi quote units

`kalshi_prices.kalshi_price` owns quote conversion for prediction-market display
and evidence/benchmark imports. Fixed-point `*_dollars` fields take precedence;
legacy unsuffixed and `*_cents` prices are divided by 100, even at one cent.
Absent fields remain unavailable. Invalid selected values raise a validation
error; they are never clamped or replaced with a lower-priority field. Separate
consumer policies (such as the display's no-trade sentinel) remain explicit.

The [Kalshi market response](https://docs.kalshi.com/api-reference/events/get-multivariate-events)
documents the fixed-point dollar fields. Tests in
`tests/forecasting/test_kalshi_price_contract.py` cover cross-consumer units,
legacy precedence and malformed values. Keep measurement conversion here rather
than duplicating it in another transport or ledger adapter.


`kalshi_selection` validates single-market URL selectors before acquisition and
selects the matching ticker from the response. A custom mirror without a ticker
must return exactly one identified market. Missing identities, no match and
multiple matches are errors; source ordering never determines the imported
question. API URLs remain distinct from website URLs. Identity regressions live
in `tests/forecasting/test_kalshi_identity_contract.py`, including a CLI check
that mismatched responses cannot write evidence or a baseline.


`polymarket_selection.PolymarketSelector` binds Gamma market/event responses to
validated ID, slug or condition-hash selectors. A single-child event is admissible;
a multi-market event needs an explicit child URL or market ID. Empty collections
permit documented event/closed-market fallback. Nonempty mismatches, duplicate
matches and malformed records fail closed. Identity checks run before parsing
probabilities or ledger writes. See `test_polymarket_identity_contract.py` for
ordering, ambiguity, selector admission and CLI no-write regressions.

## Publication and observation times

`evidence.source_evidence_payload` preserves the parser's explicit `published_at`,
including `None`. It must not fill an unknown publication time from observation
periods, weather validity dates, event occurrence, deadlines or execution start times.
Adapters without a publication field may use supported record-update/release fields;
the original source fields remain in `metadata.adapter_item`. An explicit caller
availability time is separate from publication and never proves source verification.
Without either, ledger ingestion supplies the first-seen availability time.

This policy applies to tool imports and watched refreshes. The FRED application/CLI
owner also preserves unknown publication. Regression coverage lives in
`tests/forecasting/test_source_publication_provenance.py`. Existing ledger rows are
not silently re-dated: reviewing older records requires an audited correction.


`SourceIdentity` rejects non-string or blank adapter/source identities before fetching.
`SourceImportOptions` adds strict auto-watch/backtest flags and optional ratings in
[0, 1]; `SourceBatchOptions` constrains tool batch concurrency to integers 1–8.
Single, batch and watched-source imports reuse this admission. Invalid per-source
batch input is reported for that source, while invalid batch defaults fail before
any fetch. A per-source dedupe flag overrides the batch default; auto-watch is never
enabled by a string such as `"false"`. Provider-specific options remain untouched.

Caller `metadata` is for annotations. The shared `source_annotations` validator
reserves `adapter`, `source`, `entry_id` and `adapter_item` for acquisition/parser
provenance. Import admission rejects attempts to replace those fields before
network I/O; direct payload mapping uses the same validator. Preserve this boundary
when adding an adapter so user annotations cannot impersonate a parsed observation.
