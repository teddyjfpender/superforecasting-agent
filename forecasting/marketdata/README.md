# Global data desk

This package owns the catalog and acquisition service behind Markets. The TUI,
CLI setup, and a remote gateway use the same series identities and source
semantics. Displaying data never creates a forecast or authorizes settlement.

## Ownership

| File | Responsibility |
| --- | --- |
| [catalog.py](catalog.py) | Loads isolated catalog snapshots; schemas live in `protocol/data_desk.py`. |
| [catalog.json](catalog.json) | Shared catalog and explicit starter-set membership. No client copy exists. |
| [model.py](model.py) | Quote assembly and coercion; re-exports shared dated-observation/event schemas. |
| [parsing.py](parsing.py) | Period boundaries, duplicate checks, and dated measurement assembly. |
| [provider.py](provider.py) | Injectable fetch interface, bounded verified HTTP, pacing, and safe diagnostics. |
| [discovery.py](discovery.py) | Ranked catalog and live-directory search with bounded caching and failure isolation. |
| [discovery_worldbank.py](discovery_worldbank.py) | World Bank directory identity matching; never observation or settlement validation. |
| [service.py](service.py) | Provider routing, cache ownership, refresh intervals, and failure isolation. |
| [keys.py](keys.py) | Credentials resolved by the connected backend. |
| [providers/](providers/README.md) | Source-specific fetching and parsing contracts. |

Selection persistence belongs to
[`application/data_desk.py`](../../superforecasting_agent/application/data_desk.py)
and [`storage/market_selection.py`](../../superforecasting_agent/storage/market_selection.py).
The catalog is data, not a configuration writer. RPC models live in
[`protocol/rpc/markets.py`](../../protocol/rpc/markets.py); TypeScript contracts are
generated from Python.

## Measurement meaning

Topic, geography, and data kind are independent. Forecasts, observations,
reanalysis, estimates, prices, and events must retain their own meanings.

- `dated_history` preserves each value's period and any published status.
- `published_at` is a source-supplied release time. Dataset update times and
  retrieval times must not be substituted for it.
- `retrieved_at` controls refresh scheduling; an annual observation does not
  become stale merely because its observation date is over sixty seconds old.
- Forecast issue time and validity are separate. A blended source without an
  explicit issue time reports it as unknown.
- `source_family` identifies common upstream provenance; catalog mirrors are
  not automatically independent evidence.
- Revision policy is explicit. The latest revised value is not a first release.
- Missing values remain null. Conflicting duplicates and ambiguous dimensions
  fail visibly. Weather alerts are events, not invented numerical measurements.

The existing forecast source-binding and settlement owners still decide whether
an observation can resolve a question.

## Adding coverage

1. Identify a useful measurement family and its canonical source. Check access
   conditions, units, geography, frequency, revisions, timestamps, and quotas.
2. Reuse a source parser from `forecasting/sources` where its contract fits.
   Keep HTTP and parsing independently injectable. New parsers live with their
   provider, not in the TUI or gateway.
3. Add exact identities and dimensions to `catalog.json`. Preserve stable IDs;
   a changed measurement meaning requires a new ID. Add a category only when
   selectable data actually supports it.
4. Register the provider in the service. Optional credentials use the existing
   backend credential store, never a client-local file.
5. Add source fixtures and rejection tests for plausible wrong measurements.
   Record live qualification separately from offline regression evidence.
6. Add qualified series to an explicit preset version. Catalog upgrades never
   silently enroll existing profiles or restore removed series.

See [qualification evidence](../../docs/verification/data-desk/README.md) for the
current limits. A successful sample request is not full catalog qualification.

## Verification

From the repository root, use `python3 scripts/dev.py check` and the canonical
`scripts/run_tests.sh` runner. The full Python suite is required before pushing.
Regenerate wire models with `python -m protocol.codegen` when contracts change.

[↑ Forecasting](../README.md)
