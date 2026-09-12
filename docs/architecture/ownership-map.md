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
| `superforecasting_agent/application/command_catalog/` | shared command metadata and resolution | `workflow.py` owns forecast/session definitions; `operations.py` owns operator-support definitions; the package assembles ordered metadata, validates configured commands and resolves aliases | No presentation, runtime, agent or tool imports; classic completion/menu code re-exports this catalog |
| `superforecasting_agent/application/insights.py` | shared command arguments | Typed days/source query and slash argument parsing for CLI, messaging and native TUI | No storage, runtime or presentation imports; InsightsEngine retains reporting ownership |
| `superforecasting_agent/application/sessions.py` | application services | Resumable-session selection and atomic branch-copy admission | No presentation or transport imports |
| `superforecasting_agent/hosting/runtime.py` | serving lifetime | `RuntimeHost` owns workers, session registry, store, configuration, device sign-in, shutdown ordering and restart admission | No presentation or runtime configuration imports; adapters supply protocol-specific interruption and turn-finalization callbacks |
| `superforecasting_agent/hosting/{workers,sessions,registry}.py` | host resource ownership | Worker admission/drain; live runtime registration; session use, finalization, retryable disposal and replacement admission | No transport, CLI, agent or tool imports; enforced transitively |
| `superforecasting_agent/hosting/legacy_commands.py` | compatibility worker lifetime | Lazy command acquisition, serialized use and retryable invalidation | No presentation, runtime, agent or tool imports; adapter supplies the worker factory |
| `superforecasting_agent/hosting/builds.py` | deferred initialization ownership | Admission, completion-event identity and retry after cleanup | No presentation, runtime, agent or tool imports; adapter supplies construction and cleanup |
| `superforecasting_agent/hosting/storage.py` | database serving lifetime | `SessionStore` serializes acquisition, close and explicit restart | No presentation or runtime configuration imports; failed close retains the owned handle |
| `superforecasting_agent/configuration/` | configuration values | Defaults, model-section interpretation, legacy-key normalization, nested lookup and environment expansion | No storage, runtime, forecasting or presentation imports; runtime compatibility names re-export these owners |
| `superforecasting_agent/storage/configuration.py` | shared configuration storage | `ProfileConfiguration` reads content-bound snapshots and checks save revisions; hosting re-exports it and owns its instance | No presentation or runtime imports; explicit profile paths and shared atomic writes; AppConfig is also a consumer |
| `superforecasting_agent/hosting/device_auth.py` | device sign-in lifetime | `DeviceSignIn` owns attempt identity, cancellation, deadlines, save admission and once-only terminal consumption | No presentation, runtime or credential storage imports; adapter supplies provider exchange/persistence callbacks |
| `superforecasting_agent/hosting/credentials.py` | live credential application | `refresh_credentials` preserves model selection and updates the matching agent's client and pool | No presentation, runtime, agent or tool imports; caller supplies provider resolver and reserves the session |
| `superforecasting_agent/hosting/websocket.py` | headless transport entrypoint | Authenticated host application and explicit serving lifetime | Uses shared RPC operations; no dashboard construction |
| `superforecasting_agent/storage/retention.py::mutate_meta` | atomic metadata persistence | SessionDB exposes transactional read/update with rollback; GoalManager owns expected-state validation and stale-verdict rejection | No command or presentation imports |
| `superforecasting_agent/storage/transcripts.py` | transcript export persistence | Shared unique, atomic JSON snapshots for CLI and TUI; callers capture concurrent histories under their own lock | No agent, runtime or presentation imports; no model initialization |
| `superforecasting_agent/storage/` | session persistence | `superforecasting_agent.storage.session.SessionDB` binds operations from focused storage modules | Storage leaves do not import the SessionDB facade |
| `protocol/` | kernel (wire contracts) | pydantic models under `protocol/rpc`, `protocol/events`; `generated.ts` is generated from it | **anything app-side** — `forecasting`, `tools`, `agent`, `gateway`, `tui_gateway`, `superforecasting_agent.runtime`, `run_agent`, `cli` (Tier-1 contract, enforced) |
| `forecasting/` | domain (ledger, scoring, quorum, CLI) | `forecasting.ledger`, `forecasting.cli` (façade packages), `forecasting.models` | `tui_gateway` (Tier-1); `superforecasting_agent.runtime` + `tools` are **ratcheted** (frozen lists in pyproject — may only shrink) |
| `forecasting/sources/` | source adapters, records and parsing | Domain `*_records.py`, `values.py`, `dates.py`, `package_registry.py`, `feeds.py`, and GitHub/package/research/weather/energy adapter leaves; existing `forecasting.source_adapters` names remain available | Record modules use dataclasses and domain models; no fetching, CLI, runtime, or source-adapter dependency |
| `forecasting/hooks/store.py` | hook policy mutation | Shared CLI/RPC validation and atomic field/rule mutations | Uses shared storage locking; rule read/validate/write holds one lock; failed writes never fall back to an unowned temporary file |
| `forecasting/hooks/loader.py` | validation policy loading | Compile current inline and profile rule specifications | No runtime configuration import; uses shared profile identity, never caches by object identity or file timestamps |
| `forecasting/ledger/` | domain leaf | `forecasting/ledger/__init__` (monkeypatch-forwarding façade over `core.py` + leaves) | `forecasting.cli` (Tier-1) |
| `forecasting/cli/` | surface (argparse assembler) | `forecasting/cli/__init__` (`_CliPackage` forwarding façade) | — |
| `superforecasting_agent/tooling/inventory.py` | shared tool inspection | Typed toolset inventory, selection flags and legacy filtering for CLI and native TUI | No CLI, gateway or TUI imports, enforced transitively |
| `superforecasting_agent/tooling/skill_types.py` | skill source contracts | `SkillMeta`, `SkillBundle`, `SkillSource`; re-exported by `tools.skills_hub` | Standard library only; importing contracts does not load source adapters |
| `superforecasting_agent/tooling/github_auth.py` | skill source authentication | `GitHubAuth`, re-exported by `tools.skills_hub` | Credentials resolve lazily; importing the module does not load source adapters |
| `superforecasting_agent/tooling/skill_paths.py` | skill bundle path validation | Shared name, category, and relative-file validators, re-exported by `tools.skills_hub` | Standard-library-only validation before filesystem access |
| `tools/` | tools | `tools.registry`; `tools.forecast_actions.ACTIONS` | `run_agent` (forbidden) |
| `forecasting/configuration/` | setting contracts and registry | ConfigKey, defaults and alias maps; AppConfig re-exports existing names and owns loading/diagnostics | No AppConfig, runtime/storage, tools, agent or presentation imports; enforced transitively |
| `forecasting/domains.py` | semantic classification | Explicit source categories and audited active-question corrections | No title-based inference or probability-history rewriting |
| `forecasting/source_bindings.py` | measurement contracts | NWS temperature and USGS magnitude extraction | No network calls or inferred settlement decisions |
| `forecasting/sources/bls_parsing.py` | BLS parsing | Finite measurements, exact series identity, periods and duplicate/revision checks | No network, CLI or ledger writes; periods are not publication times |
| `superforecasting_agent/storage/files.py`, `storage/locking.py` | configuration mutation and locking | Dotted mapping/list updates, atomic YAML replacement and reentrant process locks | No runtime imports; snapshot admission belongs to `runtime.config` and the raw host configuration owner |
| `forecasting/censoring.py` | coarsened observations | Typed right-censoring contracts and threshold-event probabilities | No fabricated exact outcomes or full-distribution score claims |
| `superforecasting_agent/hosting/commands.py` | configured process lifetime | Shared result, timeout, admission and child cleanup policy | No presentation, runtime, agent or tool imports; caller supplies environment and redactor |
| `superforecasting_agent/runtime/subgoal_commands.py` | shared command operation | `execute_subgoal` validates and applies criteria changes through a session-bound GoalManager for CLI, messaging and native TUI | No CLI or transport imports; GoalManager retains persistence and continuation ownership |
| `superforecasting_agent/runtime/curator.py` | curator command operations | Shared parser and skill curation operations with injected output/confirmation; CLI and TUI use the same handlers | No CLI or TUI imports; agent curator and skill usage retain storage/review ownership |
| `superforecasting_agent/runtime/plugin_commands.py` | shared plugin inspection | `describe_plugins` queries the existing manager for CLI and native TUI output without constructing a chat runtime | No CLI or transport imports; plugin manager remains the discovery authority |
| `superforecasting_agent/runtime/quick_commands.py` | command policy composition | Sync/async adapters supply profile environment and redaction to the host operation | CLI, Ink and messaging render the same result; inherited filter/redactor retain their existing ownership |
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
that have not yet migrated to application services. Session creation and model
changes do not start it. The host ownership helper serializes its use and retains
a failed-cleanup handle before allowing replacement.

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
  Its `resolve_config` operation normalizes an already captured raw mapping
  without rereading a profile. TUI startup passes that result through the agent
  factory, provider resolver, custom-pool seeding and pool strategy selection.
  Runtime values contain expanded environment references and must not replace
  raw revision-bearing settings during persistence.
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


