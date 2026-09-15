# Adding a data provider

This directory adapts external sources for the data desk. Providers own fetching
and parsing; the shared service owns caching and dispatch. The TUI consumes the
backend catalog—do not add a separate client-side provider list.

## Implementation checklist

1. **Qualify a useful measurement.** Check the official API, access terms, quotas,
   stable series/entity IDs, units, observation periods and revision policy.
   Start with a small, verified set rather than exposing an untested API wholesale.
2. **Implement the adapter.** Follow [bcb.py](bcb.py) for a small example and the
   [`Provider` interface](../provider.py): `name`, `needs_key` and
   `fetch(series, *, api_key=None) -> list[Quote]`. Inject transport and clocks;
   keep parsing independently callable. Reuse existing source parsers where suitable.
3. **Use shared infrastructure.** Use bounded HTTP helpers and `ProviderFailure`
   from [provider.py](../provider.py), plus observation helpers from
   [parsing.py](../parsing.py). Choose batching deliberately: `IndependentSeries`
   isolates one-request-per-series failures; `batch_key` supports grouped requests.
   Keep alerts as events—see [nws.py](nws.py)—rather than inventing numeric quotes.
4. **Register and describe it.** Register numeric adapters in
   [`_default_providers()`](../service.py). Add provider metadata and exact series
   bindings to [catalog.json](../catalog.json), reusing topic, region and kind IDs.
   Advertise only implemented capabilities. Add starter membership only after
   qualification; keep existing IDs stable. For credentials, declare `key_env`
   and register the slot with the shared [API-key owner](../../api_keys.py).
   Never write credentials or selections from the TUI.
5. **Prove failure behavior.** Add captured, credential-free responses under
   [tests/fixtures/data_desk](../../../tests/fixtures/data_desk/README.md) and
   adapter tests under `tests/forecasting/`. Cover missing values, wrong identities
   and units, malformed dates, conflicting duplicates, revisions and quota errors.
   Record live qualification separately from deterministic fixture tests.

## Non-negotiable semantics

- Missing measurements stay `None`, never zero. Reject ambiguous source bindings.
- Preserve observation periods; retrieval time is not publication or issue time.
- Distinguish forecasts, observations, estimates and reanalysis. Retain revision
  policy and original source provenance, including mirrored data.
- Keep authentication, rate limits, invalid responses and no data distinguishable.
  Never expose credential-bearing URLs in errors or fixtures.
- Catalog display does **not** authorize forecast settlement.

## Before submitting

From the repository root, with the development environment active:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Add new runtime owners to the strict check scope in `scripts/dev.py`. If shared
wire schemas change, regenerate with `python3 -m protocol.codegen`. Run the full
canonical suite before pushing, as required by the repository contribution guide.

See the [package overview](../README.md) and
[source qualification notes](../../../docs/verification/data-desk/qualification.md).

## Change references

Use `observation_quote()` on the full fetched history **before** chart truncation.
The default `change_basis: previous_observation` compares the latest two distinct,
non-missing source periods, however far apart. Equal releases remain zero. Price
feeds keep their source-defined previous-close comparison; future weather values
must not be treated as observed changes.

For stepwise policy targets only, declare `change_basis: last_transition` in the
catalog. The helper finds the latest adjacent unequal readings and preserves both
values and dates in `comparison`; the TUI labels these changes with `*`. This is
an observed transition, not an inferred policy meeting date. Ordinary series can
expose `last_movement` separately without replacing an unchanged period delta.

Fetch enough history to support the declared comparison. Backfill is bounded:
BCB uses dated windows of one then ten years after its latest-20 endpoint; BIS
uses 120 then 600 observations; keyed FRED expands 30 → 366 → 3660 observations.
An unavailable transition stays null. Failed or inconsistent history backfills
must preserve the latest valid measurement. Test sparse periods, equal values,
conflicting duplicates, zero baselines and backfill failures.
