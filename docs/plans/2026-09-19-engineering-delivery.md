# Engineering delivery record

Goal: implement the complete [specification](2026-09-19-engineering-improvement-specification.md),
not just the initial fixes. Baseline: `df8e3e33cd4d08c6eaad38a275f6e217e92a3375`.
Worktree: `feat/engineering-improvements`.

## Verification policy

The user explicitly requests focused tests instead of the full suite. This supersedes the
specification's full-suite execution requirement for this delivery. Retain the qualification
commands and native matrix; do not claim that an unexecuted full suite passed. Native platform
and installed-artifact requirements still need evidence at the appropriate milestone.

## Package status

| Package | State | Evidence / remaining work |
|---|---|---|
| W01 qualification | In progress | Reproduced provider test failure; preserved legacy active-provider menu; macOS boot identity replaces network discovery; docs freshness added to canonical check. Focused tests below. Windows identity capability/versioning and remote native receipts remain. |
| W02 quality ratchet | In progress | Added test TypeScript project; initial valid-root measurement found 291 diagnostics, including incomplete selection mocks, terminal stream types and protocol fixtures. Fix these before making it blocking. Remaining coverage ratchet, typed fixtures and execution tiers. |
| W03 typed sources | Pending | All specification criteria remain. |
| W04 CLI parity | Pending | Legacy active-provider behavior corrected as part of W01; shared command inventory/parity remains. |
| W05 runtime ownership | Pending | All specification criteria remain. |
| W06 TUI state | Pending | All specification criteria remain. |
| W07 questionnaire durability/lessons | In progress | Update interviews freeze advisory lesson selection, exclusions, digests and score/postmortem support. Historical contexts remain readable, and model prompts omit excluded guidance. Durable editor buffer API implemented with revision conflicts, discard tombstones, atomic receipts and lifecycle cleanup. Pending TUI autosave/restoration/status integration, new-question context and TUI provenance display. |
| W08 integrated recovery | Pending | All specification criteria remain. |
| W09 merged product qualification | Pending | All specification criteria remain, subject to focused-test policy above. |

## Focused receipts

19 September 2026, native macOS, Python 3.13.12, working-tree changes (not release certification):

- Reproduced `test_cmd_model_forwards_nous_login_tls_options`: one failure due to index-zero
  Anthropic selection and an attempted interactive read.
- Process identity, background research and complete CLI provider-resolution module: **38 passed**.
- Process identity, background research, research jobs, async delegation, developer workflow,
  and native docgen environment: **65 passed**.
- `python -m scripts.docgen --check`: passes after regeneration.
- Selected Ruff and strict `ty` check of process identity: pass.

The local background/job tests exercise the real macOS kernel identity probe. They do not
substitute for the pending Linux/Windows/native CI matrix. Old macOS identity records are
conservatively left unreconciled; they are not relabeled as the current host.

First implementation commit: `62a91b2e70`. Canonical Python quality checks pass, including
76 import contracts and generated-reference freshness. No hook bypass was used.

## Second implementation tranche

- Added typed local RPC fixtures with compiler-negative cases; unregistered calls reject.
  Questionnaire components now require only the request capability they consume.
- Updated questionnaire provenance fields, source change-basis fixtures and current composer
  props; removed status-test casts hiding malformed fixtures.
- Focused TUI run: 70 tests across six files passed; subsequent typed questionnaire/RPC/status
  run: 53 tests across four files passed. Production TypeScript check passed.
- Update interview contexts now freeze lesson selection. Shared cutoff admission excludes
  later revisions before supersession. Missing score/postmortem support is rejected, sample
  counts remain distinct from independent-cluster evidence, and guidance is advisory only.
- Focused Python run: 104 tests across interview context/generation, lesson wiring/enforcement,
  active-origin and learning trials passed. Strict interview typing passed.
- Historical evaluation compatibility review: only `learning.py` changed among evaluation
  sources; existing AST changes are confined to scope enumeration and cutoff selection.
  Completed evaluation passes frozen lessons to unchanged adjustment code. The explicit
  registry mapping preserves old identities without rewriting packets; unknown identities
  still fail closed. See `forecasting/trial_compatibility.json` for the review receipt.

