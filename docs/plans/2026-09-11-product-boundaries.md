# Product boundaries and repository hygiene delivery

Scope: all five deliverables in the user's attached objective. This is an active
implementation plan, not a claim that the existing layout satisfies them.

## Acceptance and authoritative evidence

- [ ] Domain, application, infrastructure, transport and product ownership is
  documented and enforced by import checks, including tests that introduce a
  forbidden edge and verify rejection.
- [ ] The real TUI and CLI consume shared review/resolution services, with typed
  inputs, consistent validation/defaults/errors and durable lifecycle behavior.
- [ ] Configuration and session operations have shared owners; TUI behavior does
  not depend on importing the classic CLI or constructing through run_agent.py.
- [ ] One documented fresh-checkout bootstrap/check workflow installs hooks and
  runs the same pinned quality gates locally and in CI. Gates include Python
  linting/formatting, scoped type checks, TypeScript checks, import boundaries and
  generated-contract checks. Legacy exceptions are explicit and may only shrink.
- [ ] Hosting owns profile configuration, credentials, sessions, workers and
  shutdown independently of presentation. Local and headless serving use the same
  operations with version/capability negotiation and tested incompatibility errors.
- [ ] Backend/CLI, TUI and optional integration distributions have explicit
  dependencies, clean-environment installation tests and compatibility checks.
  A minimal backend install needs no Node/TUI dependencies or bundled UI assets.
- [ ] Full behavior/regression qualification and end-to-end product checks pass;
  ownership docs and TODO are reconciled with actual current evidence.

## Implementation order

1. Extract the complete review/resolution workflow into `forecasting/application`;
   keep terminal output and argument parsing in product adapters, and consume the
   shared operations directly from structured TUI RPC.
2. Move configuration/session/agent construction ownership out of entrypoints and
   bind hosting to explicit shared services. Tighten import contracts as consumers
   migrate; compatibility facades must not own behavior.
3. Establish one quality command and bootstrap, reuse it from hooks and CI, and
   verify failure behavior. Enable useful lint/type/format coverage incrementally
   without silently treating tool failures as successful reports.
4. Version the host/client boundary and negotiate required capabilities for local
   and remote transports. Exercise isolation, reconnect and shutdown.
5. Separate distribution profiles and prove installation/use outside the checkout.

The monorepo is retained. Directory moves follow ownership changes. Existing
forecast settlement/scoring safety, ledger provenance, profile compatibility and
TUI-first presentation remain required throughout. Live forecasting, release
publication and historical SSL attribution are separate workstreams.

## Progress

Baseline: `c3c352325`. Existing six import contracts include legacy exceptions;
Ruff enforces only encoding; tracked hooks are not installed in this checkout.
No work in this plan is marked complete until its acceptance evidence exists.

First extraction in progress:

- `forecasting/application/reviews.py` owns selection and learned-error merging;
  the CLI calls it and retains only presentation.
- `forecasting/application/resolution.py` owns typed request admission and
  resolution/score/optional retrospective orchestration; the ledger remains the
  authority for settlement semantics, writes and durable finalization.
- Direct `forecast.review` / `forecast.resolve` RPCs return structured results
  without calling the classic CLI or redirecting process-wide stdout. The actual
  Ink command routing still needs migration to these endpoints.
- Cross-interface testing exposed binary retry identity differences (`"true"`
  versus `true`). The ledger now compares their meaning without rewriting the
  original stored outcome/provenance.
- Seven import contracts pass. Broader Ruff rules, formatting and ty pass on the
  application package. Those extra checks still need wiring into unified gates.
- Existing tracked hooks are installed (`core.hooksPath=.githooks`).
- Verification: 257 existing review/CLI tests passed after the first extraction;
  15 application/settlement/lifecycle tests passed after the retry fix. Full
  qualification is pending further integration, not claimed by these checks.

Hygiene audit finding: `ui-tui/eslint.config.mjs` defines five custom rules as
no-ops. Determine their intended enforcement and replace or remove misleading
rule declarations as part of the gate work; do not describe them as protection.

Shared quality workflow (`d5469e48c`):

- `python3 scripts/dev.py bootstrap` completed with exit 0 in a fresh local clone
  at `/tmp/forecast-product-bootstrap-20260911`, using its own `.venv` and
  `ui-tui/node_modules`. It built Ink, installed hooks, and passed all quality
  commands. The verification clone is clean afterward.
- Pre-commit/pre-push and `.github/workflows/product-quality.yml` call the same
  implementation. CI execution and native Windows bootstrap remain to verify.
- Missing-tool and failed-linter subprocess regressions pass; the pipeline fails
  closed. Six tests passed across those checks and application RPC parity.
- Injecting `import forecasting.cli` into the actual application package in the
  verification clone made the new import contract fail. The probe was restored.
- TUI lint passes after six existing gateway-client formatting findings were
  fixed. Five unused no-op custom rule declarations were removed; they were not
  active protections and should not have been advertised as such.

Still outstanding: actual Ink command migration, shared config/session and agent
construction ownership, fuller dependency-boundary cleanup, host/capability
negotiation, minimal independent package profiles, and full final qualification.
The two implementation commits are local pending the required full-suite push
qualification; this does not mark any of the five deliverables complete.


Ink workflow migration:

- `/review`, `/resolve` and their `/forecast` forms now call `forecast.operation`.
  Shared argument definitions and output formatting live in
  `forecasting/interfaces/commands.py`; business behavior remains in application
  services. These paths do not invoke the classic CLI or redirect stdout.
- The application request rejects negative review windows, including structured
  RPC callers that bypass argparse. CLI/RPC resolution retries preserve identity.
- A compiled Ink test runs review, resolution, scoring and retry through the real
  dashboard WebSocket, PTY and gateway against an isolated ledger. It passes; the
  test explicitly dismisses result pagers before submitting the next command.
- Verification: 264 focused Python tests passed; all 87 slash-handler tests
  passed; eight application/admission/config-owner tests passed; the real-desk
  workflow passed. The shared quality command passed, including TypeScript types,
  lint, generated contracts, Python scoped checks and import boundaries.
- MCP reload persistence uses the gateway's atomic profile writer directly,
  preserving unrelated settings and avoiding the classic CLI import.

Shared configuration/session and agent construction ownership, full hosting and
capability negotiation, distribution separation and broad qualification remain
open. The personality lookup still imports classic CLI configuration; its loader
also bridges environment settings, so removing that edge requires preserving
configuration semantics rather than merely changing the import target.


Runtime ownership migration:

- `agent/runtime.py` now owns `AIAgent`; `run_agent.py` is a compatibility
  executable and module alias. CLI, TUI, gateway, tools, forecasting workers,
  cron and ACP import the library owner. Legacy patches address the same module
  state. Repository-relative environment loading retains its original root.
- Removed every exception from the forbidden entrypoint-import contract and
  extended coverage to cron/ACP. Added a direct classic-CLI import prohibition
  for the TUI host. The isolated slash worker remains a legacy adapter.
- Separated read-only interactive configuration from explicit environment
  bridging. Personality lookup uses shared defaults and profile precedence
  without importing CLI or changing terminal/provider environment settings.
- Verification: 3,529 runtime/agent/bootstrap/provider tests passed, six skipped;
  41 configuration and provider tests passed. Python quality and all eight import
  contracts pass. Broader final qualification and push remain pending.

This removes specific ownership inversions, not all presentation/runtime coupling.
Agent library initialization still loads process environment and the historical
standalone diagnostic main remains exported by the runtime. Explicit host startup,
shared session ownership, remaining slash dispatch, protocol negotiation and
independent distributions still need implementation/qualification.

Gateway qualification after the runtime move: 184 tests passed, including all
local real-desk lifecycle cases and legacy/factory shared-state compatibility.
The six warnings report Python forkpty use from the dashboard test host.


Host compatibility admission:

- Shared descriptors advertise the supported wire-version range and actual RPC
  operations across stdio, WebSocket and HTTP. `host.negotiate` validates required
  capabilities and rejects malformed inputs or incompatible versions without
  opening a session, ledger or provider connection.
- Ink checks the descriptor before delivering gateway.ready to session bootstrap.
  Missing required methods or unsupported versions terminate that connection with
  an actionable reason. Explicit restart can admit a newly compatible backend.
- Verification: 102 Python protocol/real HTTP tests passed, 39 client/recovery
  tests passed, six compiled-desk lifecycle tests passed. Shared quality checks
  pass. Remote negotiation uses the existing authenticated HTTP endpoint.
- This is an operation compatibility contract, not a provider-health claim.
  Existing legacy clients can continue calling their supported RPCs directly.

Explicit host resource ownership, remaining shared session/command services and
independent distribution/install qualification remain required. These acceptance
items are not closed by implementing the host compatibility contract.


Independent distribution implementation:

- The backend wheel excludes TUI/web package data and namespace discovery.
  Building from an sdist avoids contamination from stale checkout build trees;
  artifact checks caught old compatibility UI files in the first direct build.
- `products/tui` owns a separate terminal wheel with its compiled Ink bundle and
  a small launcher. It has no backend dependencies. The backend launcher discovers
  that companion in installed environments; source checkout and explicit bundle
  overrides retain their existing behavior.
- Build and clean-environment verification commands are documented in
  `products/README.md` and wired into the product-quality workflow. New product
  and verification code participates in strict lint, formatting and type gates.
