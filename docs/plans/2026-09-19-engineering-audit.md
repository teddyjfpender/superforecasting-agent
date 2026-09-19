# Engineering audit: Superforecasting Agent

**Status:** investigation completed; recommendations proposed, not implemented.  
**Date:** 19 September 2026.  
**Baseline:** `df8e3e33cd4d08c6eaad38a275f6e217e92a3375`, fetched default branch
`superforecasting-agent-snapshot`.  
**Companion:** [implementation specification](2026-09-19-engineering-improvement-specification.md).

## Executive assessment

The repository has credible foundations for a forecasting product: a durable ledger,
explicit source semantics, shared application owners, generated transport contracts,
independent backend/TUI packaging, and extensive recovery tests. A rewrite would discard
valuable behavior and increase risk.

The principal weakness is the distance between those foundations and their consumers.
Large inherited orchestration paths still own policy, persistence decisions, provider
routing, and presentation together. Selected packages receive strong checks, while much
of the runtime does not receive the same checks. File extraction has sometimes retained
module-global coupling. The TUI similarly combines view rendering with interaction and
async lifecycle state. These are change-risk concentrations, not proof that every large
module is defective.

Three current qualification failures require repair before declaring this exact commit
fully qualified. The next structural work should then make the existing owners authoritative
and make their consumers thinner. Product expansion should not precede that work.

## Scope and method

Read-only code investigation in an isolated worktree. Inspected repository inventory,
Python ASTs, quality commands, hooks, packaging boundaries, protocol validation, CLI and
source dispatch, ledger/interview persistence, process ownership, TUI navigation,
questionnaire state, caching, and recorded GitHub check failures for the baseline commit.

The [reproducible inventory](../verification/engineering-audit-2026-09-19/inventory.json)
and [collector](../verification/engineering-audit-2026-09-19/collect_inventory.py)
record static measurements. The [evidence receipt](../verification/engineering-audit-2026-09-19/README.md)
records live check observations and their limits.

This is a targeted architecture and correctness audit, not an exhaustive line-by-line
security audit. No full suite was rerun, no live profile was changed, and no paid model
calls were made. Native terminal interaction, performance, and accessibility were not
newly qualified. Existing CI results are evidence about their recorded jobs, not proof
of every platform or workflow. Proposed acceptance tests below are future requirements,
not tests claimed to have passed.

## Measured baseline

| Measure | Result | Interpretation |
|---|---:|---|
| Git-tracked files | 5,888 | Includes documentation, fixtures, plugins and skills |
| Runtime Python | 1,098 files / 554,648 physical lines | Defined prefixes and root Python files; excludes plugins, skills, scripts and tests |
| Runtime under the complete selected Python strict gate | 321 files / 66,083 lines | 29.2% of files, 11.9% of lines; not test coverage |
| Authored TUI source | 311 files / 81,654 lines | Excludes test/testing directories and generated protocol |
| Python test source | 1,796 files / 578,637 lines | Volume does not establish assertion quality or coverage |
| TUI test source | 201 files / 38,965 lines | Tests are excluded from the production TypeScript project |
| Python AST parse failures | 0 | Collector run using Python 3.13 |

Physical lines include comments and blank lines. Strict membership is read from
`scripts/dev.py:STRICT_PYTHON`; other checks still apply outside it. The global Ruff
configuration is intentionally much narrower than that selected gate. Do not describe
unselected code as entirely unchecked.

### Concentrated change risk

| Location | Physical lines | Specific responsibility concentration |
|---|---:|---|
| `gateway/run.py` | 19,162 | Messaging dispatch, execution, session and platform orchestration |
| `superforecasting_agent/runtime/main.py` | 11,704 | Setup, model selection, updates and command execution |
| `cli.py` | 11,415 | Interactive shell, command behavior and conversation lifecycle |
| `forecasting/cli/core.py` | 10,838 | Argument construction, provider imports, presentation and ledger operations |
| `forecasting/ledger/core.py` | 6,594 | Persistence plus a broad domain operation surface |
| `tui_gateway/server.py` | 6,129 | Transport, registration, shared runtime and product dispatch |
| `ui-tui/src/components/deskView.tsx` | 3,402 | Desk data, selection, interactions and presentation |
| `ui-tui/src/components/marketsView.tsx` | 2,239 | Data lifecycle, navigation, layout and dialogs |

The AST collector also identifies `run_conversation` at
`agent/conversation_loop.py:189` (4,117 lines), `_cmd_import_adapter` at
`forecasting/cli/core.py:3126` (3,245 lines), and `_run_agent` at
`gateway/run.py:16303` (2,282 lines). Their selected decision-node counts are 481,
353 and 336 respectively. This is a prioritization heuristic, **not McCabe complexity**;
it includes nested functions. Do not set a release gate against these numbers without
first adopting a stable metric.

## Findings

Severity distinguishes qualification blockers from maintainability investments.
“Observed” means directly supported by code or the recorded execution; “risk” means a
plausible failure mode requiring a specific test, not a reproduced production incident.

### F01 — Native ownership capability fails qualification

