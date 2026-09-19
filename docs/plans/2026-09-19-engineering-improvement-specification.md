# Engineering improvement specification

**Status:** proposed implementation contract; no runtime changes made by this audit.  
**Baseline:** `df8e3e33cd4d08c6eaad38a275f6e217e92a3375`, 19 September 2026.  
**Evidence:** [engineering audit and findings F01–F12](2026-09-19-engineering-audit.md).

## Objective and completion definition

Make the forecasting backend authoritative, product interfaces predictable, and runtime
failure behavior testable without a live provider. The TUI is the first consumer of shared
product operations; CLI, messaging and future distributions use the same operations.

Completion means the nine packages below meet their acceptance criteria on a selected
merged commit, with receipts identifying source, dependency locks, toolchains and products.
It does not mean every inherited file is rewritten, every platform is supported, or that
calibration learning has been empirically proven to improve forecasts.

### Required invariants

1. Only explicit user-authorized promotion changes active forecast probabilities. Draft
   restoration, research, lessons, alerts and background reviews cannot do so.
2. Resolution/scoring contracts, source identity, units, period, revisions and typed censoring
   remain centrally enforced; explicit tail probabilities cannot fall back silently.
3. Retry preserves provenance and idempotency. Unknown external delivery/execution remains
   unknown or reconciliation-pending, never falsely completed.
4. Cancellation acknowledgement means cancellation was requested. Completion means the owned
   execution has actually exited or reached its specified durable terminal state.
5. A stale event, response, PID, host identity or configuration revision cannot mutate a
   replacement component's state or resources.
6. Product adapters translate inputs and outputs. They do not independently implement domain
   validation, provider defaults, persistence scope or lesson eligibility.
7. Existing profiles, plugin entry points and documented compatibility aliases continue to
   work unless an explicit, tested deprecation migration is approved.

## Target ownership and dependency direction

Use existing packages; add a directory only for a coherent owner with consumers and tests.
The sketch names responsibilities, not a compulsory mass file move.

```text
forecasting/
  application/       typed forecast, source-import and interview operations
  ledger/            transactions, immutable records, query/persistence contracts
  sources/           acquisition, parsers and semantic contracts
  interviews/        elicitation, frozen context, evaluation and promotion policy
superforecasting_agent/
  application/       shared non-forecast commands and product capabilities
  configuration/     atomic settings updates and migration ownership
  storage/           durable storage primitives
  hosting/           execution/process/resource lifecycle ownership
  runtime/           legacy presentation/bootstrap adapters, narrowed incrementally
protocol/            versioned product wire requests/results/events
cli.py + forecasting/cli/ + runtime CLI
                     parsing, rendering, exit status; delegate operations
tui_gateway/         JSON-RPC adapter and host composition
gateway/            messaging transport and session integration adapters
ui-tui/src/
  app/               composition, primary route, modal and focus ownership
  components/        rendering and local presentation
  hooks/ + lib/      typed view controllers, cache/read models, shared interactions
```

Domain owners must not import CLI, Ink, gateway server globals or terminal rendering.
Transport models may map to domain requests rather than forcing every internal object into
Pydantic. Avoid duplicate validators: an adapter validates wire shape; a shared operation
validates meaning before effects. Preserve import-linter contracts and add only enforceable
new boundaries. Every new owner README states purpose, public API, dependency direction,
state ownership, failure semantics and where tests live, in roughly one page.

## Delivery sequence and effort

Estimates are engineering days including focused tests and review, not promises of elapsed
completion. They assume one engineer familiar with the repository and working desktop CI.
Native runner failures may add elapsed time. Do not implement all packages in one PR.

| Order | Package | Priority / owner | Estimate | Dependencies |
|---|---|---|---:|---|
| 1 | W01 Restore qualification and canonical checks | P0 / runtime + developer tooling | 2–4 | None |
| 2 | W02 Ratchet types and feedback tiers | P1 / developer tooling | 3–5 | W01 |
| 3 | W03 Typed source acquisition and import | P1 / forecasting sources/application | 4–7 | W02 conventions |
| 4 | W04 Consistent CLI and command operations | P1 / application + CLI | 3–5 | W03 for source commands |
| 5 | W05 Runtime context and lifecycle seams | P1 / hosting + gateway | 4–7 | W01, W02 |
| 6 | W06 TUI navigation and async ownership | P1 / TUI | 4–6 | W02; W05 for host epochs |
| 7 | W07 Durable, lesson-informed questionnaires | P1 / interviews + TUI | 4–7 | W02; W06 integration |
| 8 | W08 Integrated deterministic recovery | P1 / product integration | 3–5 | W05–W07 |
| 9 | W09 Release evidence and current references | P1 / release engineering | 2–3 | All accepted packages |