The complete test TypeScript project is not yet a passing/blocking gate. Remaining diagnostics
are tracked by `ui-tui/tsconfig.tests.json`; no ignore baseline or blanket cast was added.
No full test suite was run. All W01–W09 exit criteria not evidenced above remain open.

## Durable buffer backend tranche

Added versioned editor-buffer save/read contracts and generated TypeScript. The ledger
stores buffers separately from confirmed interview answers and probabilities. Optimistic
concurrency rejects competing writers and changed interview revisions. Atomic retry receipts
contain no draft text; discarded content cannot be resurrected by replay. Cancellation and
commit purge draft text while profile databases isolate it. Additive schema initialization
preserves existing interview records.

Focused validation covers RPC rejection of secret/actor fields, actual subprocess exit after
acknowledgement, receipt-write rollback, changed/reused requests and lifecycle cleanup. This
is backend readiness, not yet a claim that TUI edits autosave. TUI integration remains open.

Buffer backend receipt: **47 focused tests passed** across persistence, interview lifecycle
and gateway contracts. Canonical Python/TUI static quality checks pass (including generated
contracts, reference freshness, 76 import contracts, lint and production TypeScript).
The full suite was not run. The new RPC request models retain the required `WireModel`
contract and explicitly enforce strict, extra-forbidden editor input.

## Questionnaire editor integration tranche

The TUI now restores acknowledged unconfirmed editor buffers, autosaves with serialized
and coalesced requests, preserves exact uncertain requests for retry, and requires explicit
review of stale buffers. Save/discard-and-close wait for their acknowledgements; unavailable
storage fails truthfully and an explicit leave-unsaved action allows exit. Receipt identity
is checked before displaying saved status. Confirmation retires prior editor text atomically
with the answer, while old retries preserve newer edits. Cleanup failure rolls back the answer.

Validation: 49 focused Python tests (buffers, interview lifecycle, gateway RPC) and 41 TUI
tests (editor controller, interview interactions and component flow) passed. Canonical
`scripts/dev.py check` passed, including production TypeScript. The full suite was not run.
This does not close W07: new-question lesson capture, full provenance presentation and wider
reconnect/conflict qualification remain. Other W01–W09 criteria remain as recorded above.

Editor integration commit: `92607a6938`. The complete test TypeScript project remains
non-blocking and incomplete: stream harness types and legacy callback fixtures still
need migration. New typed RPC fixtures are accepted by the interaction harness without
requiring a caller to widen their closed method catalog to arbitrary strings.

## Terminal contracts and lifecycle tranche

W02/W05 work replaced renderer socket requirements with readable/writable stream
capabilities and corrected the public `render()` declaration to return a promise.
Twenty-one view test files now await rendering before retaining cleanup handles;
previous optional cleanup calls could silently target a promise instead of an instance.
Raw-mode support checks the actual input capability.

Focused regression testing exposed and fixed two additional lifecycle defects:
`waitUntilExit()` now preserves completed results/errors for late observers, and an old
render handle cannot remove a replacement from the instance registry. The public unmount
wrapper now forwards its error argument. Renderer cleanup keeps borrowed streams alive.

The changed-view run passed 357 tests and exposed one new exit-error regression; after
fixing error forwarding, the final renderer/recovery subset passed all 12 tests. Canonical
static checks passed. The full Python or TUI suite was not run. Complete test-project
strict typing remains unfinished; remaining fixtures and handwritten declarations need
migration, and renderer/native qualification remains distinct from these local tests.

## Slash-command capability and alias admission tranche

The slash dispatcher now consumes request, log and reconnect capabilities rather
than the concrete gateway client. Generated request/result typing remains intact.
New cast-free fixtures exercise stale session responses, backend failures and
reconnect intent without constructing a process-owning client.

Inspection exposed unbounded alias recursion across catalog and backend aliases.
Per-invocation admission now detects repeated canonical names and bounds unique
chains to 32 steps. A deliberate subsequent invocation starts a fresh path. Tests
prove bounded network calls, local catalog rejection and absence of outbound chat
messages on alias failure. The nearest README now explains the actual owners,
contracts and failure behavior.

Validation: 103 focused slash-command tests passed; canonical static checks passed.
The complete test TypeScript project still fails on legacy fixtures and remains
unqualified. It reports no diagnostics in the new capability fixture or changed
application interfaces. This is W02/W04 progress, not completion of their full
acceptance scope. No full suite was run.

## Common source admission tranche

