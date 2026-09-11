# Ownership map + extension-point checklists

The formality layer of the modularization program
(`docs/plans/2026-07-10-modularization-program.md` §W0.4). Two things live here:

1. **The module ownership table** — for each fork-owned package: its layer, its
   public façade, and what it must **not** import (enforced by the import-linter
   contracts in `pyproject.toml [tool.importlinter]`, CI `lint.yml →
   lint-architecture`).
2. **Per-extension-point checklists** — for each common feature shape, the ONE
   module you touch, the registry that auto-wires it, and the test that pins it.
   The goal of the whole program: a new feature touches one small module, never a
   megafile.

---

## 1. Module ownership

| Package | Layer | Public façade | Must NOT import (contract) |
|---|---|---|---|
| `superforecasting_agent/` | product entry and runtime foundations | Lazy public domain exports; `bootstrap`, `constants`, `clock`, `logging` | Bootstrap and profile-path imports must remain usable before application setup |
| `superforecasting_agent/storage/` | session persistence | `superforecasting_agent.storage.session.SessionDB` binds operations from focused storage modules | Storage leaves do not import the SessionDB facade |
| `protocol/` | kernel (wire contracts) | pydantic models under `protocol/rpc`, `protocol/events`; `generated.ts` is generated from it | **anything app-side** — `forecasting`, `tools`, `agent`, `gateway`, `tui_gateway`, `superforecasting_agent.runtime`, `run_agent`, `cli` (Tier-1 contract, enforced) |
| `forecasting/` | domain (ledger, scoring, quorum, CLI) | `forecasting.ledger`, `forecasting.cli` (façade packages), `forecasting.models` | `tui_gateway` (Tier-1); `superforecasting_agent.runtime` + `tools` are **ratcheted** (frozen lists in pyproject — may only shrink) |
| `forecasting/sources/` | source adapters, records and parsing | Domain `*_records.py`, `values.py`, `dates.py`, `package_registry.py`, `feeds.py`, and GitHub/package/research/weather/energy adapter leaves; existing `forecasting.source_adapters` names remain available | Record modules use dataclasses and domain models; no fetching, CLI, runtime, or source-adapter dependency |
| `forecasting/ledger/` | domain leaf | `forecasting/ledger/__init__` (monkeypatch-forwarding façade over `core.py` + leaves) | `forecasting.cli` (Tier-1) |
| `forecasting/cli/` | surface (argparse assembler) | `forecasting/cli/__init__` (`_CliPackage` forwarding façade) | — |
| `superforecasting_agent/tooling/skill_types.py` | skill source contracts | `SkillMeta`, `SkillBundle`, `SkillSource`; re-exported by `tools.skills_hub` | Standard library only; importing contracts does not load source adapters |
| `superforecasting_agent/tooling/github_auth.py` | skill source authentication | `GitHubAuth`, re-exported by `tools.skills_hub` | Credentials resolve lazily; importing the module does not load source adapters |
| `superforecasting_agent/tooling/skill_paths.py` | skill bundle path validation | Shared name, category, and relative-file validators, re-exported by `tools.skills_hub` | Standard-library-only validation before filesystem access |
| `tools/` | tools | `tools.registry`; `tools.forecast_actions.ACTIONS` | `run_agent` (forbidden) |
| `forecasting/domains.py` | semantic classification | Explicit source categories and audited active-question corrections | No title-based inference or probability-history rewriting |
| `forecasting/source_bindings.py` | measurement contracts | NWS temperature and USGS magnitude extraction | No network calls or inferred settlement decisions |
| `forecasting/sources/bls_parsing.py` | BLS parsing | Finite measurements, exact series identity, periods and duplicate/revision checks | No network, CLI or ledger writes; periods are not publication times |
| `superforecasting_agent/storage/files.py`, `storage/locking.py` | configuration mutation and locking | Dotted mapping/list updates, atomic YAML replacement and reentrant process locks | No runtime imports; full-config stale-write checks remain in `runtime.config` |
| `forecasting/censoring.py` | coarsened observations | Typed right-censoring contracts and threshold-event probabilities | No fabricated exact outcomes or full-distribution score claims |
| `superforecasting_agent/runtime/model_configuration.py` | model configuration ownership | `model_section`, `persist_model_selection` | No UI imports; preserve raw environment references |
| `gateway/command_dispatch.py` | gateway command hooks | `dispatch_command_hooks` | No gateway runner import; reauthorize rewritten commands |
| `superforecasting_agent/runtime/provider_catalog.py` | provider metadata catalog | `ProviderDef`, `ProviderOverlay`, aliases and transport tables; resolved through `runtime.providers` | Data only; no model calls, configuration reads, or provider discovery |
| `superforecasting_agent/runtime/cron_commands.py` | classic CLI command surface | `ForecastCLI._handle_cron_command` binds the handler; scheduled operations use the cron tool API | No import of the root CLI; scheduling stays in `cron/` and its tool interface |
| `superforecasting_agent/runtime/handoff_commands.py` | classic CLI handoff surface | `ForecastCLI._handle_handoff_command` delegates to this handler | Gateway configuration and session storage remain the handoff authorities |
| `superforecasting_agent/runtime/audit_discovery.py`, `audit_types.py` | dependency audit discovery and records | Re-exported through `runtime.security_audit`; OSV and command orchestration remain there | Discovery does not import the audit facade or make advisory requests |
| `acp_adapter/` | editor protocol surface | `server.ForecastACPAgent`, `content` converters, and `history` replay; `HermesACPAgent` remains an import alias | Protocol transport wraps the forecast runtime without replacing the ledger |
| `tui_gateway/` | surface (RPC) | `@rpc_validated` handlers; carved `*_rpc.py` families | `run_agent` (forbidden); imports `forecasting` one-way (clean) |
| `agent/`, `gateway/`, `superforecasting_agent/runtime/` | upstream-shared runtime | — | `run_agent` (forbidden; use `agent.runtime`) |