### Host compatibility contract

`protocol/rpc/host.py` owns compatibility request/response types.
`tui_gateway/host_rpc.py` advertises the supported wire-version range and actual
registered RPC method names. Stdio, WebSocket and HTTP use that same descriptor.
Authenticated clients can call `host.negotiate` with `protocol_version` and
`required_capabilities`; incompatibility returns RPC error 4004, invalid input
returns -32602, and negotiation starts no session or model call.

Ink checks the hello descriptor before publishing gateway readiness. It requires
forecast operations and session/prompt operations, rejects incompatible hosts,
and closes its transport without entering automatic restart loops. An explicit
restart can retry after changing the backend. Capabilities indicate implemented
operations; they do not claim external providers have credentials or are healthy.
Legacy clients may still use existing RPCs; negotiation is not an authentication
mechanism or a replacement for per-operation input validation.


### Session application selection

`superforecasting_agent/application/sessions.py` owns resumable-session selection:
input validation, internal-source exclusion, explicit administrative source
selection, active-session exclusion after compression projection, and pagination.
Ink list/auto-resume, classic CLI recent history, and CLI list/browse consume it.
Storage owns SQL and compression lineage; products own rendering and the set of
currently active session IDs. Import checks forbid presentation and transport
imports from this application package.

The session database serving lifetime belongs to
`superforecasting_agent/hosting/storage.py`. The host drains admitted workers
before closing it; transports acquire it through the host adapter. Initialization
failures preserve diagnostics, failed close retains ownership for retry, and a
stopped owner cannot reopen until explicit host startup. Presentation imports are
forbidden by the storage-owner import contract.