W03 now has a strict common acquisition-options owner, included in blocking Python
lint/format/type checks. Dispatch no longer coerces numeric strings, booleans as
integers, zero limits, string booleans or invalid date/endpoint filters into provider
requests. Date-only filters remain supported; timestamp filters require a timezone.
Errors identify fields without echoing potential endpoint credentials.

Market-model refresh preserves limit types for shared admission. Watched-source
orchestration no longer converts option-pair lists into mappings or passes coerced
numeric source identities to acquisition. Failures remain isolated per source, with
no payloads produced by invalid requests.

Focused validation: 68 tests passed across request admission, source dispatch,
market models and refresh. This is not completion of W03: adapter-specific request
unions, shared CLI import migration, typed acquisition/import plans and durable
import receipts remain open. The full suite was not run.

## First shared CLI source-import operation

The FRED CLI branch now delegates to `forecasting/application/source_imports.py`.
Its strict request model validates common options, ratings, claim type and as-of
input; the application owner fetches outside the ledger transaction, validates the
whole returned batch, and commits evidence atomically. It rejects mismatched series,
nonfinite/non-numeric measurements and conflicting duplicate entry identities.
Identical entries collapse within the batch. Existing CLI copy and evidence metadata
remain compatible, and missing publication times remain missing.

Focused tests cover direct application use, the existing CLI invocation, pre-write
batch rejection, provider defaults and injected mid-write rollback. Python static
checks and all 76 import contracts pass. Cross-request idempotent receipts, typed
import plans and prediction-market/remaining CLI adapter migrations are still open;
this first migration does not close W03 or W04. No full suite was run.

## Durable FRED import receipts

The shared request now accepts a stable optional request ID; the CLI exposes it as
`--request-id`. Evidence IDs and a versioned request digest commit in the same ledger
transaction. Acknowledged retries return the same evidence without network access;
conflicting input fails before fetch. Concurrent callers recheck inside the commit
transaction so one receipt and one batch win. Legacy calls without IDs remain
independent imports; a fresh acquisition intentionally needs a new ID.

Fourteen focused tests passed, including CLI replay, conflicting reuse, concurrent
callers, receipt-write rollback and subprocess exit immediately after commit. Python
lint/types and all 76 import contracts passed; the CLI-reference freshness check
correctly required regeneration for the new option, and the reference was regenerated.
This closes retry receipts for this operation, not the broader typed-plan/provider
migration requirements. No full suite was run.

## Prediction-market persistence owner

Kalshi and Polymarket CLI evidence branches now share
`forecasting/application/market_imports.py`. The typed request and provider-record
operation persists evidence and baseline comparison atomically through existing
ledger validation. Metadata construction is shared with candidate imports. Existing
CLI text remains compatible; unquoted markets do not invent a baseline, and neither
path changes an active forecast probability.

Nine focused tests passed, including local-HTTP CLI imports for both providers,
invalid-probability rollback and injected comparison-write failures. Python static
checks, generated-reference checks and all 76 import contracts pass. Acquisition
still precedes this persistence operation; full typed acquisition plans, receipt
support for these providers and remaining adapter migrations remain open. No full
suite was run.


## Shared Kalshi quote-unit contract

Found divergent conversion in evidence imports and the prediction-market display:
the former treated legacy one-cent prices as probability 1.0 and clamped invalid
numbers. Both now use `forecasting/sources/kalshi_prices.py`, included in the full
strict Python scope. Explicit dollar fields take precedence over rounded legacy
cents; invalid selected values fail closed rather than silently falling back.
Historical benchmark prices use the same conversion. The obsolete private
magnitude-guessing helper and its unused re-export were removed.

45 focused tests passed, including recorded market fixtures, legacy/dollar parity,
non-finite and out-of-range rejection, historical prices, atomic market imports,
and local-HTTP CLI evidence/benchmark imports. Canonical Python static and generated
checks passed, with all 76 import contracts kept. No full suite was run. This closes
quote conversion for those consumers, not order-book/candlestick validation,
market identity selection, provider retry receipts or full W03 acceptance.


## Kalshi single-market identity admission

