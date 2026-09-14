# Research runtime capability implementation

Scope: the six requested upstream capabilities plus MCP issuer binding. This is
an implementation checklist, not a replacement for the non-blocking platform
qualification backlog in TODO.md. Upstream reference: `5eb99eb284`.

## Acceptance

- [ ] Progressive tool discovery: selected optional tools behind scoped
  search/describe/call; core forecasts and clarification remain direct. Validate
  arguments and permissions through existing dispatch, preserve batching and
  cancellation, test dynamic selection and cross-session isolation.
- [ ] Context continuity: durable provider-usage anchors, estimate additions,
  invalidate on history/model/schema changes; preserve forecast identifiers,
  source references and unresolved assumptions at compaction; runnable recall
  evaluation with an uncompacted control and synthetic fixtures.
- [ ] Persistent Python kernels: opt-in session state with explicit reset,
  reproducible calculation records, per-cell permissions/budgets, timeout and
  cancellation teardown, parent death and profile/owner isolation. Exercise real
  execution and the supported local/remote execution boundaries.
- [ ] Background research: batch admission, independent and grouped completion,
  early failures, durable/display truthfulness, cancellation and resource cleanup
  including partial admission and interrupted parent execution.
- [ ] Event research jobs: authenticated webhook binding to existing jobs using
  shared claims/execution; delivery deduplication, no stored-prompt mutation, no
  silent active-forecast probability changes. Exercise real HTTP and fake runs.
- [ ] Repeated result references: still execute tools, compact only identical
  successful large results, retain resolvable originals and fresh observations;
  preserve transcript replay, error/polling behavior and provider call ordering.
- [ ] MCP issuer binding: pin refresh grants, reject issuer/endpoint changes,
  explicit legacy handling, both construction paths, concurrent writes and
  profile isolation; verify refresh requests with controlled providers.
- [ ] Directory guides, configuration/reference documentation and upstream
  provenance updated. Strict gates cover new owners. Canonical full suite passes
  before publication; merged tree matches the tested tree.

## Progress

### Event script policy regression

A signed HTTP webhook now has a regression through durable admission, the actual
scheduler and a Python subprocess attempting an active ledger update. It reproduced
a missing policy bridge: pre-check and script-only subprocesses inherited a
permissive shell policy. The shared script runner now forces `proposal_only`.
The test verifies refusal, a durable failed receipt, no repeat execution on
redelivery, unchanged snapshot count and preserved scheduled cadence. A second
case uses the real agent loop and forecast tool with controlled SDK replies:
evidence persists, an attempted update becomes a durable pending proposal, and
redelivery performs no further model calls. The original probability remains
unchanged. Route-edit replay and the remaining event recovery cases are still open.

Implementation branch: `feat/research-runtime-capabilities`. No capability is
complete until its wiring and boundary tests demonstrate the acceptance above.

### First implementation milestone

- MCP binding is enforced in the shared managed and compatibility provider.
  Legacy/mismatched grants fail closed; access tokens survive; binding includes
  the token endpoint. Storage captures its profile and stale cleanup compares
  the whole loaded record before removal. Non-rotating refreshes preserve grants.
  Focused MCP regression set: 85 passed, then 10 binding cases passed including
  replacement grants reusing the same refresh token. Full suite remains pending.
- Repeated-result references are wired into both executor paths. Every call
  executes; references require an original still present in history. Changed,
  failed, pruned, edited and multimodal results remain whole. Runtime tests
  exercise sequential/concurrent calls and closed/reopened database replay.
  Focused reference/guardrail set: 32 passed. Full suite remains pending.
- Actual agent delegation dispatch now forwards images and background mode;
  previous direct tool tests did not cover this missing dispatcher wiring.

### Progressive discovery milestone

The copied catalog and agent adapter are implemented and wired before four
provider transports. Core forecasts and clarify remain direct; optional calls
reuse policy hooks, guardrails, memory/context-engine owners and registry dispatch.
Whole-batch validation and per-effect selection/cancellation checks are tested.
The latest focused milestone set passed 50 tests; the expanded runtime set passed
17 tests including the four transport branches. Documentation states the native
provider-owned runtime boundary. Full-suite and product integration remain pending.

### Context continuity milestone