**`agent/runtime.py` owns `AIAgent` and runtime state.** `run_agent.py` is a
compatibility executable/module alias; no application package may import it.
The entrypoint import contract has no exceptions and includes cron and ACP.
`cli.py` remains a presentation entrypoint; the TUI host cannot import it.
The isolated legacy slash worker still uses classic CLI dispatch for commands
that have not yet migrated to application services.

`runtime.interactive_config.read_cli_config` reads shared settings without
modifying the process. `load_cli_config` explicitly applies environment bridges
for classic CLI startup. TUI personality lookup uses the read-only operation.

### Source and recovery ownership

- `forecasting/economic_bindings.py`: pure BLS/FRED entity, unit, period and
  revision semantics. `source_bindings.py` dispatches adapter contracts.
- `forecasting/applicability_facts.py`: archive/cutoff verification;
  `settlement_binding.py`: resolution admission against the declared measurement.
- `forecasting/source_transfer.py`: versioned archive transfer, immutable origin
  history and explicit local re-verification. Hashes alone never grant authority.
- `forecasting/ledger/sqlite_runtime.py`: preserve callback failures while keeping
  the authorizer fail closed. It owns no scoring policy.
- `superforecasting_agent/storage/files.py`: locked atomic YAML mutations and
  the stable revision-bearing snapshot type; `runtime/config.py`: configuration
  defaults, loaders and snapshot admission.
- `tui_gateway/turn_journal.py`: durable partial turns and worker ownership;
  the gateway persists before delivering events, and Ink renders that status.

### Existing forecasting façades

`__init__.py` installs a `ModuleType` subclass whose `__getattr__` read-forwards
to `core` and whose `__setattr__`/`__delattr__` write-forward when `core` owns the
name — so `from pkg import _private`, `pkg._private`, and
`monkeypatch.setattr(pkg, "_private", …)` all keep working after a body moves to
`core` or a leaf. See `forecasting/cli/__init__.py` and
`forecasting/ledger/__init__.py`. This forwarding machinery is specific to those
existing packages. Session storage uses ordinary method delegates, and the public
product package uses lazy read-only exports so bootstrap stays lightweight.

---

## 2. Extension-point checklists

Each row of the program's seam audit, written from the "after" column. **One
module, one registry, one test.**

### New gate rule (saturation / style hook)