Planning envelope: **29–49 engineer-days**. Re-estimate after W01/W02 with measured test
costs and characterization results. W03/W04 and W05/W06 can proceed independently if staffed,
but there is no assumption of parallel agents or concurrent changes to shared registries.

**First milestone:** W01 plus typed test fixtures and coverage reporting from W02.
**Second milestone:** shared source/command contracts and independently owned runtime hosts.
**Third milestone:** durable questionnaire editing, trustworthy TUI state and integrated recovery.
**Release milestone:** one exact merged commit qualifies under W09.

## W01 — Restore qualification without weakening ownership

Addresses F01–F03. Deliver separate fixes for native process identity, the stale provider
fixture and generated-reference freshness.

### Contract

The hosting/storage owner exposes an identity capability with an explicit available or
unavailable result. An available identity includes sufficient host/boot/process-namespace
information for that platform's ownership claims. Persist a versioned identity scheme;
previous records that cannot be safely compared remain unreconciled rather than granting
permission to terminate a process. No network MAC address fallback alone should be assumed
universally available or authoritative.

Use native platform facilities where available, with bounded subprocess execution if needed.
Document behavior in virtualized macOS/Windows and containers. Do not add a native dependency
before checking existing facilities. Diagnostics identify capability failure without exposing
raw stable hardware identifiers.

Provider selection tests choose the desired stable provider identity; display order gets its
own assertion. Keep Nous compatibility TLS-option forwarding covered even though it is no
longer the default setup choice. Add `scripts.docgen --check` to canonical developer checks
and regenerate the stale references.

### Acceptance

- Reproduce the recorded provider failure locally with controlled input, then pass the corrected
  test and ordering tests without real credentials or interactive reads.
- Native ownership tests cover unavailable identity, randomized UUID fallback, reboot, PID reuse,
  permission denial and two hosts. Repeated cleanup never signals an unowned/replacement process.
- Previously persisted identity records remain readable with conservative recovery behavior.
- The previously failing macOS recovery job passes with a recorded explanation; Linux and Windows
  ownership tests also pass. Mock-only success does not close the native issue.
- A deliberately stale generated reference fails both canonical local checks and Docs CI.

Rollback: revert new identity acquisition while retaining safe refusal and schema readers;
never downgrade safety to restore apparent availability.

## W02 — Expand strict checks with a measurable ratchet

Addresses F04 and F12. Publish strict-scope coverage using the inventory definition. Add a
separate TypeScript test project and typed fixtures for generated RPC request/result pairs.
Do not use `as any`/`as never` to claim contract coverage; unavoidable test exceptions must be
local, explained and unrelated to the contract being tested.

Apply complete Python lint/import/format/type checks to every newly extracted owner. For
inherited shells, record the initial diagnostic baseline and reject newly introduced
violations while reducing existing ones in touched operations. A changed file cannot escape
the gate by moving out of an allowlist. Avoid blanket ignores and unreviewable formatting diffs.

### Feedback tiers

- **Fast:** canonical static checks, generated freshness, import/naming rules and focused tests
  for changed ownership packages; report actual duration.
- **Integration:** controlled-provider backend/TUI/dashboard lifecycle tests and affected product
  builds, including test fixture typechecking.
- **Qualification:** full canonical Python/TUI suites, installed artifacts, upgrades and supported
  native matrix on the selected commit.

Reuse existing `scripts/dev.py`, `scripts/run_tests.sh` and per-ref push planning. Any hook
policy change must update contributor instructions and required checks together. A receipt
is reusable only for an identical tree, locks, command, runtime and platform; a different
merge tree requires new qualification.

### Acceptance

- An intentionally malformed typed RPC fixture fails test typechecking.
- New code in owned packages cannot bypass complete checks through directory relocation.
- Multiple-ref pushes and non-`main` defaults retain existing coverage guarantees.
- Coverage report distinguishes file/line scope, diagnostic count and test coverage; no metric
  is substituted for another. Scope does not shrink without an explicit exception.