Provider input baselines now persist under versioned session metadata. Full-prefix
and request-identity hashes reject stale counts after edits, rewinds, model/tool
changes or compaction. Retained additions are estimated separately from billed
completion totals. Atomic metadata updates preserve unrelated model settings.
The TUI uses the same estimator, adopts resumed history before its first request,
and updates context reporting after undo/reset/manual compaction.

A bounded mechanical compaction index retains exact forecast/source/measurement
records and unresolved assumptions as quoted historical claims. Records are whole
or explicitly omitted with retrieval guidance; prior index records can survive
another compaction. The ledger remains authoritative.

Focused coverage passed 263 tests, with 248 passing after the final manual-command
accounting consolidation. The offline synthetic recall comparison retained 8/8
facts for the uncompacted and indexed conditions, 0/8 for the deliberately lossy
control. This is mechanical retention evidence, not a live-model or forecasting
quality result. Optional provider/model recall runs use independent prompts and
record fixture/implementation hashes. Full-suite verification for this milestone
remains pending.

The earlier MCP/reference/discovery milestone passed the canonical full suite:
32,222 passed, 147 skipped, in 525.88 seconds, and was pushed at `80a951a393`.

The first context full-suite gate found three adapter compatibility failures
(32,244 passed, 147 skipped). All three came from assigning optional context
history to agent doubles that deliberately prohibit new attributes. Startup now
adopts history only for agents exposing that field. The focused fix set passed
109 tests. Result references were also tightened to require an inline original;
a saved-output marker alone cannot prove that its bytes remain available.
Context publication remains pending a clean full-suite run.

### Kernel prerequisite: execution call authority

Local and remote code-execution RPC workers now capture the submitting context and
approval/sudo callbacks. Cancellation is scoped to each call and inherited by
nested calls, without poisoning recycled worker threads. Explicit empty and
non-overlapping tool selections no longer expand to the sandbox default. Real
local subprocess tests exercise caller routing and refusal through the generated
RPC client. Persistent kernels and authenticated/bounded RPC framing remain in
progress; this prerequisite does not yet extend interpreter lifetime.

The execution-authority prerequisite passed 120 focused tests, including the
existing code-execution/mode cases and new real-RPC permission/context cases.

### Kernel prerequisite: shared authenticated RPC

The local socket and remote file servers now share one typed request pipeline.
It bounds frames, authenticates ephemeral tokens, validates envelope types,
preserves forecast policy, and charges before effects. Remote tokens are created
inside a private directory and kept out of command arguments. Failed remote
response writes retry delivery from retained receipts instead of executing tools
again. Python output suppression is context-scoped and never closes borrowed
streams. The existing execution integration set passed 109 tests; the new socket,
remote-shell and output boundary set passed 14 tests before adding the nonfinite
JSON regression. Persistent process lifetime remains outstanding.

The complete focused RPC/execution/context set passed 128 tests, including the
finite-JSON check and real remote file-RPC dispatch. New RPC and output owners
pass strict lint, formatting and typing.

### Persistent cell runner and full-gate follow-up

The RPC/context full gate completed with 32,267 passed, 147 skipped, one failure
and one follow-on resource error. Kanban's WAL warning key used only the database
filename, suppressing warnings across profiles. It now uses the resolved path;
the regression exercises two databases, reconnect deduplication and usable
rollback journaling. Its connections now close even when assertions fail.

The standalone persistent cell runner retains variables, records ordered code
and result hashes, bounds Python output and separates native output from control
frames. Python errors report preserved partial state; reset clears the namespace.
Owner-pipe EOF terminates a running cell. Cells leaving Python threads alive
retire the interpreter before another cell can acquire authority. Real subprocess
coverage plus the Kanban suite passed 171 tests. This runner is not yet exposed
through execute_code: host ownership, per-cell RPC binding, durable calculation
records and local/remote integration remain required. No kernel acceptance box
is complete and the failed full gate has not been waived.

The follow-up full gate passed: 32,276 passed, 147 skipped, 480.19 seconds.
Commit `e798f51111` was pushed with that receipt.

### Local persistent-kernel integration

The local owner is attached to the actual agent object. Public execution dispatch
now supports opt-in session kernels and explicit reset, including fresh per-cell
RPC authority, deadlines, selected-tool validation and durable calculation
receipts. Empty tool selections stay empty. Agent close and client eviction close
the exact owner; cleanup failures retain handles rather than replacing a running
component. Python-thread and observed subprocess leftovers retire the kernel.
Working-directory/interpreter changes require reset rather than silently using
stale state. The existing child environment builder is shared by both lifetimes.