Raw host profile snapshots and their content cache belong to
`superforecasting_agent/hosting/configuration.py`. Paths are explicit; snapshots
carry resolved profile identity and revision. Atomic writes, update locking and
revision metadata belong to `superforecasting_agent/storage/files.py`. Runtime
CLI loaders retain their expansion/default policy and delegate revision identity
to storage. The host configuration owner cannot import presentation modules.

Live runtime membership and retirement belong to
`superforecasting_agent/hosting/registry.py`. Registration cannot silently replace
an existing runtime ID. Enumeration snapshots membership, and retirement preserves
an entry until finalization and resource disposal succeed. Session content remains protected by each
session's history/admission lock. The registry imports no transport or product.


### Command handoff transport semantics

Ink requests `command.dispatch` first. An unsupported native command returns
error code 4018 with `data: {dispatch: "slash.exec", execution_started: false}`.
Only that pre-execution handoff (or an absent method, -32601) can invoke the legacy
worker. The existing `slash.exec` handoff to `command.dispatch` stays available
for older clients. Error code/data and established older-host handoff messages
are preserved. Timeouts, disconnects, execution/validation failures and stale
sessions cannot trigger another execution. Plugin/skill handlers report owned
failures directly instead of allowing fallthrough.


### Runtime selection commands

`runtime/codex_runtime_switch.py` owns runtime argument interpretation, binary
readiness checks and change/migration results for CLI, messaging and native TUI.
Consumers supply persistence. TUI supplies the host snapshot owner and preserves
the current agent until a new session. Failed persistence leaves the caller
snapshot unchanged; successful persistence retains its updated revision.


### Notification routing

`hosting/notifications.py` owns conversation-key matching for background events.
Session-bound events may only be consumed by their named conversation; retry
counts cannot redirect ownership. The process registry retains that key when
producing completions. TUI polling supplies queue access and rendering/turn
callbacks; its historical routing helper delegates to the shared policy.

`hosting.notifications.poll_notifications` also owns queue admission, stop/requeue
decisions and session exclusion. Transport adapters supply formatting and delivery
callbacks. A transitive import contract prohibits presentation, runtime, agent and
tool implementation dependencies from this owner.


### Numerical backend installation boundary

`forecasting.bayes_toolkit` and `forecasting.market_compute` load installed
scientific libraries but never run package installers. Their compatibility
`ensure_industry_backends` functions now probe/load only. Core algorithms retain
the existing standard-library fallbacks; advanced models report degraded results
when their backend is unavailable. Installation belongs to environment setup.
For an existing virtual environment, optional backends can be installed explicitly:

```sh
python -m pip install 'scipy==1.16.2' 'statsmodels==0.14.5'
```

Use that environment's Python, then restart the backend so availability probes
reflect the new installation. The existing optional installer group names remain
for compatibility; forecast refresh and numerical calls no longer invoke them.


### Provider quota inspection

`runtime/quota_commands.py` owns `/gquota` validation and report construction for
CLI and native TUI. Existing Google OAuth and Code Assist adapters own credentials
and HTTP requests. This operation does not construct an agent or classic worker.


### Messaging configuration inspection

`runtime/platform_commands.py` owns `/platforms` report assembly and validation
for CLI and native TUI. Gateway configuration owns loading and reset policy; the
platform registry supplies labels. This report is configuration-only and never
claims that enabled adapters are connected.