- **Touch:** `forecasting/hooks/builtins.py` — add the rule + its remediation text
  to `BUILTIN_RULES`. (User-authored rules load from the DSL via
  `forecasting/hooks/loader.py` — no code change.)
- **Auto-wires:** `BUILTIN_RULES` is read by `forecasting/hooks/engine.py`.
- **Test:** `tests/forecasting/test_hooks_*.py` — assert the rule fires + the
  remediation string.

### New tool action (`forecast_ledger` verb)

- **Touch:** `tools/forecast_actions/<domain>.py` — add `action -> handler(args,
  ledger)` to that module's `HANDLERS` (or add a new domain module — it is
  auto-discovered).
- **Auto-wires:** `tools/forecast_actions/__init__.py` aggregates every module's
  `HANDLERS` into `ACTIONS`; `forecast_ledger_tool` dispatches on it. No central
  edit.
- **Test:** `tests/tools/test_forecast_actions*.py` (or the domain's test) — call
  the action through `ACTIONS`.

### New job type (durable background job)

- **Touch:** `forecasting/jobs/types/<name>.py` — define a `JobType` and call
  `register(<NAME>)` at module bottom (the pattern in `backup.py`,
  `reforecast.py`).
- **Auto-wires:** `forecasting/jobs/types.register` + `registered_types`; the job
  store/runtime dispatch on the registered type. Add the module to the package's
  import surface if it is not import-triggered.
- **Test:** `tests/forecasting/test_*_jobs.py` — enqueue + run the type; assert the
  record transitions.

### New CLI domain (`forecast <verb>`)

- **Touch:** `forecasting/cli/<domain>.py` — a module exposing
  `register(forecast_sub)` (add subparsers + `set_defaults(_forecast_handler=…)`)
  and its handlers. Reach `_ledger` via a call-time `_core._ledger` hop; import
  shared helpers bare from `forecasting.cli.core`.
- **Wire once:** one `from forecasting.cli import <domain> as _X` at the bottom of
  `core.py` + one `_X.register(forecast_sub)` call at the intended position inside
  `register_cli` (position = help-tree order; use one hook per contiguous block).
- **Auto-wires:** nothing else — the assembler calls `register()` hooks in order.
- **Test:** `tests/forecasting/test_cli.py`; the `dump_help_tree.py` +
  `dump_order.py` gates confirm byte-identical help.
- Precedents: `jobs_admin.py`, `curate.py`, `thesis.py`, and the Wave-1 eight
  (`doctor_admin`, `reviews`, `quorum_panel`, `markets_pm`, `triage_calibration`,
  `benchmarks`, `questions_admin`, `refresh_cycle`).

### New notify surface (delivery channel)

- **Touch:** `forecasting/notify.py` — add the surface name to `SURFACES` and a
  delivery branch in `NotifyRouter._deliver_one`.
- **Auto-wires:** routes bind by surface name (`routes.json`); `deliver_event` /
  `deliver_digest` fan out to every accepting route.
- **Test:** `tests/forecasting/test_notify*.py` — bind a route on the new surface,
  assert `deliveries.json` records an attempt.

---

## 3. The gates that keep this true

| Concern | Gate | Where |
|---|---|---|
| Import directions | `lint-imports` (import-linter) | `pyproject.toml [tool.importlinter]`, CI `lint.yml → lint-architecture` |
| Moves-only carves | difflib categorizer, help-tree + order dumps | `scripts/carve/` (see its README) |
| Blame through carves | `.git-blame-ignore-revs` | `scripts/install-hooks.sh` sets `blame.ignoreRevsFile` |
| Wire compatibility | protocol codegen staleness | `scripts/check-protocol.sh` |
| Oversize refactor | `MOVES-ONLY` marker gate | `.githooks/lib/checks.sh` |

GitHub repository and activity adapters receive their JSON reader explicitly
from `forecasting.source_adapters`. Their record construction and filtering live
in `sources/github_repository.py` and `sources/github_activity.py`; shared
identifiers and timestamps live in `sources/github_metadata.py`. The public
facade preserves existing signatures and supplies its HTTP reader, so leaves
do not import the facade or mutate a global reader.

Package release loaders use the same explicit-reader boundary in
`sources/package_releases.py`, with identifier and version metadata parsing in
`sources/package_registry.py`.

OpenAlex and Crossref loaders and their metadata parsers live in
`sources/openalex.py` and `sources/crossref.py`. Both use the same explicit JSON
reader boundary. Shared ISO date conversion lives in `sources/dates.py`; its
existing helper names remain available through the source facade.

Treasury Fiscal Data records live in `sources/treasury.py`, with endpoint, value,
and date parsing beside the loader. Shared optional-number parsing in
`sources/values.py` rejects non-finite values and numeric overflow; individual
adapters keep their existing raw-value fallback policy.

Census demographic and regional records live in `sources/census.py`, including
dataset paths, geography fields, and public citation URLs. The facade supplies
the JSON reader and preserves existing loader and helper imports.

EIA energy observations live in `sources/eia.py`, with the JSON reader supplied
by the facade. Both current and legacy response formats share the same record
construction, which omits API keys from evidence URLs while preserving request
authentication.

Open-Meteo daily forecasts, air quality, and historical observations share
`sources/openmeteo.py`, including coordinate, date, and response-field parsing.
The source facade supplies the JSON reader and retains the existing API names.

The BLS time-series loader and period parsing live in
`forecasting/sources/bls.py`; `source_adapters` preserves the public loader and
HTTP reader seam. Invalid observation years are skipped without losing valid rows.

World Bank and IMF country indicators share the date and metadata parsers in
`forecasting/sources/macroeconomic.py`; public source-adapter exports remain stable.

Socrata records and CKAN catalog metadata live in `sources/socrata.py` and
`sources/ckan.py`. Their epoch/ISO metadata timestamp conversion shares
`dates._optional_epoch_or_iso_timestamp`; unrepresentable numeric metadata is
unavailable while otherwise valid records remain importable.

arXiv Atom papers and PubMed XML articles live in `sources/arxiv.py` and
`sources/pubmed.py`, reusing feed/XML helpers without importing the facade. PubMed
keeps articles with unrepresentable optional publication dates as undated records.

Stooq CSV prices, Yahoo chart prices, and CoinGecko market snapshots live in
`sources/stooq.py`, `sources/yahoo.py`, and `sources/coingecko.py`. Yahoo and SEC
share bounds-checked parallel-array access through `sources/values._list_get`.

Public-attention evidence loaders live in `sources/hackernews.py`,
`sources/reddit.py`, `sources/bluesky.py`, and `sources/mastodon.py`. Each owns
its endpoint and response parsing, with the shared facade supplying the HTTP
reader and retaining public imports.
Reddit keeps posts with unrepresentable optional timestamps as undated evidence.
ISO-only optional metadata timestamps share `dates._optional_iso_timestamp`;
source wrappers retain their field labels and public signatures.

NVD and CISA vulnerability evidence live in `sources/nvd.py` and
`sources/cisa_kev.py`; NVD accepts current reference arrays and legacy wrappers.
USGS earthquakes, NASA EONET events, and NWS alerts live in `sources/usgs.py`,
`sources/eonet.py`, and `sources/nws.py`. Unrepresentable optional USGS timestamps
leave events undated without discarding the rest of the feed.

ReliefWeb reports, Federal Register documents, and CourtListener search records
are owned by `sources/reliefweb.py`, `sources/federal_register.py`, and
`sources/courtlistener.py`; the facade supplies the common HTTP reader.

ClinicalTrials.gov studies and openFDA application records live in
`sources/clinicaltrials.py` and `sources/openfda.py`. OWID CSV and WHO GHO
indicators live in `sources/owid.py` and `sources/who_gho.py`. Entity filters
skip unnamed rows; empty WHO arrays are valid results, and unrepresentable
optional years leave observations undated.

OpenFEMA declarations live in `sources/fema.py`; empty declaration arrays
remain valid import results, including supported legacy wrapper keys.

GDELT article lists and FiveThirtyEight polling CSV parsing live in
`sources/gdelt.py` and `sources/fivethirtyeight.py`, with reader injection from
the facade and unchanged date normalization, filtering, and sorting.

Wikipedia pages/revisions and Wikimedia pageviews live in `sources/wikipedia.py`
and `sources/wikimedia.py`. Facade callbacks preserve the shared reader, revision
lookup, and test clock. Historical revisions with empty content never reuse the
live page extract.

FRED API, CSV, and HTML decoding live in `sources/fred.py`; facade delegates
preserve shared HTTP readers, while fallback orchestration and timeout settings
remain in the source facade.

Pure SEC identifier and filing/company-fact parsing lives in
`sources/sec_parsing.py`; lookup, caching, identity headers, and fetching remain
in the facade. Invalid optional fiscal years do not discard company facts.
Source/FRED timeout configuration shares finite-number parsing and retains alias
precedence and default values.

Metaculus endpoint, outcome, prediction, and metadata parsers live in
`sources/metaculus_parsing.py`, alongside import-record and benchmark-case
construction. The facade retains fetching and benchmark orchestration.
Array predictions preserve choice positions: an unavailable value cannot shift
a later probability onto a different label.

Metaculus and Kalshi share the label-aware timestamp parser in `sources/dates.py`.
Prediction imports retain valid time semantics and treat unrepresentable optional
timestamps as unavailable. Manifold millisecond conversion also handles calendar
range errors and remains the numeric timestamp path used by Polymarket.

Manifold and Kalshi endpoint and metadata parsing live in
`sources/manifold_parsing.py` and `sources/kalshi_parsing.py`. The facade keeps
HTTP and benchmark orchestration; import records and benchmark-case conversion
live beside the venue parsers. Existing helper names remain available for callers.

Resolved Metaculus and Kalshi benchmark responses select the first recognized
array, including an empty one. Empty pages are valid and do not fall through to
older response aliases.

Classic CLI filesystem checkpoint and runtime snapshot commands live in
`superforecasting_agent/runtime/checkpoint_commands.py`. `ForecastCLI` binds the
three methods directly; checkpoint storage and backup services retain ownership
of persistence and restoration. The leaf does not import the root CLI.

Classic CLI profile, curator, debug, and update entry points live in
`superforecasting_agent/runtime/maintenance_commands.py`. Their service imports
remain lazy. Invalid curator quoting uses the existing command error handler,
without invoking curator work.

The Azure Foundry setup wizard lives in `runtime/azure_setup.py`. Runtime main
reexports its existing callable; endpoint detection and credential configuration
remain in their existing services and load only when the wizard runs.

Custom-provider naming, API-mode selection, reference preservation, and config
persistence live in `runtime/custom_provider_setup.py`. Main keeps the wizard
call sites and reexports the helpers, preserving existing caller patch points.

Subscription OAuth model-selection flows for Nous, OpenAI Codex, and xAI live
in `runtime/oauth_setup.py`. Authentication and credential storage remain in
`runtime/auth.py`; main reexports the existing setup callables.

Bedrock setup (AWS credentials or API key) lives in `runtime/bedrock_setup.py`;
Anthropic credential selection and OAuth setup live in `runtime/anthropic_setup.py`.
Main keeps their existing callable names, while adapters and auth services retain
credential resolution and storage.

Shared API-key entry and generic provider setup live in `runtime/api_key_setup.py`.
The main facade supplies its current model catalog and key-prompt callback on
each invocation, preserving existing patch points and the public call signature.

The classic CLI session browser and relative-time labels live in
`runtime/session_browser.py`. Main reexports the existing picker and label helpers;
SQLite session queries and the Ink TUI session picker retain their own ownership.

### Paired learning trial boundaries

- `forecasting/learning_trials.py`: enrollment, immutable packet/request ownership,
  arm claims and failure recovery.
- `forecasting/trial_provider.py`: provider readiness, receipts and quota reservations.
- `forecasting/trial_contracts.py`: versioned response validation and reviewed
  evaluation compatibility; `trial_evaluation.py`: read-only paired scoring.
- `forecasting/trial_readiness.py`: pre-enrollment evidence/lesson coverage audit.

Execution identity and evaluation identity are separate. Compatibility mappings
require source review; never update historical trial rows to make a hash match.