- Record fast/full duration and flakiness baseline, then choose optimization targets from it.

## W03 — One typed source acquisition/import operation

Addresses F05. Migrate one economic adapter and one prediction-market adapter first, then
move remaining duplicated CLI paths in small batches. Extend existing dispatch rather than
introducing an unrelated provider framework.

### Proposed internal API shape

```python
# Illustrative names; reuse existing equivalent domain models.
def acquire(request: SourceRequest, execution: ExecutionContext) -> AcquisitionBatch: ...
def prepare_import(batch: AcquisitionBatch, policy: ImportPolicy) -> ImportPlan: ...
def commit_import(plan: ImportPlan, ledger: ForecastLedger, request_id: str) -> ImportReceipt: ...
```

`SourceRequest` has a stable adapter ID and discriminated validated options, not unrestricted
kwargs. It validates booleans as booleans, integer limits and supported date formats before
network I/O. Adapter-specific options remain adapter-specific. `AcquisitionBatch` records
source/retrieval identity, publisher timestamps when supplied, observation periods, units,
entity/series identity, revision policy and raw-content digest as applicable. Missing
publication time stays missing; retrieval time is a distinct field.

`ImportPlan` separates accepted, duplicate, rejected and unsupported records, with stable
reason codes. Source-bound settlement admission remains stricter than display ingestion.
`ImportReceipt` identifies persisted records and provenance. An interrupted/repeated commit
with the same request identity cannot duplicate evidence or silently replace revisions.

### Acceptance

- CLI, tools and gateway given equivalent typed inputs produce equivalent plans/errors.
- Reject string `"false"` as a boolean, zero/negative invalid limits, wrong units/entities,
  ambiguous periods, unsupported revisions and fabricated timestamps before settlement.
- Fixtures cover valid sparse economic series, first release versus revision, prediction-market
  outcomes/probability units, changed source shape, duplicate/reordered observations and time zones.
- Parser tests need no network or ledger. Acquisition tests use local HTTP fixtures. Persistence
  tests inject failure before/after transaction boundaries and prove retry behavior.
- Existing source-bound export/import verification distinctions remain intact.

Rollback: retain old public command spelling; switch its implementation by adapter only after
parity tests pass. Do not dual-write both import paths.

## W04 — CLI behavior and command discoverability

Addresses F02, F07. First inventory public forecast commands, runtime commands, slash commands,
TUI-only actions and compatibility aliases, recording owners and intentional differences.
Prioritize source import, configuration/model selection and job/cancellation commands.

### Contract

Every shared operation defines typed inputs, defaults, validation errors, side effects and
persistence scope. Presentation adapters own human text and transport envelopes. Stable
command IDs must not depend on menu index or translated label.

For commands supporting machine output, define and test their success/error schemas, stdout
versus stderr behavior and exit statuses. New machine-mode commands must never prompt; missing
input returns a structured actionable error. Preserve existing documented exit codes and
schemas, adding a versioned mode where changing them would break scripts. Keep progress out
of machine-result stdout.

Root help remains forecast-first, groups advanced/provider operations, and exposes aliases
without duplicating the entire command tree. Use existing catalog/parser metadata for help
projections; do not make a universal parser framework a prerequisite.

### Acceptance

- Table-driven parity tests cover defaults, invalid inputs, provider identity, profile selection,
  persistence destination, cancellation and permission errors across participating interfaces.
- `--help` and `--version` work without provider credentials or initializing a live model.
- Subprocess tests assert exit code, stdout/stderr and noninteractive completion for representative
  success and failure cases in an isolated profile.
- Config operations continue using the shared atomic updater; two independent updates preserve
  unrelated keys, and secrets remain outside ordinary diagnostic output.
- Compatibility/profile/plugin fixtures pass; migration instructions name any intentional change.

## W05 — Explicit runtime hosts and lifecycle phases

Addresses F06 and F11. Replace command-handler server rebinding with a typed context carrying
only required capabilities: command execution, config access, session/job access and event
emission. Context lifetime belongs to the host, never module import. Register handlers against
that instance. No generic service container is needed.