The focused local integration set passed 144 tests, including actual agent
dispatch across two turn IDs, actual close, blocked RPC cleanup retries, profile
separation, timeout/reset, background child-process cleanup and durable receipts.
New owners pass strict checks. Remote persistence, comprehensive parent-death and
descendant ownership qualification, complete reproducible input/environment
records, and the final full-suite/product audit remain outstanding. This is a
local integration milestone, not completion of the kernel requirement.

The local integration full gate passed: 32,288 passed, 147 skipped, 479.25
seconds. Commit `77e7668db2` was pushed with that receipt.

### Recorded calculation inputs and replay

Version 2 receipts bind complete retained cell metadata and ordered RPC inputs.
Input admission is recorded before dispatch; interrupted or missing input writes
cannot become replay evidence. Records include the actual child interpreter and
installed-package metadata. An explicit module CLI verifies archives and replays
trusted Python with frozen tool observations; it never dispatches live tools.
The report separates output agreement from runtime agreement and preserves source
receipts. Redacted or truncated original code/data/output fails exact verification.
Large interactive output is bounded while full retained observations remain
available for comparison. Direct Python I/O and randomness are explicitly outside
the frozen RPC input boundary; this is not a universal environment snapshot.

Real subprocess/CLI replay and the combined execution regression set passed 153
tests, including output-mismatch exit status. New owners pass strict
checks. Cleanup also stopped using bare-PID fallback probes for reparented child
exit confirmation; retained process identity and terminal status are authoritative.
Remote kernels, broader parent-death ownership qualification and final product
acceptance remain outstanding.

### Remote kernel integration in progress

The isolated `feat/research-remote-kernels` worktree now exercises the persistent
protocol over a real POSIX shell transport. A remote supervisor owns the runner
process group, authenticated control files, per-cell admission and completion,
and an expiring owner lease. Host cleanup retains the environment and remote
directory until termination is confirmed. This is controlled transport evidence,
not credential-dependent Daytona/Modal qualification.

Public execute_code dispatch retains state across turn IDs. Exact-object backend
leases prevent idle or manual cleanup while the kernel owns the environment;
subsequent calls reject a replaced environment. Releasing an old owner does not
remove or clean its replacement. Control commands borrow the shell snapshot
without writing either its environment or working-directory state. A real-shell
regression verifies ordinary user commands still persist both.

The initial combined runner/remote/local/shell set passed 48 tests; public dispatch
and shell-state follow-up passed 25 tests. Strict lint, formatting, typing, all 76
architecture contracts and protocol generation checks pass. Broader execution
regressions, parent-death/resource ownership review, documentation and the full
publication gate remain pending. These changes are not yet committed or pushed.

The broader kernel, shell-state, code-execution and execution-mode regression set
passed 157 tests in 8.87 seconds after the public-dispatch changes. Full-suite
publication and the remaining ownership audit are still required.

The ownership audit now rejects cancellation/deadline expiry after RPC setup but
before sending code. Remote heartbeat and bounded cleanup use their own stop
scopes while preserving profile context; retiring a call cannot cancel cleanup.
Nested tool cancellation still propagates and the caller's original interrupt
state is restored. A real abrupt supervisor-death test confirms its running
kernel group exits while an unrelated sibling survives; no false termination
receipt is synthesized. The expanded kernel/execution/interrupt set passed 174
tests in 9.79 seconds. Directory guides now describe the remote protocol and
unconfirmed cleanup limits. Full-suite publication remains required.

### Background admission prerequisite

The isolated `feat/research-background-batches` worktree reserves capacity under
the async registry mutex before allocating children. Reservations account for
running and not-yet-built work together and convert directly into running records.
Release is idempotent. Executor creation failures now remove the admitted record.
Children remain attached to the parent until scheduling succeeds; rejected
children detach only after close succeeds, so failed cleanup preserves ownership.
Construction failures release reservations and close previously allocated children.
The existing single-task guard now runs after JSON task normalization.