Replaced first-row selection with a pure strictly checked source owner. Ticker
paths and query filters must identify one market before network acquisition;
returned records must contain exactly one matching ticker. Untargeted custom
mirrors may return one identified market, never an ambiguous collection. Invalid
wrappers and missing identities fail closed. API URL routing now preserves both
external-api and api.elections endpoints; lookalike domains are not rewritten,
and raw tickers are URL-escaped without permitting path substitution.

The initial focused identity/timestamp/CLI selection passed 43 tests. After API
routing coverage and the CLI no-write regression were added, the final identity
file passed all 25 tests. Canonical Python checks and all 76 import contracts
passed. The CLI mismatch regression checks nonzero exit, actionable stderr,
empty evidence/baseline collections and unchanged active forecast. No full suite
was run. Polymarket event/market identity selection and the remaining W03 request,
plan and receipt requirements are still open.


## Polymarket event and market identity admission

Removed arbitrary first-row selection from evidence acquisition. A strict pure
selector validates endpoint identifiers before I/O, matches market/event identity,
and admits one event child only when unambiguous or explicitly selected by the
public child URL. Market IDs, slugs and condition hashes are checked independently;
nonempty mismatches cannot trigger fallback to a different event. Empty responses
retain the existing event and settled-condition fallback. Duplicate matches,
malformed objects and event metadata masquerading as a market response fail closed.
Lookalike website hosts are no longer rewritten as Polymarket URLs.

66 focused tests passed across identity, condition-ID resolution, event-watch
compatibility, timestamps and local-HTTP CLI import. The final identity file,
including an event-envelope and CLI no-write regression, passed 20 tests. Existing
numeric-event and timestamp fixtures were corrected to return their requested IDs.
Canonical Python checks and all 76 import contracts passed before the final
regressions; pre-commit repeats these checks against the final staged code. No full
suite was run. This closes single-market identity selection, not all Polymarket
probability semantics, typed source plans, shared command parity or retry receipts.


## Shared import receipts and prediction-market acquisition retries

Extracted FRED's receipt persistence into the shared application owner and added
comparison IDs through an additive schema migration, preserving historical FRED
digests. Kalshi/Polymarket acquisition now has a typed request/fetch boundary;
request-ID replay checks precede fetching and repeat under the commit transaction.
Evidence, baseline comparison and receipt commit together. Concurrent acquisition
may make two reads but commits one result; retry after acknowledgement loss makes
no new source read. CLI evidence imports expose `--request-id`, reject candidate
use and render request conflicts through the normal domain error path.

70 focused source/import/identity tests passed. The final nine receipt tests passed,
including both-provider CLI replay/conflicts, concurrent callers, storage rollback,
legacy schema preservation, missing referenced comparison, and subprocess exit
immediately after commit. A missing CLI error import exposed by the conflict test
was fixed. Python static/generated checks and 76 import contracts passed before
that small final correction; pre-commit validates the final staged tree again.
The CLI reference and application guide are updated. No full suite was run.

The schema addition is backward-readable by this version; downgrade to older
positional-insert code needs a pre-upgrade backup. Full typed import plans,
remaining adapters and all participating gateway/tool parity remain incomplete.


## Command RPC context and registration ownership

Removed the command family's server imports, registrar globals and mutable `_core`
rebinding. Named handlers now capture a typed `CommandContext`; registering a second
host cannot redirect the first host's callbacks. The direct context registration
API supports independently supplied capabilities. The singleton adapter preserves
its explicit server reload behavior. Each invocation pins its runtime host and
participates in worker admission/draining. Stopped-host requests consistently fail
with the existing `5030` admission code, before curator-specific dispatch.

179 focused registration/configured-command/goal tests passed after extraction.
The expanded run passed 181 tests with one new test teardown error (attempting to
drain before closing admission); after correcting that teardown, all three context
tests passed. They exercise two real RuntimeHost instances, repeated shutdown,
barrier-controlled in-flight ownership and host replacement during a call.
Python static checks passed, with a new direct import boundary bringing the count
to 77 kept contracts. Pre-commit rechecks the staged result. No full suite was run.

This closes command-family registration rebinding, not all W05 host ownership:
other carved RPC modules still use the server adapter; singleton callbacks and
profile-global plugin/skill services require further migration and integrated
qualification before claiming arbitrary multi-host isolation.


## Tool RPC capabilities and shared invocation ownership

