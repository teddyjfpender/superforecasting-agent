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