**High; observed; system.** The macOS Node 22 installed-products job fails during durable
background/event recovery with `No stable machine identity is available for durable ownership`.
`superforecasting_agent/storage/process_identity.py:11` uses Linux boot/PID-namespace
identity, but on other platforms rejects the multicast-bit fallback from `uuid.getnode()`.
The rejection is conservative and appropriate when identity is unknown; the capability
assumption is not satisfied in this supported environment.

Provide explicit platform identity capabilities and an actionable unsupported-identity
result. Preserve positive proof of ownership and termination. Never fix this by trusting a
PID alone or accepting a per-process random identity. This failure does **not** establish
the cause of the historical native SSL crash or late bad-file-descriptor incident. See W01.

### F02 — Provider UI ordering is coupled to compatibility tests

**Medium; observed; CLI.** The Tests job fails in
`tests/cli/test_cli_provider_resolution.py:621`,
`test_cmd_model_forwards_nous_login_tls_options`. The test replaces
`_prompt_provider_choice` with the constant index `0`. Provider ordering changed, so it
enters the Anthropic flow and attempts an uncaptured interactive choice instead of the
mocked compatibility login. The logged stack reaches `runtime/anthropic_setup.py:162`.

This is evidence of a stale positional test, not evidence that users selecting Anthropic
are incorrectly routed. Test stable provider identity, preserve legacy login coverage,
and assert visible ordering separately. See W01 and W04.

### F03 — Local quality success does not include reference freshness

**Medium; observed; repository.** The Docs job reports stale generated protocol,
tool-actions, job-types, providers, and config-and-env references. The local
`scripts/dev.py:174` check runs protocol code generation and news-catalog checks but does
not run `python -m scripts.docgen --check`. A contributor can pass this command while
leaving those references stale. Add the existing check to the canonical path and regenerate
from authoritative owners; do not introduce another documentation generator. See W01.

### F04 — Strict checks stop before the largest orchestration owners

**High change risk; observed scope, not a reproduced defect; system/CLI.** The selected
strict gate covers 11.9% of measured runtime lines. The largest dispatch and lifecycle
functions remain outside it. `pyproject.toml` global Ruff rules do not substitute for
selected import, formatting and typing gates. TUI production TypeScript is strict, but
`ui-tui/tsconfig.json` excludes `src/__tests__`; production compilation therefore cannot
prove that test fixtures implement generated contracts.

Extend checks around extracted operations and touched behavior, then ratchet the remaining
shells. Include a dedicated test typecheck and typed RPC fakes. Avoid a repository-wide
formatting/type-suppression migration that obscures correctness changes. See W02.

### F05 — Source import policy is spread across dispatch surfaces

**High change risk; observed; system/CLI.** The 3,245-line `_cmd_import_adapter` owns
provider-specific import behavior, while `forecasting/sources/dispatch.py:74` also selects
adapters and interprets an open `dict[str, Any]`, returning `list[Any]`. For example,
`int(args.get("limit") or 10)` and `bool(args.get("dedupe", True))` rely on callers to supply
already-correct types and semantics. They are not themselves a validated public request.

Consolidate typed acquisition/import operations, not all financial or scientific concepts
into one generic record. Market display series and settlement evidence have different
trust requirements. Preserve independent fetching, parsing, semantic validation and
transactional persistence. See W03.

### F06 — Extracted gateway modules retain server-global ownership

**High change risk; observed; system.** `tui_gateway/commands_rpc.py:14-48` imports the server
and rebinds `_core`, `_ok`, `_err`, and catalog globals in `register(server)`. Handlers
continue to read server state through that module. Moving code to this file did not remove
the dependency cycle or establish independent host ownership.

Use a narrow typed runtime context passed to handler registration; do not build a generic
service locator. Prove two hosts can register and shut down independently in one process.
Keep existing JSON-RPC contracts and domain errors. See W05.

### F07 — CLI discoverability and execution ownership remain separate concerns

**Medium; observed architecture; CLI.** `superforecasting_agent/cli.py:58` derives forecast
command names by constructing argparse and inspecting private actions. The slash catalog
already exists in `superforecasting_agent/application/command_catalog.py`; runtime menus,
forecast argparse and TUI catalog additions are separate surfaces. This is not a reason
to replace every parser with one mega-registry.

Specify canonical command identities, capability visibility, shared request validation,
error meanings, persistence scope and noninteractive behavior. Keep presentation adapters
and compatibility spellings explicit. Audit parity with table-driven tests before claiming
particular defaults are wrong. See W04.

### F08 — TUI route, modal and lifecycle state needs clearer ownership

**Medium/high change risk; observed architecture, prospective failure tests; TUI.**
`ui-tui/src/app/overlayStore.ts` combines view flags, blocking predicates and prompt queues;
`navRoutes.ts` separately maintains route transitions and reset patches. Large views own
RPC requests, data state, keyboard dispatch and layout. A new view can require coordinated
changes across several lists.

Represent the primary route explicitly and keep correlated prompts/modal ownership separate.
Move async state transitions into small controllers when behavior warrants it. Retain the
existing prompt FIFO and reconnect semantics. Do not replace Ink or implement a second
React dashboard transcript. See W06 and W08.

