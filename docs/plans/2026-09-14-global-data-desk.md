# Global data desk

Implementation of the accepted global-data-desk proposal. This document tracks the
whole goal; completing a foundation or a small provider subset does not complete it.

## Required behavior and evidence

| Requirement | Completion evidence | Status |
| --- | --- | --- |
| Global starter and intentional empty setup | Setup and first-run TUI tests; actual isolated profile walkthrough | Implemented; final gate pending |
| Roughly 120–180 qualified, geographically diverse series | Validated preset manifest, coverage audit and provider qualification receipts | Implemented; final gate pending |
| Preview/customize, apply later, preserve personal selections | Atomic/concurrent/idempotent profile tests; modal walkthrough | Implemented; final gate pending |
| Real dated history and progressive acquisition | Parser fixtures; slow-provider, cancellation, quota and partial-delivery tests | Implemented; final gate pending |
| Separate topic, geography and observation kind | Backend catalog contracts and UI filters; no unsupported categories advertised | Implemented; final gate pending |
| Starter sets, Browse data and Sources modal | Keyboard and narrow-terminal verification; explicit apply and Escape cancel | Implemented; final gate pending |
| Backend owns settings and secrets on local/VPS sessions | Remote-profile parity and secret-prompt tests; no client credential/config writes | Implemented; final gate pending |
| Release-aware freshness and honest failure states | Deterministic time/status tests; original publication/revision meaning retained | Implemented; final gate pending |
| Shared parsing and semantic admission | Provenance/identity/unit/revision fixtures; display never authorizes settlement | Implemented; final gate pending |
| CLI/TUI/gateway shared operations and generated contracts | Contract tests and strict quality gates | Implemented; final gate pending |
| Current documentation and clean publication | Owner READMEs, final consolidated verification receipt, commits/push | Implemented; final gate pending |

## Provider qualification scope

Qualify measurement semantics, supported queries, access conditions, quota behavior,
revision policy, history and provenance before admitting a source to the starter.
Existing ingestion support is a reuse candidate, not automatic qualification.

- Existing quote providers: Yahoo, Frankfurter, CoinGecko, FRED, BLS, BEA, Stooq.
- Existing global/environment ingestion: World Bank, IMF, Open-Meteo forecast,
  historical reanalysis and air quality, NWS; review relevant additional adapters.
- Global expansion: OECD and BIS.
- Europe: Eurostat and ECB.
- APAC: ABS, SingStat, e-Stat (registered API).
- Latin America: BCB, IBGE, INEGI (registered API).
- Middle East/Africa: qualified World Bank/IMF country coverage, SAMA API,
  direct UAE investigation and direct African source qualification.

Record unsupported or unavailable integrations with concrete evidence; never add
nonfunctional provider entries or disguise an estimate as an observed outcome.

## Implementation order

1. Shared catalog, typed series identity and atomic profile-selection operations.
2. Source qualification, reusable adapters, rich observations and bounded progressive
   refresh with source-specific freshness and error classification.
3. Generated RPC contracts, CLI/setup integration, backend credential operations.
4. TUI catalog, three-view Add data flow, reversible onboarding and remote parity.
5. Consolidated quality, parser/contract/recovery checks and actual first-run TUI
   walkthrough; commit and publish the verified result.

## Working constraints

Preserve the existing quote wire during migration. Keep the main TUI as the first
consumer and the dashboard as its terminal host. Keep acquisition separate from
forecast creation, scoring, lessons and settlement authorization. Use existing
storage locks, atomic writers, credential services and request ownership.

Implementation comes before the consolidated test pass. Run focused checks only
where they resolve a concrete implementation uncertainty or failure.

## Implementation checkpoint — 14 September

The catalog, setup choices, additive preview/apply, backend credential prompts,
three-view modal and regional adapters are implemented. The isolated CLI receipt
confirms empty state survives restart and repeat preset application is harmless.
The no-weather variant adds 114 entries; the complete global preset contains 163.

Focused Python validation passed 149 tests before the final ownership/freshness
changes. TUI selection, prediction-market preservation, search/fetch and modal
checks passed, including explicit preview/apply and Escape cancellation at 80×24.
The final focused TUI pass covered 61 tests across seven files. Canonical strict quality checks pass, including 76 import contracts, generated
type drift, TUI lint and TypeScript. The full Python suite remains the push gate.

The architecture gate exposed protocol imports of application/acquisition owners.
Pure catalog, observation and selection schemas now live in `protocol/data_desk.py`;
loading, fetching, persistence and credentials remain in their existing owners.

See [source qualification](../verification/data-desk/qualification.md) for exact
coverage, live failures and conditional candidates. First delivery does not claim
credentialed e-Stat/INEGI or direct SAMA/UAE/African integrations are complete.
