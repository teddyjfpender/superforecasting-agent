# Runtime correctness closeout — 2026-09-13

Scope: the six requested runtime, cancellation, integrated recovery, strict-quality,
source-contract and documentation items. Focused implementation verification is complete; publication is subject
to the full-suite pre-push gate.

Implemented:

- Managed HTTP clients retain exact connections if HTTPX/httpcore close fails;
  cleanup retries preserve replacement clients. SDK construction failures dispose
  their owned HTTP client. Unknown third-party close implementations remain pending
  rather than being falsely declared clean.
- Removed SDK socket peeking/blocking-mode mutation from agent recovery. Closed
  client replacement is serialized under its owner lock.
- Conversation deadlines include queuing/construction time, interrupt the exact
  active agent, reject late outcomes and retire interrupted cached agents. Timer
  callbacks drain before reuse. Non-cooperative calls retain admission until exit.
- Browser cleanup records PID plus creation time, uses identity-aware termination,
  and waits for exit. Unverified legacy live daemons fail closed. Cloud allocation
  errors preserve an allocation-bound disposer before endpoint validation/fallback.
- Skills Hub HTTP uses request-scoped cooperative cancellation through headers/body
  and waits for teardown. Parallel source searches inherit their cancellation
  context; quarantine/install publication checks cancellation before mutation.
- Pure economic numeric parsing rejects noncanonical numeric strings, overflow and
  identical duplicate rows; existing entity/unit/period/revision checks remain.
- New ownership modules join strict checks. Current TODO and ownership documentation
  replace chronology; historical text is archived with explicit labels.

Focused evidence so far: 47 SDK/conversation/market checks; 301 Skills Hub/browser/
command checks; 34 source/cancellation/real-TUI checks, including repeated dashboard
reconnects with durable failed/completed receipts. Shared quality: 76 import
contracts passed. These precede the final integrated batch; they do not substitute
for its full-suite result.

Final focused evidence: 60 ownership/cancellation/settlement checks passed; 56
integrated recovery checks passed (including real Ink/PTY/dashboard/SQLite and
repeated authenticated headless connections). Browser identity/provider allocation
checks passed 28 tests. The broad regression run found four legacy reaper tests
expecting unchecked PID termination; these now assert identity-aware behavior and
pass. A new allocation failure regression confirms fallback cannot discard a
resource whose disposer failed. New numeric lexical cases also run through actual
ledger settlement admission, not only the parser.

Quality gates pass, including all 76 import contracts and strict checks expanded to
browser provider validation, retained HTTP transport cleanup and economic parsing.
Final full-suite publication evidence: `/tmp/forecast-six-final-push.log`.

Limits: macOS local-provider evidence does not qualify every supported platform or
live integration. Cancellation inside arbitrary third-party code is cooperative;
non-cooperative work retains ownership until it exits. Unknown third-party SDK
cleanup remains fail-closed; only explicitly owned retryable transports can be
certified by successful retries. Legacy live daemon records without creation
identity are retained for operator review, never killed speculatively. The historical
native SSL crash still has no proven attribution; removal of raw socket mutation
is a concrete independent correction, not a retrospective root-cause claim.
