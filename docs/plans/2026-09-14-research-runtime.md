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