- Verified locally on Python 3.13: backend create/update/resolve/score with Node
  absent from PATH; terminal-only remote prerequisites; combined companion
  discovery. Thirty-four launcher/workflow regression tests passed.

Not complete: cross-platform execution of these new profile checks, actual
installed-terminal transport/lifecycle qualification, legacy release/installer
wiring, and final full-suite qualification. Shared host/session ownership and
remaining command migration also remain open.

Additional distribution evidence: the backend-only build succeeded with only uv
on PATH (no Node/npm). Optional web dependencies passed `uv pip check`, and the
installed HTTP host constructed and released its local socket successfully.


Shared session selection:

- Moved resumable-session policy into `superforecasting_agent.application` and
  routed Ink list/auto-resume, classic CLI history and CLI list/browse through it.
  Human-facing sources are accepted across interfaces; explicit source filters
  still allow administrative access to internal sessions.
- Fixed fixed-window lookup: a user conversation behind more than 200 internal
  sessions is still discoverable, and filtering the active conversation does not
  consume the requested result limit. Limits are validated before storage access.
- Verification: 332 focused session/gateway/CLI tests passed, then 99 adapter
  tests passed after CLI error handling was aligned. New application code is
  included in strict lint/format/type gates and an enforced import boundary.
- This is selection ownership, not complete host/session ownership. Session
  construction/finalization, worker draining, database lifetime and legacy
  command adapters still need consolidation. Most-recent RPC's legacy error-to-
  empty-result behavior also remains a recovery transparency follow-up.


Recovery transparency follow-up:

- `session.most_recent` returns an error for storage failure; only a successful
  empty query returns a null session ID. Startup config/history failures no longer
  create replacement sessions automatically. The terminal gives explicit retry
  (`/resume`) and new-session (`/new`) actions.
- Compiled testing exposed a second layer of ambiguity: the common TUI RPC
  wrapper converts exceptions into null responses. Startup now validates those
  responses separately from a valid empty-history result. Unit cases cover both
  rejection and null, and late responses from older startup generations are ignored.
- Serialized lazy database construction so concurrent RPC startup cannot open
  multiple session-store handles. Six concurrent callers share one handle in the
  regression test. Complete database lifetime/drain ownership remains separate.
- Verification: 227 backend/concurrency tests, 64 UI event tests, and all seven
  compiled-desk lifecycle tests passed. The injected database-unavailable case
  proves a visible failure and zero replacement session rows. Shared quality gates
  pass. The original compiled test failed before the null-response fix.

Full host resource/lifecycle ownership, remaining application command migration,
installed-product/cross-platform qualification and release assembly integration
remain open; these recovery fixes do not complete the overall architecture goal.

Agent resource ownership follow-up:

- The shared agent lifecycle now serializes client eviction and full shutdown
  with a per-agent reentrant lock. Full teardown claims ownership once before
  invoking callbacks; repeated close cannot clean a replacement agent's resources
  merely because it reuses the durable session ID.
- New regressions failed before the fix: repeated close removed a replacement
  terminal environment, and concurrent close invoked task cleanup twice. Tests
  also cover eviction overlapping shutdown and a reentrant cleanup callback.
- Verification: 18 resource ownership, zombie cleanup and OpenAI client lifecycle
  tests passed; the shared Python quality gate passed. These checks establish
  teardown idempotence, not host-wide draining or session handover safety before
  the first close. Those broader runtime responsibilities remain open.

Abandoned startup ownership:

- Lazy agent construction now disposes a completed agent if its session was
  closed during construction, skips worker allocation when already detached,
  stops any orphan notification poller, and releases waiters with an explicit
  initialization error. Previously orphan cleanup covered the slash subprocess
  and approval registration but left the constructed agent's clients open.
- The deterministic close-during-build regression waits for agent disposal and
  verifies that initialization waiters receive the closed-session error. This
  is startup cleanup; active-turn draining and complete host ownership remain open.

Commit-content hygiene:

- Shared snapshot admission checks require in-place quality tools to inspect
  the staged tree for commits and each submitted tree for pushes. Unstaged or
  untracked non-ignored files fail closed; ignored toolchains remain supported.
  Hooks repeat admission after checks and never stash or rewrite user changes.
- Pre-push no longer ignores all refs after the first: every submitted tree is
  admitted, and every remote baseline participates in changed-domain checks.
- Six workflow tests pass, including real Git fixtures for a staged bug hidden
  by an unstaged fix, a different pushed tree, untracked import shadowing, and
  actual pre-push rejection of a mismatching second ref before quality execution.
- This intentionally requires matching in-place contents; automatic isolated
  snapshot validation is not claimed. CONTRIBUTING documents the partial-staging
  constraint. Shared Python quality and shell syntax checks pass.

Shared scoring operation:

- Added a typed scoring use case owning current-score and optional baseline
  orchestration. Ledger settlement semantics and score lineage remain unchanged.
  Classic CLI and Ink `/score` / `/forecast score` now share argument definitions,
  formatting and application execution through `forecast.operation`.
- Tests cover invalid structured booleans before writes, matching CLI/RPC output,
  baseline opt-in versus absence, preserved score identity, no presentation import,
  and real compiled Ink resolution followed by scoring against durable storage.
- Verification: 265 application/CLI tests and 89 slash-handler tests passed;
  shared Python/TypeScript quality gates and the Ink build passed. Six existing
  desk cases passed in the initial integration run; the extended scoring case
  timed out at the default viewport, then passed at an explicit 160x45 viewport
  while observing the final baseline output. Full-suite qualification remains open.

Installed terminal qualification and output ownership:

- Extended the product-wheel verifier to launch the terminal-only installation
  against a separately installed backend outside the checkout, wait for the
  credential-free startup state, display a durable score with baseline status,
  close the viewer and exit cleanly. The fixture drains PTY output during exit
  and allows the viewer-close redraw to release keyboard focus before `/quit`.
- The new test exposed a real presentation failure: tracing the installed host
  proved that scoring returned a valid result, but its composer-relative floating
  viewer did not visibly paint over the setup screen. Output paging now belongs
  to the viewport and uses the existing explicitly bounded modal primitive.
  Navigation and rendering share wrapping widths and the adjusted page height.
- Fresh clean-environment verification passed for the backend without Node,
  separate terminal/backend execution, companion discovery and optional web host.
  Seven real desk cases passed; 97 existing slash/completion/pager tests passed,
  followed by six focused paging/render tests covering 80x24 and 160x45 and the
  final page of long reports. Shared quality gates pass.
- Native Windows PTY execution remains explicitly skipped by this verifier;
  remote-network lifecycle qualification, release/installer assembly and full
  regression qualification remain open. No live model/provider was needed.

Headless transport ownership:

- Default event-sink registration now has one shared owner. Registrations can
  detach in any order, retaining every surviving tee/replacement sink and the
  original fallback. Stale cleanup cannot overwrite an externally replaced sink.
- HTTP hosts bind their socket before publishing the sink. `server_close()`
  releases their registration and event hub automatically; the legacy explicit
  restore call remains idempotent. Closing a host does not close its predecessor.
- Focused HTTP/event-log/ownership verification passed 45 tests. Additional
  concurrent registration coverage verifies that all eight live sinks receive
  an event and concurrent detach restores the baseline without closing it.
- This centralizes event-sink lifetime, not all runtime resources. Session-store
  lifetime, active-turn draining, agent/session construction ownership and the
  remaining presentation adapters still require consolidation.

Full `tests/tui_gateway/` qualification after that change: 183 tests passed,
including concurrent transport registration. Shared Python quality gates pass.

WebSocket send ownership:

- Each connection tracks its loop-owned sends, serializes writes, rejects new
  work after close, and cancels/drains active and queued sends during async close.
  Worker timeouts cancel their scheduled future instead of leaving a send alive.
- The handshake now lives inside the same cleanup boundary as request handling;
  failed or cancelled greetings close the socket without entering the receive loop.
  Async write/drain calls explicitly reject use from a different event loop.
- All 189 gateway tests passed. New cases cover close before a queued send runs,
  cancellation of an active send and its queued successor, worker timeout,
  failed/cancelled handshakes, repeated cleanup and wrong-loop admission.
  Shared Python quality gates pass. This does not establish remote installed-TUI
  lifecycle behavior; that remains a separate distribution verification item.

Frozen-commit regression qualification (`386f83ced`):

- Full Python runner completed: 30,456 passed, 60 failed, 148 skipped. The
  complete Ink suite passed 2,039 tests, with one skipped. These are scoped
  results, not a successful full Python qualification.
- Most Python failures replaced the old `run_agent` module and therefore missed
  construction through `agent.runtime`. Updated those fake-runtime boundaries;
  no production entrypoint dependency was restored. ACP/cron/gateway behavior
  assertions remain intact.
- Updated distribution ownership assertions for the independent terminal wheel,
  checked runtime guidance at its library owner, and replaced obsolete session
  over-fetch assertions with returned-limit/order checks across multiple pages.
  Interactive config tests now explicitly cover CLI and gateway process contexts;
  importing the messaging gateway sets a process marker and exposed test-order
  dependence in the prior fixture.
- All affected test files passed together: 340 passed, one skipped. A fresh full
  Python qualification is still required after the remaining architecture work.
- Read-only strict import audit: protocol and session application contracts pass
  with indirect imports forbidden. Forecast application operations still reach
  presentation through research model lookup, scheduled/reforecast runner
  construction, ledger distribution rendering and runtime setup dependencies.
  These paths need owner corrections rather than additional ignore lists.