Focused async/delegation coverage passed 161 tests, including capacity rejection
before child construction, reserved batch capacity, atomic slot conversion and
executor failure cleanup. This is an admission prerequisite: batch grouping,
durable outcomes, delivery recovery and TUI integration remain outstanding.
The completion queue only checkpoints processes; its old module documentation
must not be treated as evidence of durable delegation results.

### Durable batch journal prerequisite

A strict storage owner now freezes whole-batch admission and records outcomes
and delivery events in one transaction. Independent completions arrive early;
grouped completions preserve input order and wait for every member, with early
failure events. Owner checks reject unstarted completion, repeated start and
conflicting results. Identical terminal retries are idempotent. Delivery events
survive reopening and require acknowledgement by the originating session.
Fault injection verifies outcome/event rollback together. The journal does not
infer worker liveness or retry external effects. Runtime dispatch, owner recovery,
redaction and TUI delivery wiring remain required before this capability is usable.

Single background dispatch now persists admission before worker start and writes
terminal outcomes before publishing notification hints. Task specifications and
results pass through redaction before storage. A dropped notification leaves a
queryable pending event. Failed result writes retain an explicit
completion_pending state and retry persistence without running research again;
per-record serialization prevents concurrent retry notifications. If durable
start fails, an unstarted-child cleanup callback runs; failures retain ownership
and capacity until cleanup succeeds. The original process-queue durability claim
in async_delegation's module guide has been corrected.

The combined journal/async/delegation set passed 168 tests, including missing
notifications, failed result writes and failed start cleanup. Strict checks pass.
Whole-batch runtime admission, incremental grouped delivery, durable owner-death
reconciliation, and CLI/gateway/TUI acknowledgement and recovery remain required.

Public background delegation now accepts task batches. One transaction freezes
all member specifications and delivery groups before any submission; the reserved
capacity converts into individual running handles. Partial scheduling returns
accepted handles alongside rejected members rather than reporting a false total
failure. Unsubmitted members are durably rejected on an interrupted dispatch and
unstarted child allocations retain cleanup ownership. The tool schema exposes
per-task delivery_group; omitted groups return independently.

Notification hints now follow journal events: a completed grouped member does
not notify before its barrier, group results retain input order, and failures
surface early. In-process event IDs suppress duplicate hints from simultaneous
member completion. This does not replace durable consumer acknowledgement or
reconnect recovery, which remain outstanding, along with owner-death reconciliation
and profile/cancellation propagation audit for detached workers.

### TUI durable delivery integration

The TUI notification poller now recovers journal events for its exact session
when notification hints are absent. Live and recovered hints share one canonical
formatter. A deterministic event-bound receiving turn commits in the session
journal before acknowledgement. Duplicate hints acknowledge the existing receipt
without starting another model call; conflicting prompt content fails closed.
Acknowledgement failure does not prevent an already-durable turn from starting.
Unavailable session storage refuses delivery and leaves the research event pending.
The secondary end-of-turn drain leaves these events to the owner-aware poller.

The focused notification, turn-journal, async and journal set passed 38 tests;
strict checks pass. A real SessionDB-backed TUI submission test proves one worker
admission across duplicate hints and a saved receiving prompt before event
acknowledgement. CLI/messaging acknowledgement, detached-worker profile propagation,
owner-death reconciliation, durable TUI task status and full integration/release
gates remain outstanding. This is not complete background capability acceptance.

### Detached worker and owner recovery follow-up

The recovery worktree captures session/profile context for detached workers while
removing only inherited parent cancellation. Profile home is pinned from durable
admission; the child still honors its own thread interrupts and nested scopes.
Cleanup retries run under that same captured context. Two real worker threads
verify distinct profile/session routing after the parent is cancelled.

Journal version 2 adds process-owner identity. Recovery checks saved PID creation
time only on the same named machine/network identity and marks positively exited
owners interrupted without retrying effects. Foreign hosts, inaccessible processes
and legacy records without identity remain unconfirmed. Tests cover real owner
process exit, simulated PID reuse, live owners and foreign-host refusal.
Status reads now include durable results and explicitly label active records with
no locally observed worker unconfirmed. Unresolved work is not removed by the
completed-result retention limit.

The combined async/storage/context/TUI notification set passed 48 tests; strict
checks and 76 architecture contracts pass. CLI/messaging delivery acknowledgement,
TUI presentation of recovery diagnostics, cross-profile notification routing and
full integration gates remain outstanding.