`forecasting/distribution_parameters.py` owns pure Gaussian moment extraction
shared by censoring and ledger scoring. Neither censoring arithmetic nor the
numerical engines need ledger construction. Transitive numerical import
contracts prohibit runtime, agent, tools and presentation dependencies.


### Background agent inheritance

`agent/background_options.py` owns inheritance from a parent agent plus explicit
host defaults. Empty selections are meaningful; mutable configuration is copied.
Adapters supply session identity/storage and defaults. `agent.agent_factory` owns
construction using the inherited resolved runtime, without resolving a new account.


### Startup prompt assembly

`agent/startup_prompt.py` owns validation and combination of a system prompt
with requested startup skills for CLI and TUI. The existing skill loader owns
lookup and usage tracking; product adapters supply parsed skill names and session
identity. Missing skills fail before model construction.

Classic CLI foreground and background construction also uses
`agent.agent_factory.build_agent`. Resolved provider fields, ACP command arguments
and credential pools share the TUI mapping and provider/model validation. The CLI
still owns its presentation callbacks and session initialization; full foreground
configuration assembly and legacy slash-worker removal remain unfinished.

`runtime/cron_commands.py::cron_command_output` owns scheduled-task slash-command
parsing, invocation and textual results for classic CLI and native TUI dispatch.
It uses the existing cron tool/storage operations and returns text without global
stdout redirection. Neither an agent nor a classic CLI worker is needed. Tool
failures remain visible; the transport must not replay a command after execution.

`agent/session_lifecycle.py` retains child-agent handles whose release/full close
fails. Cleanup reports incomplete disposal to the host after attempting independent
resources. Retries operate on those exact handles; task-ID cleanup remains once per
parent owner. Reentrant child disposal is guarded independently from the parent's
resource lock, so callbacks cannot replay an in-flight batch.

`agent/openai_clients.py` retains failed SDK close handles. Lifecycle teardown
refuses to report complete while these remain unconfirmed: HTTPX can set its
closed flag before transport disposal raises, making subsequent public close calls
no-ops. Retention is diagnostic containment, not a promise of automatic transport
recovery; private SDK/socket internals remain outside agent ownership.

Terminal sandbox publication is tied to its per-task creation-lock identity.
Cleanup invalidates that identity atomically with detaching the active environment.
Retired creators and waiters cannot publish into or execute against a replacement
session; unpublished sandbox disposal uses its direct object handle.

File adapters bind to an exact environment object and creation generation. Both
lazy environment and adapter publication reject retired generations. Terminal
cleanup uses conditional cache invalidation against its detached environment, and
live-path bookkeeping obtains cwd from the currently active environment.

`tools/environments/configuration.py` owns the pure mapping from loaded terminal
configuration plus per-task overrides to sandbox constructor arguments. Terminal
and file tools consume the same mapping, including backend images, cwd, timeout,
SSH/local persistence and container options. Mutable container options are copied
for each construction. The module has strict lint/format/type coverage and a
transitive import contract forbidding dependencies on its runtime consumers.

Goal managers no longer use a process-global database cache. A supplied database
provider yields borrowed host storage; otherwise the standalone manager owns its
connection and supports `close()` and context-manager use. Failed explicit close
retains ownership for retry, and initialization failure closes only owned storage.
A weak finalizer supports legacy callers that discard standalone managers without
closing explicitly. Compatibility load/save helpers close their own short-lived
connections. CLI/gateway callers can migrate to their existing host DB providers
without changing goal validation or compare-and-swap behavior.

Classic CLI and messaging-gateway goal managers now borrow their existing
`_session_db`, as TUI managers borrow host storage. Missing host storage never
falls back to standalone database creation. CLI goal-manager reuse checks both
session and database identity; rebinding closes only the old manager, not its
borrowed connection. Gateway command lookup, queued-continuation checks and
post-turn judging all use the same host store.

Tool selection distinguishes absent configuration from a saved empty list.
`tooling/selection.py` owns this policy: saved `[]` enables no tools, including
implicit plugin/MCP/credential additions. TUI startup forwards the resolved list
unchanged; it must not translate `[]` into the agent's `None` (all-tools) sentinel.

`tooling/startup_selection.py` owns startup toolset override validation, plugin
lookup, enabled/disabled MCP classification and configured-selection fallback.
The TUI passes its override string and setting label and renders returned notices
through a callback. The shared owner has strict lint/format/type checks and a
transitive import contract prohibiting classic CLI and TUI dependencies. Empty
configured selections remain empty; explicit all-tool overrides remain `None`.

Every import-bound RPC family rebinds its server references, callbacks and constants
when registered. Registration transfers the family to the receiving process-level
server owner; it does not support simultaneously serving multiple server module
instances through the same module globals. Closure-based families already capture
the receiving server. The registration-owner regression discovers import-bound
families and checks every imported dependency against its registered owner.