Extract conversation and gateway phases only at meaningful boundaries: request admission,
context preparation, model/tool execution, durable checkpoint, finalization and owned cleanup.
Keep current entry points as adapters. Define which phase may write, spend, emit or close.

### Acceptance

- Two runtime hosts in one interpreter register handlers, operate independently, and survive
  the other host's repeated shutdown. No global rebinding redirects requests.
- An expired host/event epoch cannot update a replacement session or close its client, process,
  socket or pipe. Closure failure stays diagnosable and retryable by the original owner.
- Cancellation during model calls, tool execution and checkpointing preserves durable work;
  pending cancellation is not rendered as completed before confirmed exit.
- Authentication expiry/rate limits retain their typed retryability and domain errors.
- Ledger admission/preparation is side-effect-free; transaction tests prove no partial resolution,
  score, postmortem or lesson records and no duplicates on retry.
- External calls with uncertain completion enter reconciliation state instead of automatic
  replay unless their documented idempotency permits replay.

Do not attribute historical SSL/BFD incidents from these tests alone. Keep diagnostic hooks,
artifact requirements and containment intact.

## W06 — Predictable TUI navigation and async data ownership

Addresses F08. Introduce a discriminated primary route under the existing app owner, with
separate modal/prompt ownership and explicit focus target. Maintain compatibility selectors
while migrating one view at a time. Preserve correlated prompt IDs and queued prompts.

A view controller owns request identity, selection, loading/error/refresh state and cache
subscription; the component owns terminal rendering. A request/event is admitted only for its
active profile, host/session epoch and request generation. Reuse the existing scoped cache;
refresh can show retained data with a truthful stale/loading indication.

### Interaction contract

- One keyboard owner handles an action for the current focus/modal state. Text entry keeps
  printable keys; global shortcuts do not steal composer or search input.
- Displayed shortcut hints derive from the same enabled action definitions as dispatch where
  practical. Disabled actions disclose their reason and cannot pretend to succeed.
- Selection and reader/chart scroll are independent. New selection starts at its defined scroll
  origin; only explicit scroll actions move content. Resizing cannot move sibling panels out of view.
- Reconnect distinguishes disconnected, reconnecting, resynchronizing and ready; a transport
  connection alone does not imply durable session restoration.

### Acceptance

Deterministic interaction tests cover primary-route exclusivity, modal return focus, prompt FIFO,
left/right/tab/escape ownership, editor focus, late responses, profile switches, repeated
reconnects and resize at 80×24, 120×36 and 180×50. Narrow windows may use an explicit compact
layout, but must not silently hide the exit/action path. Terminal rendering tests include wide
characters and long labels. Test controlled providers first; native smoke qualifies the renderer.

No claim of WCAG/assistive-technology compliance follows from color tests alone. Audit the
existing palettes and no-color cues, then document native accessibility limits.

## W07 — Crash-safe and lesson-informed questionnaires

Addresses F09/F10. Deliver two distinct changes, with separate migrations and review.

### A. Unconfirmed editor buffers

Add a profile-scoped durable editor-buffer record keyed by interview ID, base revision and
question ID. Store text/choice/note drafts and a monotonic buffer revision. A bounded debounce
may save edits; render `unsaved`, `saving`, `saved locally`, or `save failed` from actual
acknowledgement. Do not describe pending debounce contents as saved.

Saving a buffer must not call answer confirmation, evaluation, generation or promotion.
On restore, show recovered unconfirmed content and require explicit confirmation. Reject or
surface conflicts when the underlying interview/question revision changed; never overwrite a
new confirmed answer. Define discard and retention/cleanup behavior, including cancelled
interviews and profile removal. Do not store secret prompt contents in these buffers.

### B. Frozen lesson applicability

Extend the frozen context with a versioned lesson-selection record from the existing lesson
owner: exact lesson/revision identifiers, content digest, applicability conditions, supporting
sample/cluster counts, scope, supersession state, selection policy version and inclusion or
exclusion reasons. Apply cutoff rules consistently and distinguish then-known information from
later retrospective knowledge.

New contexts may use the new schema; historical contexts remain byte-identical and evaluable
under their original schema. Generation and evaluation receive the same frozen packet. Model
output cannot upgrade small-sample guidance into mandatory correction or bypass source/lesson
policy. Prompt size admission must preserve the full durable packet and explicitly record any
permitted presentation selection; no silent evidence truncation.