Recovery presentation now maps durable results and pending/unconfirmed states
through the typed status RPC into the agents overlay. Failed event-driven refreshes
retain last-observed results with an unavailable notice; late failures from a
replaced session cannot change its state. Background cancellation checks the exact
session and profile before invoking the captured worker callback. Updated ownership
fixtures reflect journal-backed admission instead of incomplete in-memory records.
Focused Python verification: 54 recovery/ownership tests and 34 command/notification/
protocol tests passed. Frontend verification: 96 delegation/event/history/reconnect
tests passed. The original full-suite notification compatibility failure is fixed
in the focused set; a fresh full-suite gate remains required before pushing.

Profile notification routing follow-up: journal-generated events carry an opaque
hash of the resolved owning home. Shared routing checks both profile and session;
CLI drains, messaging drains and TUI durable admission use that policy. Messaging
reads a bounded queue snapshot so requeued foreign events cannot loop indefinitely.
The TUI polls its durable journal independently of queue emptiness and selects one
saved event directly, preventing foreign hints from starving recovery or accumulating
duplicate local hints while busy. Focused async/notification/turn verification:
49 passed; strict checks and 76 architecture contracts pass. Live CLI/messaging
acknowledgement still needs durable receiving admission; routing alone does not
establish crash-safe delivery. Cross-interface integration and full gate remain.

Receiving-admission consolidation: the shared notification owner now validates
session/profile/event identity and commits the receiving turn before invoking the
source acknowledgement callback. TUI uses this owner. Tests reopen the session DB
after an acknowledgement failure and prove duplicate admission returns the same
turn without new execution; changed payloads, foreign ownership and failed writes
never acknowledge. Background dispatch also falls back to its parent/root session
when classic CLI execution has no approval-session context. Real worker/journal
tests cover CLI fallback, inherited nested ownership and explicit gateway routing.
Focused combined verification: 54 passed. CLI queue envelopes and receiving-turn
execution/recovery integration are still pending; the shared primitive alone does
not complete delivery there.

Classic CLI receiving integration: both completion drains now enqueue an explicit
background envelope rather than discarding event identity. Idle delivery queries
saved journal events as well as queue hints. Background envelopes bypass slash/file
submission dispatch and use shared receiving admission before chat; reported model
completion, failure or interruption becomes the durable receiving state. Duplicate
admissions never invoke chat again. An early chat return without a model outcome is
interrupted, not success. The CLI adapter test verifies running state during chat,
completed persisted text, idle restoration and duplicate delivery. Shared execution
tests cover completed/failed/interrupted/missing outcomes. Focused combined set:
49 passed; strict gates and 76 architecture contracts passed. Explicit CLI display
and resumption of interrupted receiving receipts still need integration testing;
this checkpoint does not claim full recovery UX or messaging acceptance.

Messaging admission checkpoint: synthetic MessageEvent carries local journal
metadata separately from its platform reply anchor. The existing gateway execution
store remains the receiving owner: background input uses the journal event as its
client deduplication key, verifies identical persisted payload on redelivery, and
acknowledges only after create_run commits. Background persistence failure now
fails closed; ordinary incoming messages retain their existing policy. Interrupted
agent results terminalize as interrupted. Store reopen/conflict and adapter identity
checks plus adjacent routing/race tests passed (72 total); strict checks and 76
architecture contracts passed. This does not yet prove the full handler under
injected persistence/ack failures. Idle messaging recovery, queued-adapter crash
boundaries, session/profile context and end-to-end delivery remain required.

Idle messaging recovery checkpoint: the gateway owns a cancellable recovery task
that reads journal sessions requiring reconciliation/delivery and dispatches one
saved result per known idle session. Unknown/busy sessions retain their durable
records. Startup avoids replacing a live watcher; shutdown cancels/awaits the exact
owned task. Adapter busy handling leaves journal events pending instead of merging
them with user text or interrupting active work. Recovery tests run without queue
hints and verify acknowledgement remains downstream of adapter dispatch; the real
base-adapter test preserves pending user text and its interrupt flag. Focused
storage/recovery/adapter set: 48 passed (earlier adjacent set: 62 passed). Strict
checks and 76 architecture contracts passed. Full push gate follows. Remaining
acceptance includes complete gateway failure injection, interrupted receiving UX,
profile multiplexing and event-triggered job implementation.