Indirect boundary enforcement:

- Protocol and session application contracts now reject indirect forbidden
  imports. Two isolated package fixtures load the actual shipped contract
  definitions, pass with an allowed intermediate module, then insert that
  module's CLI dependency and verify a nonzero lint command exit with the exact
  transitive path. No production files are modified by these probes.
- Research adequacy and nightly forecast model lookup use the existing shared
  resolver directly instead of importing the CLI alias. Regression checks block
  presentation imports and verify configured model identity reaches both runners
  for bare-string, current mapping and legacy mapping configuration.
- The 36 existing research/nightly tests and three new model-lookup cases pass;
  both negative import probes pass. Shared Python quality and all nine contracts
  pass. The other seven contracts still permit indirect imports; the strict
  forecast application audit is not claimed complete.

Shared forecast production workflow:

- `forecasting.application.pipeline` now owns stage ordering, per-stage outcome
  tracking, bounded research adequacy retries and final ledger-derived status.
  The CLI retains compatibility adapters, while detached reforecast jobs (used
  by the desk's batch action) and the `full_forecast` tool call the service
  directly. They no longer import CLI orchestration.
- `agent.forecast_stage` owns execution through the common agent factory, stage
  toolsets and the existing research retry setting. Each stage closes its agent
  after success, provider failure or interruption. Cleanup failures are logged
  without overwriting the returned result or original exception.
- Existing explicit commit/proposal policies, protocol prompts, ledger gates,
  retry no-progress behavior, stage callbacks and durable result derivation are
  retained. CLI private runner injection remains supported by its adapter.
- Ninety focused tests passed, including CLI/tool production, desk job RPC and
  execution, proposal-only/material-update behavior, research audit bounds,
  interruption and cleanup failure. The new execution adapter is included in
  the blocking Ruff/format/type scope. Shared Python quality and all ten import
  contracts pass; an added contract prohibits direct CLI imports from these
  execution consumers.
- Scheduled warning-runner construction still resides in the CLI. The ledger's
  dashboard-helper dependency and indirect runtime/presentation paths remain
  open, as do full runtime hosting and remote installed-terminal qualification.

Shared warning execution:

- `forecasting.application.warning_runners` owns bounded candidate execution,
  prerequisite bootstrap, material/marginal/proposal result classification,
  scheduled runner construction and explicit operator runner composition. CLI
  functions now adapt options and preserve existing private execution injection.
  The scheduled entrypoint imports the application owner directly.
- The runtime adapter owns triage-runner construction. Warning operations retain
  the existing durable evidence-row and postmortem/autopilot acknowledgment gates.
  Invalid iteration/count limits, non-boolean force and unsupported cycle commit
  policies fail before storage access or model execution.
- Fixed an uncovered scheduled-policy inconsistency: reforecast work already
  requested `proposal_only`, but scheduled evidence research had omitted the
  policy. Both scheduled paths now pass it to the shared stage agent. Explicit
  operator research retains its existing policy behavior.
- Sixty-three tests passed across cycle/commit policy, scheduled/operator warnings,
  evidence collection and material-change drains. New cases verify a pending
  proposal with unchanged current snapshot, acknowledgment only after new evidence,
  rejection of success-without-new-evidence, and malformed option admission.
  Shared Python quality passes; all ten import contracts pass, with the execution
  contract extended to prohibit scheduled entrypoint imports of CLI orchestration.
- Full forecast-service transitive isolation is still incomplete: ledger
  distribution interpretation still reaches dashboard helpers, and indirect
  runtime startup/setup dependencies remain to extract.

Distribution interpretation ownership:

- `forecasting.distribution_summary` now owns the pure moment/quantile/PMF
  interpreter previously hosted in the dashboard. Ledger thesis/factor math,
  distribution assessment and explicit recentering import it directly. Headline
  formatting stays in the dashboard with compatibility aliases for old callers.
  A missing core interpreter no longer silently disables distribution checks.
- The forecast package lazily exposes its public ledger/model classes. Importing
  a pure submodule no longer initializes the whole ledger graph; type-checking
  imports and runtime class identities remain compatible. A fresh subprocess
  blocks storage/models/presentation/agent imports and successfully evaluates
  a distribution summary.
- Finite-number admission now rejects integers too large for a float instead of
  raising OverflowError. Headline numeric conversion uses that same admission.
  Existing explicit intervals, quantile and normal-equivalent calculations are
  preserved; descriptive summaries do not replace authoritative scoring or
  explicit tail probabilities.
- 222 interpretation/ledger/thesis/factor/dashboard tests passed; 12 ownership
  and negative-import probes passed; 32 censoring and ownership tests passed.
  The new interpreter and lazy public facade are in the blocking lint/format/type
  scope. All twelve import contracts pass, including strict transitive isolation
  for the interpreter and direct dashboard exclusion for ledger/distribution
  checks. Broader indirect application/runtime dependencies remain open.

Full qualification and hook isolation:

- At frozen source commit `6cc777605`, the full Python runner passed 30,546 tests
  with 148 skipped and 58 warnings. JUnit:
  `.test-results/pytest-20260911T192733Z-99681.xml`. No excluded integration suite
  or native Windows PTY claim is implied by that run.
- A fresh backend wheel built from that commit passed the independent profile
  verifier alongside the unchanged terminal wheel: backend create/update/resolve/
  score without Node, actual installed terminal negotiation/scoring/exit, companion
  discovery and optional web-host construction. Logs and wheels are retained at
  `/tmp/forecast-profiles-6cc777605*`; remote-network lifecycle remains open.
- The first push was rejected by its Python hook subset (9 failures, 4 collection
  errors). The target mapper explicitly passed a standalone local-gateway fixture
  to pytest. Importing it modified sockets and gateway handlers before failing on
  its required subprocess environment, contaminating later tests. The ordinary
  full runner had correctly never collected that non-test executable.
- Hook selection now maps runtime fixture changes to the real lifecycle tests;
  general test helpers use normal directory discovery. The gateway fixture's
  modifications and execution are guarded by `main`, so accidental imports cannot
  mutate the host. Regression tests exercise both actual Git target selection and
  fixture import isolation. Two doctor mocks now address the imported plugin class
  directly instead of relying on cached parent-package attributes.
- The affected subset, including explicit fixture collection and all local real
  desk cases, passed 309 tests. Shared Python quality and shell syntax pass. The
  first push's 558 changed-TUI tests also passed; the rejected push did not update
  the remote branch. Push qualification must be retried with the corrected hook.

Shared delegation configuration and gateway persistence:

- Verified remote branch `codex/learning-settlement-runtime` at `571414d23` after
  the corrected hooks passed 19,435 Python tests (74 skipped) and 558 TUI tests.
- Delegation reads detached current settings from the runtime configuration owner
  instead of importing cached classic-CLI settings. Interactive defaults now copy
  the canonical delegation defaults; explicitly configured limits remain intact.
- Gateway confirmation preferences use the existing profile-aware atomic updater
  directly. Failed persistence no longer produces a success note claiming that
  subsequent confirmations are disabled; the currently authorized action still runs.
- 160 focused delegation/configuration/confirmation tests passed, including real
  profile writes preserving unrelated settings and injected failures for both
  destructive-command and MCP-reload preferences. Shared Python quality and all
  twelve import contracts pass; delegation now joins the no-CLI consumer contract.
- Complete runtime hosting, transitive application isolation, broader command
  migration and remote installed-product qualification remain open.

Noninteractive runtime identity and subscription ownership:

- Moved the Tool Gateway offer, labels and prompting into the existing OAuth
  setup owner. Subscription eligibility and settings application remain available
  without importing the interactive setup module. Selection defaults, opt-in
  scope, persistence and cancellation behavior are retained.
- Moved active-profile identity lookup into the existing dependency-free home/path
  owner. Agent construction, TUI, gateway, CLI and plugin readers use that owner;
  profile management retains its compatibility export and administrative operations.
  Reading a profile name no longer imports service-management code.
- 429 focused profile, subscription, OAuth, API and plugin tests passed (four
  skipped). Thirteen focused ownership tests passed, including a fresh process
  rejecting runtime/presentation imports during identity lookup and actual import
  checker rejection of an injected indirect presentation dependency.
- Shared Python quality passes with fourteen contracts. Profile identity has a
  strict transitive boundary; subscription eligibility currently has a direct
  setup exclusion. Complete transitive forecast-service isolation and independent
  host/session lifetime ownership remain open.

Shared benchmark execution:

- Offline readiness benchmark execution and probability-source transformation now
  belong to `forecasting.application.benchmarks`. CLI adapters retain their public
  call signatures, command errors and progress output; the forecasting tool calls
  the application service directly instead of importing CLI orchestration.
- The service rejects non-offline sources before dataset access or writes. Unknown
  transformation sources no longer silently fall through to baseline-ensemble.
  Agent protocol failures retain per-case skipping and optional progress reporting;
  forecast-engine, baseline weighting and run provenance semantics are preserved.
- 264 CLI/application/readiness tests and 80 forecasting-tool tests passed. The
  first new import-isolation test unnecessarily ran the full corpus and hit its
  30-second timeout; it now persists one deterministic fixture. Existing full-corpus
  coverage remains and passed. Shared Python lint/format/types and all fourteen
  import contracts pass; diagnostic tools join the no-CLI execution contract.
- A fresh strict transitive audit confirms the benchmark-to-CLI edge is removed.
  Remaining paths include cron profile admission through administrative modules,
  session tool selection through interactive tools configuration, and diagnostic
  thesis summaries through dashboard code. These are incomplete boundaries, not
  additional allowed exceptions. Independent host lifecycle work remains open.

Shared profile admission:

- `superforecasting_agent.profile_paths` now owns profile normalization, validation,
  path selection and existing-profile admission. Cron jobs/scheduler and early CLI
  profile selection call it directly. Administrative commands retain compatibility
  exports and remain responsible for creation, deletion, cloning and service cleanup.
- Direct path selection now validates identifiers before constructing paths, closing
  the traversal/reserved-name bypass. Strict validation uses full matching and
  rejects a trailing newline; user-facing normalization still accepts surrounding
  whitespace and mixed-case display names before applying the shared validator.
- 145 profile/export/dashboard/cron tests, 383 cron tests, thirteen admission/import
  boundary tests and five isolated CLI startup tests passed. Shared Python quality
  passes; the new owner is in strict lint/format/type scope. Sixteen import contracts
  pass, including transitive administration exclusion for profile admission and a
  direct no-profile-administration contract for cron selection.
- The strict application audit no longer finds cron profile admission as a path to
  presentation. Session tool selection and diagnostic summary ownership still lead
  to presentation, and full independent runtime hosting remains unfinished.

Shared tool selection and combined configuration updates:

- `superforecasting_agent.tooling.selection` owns platform selection, configurable
  catalog metadata, plugin/default/MCP policy and tool-setting mutations. Runtime
  consumers, including the TUI, sessions, API and cron, no longer import the
  interactive configuration wizard for selection. The wizard retains prompting,
  installation and compatibility exports.
- Combined TUI and CLI tool/MCP updates now apply both changes before saving once.
  Previously toolset changes persisted before MCP mutation, allowing partial writes
  on failure. Shared mutation operations reject unknown actions instead of treating
  them as enable. Existing atomic configuration persistence remains authoritative.
- 679 selection/CLI/cron/API/gateway tests passed; ninety focused configuration and
  combined-write tests passed after the CLI single-save correction. Tests verify
  one save containing both changes, zero writes on MCP mutation failure, retained
  unrelated settings and no interactive configuration imports from the desk RPC.
- Shared Python quality passes with eighteen import contracts. Selection is in the
  blocking lint/format/type scope. A fresh strict audit finds no application paths
  to CLI, runtime main, command interfaces or TUI gateway; their application contract
  now rejects indirect imports, with an injected-edge regression proving enforcement.
  Six shipped strict-contract negative probes pass.
- Dashboard summaries and gateway dependencies still fail the broader transitive
  audit and retain their existing direct exclusions. Complete host/session lifetime
  ownership and remote installed-product qualification remain unfinished.

Shared aggregate summaries:

- Thesis/factor summary reads now belong to `forecasting.application.aggregate_summaries`.
  The real TUI RPC, CLI thesis report and forecasting tool consume that owner;
  dashboard exports remain compatible and workspace/chart rendering stays there.
  Existing summary fields, event headline precedence, sensitivities and withheld
  states are retained. Invalid summary limits fail before querying storage.
- 125 thesis/event/tool tests passed, followed by 251 application/factor/CLI/RPC
  and import-boundary tests. The new tool isolation fixture initially failed the
  ledger's scoreability admission; giving it explicit aggregate resolution criteria
  fixed the fixture without relaxing the validator.
- Shared Python quality and eighteen import contracts pass. The application
  contract now rejects indirect dashboard imports too. The broader strict audit
  finds only gateway dependencies: shared session context, platform registry,
  notification/status and scoped resource-lock helpers still have gateway owners.
  Those need ownership correction, alongside independent host lifetime and remote
  installed-product qualification; the overall architecture goal remains open.

Shared session context ownership:

- `superforecasting_agent.session_context` now owns task-local routing state for
  agents, tools, cron, ACP, gateway and TUI. Production readers/writers import it
  directly; the legacy gateway module aliases the same module object, preserving
  ContextVar identity, private reset seams and compatibility monkeypatches.
- Retained the explicit-clear behavior that suppresses stale environment fallback.
  Corrected guidance: executor calls require explicit context propagation, while
  `asyncio.to_thread` propagates context; clearing does not restore outer scopes.
- 213 routing/approval/tool tests and 365 shared-context/cron/TUI/import tests passed.
  New tests prove alias identity, pure import without gateway initialization and
  cancellation isolation between tasks and executor work. Test isolation resets
  the canonical owner rather than depending on an imported gateway facade.
- Shared Python quality and nineteen import contracts pass. The context module is
  in strict lint/format/type scope and has a transitive no-host/no-presentation
  contract. Remaining application-to-gateway edges involve platform registration,
  scoped locks/status and MCP progress callbacks; independent hosting remains open.

Shared platform registration:

- `superforecasting_agent.platform_registry` owns platform metadata, registration
  and deferred factory callbacks. Prompt/tool policy, plugin discovery, cron and
  gateway consumers import it directly; the legacy module aliases the same owner
  so registrations and overrides cannot split into separate singleton registries.
- 207 registry/plugin/tool-selection tests and 260 ownership/cron/messaging/import
  tests passed. A fresh-process probe blocks gateway imports and factory/check
  callbacks while registering, reading and removing metadata; compatibility tests
  verify shared class/module/singleton identity.
- Shared Python quality and twenty import contracts pass. Platform registration
  participates in strict lint/format/types and a transitive no-transport contract.
  The latest broader audit narrows remaining gateway dependencies to image caching,
  a secret-entry hint constant, and host-PID liveness checks. These are shared
  infrastructure concerns still awaiting extraction; host lifecycle remains open.

Complete transitive presentation exclusion for forecast application services:

- Shared PID liveness checks now live in `superforecasting_agent.processes`, used
  by process tracking, browser cleanup, MCP cleanup and gateway status. The Windows
  ctypes fallback now declares pointer-width arguments for wait/close calls as
  well as the OpenProcess return type; tests exercise a handle above 32 bits and
  verify exactly one close, no signal call and inaccessible/missing PID behavior.
- Local image bytes are cached by `superforecasting_agent.storage.media`, using
  the active profile on each call. Messaging retains its compatible cache wrapper;
  MCP no longer imports messaging dependencies or silently drops images solely
  because that package is unavailable. The remote secret-entry hint has a shared
  constant owner as well.
- 261 process/gateway/media tests passed (two skipped), followed by 23 native-call,
  MCP image, isolated-import and boundary tests. An old MCP test compared against
  a gateway cache path frozen under a previous test profile; it now checks the
  actual current profile path. Cross-profile caching is verified in a fresh process.
- The full application contract now rejects indirect imports of CLI, command
  interfaces, dashboard, TUI gateway, messaging gateway and runtime main. The
  broader audit passes without exclusions for those presentation packages.
  Shared quality passes with twenty contracts; process/media owners are included
  in strict lint/format/types. A full regression run is next before publishing
  this batch. Host resource lifetime, remote serving, release/installer assembly
  and cross-platform product qualification still require completion.

Regression qualification follow-up:

- The first full run at `3248b277c` completed with 30,608 passed, 148 skipped
  and five failures. All five referenced former owners in test mocks or source
  assertions: tool selection, session context and PID liveness. Production
  consumers already used their extracted owners.
- Updated those seams, including additional PID tests whose obsolete mocks had
  allowed false-positive passes. Retained the original behavioral assertions.
  The five affected test files now pass 436 tests with one skip. A new full run
  is still required before this batch can be pushed.
Host stream ownership (isolated follow-up):

- Importing the RPC server no longer redirects process-wide stdout. The stdio
  entrypoint reserves stdout for protocol frames only while it is serving the
  command pipe and restores the prior streams on return or failure. HTTP-only
  serving leaves the embedding process's streams unchanged; explicit HTTP/stdio
  tee mode retains protocol stream ownership.
- Thirty-four focused stream-ownership and HTTP host tests passed, including a
  fresh server import and injected entrypoint failures. Real installed-terminal
  qualification for this follow-up is still required. This change was developed
  in an isolated worktree while the prior frozen commit's full suite ran.

Headless WebSocket entrypoint (isolated follow-up):

- Added `superforecasting-agent-host` / `python -m superforecasting_agent.hosting`,
  using the existing WebSocket dispatcher and capability negotiation without the
  dashboard application. Authentication comes from a required token file; bearer
  headers take precedence over query tokens and browser origins require exact
  opt-in. Access logging is disabled to keep query credentials out of URL logs.
- Seventeen host/stdio tests passed, covering rejected credentials/origins before
  runtime admission, successful existing-protocol negotiation, incompatible
  versions, malformed JSON and stream ownership. Shared Python quality passes;
  new hosting code participates in strict lint/format/type gates.
- This is an independently invocable transport host, not complete host resource
  ownership. Active-worker draining, database lifetime, installed remote-terminal
  lifecycle tests and broader release wiring remain required.

Installed headless host qualification:

- Integrated the stdio ownership and authenticated headless WebSocket entrypoint
  into the main work branch. The backend-only wheel accepts protocol negotiation
  over a real localhost socket without importing the dashboard.
- The first installed probe exposed a credential leak: Uvicorn's WebSocket
  handshake records use its error logger even with HTTP access logging disabled.
  Host logging now redacts URL query strings while retaining paths and diagnostics.
  Both rejected authentication/origin requests and accepted requests are exercised.
- Added `scripts/verify_headless_host.py` to the independent distribution verifier
  and blocking Python lint/format/type scope. It runs the installed host outside
  the checkout, checks authorization and capabilities, and verifies credential-free
  logs plus completed shutdown. Uvicorn deliberately re-raises termination signals
  after orderly shutdown; the verifier requires the shutdown completion marker as
  well as an expected exit status. The native Windows signal branch remains
  unqualified; the installed probe passed on macOS.
- The candidate backend wheel built from `f507daf3e` passed the real installed
  probe after correcting that shutdown expectation. Seventeen focused host tests
  and shared Python quality with twenty import contracts pass. This is a host
  transport/install check, not proof of full remote Ink or session lifetime safety.

Explicit host worker lifetime:

- Added presentation-independent `hosting.workers.RuntimeWorkers`: lazy executor
  creation, tracked inline requests and dedicated background threads, closed
  admission, queued-call cancellation and bounded draining with idempotent retries.
  A strict transitive import contract and injected-edge test enforce its ownership.
- Stdio and headless WebSocket serving explicitly start/stop the runtime. Shutdown
  interrupts session agents and registered background agents, releases approvals,
  stops pollers/cron/auth work and drains admitted tasks before closing agents or
  the shared session database. A timeout retains resources and reports incomplete
  shutdown; it does not authorize closing handles still used by workers.
- Background prompt agents now close their own resources. After draining, unfinished
  turn receipts become interrupted without overwriting terminal receipts; session
  rows remain un-ended for resume, including a new host lifetime in the same process.
- 242 gateway/lazy-session/import tests passed; four focused worker tests pass,
  including real SQLite reopen after a final write during shutdown. Tests that
  launch full hosts now isolate their runtime ownership instead of leaving stopped
  global workers behind. The EOF deadline probe now reflects import-safe stdout.
  Shared Python quality passes with twenty-one import contracts.
- This does not complete host extraction: session/configuration state and close
  orchestration still reside in the RPC server. Explicit session-close races,
  complete ownership of external delegation/provider resources, installed remote
  Ink lifecycle verification and cross-platform qualification remain open.
- The backend-only wheel built from `f8a415a5d` also passed the installed localhost
  authentication, negotiation, query-redaction and graceful shutdown probe outside
  the checkout. Full regression and installed remote Ink qualification are pending.

Session close admission:

- `hosting.sessions` owns session-use leases and close admission independently of
  presentation. RPC execution and post-auth credential refresh hold a lease while
  using session resources. Close rejects active calls, model turns, agent builds
  and background jobs, and marks the session closing under the same lock before
  detaching it. Stale references cannot acquire new leases.
- Replacement admission checks active work before reserving the old session.
  Completed host drain has an explicit internal cleanup path; it does not rely
  on a possibly stale `running` display flag. Notification consumers refuse to
  start turns after close or host shutdown begins. Background-job ownership spans
  construction as well as the model call and cleanup.
- 248 gateway/lifecycle/import tests pass, including concurrent RPC-versus-close,
  busy build/background cases, exactly-once close and stale-reference admission.
  Shared Python quality passes with twenty-two import contracts; the session
  admission contract includes a deliberately forbidden indirect-import test.
- The TUI branch handoff remains two separate calls (create branch, close old
  session); it needs a coordinated shared operation and explicit failure handling.
  Further session/configuration host extraction, external-resource ownership and
  installed remote Ink qualification remain unfinished. Full regression is next
  for the accumulated batch before pushing.

Coordinated branch handoff and complete transcript copying (isolated follow-up):

- CLI, messaging and TUI now share `application.sessions.branch_session` and a
  single storage transaction for branch identity, title, full transcript/counters
  and optional parent ending. Failed message copies roll back instead of being
  silently skipped. Tool-call identities and provider reasoning metadata survive
  the TUI path, which previously copied only role and content.
- Ink uses the new `session.branch_replace` capability. The host reserves the old
  idle session, prepares its replacement, rolls back failed construction, and
  closes the old runtime before releasing the new one for use. Newer clients
  reject hosts missing this capability instead of assuming compatible semantics.
  Client failures preserve the visible session/transcript and surface the error.
- The isolated worktree now has its own frozen Python environment. Reusing the
  primary environment exposed editable-install leakage in a subprocess test.
  Fresh setup also exposed missing web dependencies for the newly added host
  checks: bootstrap now installs the web extra for contributors and CI. Minimal
  backend installs retain optional web dependencies. Reconciled the older setup
  guide and added session/host ownership entries to the architecture map.
- Verification: 258 CLI/TUI/lifecycle tests, 223 storage/gateway tests and eighteen
  client handoff/transport tests pass. The exact documented bootstrap command,
  including hooks and Python/TypeScript quality checks, passes in this isolated
  environment. Primary full regression continues separately on `4f1532e81`;
  these changes have not yet been included in that full run or pushed.

Integrated qualification follow-up:

- Full regression at `4f1532e81` finished with 30,628 passed, 148 skipped and
  twelve failures in the larger gateway-server test module. Thread doubles still
  rejected the new diagnostic name argument; the old close-race expectation
  required immediate disposal during agent construction. Updated the tests to
  verify retained ownership and successful retry. Test pollers/workers now have
  explicit owners rather than relying on private Thread target/argument inspection.
- The failure investigation also found a production accounting gap: thread
  construction could raise before the cleanup guard, leaking an active admission.
  Construction now falls inside the guard; an injected failure proves subsequent
  draining succeeds. The repaired gateway-server/ownership selection passes 230 tests.
- Integrated the committed branch-copy/handoff/bootstrap changes from the isolated
  worktree. Full regression must be rerun on this combined tree before pushing;
  neither earlier narrow passes nor the failed full run qualify this batch.
- Combined focused qualification after integration passes 688 lifecycle, storage,
  CLI and gateway tests. Branch rollback now asserts the specific SQLite integrity
  error caused by an invalid transcript row rather than accepting any exception.

Installed remote product consumption (isolated verifier follow-up):

- Built independent backend and terminal wheels from `d77522b25`. Their fresh
  installation checks pass: backend create/update/resolve/score with Node absent,
  terminal-only environment without the forecasting package, companion discovery,
  and actual installed Ink scoring against a separate local backend.
- Extended the existing installed-terminal PTY probe to accept a remote host URL,
  then wired it into the headless-host verifier. The same independently installed
  Ink wheel now negotiates authenticated WebSocket hosting, scores the durable
  forecast and exits cleanly. Host authorization/origin rejection, query-log
  redaction and completed shutdown checks pass afterward. No checkout application
  imports or live provider credentials are used by the installed products.
- Artifact SHA256: backend `07fca6fa782f58eb8537408a88af76b2ecc0057d88a3f04318410243e60177a8`;
  terminal `58f2943d24d74a7f16cdd570fabd23d95949c62f4f0ef0ae07ae955be5661b03`.
  Shared Python quality passes for the extended verifier. This establishes basic
  installed local/remote product operation on macOS, not interrupted model-stream
  recovery, native Windows/Android PTY support or publication of these artifacts.
- The primary full suite remains running on the frozen source commit; this
  verifier-only follow-up is isolated until that qualification completes.

Independent release artifact assembly (isolated follow-up):

- The local release builder delegates to `build_profiles.py`, which now retains
  its backend source archive and supports reuse of a prebuilt Ink bundle. The
  terminal is a separate wheel, not copied into the runtime package. Optional
  dashboard output is a separate archive usable via the existing web-dist setting.
- Local dry-run and production workflow assembly name, checksum, sign and upload
  the independent artifacts. The workflow uses the shared installed local/remote
  profile verifier before signing. No release or registry was published here.
- Twenty-eight release/manifest tests and six workflow-contract tests pass, plus
  shared Python quality. The dry-run test checks the terminal manifest/checksum
  entry and verifies that the backend contains no TUI/dashboard asset directories.
  A macOS Bash 3.2 empty-array expansion failure was fixed in the optional-artifact
  path; both the empty path and actual dashboard archive path now complete.
- An actual optional-dashboard dry-run completed. Every manifest hash and byte
  size matched its output artifact; the archive contains its index and workflow
  YAML parses. Installer selection/upgrade support for multiple wheels remains
  incomplete and must be finished before publishing this artifact layout.

POSIX companion installation follow-up:

- The standalone installer selects backend and terminal assets by manifest role,
  independent of GitHub asset ordering. Both selected wheels must pass checksum
  and manifest verification before pipx installation begins. Ambiguous asset and
  checksum entries fail closed. Historical single-wheel releases remain supported.
- `INSTALL_TUI=0` selects backend-only installation; the default injects the
  verified terminal companion into the backend pipx environment. The pip fallback
  submits both wheels in one install command. Manifest pins remain binding even
  when the historical missing-checksum override is explicitly selected.
- Controlled shell tests cover separate artifact bytes, reversed asset ordering,
  corrupt/missing/duplicate companions, manifest disagreement and backend-only
  selection. Windows companion installation and other upgrade entrypoints remain
  unfinished; this change does not qualify cross-platform distribution as complete.

Windows companion installer parity:

- PowerShell selects the backend and optional terminal by manifest role, verifies
  every selected artifact before installation, rejects duplicate assets/checksums,
  and installs the companion into the backend pipx environment. `-BackendOnly`
  supports the minimal profile; legacy single-wheel releases stay supported.
- Added a hermetic PowerShell verifier with ten scenarios, including actual
  installer control flow with a fake Python/pipx executable, independent wheel
  versions, reversed release ordering, backend-only selection and integrity
  failures. The release workflow runs it on native Windows before its existing
  published-artifact verification step.
- Ten scenarios passed locally under a temporary PowerShell 7.6.6 macOS ARM64
  runtime whose archive matched GitHub's published SHA256 digest. This proves
  script behavior, not native Windows installation or PowerShell 5.1 execution.
  The 33 focused Python release/installer tests and shared Python quality pass.
- VPS upgrade/installation scripts still select the first release wheel and need
  migration. Runtime release updating also needs review for companion ownership.

VPS upgrade artifact ownership:

- Added a verification-only staging mode to the standalone POSIX installer.
  `RELEASE_DOWNLOAD_DIR` must name a new directory; a wheel inventory is written
  only after selected artifacts pass verification and are copied successfully.
  This mode does not install pipx, install packages or stamp a user profile.
- `upgrade.sh` reuses that selection/verification owner with its already admitted
  manifest, preserving the migration guard and backup sequence and avoiding a
  second unpinned latest-release selection. It supports terminal injection,
  backend-only upgrades and an explicit local terminal companion. All supplied
  local checksums must pass before backend installation.
- The upgrade staging tree now transfers ownership to the forecast user before
  pipx runs as that user; the former root-only mktemp directory was inaccessible
  to a real unprivileged installation. The controlled tests use fake privilege
  commands, so they do not establish a real Linux permission/deployment exercise.
- Hetzner first-install and fresh-box scripts still require split-artifact
  migration; standalone provisioning cannot assume a checkout sibling exists.

Provisioning and fresh-box product wiring:

- Hetzner provisioning accepts a separately checksummed local terminal wheel and
  installs it only after all selected artifact checks succeed. Downloaded products
  reuse the standalone installer staging owner. Checkout runs use the sibling
  script; standalone runs checksum-verify the release installer before executing
  its staging mode. Older one-wheel releases retain a non-executing fallback when
  their installer lacks staging. Ambiguous release selections fail closed.
- The fresh-box verifier builds one current backend/terminal artifact set, checks
  both wheels, and passes both to provisioning. It no longer picks an arbitrary
  stale backend wheel from dist. Downloaded staging directories are handed to the
  installation user before pipx reads them.
- Updated the stale-build remedy to install the backend and inject the terminal;
  `pipx install dist/*.whl` is not valid for a multiple-product release.
- Docker is installed locally but its configured daemon is unavailable. The
  actual fresh-container/system/SSH exercise is therefore still unverified for
  the split distribution. Controlled installer tests do not replace that gate.

Host session-store ownership:

- `hosting.storage.SessionStore` now owns lazy session-database construction,
  serialized access to initialization/closure, and initialization diagnostics.
  The TUI RPC server delegates access and lifecycle rather than owning global
  `_db`, `_db_lock` and `_db_error` state. Both local and remote hosts use this owner.
- Closing stops future acquisition even if the underlying close fails. Failure
  retains the handle for an explicit retry; a new lifetime cannot start while
  the old connection remains owned. Successful close is idempotent. Only explicit
  host startup admits a new database after shutdown, preventing stale callers
  from silently opening orphan storage. Hosts still drain workers before close.
- 471 focused gateway/session tests pass, including actual SQLite shutdown and
  resumed durable state. Owner tests cover concurrent initialization, diagnostic
  recovery, close failure/retry and stale acquisition. Shared quality passes with
  twenty-three import contracts; the new storage-owner contract forbids indirect
  presentation imports and participates in the injected-edge regression test.
- Session registry, configuration and full resource-finalization orchestration
  still need extraction from the RPC server. This is storage-lifetime ownership,
  not a claim that complete hosting has become presentation-independent.

Host profile-configuration ownership:

- `hosting.configuration.ProfileConfiguration` owns raw host configuration
  snapshots, content-based caching and profile-aware revision admission. The RPC
  server delegates loading, saving and atomic key updates; its four configuration
  cache globals and runtime-config import for snapshot persistence are removed.
- The shared storage layer owns `ConfigSnapshot` metadata and the revision hash;
  runtime CLI configuration retains its compatibility alias to that same owner.
  Existing atomic YAML locking, comment-preserving updates, and CLI expansion/
  normalization semantics are preserved. No new parallel persistence mechanism
  is introduced.
- Tests prove detached snapshots, profile-switch isolation, cross-profile save
  rejection, content changes with unchanged size/timestamps, malformed-file
  diagnostics without overwrite, and independent owners preserving atomic edits.
  506 host/gateway/parity tests and 115 configuration/storage tests pass. Shared
  quality passes with twenty-four import contracts, including a negative test
  injecting an indirect presentation dependency into host configuration.
- Session registry/finalization, broader credential orchestration and remaining
  classic command adapters still need ownership work. This does not move CLI
  presentation or environment-expansion policy into the raw host snapshot layer.

Session finalization ownership and failed handoffs:

- `hosting.sessions.finalize_session` owns boundary finalization independently of
  transports, with explicit durable-end and notification adapters. The database
  end happens before optional memory/hooks and before finalization is marked
  complete. A failed durable write propagates and can be retried; successful
  finalization is idempotent. Shutdown still leaves durable sessions resumable.
- Explicit close retains registry membership and resource ownership on failure,
  resets close admission, and returns an actionable RPC error. An unavailable
  store cannot silently turn an explicit close into a successful durable end.
- The change exposed that resume previously swallowed failed prior-session
  cleanup. Resume and branch replacement now roll back their prepared runtime on
  prior-session finalization failure. Resume reserves its new runtime until the
  handoff succeeds, preventing notification turns during preparation.
- 478 gateway/session tests pass; 72 focused protocol/close/branch tests then pass
  with added durable-write failure cases for both handoff paths. Tests assert
  prior-session retention, released admission, absent replacement leaks, correct
  compressed-session identity, and exactly-once hooks after a successful retry.
  Optional memory/hook failures are logged; full external resource disposal and
  registry ownership remain separate unfinished host responsibilities.

Live session registry ownership (isolated follow-up):

- `hosting.registry.SessionRegistry` owns registration, the shared membership
  lock, stable enumeration snapshots and retirement. The RPC server delegates
  registration/retirement; failed finalization releases admission without
  detaching the session. Duplicate runtime registration cannot replace an owner.
  An import contract rejects indirect presentation dependencies.
- Collision testing exposed branch rollback's assumption that any matching
  runtime ID belonged to the failed construction. Rollback now checks durable
  identity before closing it, and resume rejects runtime-ID collisions before
  reserving the prior session. A real ledger test preserves an unrelated runtime
  and deletes only the failed branch record.
- The expanded selection exposed unclosed subprocess pipes. Allocation tracing
  located them in slash-worker construction during resume: protocol fixtures
  cleared session membership without shutdown, and production worker close did
  not close pipes or wait after forced kill. Fixtures now invoke host shutdown;
  pipe readers own their streams, and worker close serializes shutdown, reaps
  terminate/kill, joins readers and closes streams. Failed reader construction
  also disposes of the child.
- The 497-test host/protocol/import selection passes after those repairs. Two
  real-child tests prove forced-kill reaping, concurrent repeated close and reader
  construction failure cleanup. These isolated changes are not yet part of the
  primary full regression running on `66df97c89`; full qualification is pending.

Retryable resource disposal (isolated follow-up):

- Session retirement now includes resource disposal after durable finalization.
  The host retains the registry entry when notification unregister, agent close
  or slash-worker close fails. Successful steps are recorded by resource identity
  and are not repeated on retry; all independent resource steps are attempted.
- Once disposal starts, pending cleanup blocks session use and replacement.
  A failed durable write still permits ordinary use because disposal has not yet
  begun. Explicit close errors identify retryable cleanup instead of returning a
  false successful close for partially released resources.
- Shutdown attempts every session, reports incomplete cleanup without closing
  the shared database, and permits a subsequent cleanup retry. New startup remains
  blocked until prior registry/database ownership is fully relinquished.
- Focused failure-injection tests prove retained membership, no use after partial
  disposal, failed-step-only retries, and database lifetime across failed shutdown.
  The current AIAgent resource implementation still contains internally swallowed
  cleanup failures; this host layer can only retain failures propagated by owned
  resources. That lower-level ownership/diagnostic audit remains unfinished.

Installed qualification after registry/disposal integration:

- Built independent wheels from isolated commit `0e4a7033f`, whose tracked source
  matches primary `2794b8659`, into `/tmp/forecast-profiles-owned-host`. Backend
  SHA256: `83c89bbfc646eecb66f42fce9025708df7dcccbf11828980e82ef4d128c273d8`;
  terminal SHA256: `6d7f9dd272781c2170fe340046d96648b2b6358172bbf04091aa43a55b00e4f9`.
- Clean-environment verification passed: backend create/update/resolve/score with
  Node absent; independent terminal prerequisite checks; real installed Ink score
  and clean exit against local and authenticated remote hosts; incompatible/auth
  admission, credential-free host logs, dependency consistency and clean shutdown.
  Log: `/tmp/forecast-owned-host-installed.log`. These are local fixture outcomes,
  not provider-backed forecasts or a claim of native cross-platform qualification.
- The fresh-container exercise is now running after recovering a stale Colima
  disk attachment through Lima's disk-unlock command. The owning instance was
  confirmed stopped without a VM host process before recovery. No disk contents
  were deleted. Primary full regression continues independently.
- Lower-level agent cleanup audit: `agent/session_lifecycle.py` clears child
  references before best-effort closes and claims `_resources_closed` before
  callbacks; `agent/openai_clients.py` swallows SDK close failures. Blindly
  retrying task-ID cleanup could reclaim a replacement agent's resources. Further
  work must retain concrete owned handles/generations for retry and diagnostics,
  while preserving the existing repeated-close replacement-resource tests.

Split-product fresh-container deployment qualification:

- `scripts/test-fresh-box.sh` completed successfully against a fresh Ubuntu 24.04
  ARM64 container on the local Colima Linux VM. It built and checksum-verified
  separate backend/terminal wheels, installed them through real pipx provisioning,
  started the gateway/cron service, passed config doctor/version-stamp checks,
  and verified SSH shell/one-off escape hatches plus the default TUI landing.
- The terminal rendered its first screen, and the tmux desk survived an SSH link
  drop/reconnect. This reconnect check establishes the persistent terminal desk;
  it does not replace the separate durable turn-recovery/provider-failure tests.
- Log: `/tmp/forecast-split-fresh-box.log`; all stages completed with exit zero.
  Source was isolated commit `447c41ff2` (documentation-only successor to the
  source-qualified `0e4a7033f`). The harness removed its own disposable container.
  The VM remains running; unrelated auto-started containers were left untouched.
- This establishes fresh Linux container installation/provisioning of the split
  products. Native Windows/Android qualification, an actual split-package upgrade
  exercise, and longer installed remote provider-stream recovery remain open.

Deployment checks now fail closed:

- Removed warning-only success for a missing scheduler banner, an unknown TUI
  frame, and a blank terminal pane in `scripts/test-fresh-box.sh`.
- Re-ran the complete Ubuntu 24.04 split-product exercise with those hard gates:
  every stage passed, including the recognized 927-character first frame and
  desk survival across SSH link loss. Log: `/tmp/forecast-strict-fresh-box.log`.
- Primary `2794b8659` completed full Python regression: 30,687 passed, 148 skipped,
  58 warnings. JUnit: `.test-results/pytest-20260911T215817Z-92992.xml`.
  These results do not establish native Windows coverage or a version upgrade.

Live credential application boundary:

- `hosting/credentials.py` owns applying a fresh credential generation to the
  matching live agent. RPC retains session admission, failed-build retry,
  presentation-worker restart and event delivery; it delegates the credential
  operation to the host. Provider resolution/storage are supplied dependencies.
- The shared operation passes the selected model into provider resolution,
  rejects unrelated provider sign-ins before resolution, and updates the recovery
  pool only after the client switch succeeds. Resolution/switch failures remain
  observable to the adapter, which reports whether credentials were applied.
- Added a transitive import contract and forbidden-edge regression. Quality gates
  pass with 26 contracts. Gateway/auth/boundary selection passed 499 tests,
  including current-provider aliases and failed-resolution/client-switch cases.
  Log: `/tmp/forecast-credentials-gateway-tests.log`.
- This does not complete credential orchestration: device-flow lifetime and
  failed-build retry are still RPC-owned; remaining command adapters and agent
  tool-resource cleanup need further ownership work.

Runtime composition and serving lifetime:

- `hosting/runtime.py::RuntimeHost` now composes workers, live sessions, session
  storage and profile configuration. It owns serialized start/shutdown, agent
  interruption, worker drain, session-disposal ordering and final database close.
  RPC consumers use that owner instead of independent module-global resources.
- A failed service stop or prompt release retains shutdown state even when no
  session/database is open; restart is denied until shutdown completes. Repeated
  successful shutdown does not run disposal callbacks again. Callback-driven
  cleanup cannot close the store while live registry entries remain.
- Removed the unused `_shutdown_sessions` alternate implementation. Its durable
  restart regression now drives actual host shutdown and reads the transcript
  through a newly opened database, rather than testing an inactive code path.
- Direct owner tests cover failed service stop, prompt release, retained session
  membership and failed restart. The gateway/application/bootstrap selection
  passed 610 tests (`/tmp/forecast-runtime-owner-qualified-tests.log`). All 27
  import contracts pass, including the host lifecycle's transitive boundary.
- The real Ink/dashboard/provider/SQLite lifecycle selection passed all seven
  cases (`/tmp/forecast-runtime-owner-real-desk-fixed.log`): cancellation, gateway
  death, provider failure/disconnect/quota, unavailable history and shared forecast
  operations. This is local provider-fixture evidence, not native Windows proof.
- Fresh contributor bootstrap had omitted the existing `pty` extra. The same
  bootstrap command now installs it alongside dev/web extras and passed through
  TUI build, lint, type and Python quality checks. Transport tests now report
  text startup errors directly instead of obscuring them with a missing-byte key.
- Remaining boundaries include device-auth workflow state, legacy command worker
  behavior, and concrete tool-resource ownership for safely retryable agent cleanup.

Installed runtime composition qualification:

- Built from isolated `9b6e98c8a` (source-equivalent to primary `374dd2d49`), then
  verified in clean environments outside the checkout. Backend wheel SHA256:
  `79f3d334e7b96b3e14ed80258c7ff15cd29e6942ac2a564620268bd4305470ed`;
  terminal: `03c9d82691c80a95a0e64f3adce24b5676aae8e440861244d857d4256b17e7b2`.
- Backend lifecycle without Node, independent terminal installation, real Ink
  scoring against separate local and authenticated remote hosts, compatibility
  admission, clean termination and credential-free logs passed.
  Log: `/tmp/forecast-runtime-owner-installed.log`. This qualifies the runtime
  composition changes before the following device-auth change.

Device sign-in ownership and stale-result protection:

- `hosting/device_auth.py::DeviceSignIn` owns attempts independently of RPC and
  provider storage. New attempts cancel previous ones. The same lock serializes
  replacement/cancellation with the final credential save; an obsolete exchange
  cannot persist tokens or overwrite the current attempt's status.
- Terminal status is consumed atomically, so concurrent polls cannot apply one
  success twice. Cancellation wakes long poll intervals immediately. Results that
  arrive after the deadline fail without being saved. Host shutdown cancels the
  attempt before draining its owned worker; restart creates a fresh auth owner.
- RPC still selects the supported provider and supplies its network/token-storage
  adapters. It reports cancellation directly in the cancelling poll response;
  subsequent polls return none, preserving once-only terminal consumption.
- Gateway/auth/boundary selection: 514 passed. Final focused owner/auth selection,
  including host shutdown/restart: 22 passed. Logs:
  `/tmp/forecast-device-auth-qualified-tests.log` and
  `/tmp/forecast-auth-owner-final-tests.log`. All 28 import contracts pass.
- Remaining application boundaries include failed-agent-build retry and legacy
  command behavior. Lower-level agent tool-resource retry ownership, cross-version
  product upgrades and broader platform qualification remain open.

Shared command catalog and compatibility boundaries:

- Command definitions, category ordering, subcommands, alias lookup and configured
  alias expansion now belong to `application/command_catalog/`. Workflow commands
  and operator-support commands have separate definition modules; each module is
  below 400 lines. Classic completion/menu adapters retain compatibility exports.
- TUI catalog and command resolution import the shared owner directly. Classic CLI
  and messaging alias expansion use the same operation. The catalog can import
  and resolve commands without loading runtime adapters, prompt-toolkit, Rich,
  CLI, TUI or messaging presentation.
- Serialized command metadata, ordering, descriptions and subcommands matched the
  pre-extraction snapshot exactly. Existing registry objects and public resolver
  exports retain shared identity across the compatibility module.
- Catalog, alias, gateway and boundary tests: 395 passed, log
  `/tmp/forecast-command-catalog-final-tests.log`. Shared quality checks pass with
  29 import contracts. Contributor guidance and the ownership map name the new
  definition owners.
- This extracts definition/resolution ownership; the legacy slash worker still
  constructs the classic CLI for commands not yet migrated. Shared command
  execution and failed-agent-build recovery remain unfinished.
- Primary runtime composition batch `374dd2d49` completed full regression with
  30,701 passed, 148 skipped and 58 warnings, then pushed successfully. Remote SHA
  was verified. Log: `/tmp/forecast-host-owner-push.log`.

Push-gate coverage for shared and newly introduced owners:

- The prior changed-file selector silently omitted root CLI changes and new
  application/hosting packages unless a changed test happened to cover them.
  Unmapped Python changes now fall back to the full test directory; known domains
  retain their existing selection. New owners cannot become an untested category.
- Real temporary-Git-repository regressions cover root CLI, application, hosting
  and an unfamiliar package. All 12 developer-workflow tests passed, log:
  `/tmp/forecast-hook-owner-coverage.log`. Full regression for the already
  integrated auth/catalog batch runs independently in the frozen primary tree.

Configured command admission and TUI execution routing:

- The application catalog now validates configured command mappings, kinds and
  non-empty textual targets/commands. Built-ins take precedence consistently;
  malformed definitions fail with the same message in CLI and TUI instead of
  becoming attribute errors or unexpected command strings.
- TUI configured commands bypass the classic slash worker and agent construction.
  Alias chains are fully expanded and checked for cycles in shared code before
  handing the target to Ink; invocation arguments are appended once by the client.
  Configured shell commands execute only through command.dispatch, avoiding a
  failed execution followed by an automatic duplicate in the fallback path.
- A real subprocess regression counts executions across slash.exec handoff and
  command.dispatch failure. Further tests cover malformed JSON/YAML types, cyclic
  aliases, model-name case preservation and attempted built-in overrides.
- Gateway/catalog/CLI validation selection: 657 passed, log
  `/tmp/forecast-configured-commands-qualified.log`. Shared quality gates pass.
- Shell execution environment, output/error policy and process cleanup still need
  consolidation across synchronous CLI/TUI and asynchronous messaging adapters.
  Other legacy slash commands remain outside the shared execution boundary.


### On-demand compatibility worker ownership

- Normal session creation and model changes no longer construct the classic CLI
  worker. Only a legacy slash command admits that compatibility subprocess.
- The host helper serializes command use and invalidation. Cleanup failures retain
  the retiring handle; no subsequent command can reuse or replace it until cleanup
  succeeds. Interruptions retain their original exception and cleanup diagnostics.
- The command metadata regression now checks the shared catalog's values instead
  of depending on the location or formatting of constructor source text.
- Focused gateway, metadata and negative boundary checks initially reported 714
  passed, one skipped and one stale formatting assertion; the assertion now reads
  the actual command registry. The shared Python quality gate passes all 30 import
  contracts. Final metadata and real desk verification is recorded below.
- This does not remove the legacy dispatcher itself or finish failed-agent-build
  ownership. Those remain application/hosting migration work.

- Final metadata and real Ink/dashboard/local-provider/SQLite run: 168 passed,
  one skipped (platform-specific metadata), seven existing forkpty warnings.
  All seven real desk cases ran, covering provider failures, reconnect, cancellation,
  gateway death, unavailable history and the shared forecast workflow.


### Shared configured shell execution

- CLI, TUI and messaging now delegate configured shell snippets to one host
  owner, with a structured result. All preserve stdout and stderr, detect nonzero
  exits, use a 30-second deadline and cap displayed output at 4,000 characters.
- All three now use the existing profile-aware subprocess environment filter and
  output redactor. CLI and TUI previously inherited provider credentials directly.
  Invocation arguments are not interpolated into configured shell source.
- Async cancellation waits for process admission, kills the owned process group
  (Windows uses taskkill), and drains pipe readers despite repeated cancellation.
  The sync adapter runs the same operation with its own event loop.
- Focused tests exercise real shell timeout/reaping, stderr plus nonzero exit,
  environment filtering, invalid UTF-8, secret redaction, and deterministic repeated
  cancellation during startup. Existing CLI and TUI command dispatch tests pass.
- This owner is included in strict lint/format/type checks. The inherited environment
  and redaction helpers remain dependencies to consolidate; Windows process-tree
  behavior has not been newly qualified by the POSIX tests.

- The host owner imports only the standard library; a thin runtime adapter supplies
  the existing environment filter/redactor. A transitive negative import contract
  prevents process ownership from reaching presentation, runtime, agent or tools.
- Before the final ownership split, 532 command/gateway tests passed. The final
  split is separately covered by command behavior and negative boundary tests.

- Final verification: 55 focused command/boundary tests passed; strict Python
  lint, formatting and types passed; all 31 import contracts and protocol drift
  checks passed. Full push qualification remains separate.


### Deferred build admission and recovery

- The host now owns initialization admission and failed-build retry decisions.
  Rejected worker startup records a completed error instead of leaving the session
  permanently busy. Each admitted callback receives its own completion event.
- Sign-in recovery checks initialization errors before treating an attached agent
  as healthy. Failed partial agents are closed before replacement; failed close
  retains the agent and error for another retry. Notification release is not
  repeated after success.
- Cleanup callbacks run outside the history lock, while the caller's session-use
  reservation prevents close/replacement. Concurrent starts admit only one build.
- 257 initialization/auth/gateway tests passed. A final 26-test run covers the host
  state transitions, partial-agent sign-in recovery, and negative import contracts.
  Strict Python checks pass, including all 32 import contracts.
- Construction and notification wiring still belong to the RPC adapter; broader
  agent-internal cleanup and compatibility command migration remain unfinished.
  The primary branch's full push gate runs separately and does not include this
  isolated follow-up.


### Installed backend upgrade and independent terminal qualification

- `verify_profiles.py --upgrade-from <previous-backend-wheel>` now creates
  forecast/evidence and session state before installing the candidate, checks
  unchanged existing values/types and configuration, then exercises the installed
  CLI and independent local/remote terminal. Missing history/evidence fails.
- macOS Python 3.13.12: retained backend 0.21.2 upgraded to candidate 0.22.0.
  Question, probability history, timestamped evidence, Unicode session history and
  raw configuration survived. Installed resolution/scoring, local Ink, authenticated
  remote Ink, host termination and credential-log checks passed.
- Previous wheel SHA-256:
  `09c3ec93d5dec5e26353922c2162f50d5702e4c5264a846643470c9fa4abfaca`.
  Candidate wheel SHA-256:
  `294771183bf80fd3a866dd388d4975211014689bfd80eea524d9c119ecb75226`.
  Candidate built from isolated runtime commit `58e91e7a8`; this is local artifact
  qualification, not publication or native Windows/Android evidence.
- Seven verifier regression cases reject missing/retyped/changed history while
  allowing additive fields. The terminal package remains version 0.1.0; this does
  not claim an upgrade between different terminal versions.


### Native command handoff before provider initialization

- Slash routing now identifies native pending-input/snapshot handlers, skill
  invocations and plugin handlers before constructing an agent. Local command
  admission no longer depends on provider credentials or the classic CLI worker.
- 246 command-routing/gateway tests passed, including negative assertions for
  both agent and classic-worker construction.
- The prior integrated batch `dcb0585aa` passed the full Python suite:
  30,744 passed, 148 skipped, 58 warnings. Remote branch identity was verified at
  `dcb0585aaa63c6456eeefca87eba308bf909e92a`. Build-recovery and upgrade-verifier
  follow-ups are not covered by that full run.


### Validation rule loading boundary and stale policy correction

- Removed the hook loader's dependency on runtime configuration for its profile
  directory; the shared profile identity owner supplies that path. Deleted the
  corresponding frozen import exception and added strict lint/format/type coverage.
- Removed compiled-rule caching keyed by list identity and file timestamps. Those
  values do not identify a validation policy: in-place edits, object-ID reuse and
  same-size timestamp-preserving replacement could apply stale rules to new forecasts.
  Rules now compile from current specifications without retaining old policies.
- 38 hook loader, DSL, configuration and blocking tests passed. Regressions prove
  inline edits, same-size/preserved-timestamp file replacement and profile switches
  affect rule evaluation. All 32 architecture contracts passed.


### Hook configuration and rule mutation ownership

- Hook setting edits now use shared atomic field mutations against current raw
  configuration, preserving unrelated settings instead of saving merged defaults.
  Removed the store's direct runtime-configuration import exception and enabled
  strict lint/format/types for this owner.
- Rule add/edit/remove holds the shared file lock across read, validation and
  atomic replacement. Failed atomic writes propagate; the fixed-name temporary
  fallback is removed. Malformed rule files/configuration blocks cannot be
  silently replaced, and the enabled setter requires a real boolean.
- 341 hook/TUI-gateway tests passed. The final store/promotion/v2 set reports
  53 passed and eight existing skips. New regressions cover overlapping edits,
  failed writes, malformed data preservation and unrelated configuration retention.


### Hook policy transport validation parity

- Removed RPC bool/string coercions before shared hook setters. In particular,
  the string `"false"` previously enabled hooks because Python truthiness ran
  before validation. Only actual booleans now reach persistence.
- Shared profile/severity/rule-ID setters reject invalid input types with
  user-facing validation errors. CLI disable now reports those errors consistently
  with CLI enable/profile/severity rather than exposing an uncaught exception.
- 34 RPC/store tests passed, including invalid booleans leaving configuration
  untouched, true/false round trips and CLI/service error parity. Strict Python
  quality and all 32 architecture contracts passed.


### Shared rule parsing and compilation admission

- Rule parsing now retains structured field issues instead of coercing malformed
  objects/identifiers or raising before validation. Loader, CLI, preview and save
  consume the same validator; invalid configured rules are skipped safely.
- Predicate validation rejects ambiguous combiners, unhashable signal/operator
  input, nonfinite numeric comparisons, booleans as numeric thresholds and numeric
  or string substitutes for boolean comparisons. Direct compilation also validates.
- The DSL owner now passes strict lint/format/types. Final DSL/store/RPC/v2 tests:
  101 passed. Preview and save report identical field issues without writing files.
- The preceding integrated batch `41d551d7c` passed 30,766 tests, with 148 skips
  and 58 warnings, and was verified pushed to the working branch. Subsequent hook
  fixes are separately tested follow-ups awaiting integrated full qualification.


### Explicit native/legacy command handoff

- Ink no longer retries every slash-worker failure through another dispatcher.
  The host marks pre-execution handoffs explicitly; the client preserves RPC
  error code/data and checks session/command identity before following one.
- Timeouts, disconnects and execution failures retain their original diagnostics.
  Established legacy handoff messages remain supported, and a host without
  `slash.exec` can route directly through its native dispatcher.
- 121 focused TypeScript tests passed, including wire metadata, stale-session
  fencing and rejected retry cases. 246 backend routing/gateway tests passed.
  Type checking, lint, Python quality and production bundle compilation passed.

- Real desk plus backend handoff run: 28 passed, including all seven actual
  Ink/dashboard/local-provider/SQLite lifecycle cases; seven existing forkpty
  warnings. The later absent-method compatibility branch is covered by the
  focused TypeScript test rather than a legacy-free installed host.
