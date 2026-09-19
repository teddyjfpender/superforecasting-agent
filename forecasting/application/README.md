# Forecast application operations

Coordinates review, resolution, scoring, triage, model building and sharing for CLI and terminal consumers.

## Ownership and boundaries

Put shared validation and lifecycle behavior here. Interfaces supply context and render results; they must not recreate settlement or scoring policy.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                             | Responsibility                                                                     |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                       | Interface-independent forecast operations consumed by product adapters.            |
| [aggregate_summaries.py](aggregate_summaries.py) | Shared thesis and factor summaries for tools and product adapters.                 |
| [benchmarks.py](benchmarks.py)                   | Presentation-independent benchmark execution and probability generation.           |
| [market_output.py](market_output.py)             | Thread-owned transfer of the latest market artifact from tools to orchestration.   |
| [model_build.py](model_build.py)                 | Shared market-model build operation for forecast entrypoints.                      |
| [pipeline.py](pipeline.py)                       | Shared forecast-stage orchestration for tools, jobs and command adapters.          |
| [question_reuse.py](question_reuse.py)           | Read-only candidate matching shared by question creation and forecast entrypoints. |
| [resolution.py](resolution.py)                   | Resolution use case; product adapters do not own settlement policy.                |

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

## Structured evidence imports

`source_imports.py` owns the typed FRED evidence-import operation. Callers provide
`FredImportRequest` and a fetch capability; the CLI only constructs the request and
renders returned evidence. The operation fetches outside the write transaction,
checks series identity, dates, finite numeric values and duplicate entry identities,
then writes the batch atomically through ledger admission. Source observation dates
are not promoted to publication timestamps. Raw evidence claims remain distinct
from verified settlement bindings.

Identical entries within a batch collapse; conflicting entries fail the batch.
FRED imports accept an optional stable `request_id`. Evidence IDs and the request
digest are committed atomically; replay returns the original evidence without
refetching, and different input under the same ID fails. Additional adapter
migrations remain tracked in the engineering plan. Tests: `tests/application/test_source_imports.py` and the
FRED CLI import regression in `tests/forecasting/test_cli.py`.

For CLI retries, supply `forecast import fred UNRATE --question <id> --request-id <id>`.
Reuse the ID only to retry the same operation and options, including after a lost
acknowledgement. Use a new ID for a deliberate fresh acquisition. Without an ID,
legacy invocations remain independent imports. Receipts live in the profile ledger;
missing referenced evidence fails closed rather than silently importing again.

`market_imports.py` owns Kalshi/Polymarket evidence and baseline-comparison persistence.
Callers supply a parsed provider record and `MarketEvidenceRequest`. Both writes use
one transaction, so invalid probabilities or failed comparison storage cannot leave
partial evidence. A missing quote creates evidence without inventing a baseline.
`market_import_metadata` also supplies candidate metadata; candidate confirmation and
active forecast promotion remain separate operations. Tests live in
`tests/application/test_market_imports.py`, with local-HTTP CLI regressions in
`tests/forecasting/test_cli.py`.


`acquire_market_evidence` accepts `MarketAcquisitionRequest` and a typed fetch
capability. It checks durable receipts before acquisition and again before commit.
CLI Kalshi/Polymarket imports with `--question` support `--request-id`; repeated
input returns the original evidence/comparison without refetching. Different
input with the same identifier fails. Candidate imports cannot use this option.
No request ID preserves independent-import behavior.

`import_receipts.py` is the shared FRED/market receipt owner. Its migration adds
comparison IDs while retaining old FRED IDs and digests. Receipt, evidence and
comparison writes share a transaction; a missing referenced record fails closed.
Tests: `tests/application/test_market_import_receipts.py` (concurrent calls,
rollback, CLI replay, historical schema and process exit after commit).

Downgrades require a pre-upgrade ledger backup: binaries using the previous
four-column positional receipt insert cannot write after the comparison column
has been added. Do not remove the new column and discard market receipt data to
force an in-place downgrade.

`source_batches.commit_source_payloads` is the shared persistence operation for
single-source and concurrent-batch tool imports. Fetch and parse first; pass one
source's payloads, the target question and a strict boolean dedupe policy. The
operation reads duplicate identities inside an immediate transaction and either
commits all accepted rows or rolls the source back. Results retain input indices
for presentation without duplicating persistence policy. Existing ledger validation
remains authoritative; URL archival is disabled during these structured imports.
Auto-watch remains a separately reported optional action after successful import.

This operation preserves existing entry-ID deduplication semantics. It does not
establish revision equivalence, deduplicate observations without IDs, or replace
the typed FRED/market request receipts. Those acquisition-plan and cross-interface
migrations remain in W03. Tests: `tests/application/test_source_batches.py`.

Shared source batches compare provider entry identity **and** acquired provenance
before declaring a duplicate. `SourceRevisionConflict.reason_code` is
`source_revision_conflict`; it identifies the conflicting input row and entry ID.
Changed raw observations, source identity, publication time or URL require review,
and any conflict rolls back that source's whole batch. User ratings do not change
publisher provenance. Explicit `dedupe=False` appends a separate historical record;
it never replaces an earlier observation. Divergent historical records sharing an
entry ID remain ambiguous for automatic deduplication. This is conservative import
admission, not a source-specific first-release/revision settlement policy.

`commit_source_payloads(..., request_id=...)` uses the shared import-receipt store
for atomic evidence/result receipts. Exact payload and policy retries return the
original evidence and row indices, including records without provider entry IDs.
Changed inputs with an existing identity fail; evidence and receipt writes roll
back together. Versioned batch-index metadata validates complete, disjoint input
coverage while existing FRED/market receipts migrate additively.

Single-source tools accept `request_id`. Batch tools derive an identity per source
position from the batch request ID, unless a source provides its own. Keep source
order and acquired payloads stable for retries. This is commit-level idempotency:
tools still acquire data before comparison, and changed acquisitions fail instead
of being silently substituted. Acquisition-level frozen retry remains the typed
provider operation's responsibility.