Event-job worktree checkpoint (`/tmp/sfa-event-research`): scheduler execution/save/
delivery/marking has been lifted into shared `process_job`; existing scheduler
regressions pass. New `JobTriggerJournal` freezes first-admitted specifications,
compares SHA-256 input identities on duplicate delivery, and serializes scheduled
and event claims for the same job with a partial unique running-job index. Claims
use separate ownership tokens and terminal updates reject stale owners/conflicting
outcomes. Reopen and concurrent claim tests pass. This store is NOT wired into
scheduler/webhook execution yet and has no owner-death reconciliation; neither
claims nor event-job acceptance is complete. Next: shared execution claim wiring,
authenticated route binding, durable dispatch/recovery, no-probability-mutation
checks and actual HTTP/controlled-provider integration tests.

Shared execution claim wiring: `process_job` now admits a frozen trigger, obtains
its exclusive job claim, executes/saves/delivers/marks once, and persists the
terminal result. Duplicate or competing claims do not execute. A failed job-status
write is not attempted twice; failure to save the terminal trigger receipt does
not reclassify an already processed model outcome or rerun effects. Scheduler ticks
drain accepted triggers even with no due schedule, then refresh due-job state.
Controlled scheduler tests prove a saved event executes once across two ticks and
that an interrupted status write does not repeat model execution or status marking.
Combined scheduler/storage checks: 138 passed; strict gates passed. Still required:
HTTP route binding, event-vs-scheduled cadence semantics, process-owner recovery,
configuration/profile binding and full integration acceptance.

HTTP binding checkpoint: authenticated routes with `cron_job` durably admit the
exact stored job before prompt/skill rendering or volatile deduplication. Delivery
IDs are mandatory/bounded, route-scoped, and conflicting body hashes are rejected.
Unsigned/insecure job routes, disabled/missing jobs, conflicting delivery-only mode
and mismatched job-store profile fail closed. Explicit route-profile overrides are
currently rejected pending proper profile-scoped dispatch. Job runs preserve
recurrence/repetition fields for webhook triggers while recording outcome metadata.
A real aiohttp client/server test verifies signature refusal, accepted admission,
duplicate identity, conflicting replay and unchanged stored prompt. Seven focused
HTTP/shared-execution tests passed; the adjacent set passed 136. Root push gate
failed one partial-startup fixture (32,355 passed); c5b0bdfe29 fixes watcher lookup,
66 startup/routing tests pass, and the canonical push retry runs separately under
session 66595, log /tmp/research-background-recovery-retry-push.log.

Job owner recovery checkpoint: version 2 trigger claims capture host/PID/process
creation time. Scheduler recovery terminalizes only positively exited local owners,
never reexecutes those triggers, and leaves legacy/foreign/unverifiable claims
unchanged. Host identity is shared with background research. Tests cover a real
child process exiting after claim, PID reuse, live owners, foreign owners and v1
migration with no invented identity. The first expanded test run exposed unclosed
SQLite connections in the new test fixtures; their context managers now explicitly
close connections instead of only committing transactions. The corrected expanded
storage/scheduler/HTTP set is recorded in /tmp/research-job-owner-final2.log.
Profile routing and broader recovery/product acceptance remain unfinished.

Profile-scoped job storage: reads/writes/output paths now honor `storage_home()`
without changing compatibility globals. Scheduler ticks bind their owning storage;
webhook adapters capture their launch profile and may resolve an explicit existing
route profile for exact job lookup/admission. The target profile requires its own
active scheduler; accepted HTTP state does not claim execution. Two-profile tests
exercise identical job IDs, separate frozen input/output paths and unchanged event
recurrence/repeat counters. Actual HTTP verifies explicit target-profile admission
without creating a trigger journal in the launching profile. Background milestone
push through c5b0bdfe29 succeeded after the canonical full Python and frontend gates.
Remaining event acceptance includes route-edit/redelivery policy, runtime-profile
credential isolation, job-status write/recovery semantics, and full HTTP-to-execution
failure injection; interrupted-receipt UI/resume and broader capability audits also
remain open.

Event-job checkpoint verification: the full cron directory plus trigger/background
storage and webhook integration/adapter/direct-delivery sets passed 477 tests in
6.98 seconds. Strict checks passed. This is a checkpoint, not final capability
acceptance or full-suite verification of the event-job changes.