Removed the tool family's singleton imports and registration rebinding. Named
handlers now capture `ToolContext`, including configuration read/write and session
reset capabilities, and retain the existing reservation before persistence/reset.
Command/tool handlers share `rpc_binding` for pinned-host admission and draining.
The singleton composition retains legacy profile behavior; direct registrations
can supply separate persistence and callbacks without changing another host.

212 focused registration, command, inventory, tool configuration/reset and context
tests passed. Expanding strict typing exposed a Sequence-versus-list mismatch at
tool-definition lookup; the adapter now copies a present selection into a list
while preserving None. All 19 inventory tests passed after adding tuple and None
regressions. Canonical Python static/generated checks and 77 import contracts
passed, with tools_rpc/rpc_binding added to full strict coverage and the direct
server-import prohibition. No full suite was run.

Other RPC families, singleton profile services and complete integrated recovery
qualification remain open; these tests establish this family's ownership only.

## TUI renderer fixture contracts and scroll capabilities

The complete test TypeScript project reported 204 diagnostics. Removed inert
renderer `debug` options and unnecessary stream-to-OS-terminal/never casts from
affected fixtures. The scroll helper now requires only the scroll and selection
capabilities it calls; its fixtures use that actual interface without casts.
Production behavior remains unchanged. The testing guide now distinguishes typed
RPC fixtures, inherited untyped helpers, stream ownership and native qualification.

All 129 tests in the 18 changed test files passed. Canonical Python/TUI static
checks passed, including production TypeScript and all 77 import contracts.
The complete test project now reports 174 diagnostics, down 30; it is still not
clean or blocking. The large slash fixture and remaining RPC/view fixtures remain
required W02 work. No full Python or TUI suite was run.


### W02 follow-up — prediction-market fixture and response contracts

- Declared optional `pm.list` freshness and catalog status in the Python wire owner,
  regenerated TypeScript/reference documentation, and removed the client's separate
  catalog shape. Existing fresh responses may omit these additive fields; an unknown
  catalog refresh timestamp remains null.
- Replaced prediction-market list and delayed book/history fakes with method-bound
  `RpcFixtures`. Selection-race fixtures now carry complete event/distribution/outcome
  and order-book records, without gateway or DTO casts. The deliberately malformed
  missing-estimate event remains an explicit compile-negative test.
- Validation: 44 focused Python protocol/gateway tests passed; 19 focused TUI tests
  passed; canonical `scripts/dev.py check` passed (including 77 import contracts).
  Dedicated test-project compilation still fails with 165 diagnostics, down from 174;
  W02 remains partial and no full suite was run.
- The protocol round-trip test now excludes unset additive fields, matching the actual
  gateway's validate-without-rewriting behavior. Required null values are preserved.

### W02/W06 follow-up — job attachment response ownership

- Migrated job-attachment fixtures to generated jobs.active/jobs.status responses and
  complete job DTOs using RpcFixtures; removed the request-only gateway cast. The
  production hook consumes generated results directly rather than an unchecked mirror.
- Added attachment epochs and monotonic response admission: returning to the same job
  cannot admit an earlier attachment's completion, overlapping responses cannot regress
  displayed progress, and delayed startup discovery cannot resurrect an old attachment
  after an explicitly selected job completes. Wrong-job records are ignored and repeated
  stop calls unsubscribe once.
- Focused verification: 81 tests passed across job attachment and Desk rendering; the
  subsequently added wrong-job regression brings the attachment file to 10 passing tests.
  The Desk completion fixture now includes the job identity emitted by the actual backend.
  Canonical static checks passed; test-project diagnostics fell from 165 to 160.
- W02/W06 remain partial: this does not establish real transport reconnect qualification,
  complete test-fixture typing, or the remaining route/modal ownership requirements.

### W02 follow-up — slash command fixture contracts

- Converted slash-command RPC fixtures to generated method-bound responses, including
  auth, forecast dashboard/detail/operations, configuration, voice, browser management,
  native command dispatch and explicit legacy handoffs. Unknown methods no longer receive
  a fabricated empty success from the default fixture.
- Filled required operation/reload response fields, provided actual reconnect capabilities,
  and typed delayed native-command completion. Local catalog/history fixtures now expose
  their actual consumer types rather than null-only/empty-array inference. Preserved the
  existing routing, alias, session replacement, scope and stale-result assertions.