### Acceptance

- Kill/restart after acknowledged buffer save: draft returns as unconfirmed; active probabilities
  and confirmed answers remain unchanged. An unacknowledged edit is not falsely promised durable.
- Duplicate save/confirm and revision conflicts preserve exactly the intended answer history.
- Lesson applicability, exclusion, supersession, small-sample and future-cutoff fixtures produce
  explainable frozen selections; later library changes cannot rewrite an old evaluation.
- TUI shows concise guidance with expandable provenance and uncertainty, not an overwhelming
  checklist. Unknown/skip, base rate, evidence independence and change rationale remain available.
- Tests prove consultation and invariants. Claims of improved calibration still require a separate
  prospective paired trial and are not an engineering completion criterion.

## W08 — Integrated failure qualification

Addresses F08/F11. Extend the existing controlled-provider integration harness rather than
starting a competing harness. Run the real gateway, session database, TUI process and dashboard
transport together; fake only external providers and clocks/fault scheduling.

For each scenario, assert durable state and displayed state at intermediate transitions:

| Injected event | Required observation |
|---|---|
| Auth expiry or quota response | Actionable failure/retry state; preserved draft/checkpoint |
| Stream interruption after partial output | Partial output marked incomplete; no false successful finalization |
| Death before/after durable commit | Restart reconciles committed work and retries only permitted work |
| Nested delegation/handoff interruption | Parent and child ownership/status agree; no orphan spend on replay |
| Reconnect repeated with delayed old events | New epoch wins; no duplicate prompts/messages or stale completion |
| Cancel followed by process-exit delay | Cancellation pending until actual termination; resource ownership retained |
| Resize while modal/editor active | Stable focus, bounded layout, truthful visible shortcuts |
| Config/profile switch during fetch | Old response cannot populate another profile's cache/view |

Use deterministic barriers rather than arbitrary sleeps. Include sequence numbers/correlation
IDs in assertions and redact diagnostics. Isolate processes/resources per test and assert
cleanup; do not make global test-order changes the only remedy for resource leaks.

Completion requires repeatability on supported desktop runners, not a single local green run.
Record first-failure artifacts and an explicit flake policy. A skipped scenario remains visible
as unqualified; it cannot be counted as a pass.

## W09 — Qualify one merged product and publish current references

Addresses F03/F12 and all package exits. Build backend/TUI artifacts from one selected merged
commit; qualify those installed artifacts, not only editable source checkouts. Record hashes,
Python/Node/OS versions, dependency locks, commands and results.

Verify fresh installation, upgrade from a named prior release, customized skills/plugins,
legacy profiles, cancellation/recovery and supported CLI/TUI startup. Check backend-only
installation remains Node-free and the dashboard continues to embed the same TUI. Verify
machine diagnostics include version/source identity and redact secrets in realistic failures.

Refresh generated reference docs, ownership map, directory READMEs, beta scope and tester brief.
Keep TODO actionable by linking accepted packages and moving completed receipts to history.
Keep Android/Termux, Daytona/Modal and unavailable SSL artifact investigation explicitly deferred.

### Release exit

- All nine acceptance packages have exact-commit receipts or an explicit reviewed scope change.
- Supported native products and full canonical checks pass; no unexamined bypass is presented as
  qualification. Failed checks have attributed causes and fixes or accurately reduced support.
- New migrations have round-trip/backward-read fixtures and documented rollback limitations.
- Beta publication preserves immutable identity and does not advance stable channels accidentally.
- No required API/schema changed without compatibility notes and consumer tests.

## Review and change-control rules

Each implementation PR identifies its work package, before/after behavior, affected owner,
public contract, migration, focused validation and remaining uncertainty. Keep mechanical
moves separate from semantic changes when that improves review. Freeze protocol fixtures
before moving orchestration; do not freeze accidental internal helper behavior as public API.

Avoid speculative factories, generalized event buses and broad renaming. Prefer a direct typed
function or context with demonstrated consumers. The audit does not authorize deleting
compatibility paths, weakening source settlement rules or replacing the UI framework.

After each milestone, update the measured baseline and remaining work. Stop decomposition when
the behavior has a clear owner, interfaces agree, and tests can exercise failures independently.
File size alone is not an unfinished requirement.