### F09 — Unconfirmed questionnaire edits are not durable drafts

**Medium; observed; TUI/system.** `forecastInterview.tsx:43-67` keeps notes, text and choices
in local state/ref maps. Existing guards prevent accidental navigation/commit of unconfirmed
edits, but process death cannot recover that component memory.

Persist an explicitly unconfirmed editor buffer separately from confirmed interview answers.
Restoration must never silently promote a belief, start a model call, or mutate the forecast.
Include revision conflicts, profile isolation and save-status truthfulness. See W07.

### F10 — Questionnaire generation lacks explicit frozen lesson selection

**Medium product-integrity gap; observed narrow path; system.**
`forecasting/interviews/context.py:17-49` freezes question, baseline, evidence, reference
classes and prior interview. `generation.py:60-95` builds the model packet from those fields;
neither adds an explicit applicable calibration-lesson selection. A baseline can indirectly
contain lesson references; this is not equivalent to selecting and freezing relevant lesson
content and applicability for the new elicitation.

Snapshot creation already enforces lesson policies in `forecasting/ledger/snapshots.py`.
Do not duplicate that policy or claim learning is absent everywhere. Reuse the lesson owner
for questionnaire context, preserve immutable prior captures, and record why guidance was
included or excluded. This establishes consultation, not evidence of better forecasts. See W07.

### F11 — Lifecycle complexity needs controlled extraction, not a rewrite

**High change risk; observed; system.** Conversation execution, messaging execution and
snapshot creation contain substantial branching and side effects. Existing transactions,
resource identity checks and recovery tests are assets. Splitting methods without preserving
transaction and cancellation boundaries can make failures worse.

Extract pure admission/preparation and explicit execution phases behind existing APIs.
Require interruption tests at each durable transition and prove retries do not duplicate
scores, lessons, outbound delivery or model spend. Do not assert exactly-once external
side effects when the provider cannot supply that guarantee. See W05 and W08.

### F12 — Quality evidence needs a sustainable execution strategy

**Medium; observed workflow; repository.** The pre-push path includes whole-suite Python
execution as well as scoped frontend checks. Strong checks exist, but a costly single tier
creates pressure to bypass them and conflates contributor feedback with release qualification.
Existing per-ref push planning should be preserved.

Adopt explicit fast, integration and release tiers sharing the same command owner. Reuse
results only for identical source/dependency/toolchain identities. Keep full integration
qualification before release; do not weaken protected checks just to obtain a green result.
See W02 and W09.

## Existing architecture to preserve

- `protocol/validation.py` already strictly checks successful wire results, rejects structural
  parameter errors and retains documented domain error behavior. Generated method/result
  mappings already reach the TUI client. This audit does not propose rebuilding them.
- Ledger transactions and nested savepoints exist. Frozen interview contexts and revisions
  preserve provenance; baseline promotion is explicit.
- Shared configuration/storage/hosting/application owners, import contracts, naming checks,
  dependency locks, product build profiles and ownership documentation already exist.
- `ui-tui/src/lib/deskViewCache.ts` already scopes caches by connection/context and bounds
  entries. The next task is lifecycle and freshness verification, not adding a second cache.
- Prompt queuing, cancellation ownership and source-specific semantic checks should remain
  centralized. Compatibility adapters protect existing profiles and plugins.
- The dashboard embeds the TUI. Its surrounding web widgets must not become a competing
  owner of terminal session state.

## Security and qualification status

At inspection time GitHub returned **zero open Dependabot alerts**. The baseline OSV jobs
passed. This corrects older alert counts; it does not prove the absence of vulnerabilities
or replace review of credential handling, trust boundaries and plugin execution.

The baseline has successful TUI, e2e, Python compatibility, Linux/Windows installed-product,
Nix and architecture/lint checks, alongside the specific failed Tests, macOS product and
Docs jobs above. A workflow failure must be attributed to its actual failing job; it does
not negate every successful job in that workflow. No new release certification is made.

Android/Termux, credential-dependent Daytona/Modal verification and historical SSL attribution
remain explicitly deferred. Desktop Linux or a cloud VM cannot certify Android, and more
generic SSL stress runs cannot reconstruct missing original crash artifacts.

## Complexity reduction decisions

Prefer these reductions where their acceptance tests pass:

1. Remove duplicated provider-option interpretation from CLI import branches after shared
   typed acquisition is authoritative. Retain source-specific parsers and contracts.
2. Remove server-module rebinding from extracted gateway handlers after explicit host context
   exists. Avoid a new dependency-injection framework.
3. Replace mutually exclusive primary-view flags with one route value; keep genuinely
   independent overlays independent.
4. Generate reference/help projections from existing authoritative metadata; remove redundant
   handwritten lists only after compatibility and visibility tests establish equivalence.
5. Delete obsolete compatibility internals only when import/profile/plugin migration fixtures
   establish they are unused or replaceable. Naming alone is not evidence of dead code.

No speculative line-saving estimate is provided. Measure diff size and responsibility
reduction per work package. A small, correct shared operation is more valuable than a
new directory containing the same global dependencies.