- Validation: 105 tests passed across createSlashHandler, slashCapabilities and RpcFixtures.
  The slash-command test file has no remaining TypeScript diagnostics; the complete test
  project remains failing with 33 diagnostics (previously 160). No full suite was run.
- W02 remains partial until the remaining fixtures pass and the dedicated typecheck is
  included in the blocking canonical quality path. No runtime API was weakened for these tests.

### W02 milestone — blocking TUI test typecheck

- The complete `tsconfig.tests.json` project now passes without exclusions or blanket
  suppressions. `npm run type-check` checks production plus tests; the dedicated
  `type-check:tests` command supports focused feedback. Existing canonical developer,
  hook and CI callers of `type-check` inherit this gate without another workflow owner.
- Corrected renderer/provider child props, awaited asynchronous renderer creation before
  cleanup, supplied complete chart/terminal capabilities, and aligned completion, voice,
  callback and tool-progress fixtures with their real consumer types. The completion
  fixture uses an unstarted GatewayClient with typed local RPC handlers. Removed `never`
  casts from desk grouping fixtures; no production interfaces were weakened.
- Verification: 219 tests passed across the 22 changed fixture files; production and full
  test-project typechecking passed. No full Python or TUI suite was run.
- This completes the dedicated test-typecheck gate criterion, not all W02: Python strict
  coverage ratchets, feedback tiers and existing unchecked fixture escapes remain work.
  Typechecking alone does not certify native rendering, integration recovery or releases.


### W02 feedback tiers — explicit canonical runner

- Added `scripts/dev.py verify` with fast, integration and local qualification tiers.
  Fast requires explicit existing Python test files/node IDs or TUI test files and
  validates every selector before commands run. Empty selections, traversal, directories
  and unsupported selector/tier combinations fail closed. The qualification tier alone
  explicitly plans complete suites; it was tested using intercepted commands, not run.
- Integration reuses the real local desk/dashboard/host fixtures and selected TUI recovery
  tests, builds the client first, and retains canonical hermetic Python execution. Every
  command and tier prints elapsed time; errors stop execution and suppress a success claim.
  The runner is now itself under complete selected lint/format/type checks.
- Measured on this macOS checkout: fast tier with 26 script tests passed in 8.10s;
  integration tier passed in 37.73s with 33 Python tests and 59 TUI tests. These are observed local
  durations, not cross-platform performance or a flakiness baseline. No full suite run.
- Hook/protected-check policy is unchanged. Pre-push still requires full Python tests;
  a safe changed-owner selection policy and exact-tree receipt design remain incomplete.
  Tier success is explicitly not installed-artifact/native matrix qualification and no
  cached receipt is reused. Contributor and script guides describe the same distinction.

- Integration emitted 18 Python 3.13 `forkpty()` multithreaded-process deprecation
  warnings in the real dashboard/local desk scenarios. No deadlock occurred in this run,
  but safe child spawning is not established by that outcome. W05/W08 must examine the
  PTY spawn boundary; do not silence the warning or attribute historical SSL/BFD failures
  from this evidence. The focused tests retained their normal warning output.

### W05/W08 — remove Python-after-fork dashboard startup

- Traced all 18 integration warnings to `PtyProcess.spawn` calling Python `forkpty`
  in the threaded dashboard process. Replaced that allocation/startup path with
  a strict hosting owner using `os.posix_spawn(setsid=True)` and an isolated helper
  interpreter. The helper acquires the controlling terminal, closes unrelated inherited
  fds and executes the requested argv; no Python application state is copied after fork.
- Bounded startup/error handshake preserves missing-executable/cwd errors and detects
  helper failure or timeout. Failed startup releases descriptors and reaps the direct
  child before returning; successful startup transfers PID/master ownership to the
  existing PtyProcess bridge. Unsupported safe spawning fails closed with an actionable
  platform diagnostic, without an unsafe fork fallback. Existing resize/read/write and
  retained-dashboard session behavior are preserved.
- Verification on macOS ARM64/Python 3.13: 39 focused hosting/PTY/dashboard/local-desk
  tests passed with no warnings (previous integrated run had 18 forkpty warnings).
  Dedicated spawn regressions additionally cover closed standard descriptors and
  unsupported runtime diagnostics. Canonical Python static checks pass; new hosting
  modules receive complete selected lint/format/type checks.
- This is evidence for removal of the observed threaded-fork hazard, not attribution
  of historical SSL or bad-file-descriptor incidents. Native Linux and installed-artifact
  requalification, other runtime lifecycle seams and the full W08 matrix remain open.


### W05 PTY follow-up — inherited signal dispositions

- A focused regression reproduced Ctrl+C failure when the dashboard parent ignored
  SIGINT: the terminal displayed `^C` but the child never received KeyboardInterrupt.
  Ignored dispositions survive exec, so a fresh helper alone did not solve this case.
- POSIX spawn now resets terminal interrupt/quit/hangup/termination, job-control and
  resize signal defaults, without changing the parent's dispositions. The existing
  child signal-mask reset and helper SIGPIPE restoration remain in place.
- Verification: the regression failed before the change; all 23 focused spawn/bridge
  tests passed afterward. No full suite or historical crash attribution is claimed.

### W07 — frozen general guidance for new-question interviews

- New create interviews now capture version-3 context in the same transaction as
  their first draft. The learning owner receives an explicitly unclassified target,
  never a fabricated forecast question. General guidance is eligible; domain and
  outcome conditions must not be inferred from a title or questionnaire default.
- Generation and evaluation reuse the exact frozen lesson packet. Begin retries
  return the original capture; later lesson changes cannot rewrite it. Historical
  create interviews without context retain their original behavior without live
  backfill. Update contexts and their contract checks are unchanged.
- Verification: 100 focused interview/context/source/buffer/agent/generation tests
  passed in 2.58 seconds. Canonical Python static checks passed, including all 77
  import contracts and generated-reference checks. No full suite was run.
- Remaining W07 work includes classified new-question selection, visible lesson
  provenance, and the outstanding TUI conflict/reconnect acceptance criteria.

### W07 — inspectable frozen lesson provenance

- Added the typed `forecast.interview.lessons` operation and generated client contract.
  It projects an exact saved context with cutoff/policy, lesson revision and digest,
  scope/applicability, inclusion/exclusion reasons and supporting record references.
  Historical absence stays absent; corrupt context fails closed. Excluded guidance
  text is not presented as advice, and no live library read occurs.
- Ctrl+Y opens the TUI guidance reader without confirming pending answers. A compact
  summary distinguishes support counts from independent outcomes; Enter exposes
  provenance, Left/Right selects records and arrows/Page keys scroll. The reader
  ignores late unmounted responses and rejects mismatched interview/revision/context
  identities. Explicit retry handles failed loads. Fixed overlapping reader content
  exposed at 60 columns; inherited modal/theme and bounded scrolling are retained.
- Verification: 72 focused Python context/protocol tests and 38 TUI interview controls
  tests passed, including guidance navigation at 60×18, 80×24 and 120×40 and response
  mismatch/retry. Canonical static checks passed; no full suite was run.
- This completes the first read-only provenance surface, not all W07 acceptance.
  Classified new-question lesson selection and integrated conflict/reconnect evidence
  remain outstanding. Learning effectiveness is not inferred from these tests.

### W07/W08 — real questionnaire reconnect, conflict and process-death recovery

- Strengthened editor restore ownership: a superseded restore success/failure cannot
  replace the current controller, cross-interview and duplicate-question responses
  fail closed, and buffer revisions newer than the displayed interview are conflicts
  even when the server reports them current. Recovered durable text is explicitly
  labelled unconfirmed and saved locally.
- Extended the existing real Ink/stdio gateway/SQLite/dashboard WebSocket/PTY harness,
  not a mock reconstruction. It types a draft, waits for the rendered saved receipt,
  checks the ledger, reconnects three times without duplicate writes, then restarts
  the terminal. A concurrent answer requires explicit conflict restoration; an owned
  process-group SIGKILL proves recovery does not depend on graceful flushing.
- Intermediate and final assertions bind visible status to saved text, interview and
  buffer revisions. No restored text becomes an answer, and no forecast question is
  created. The harness checks old and replacement terminal ownership/termination.
- Verification on macOS ARM64, Python 3.13.12, Node 26.0.0: two normal/conflict integration
  cases passed in 7.40s; the process-death case passed in 5.36s; 46 focused TUI buffer and
  interview tests passed. Canonical static checks passed. No full suite was run.
- Native Windows/Linux repetition and the remaining W08 scenario matrix are still
  unqualified; this receipt does not imply cross-platform completion.
