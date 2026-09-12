# Active engineering backlog

The current priority is reusable product boundaries and enforceable repository
hygiene. This is an implementation backlog, not a list of forecasting operations.
The [ownership map](docs/architecture/ownership-map.md) defines module owners;
the [architecture work log](docs/plans/2026-09-11-product-boundaries.md) records
changes, tests and their limits. The previous checklist is preserved in the
[chronological archive](docs/plans/2026-09-12-todo-archive.md).

## 1. Finish application and product boundaries

- [ ] Migrate remaining classic slash-worker commands to shared operations.
  The TUI must not need a second classic CLI runtime to execute business behavior.
  Native handoff now uses host/session admission and the shared waiter: local timeouts now cancel only unclaimed pending work, and running/terminal gateway states cannot be overwritten by timeout. Attempt identity is now enforced on gateway transitions and CLI cancellation/waiting. Shared application observation/waiting returns durable outcomes on cancellation, and the CLI borrows host storage without opening a fallback connection; native progress/completion is verified through the real terminal with a simulated destination. Foreground/background admission now shares durable handoff validation, including reconnected sessions and read failures. A real terminal test now covers cancelling a claimed-transfer wait, retained-PTY dashboard reconnect, blocked source work and a new independent session. Interrupted gateway recovery and cross-platform handoff qualification remain to be completed.
  Preserve aliases, validation, error semantics and state ownership. Configured aliases already redispatch through the local TUI registry. Messaging-only commands now fail before worker construction; /whoami metadata no longer advertises unavailable terminal behavior. Snapshot
  listing, creation and pruning now share application/storage owners;
  host-coordinated live restoration remains to be implemented. Restore now stages
  all files before publication and rejects partial success. A versioned restore
  journal retains hash-verified copies for idempotent recovery after process death;
  host-wide writer quiescence and restore/recovery admission remain prerequisites. Kanban now runs
  natively with host/session cancellation and visible activity. Real terminal tests
  cover watch, resizing, Ctrl+C, gateway death/reconnect and continued command use.
  Extended remote-host command recovery remains to be qualified.
- [ ] Finish separating agent construction from RPC orchestration. Deferred-build
  admission/retry, initialization completion and partial-agent retention, and notification polling/admission now belong to the host;
  protocol event delivery remains an adapter responsibility.
- [ ] Reduce the remaining frozen domain-to-runtime/tool import exceptions.
  Move a capability and its tests together; directory moves alone are insufficient.
  Shared defaults/normalization and read-only profile access are now independent.
  Ledger scoring/snapshot settings, hook policy and estimate-first policy use them;
  scheduler, worker and research readers use the same owner. Quorum command reads and writes now use independent configuration and installation
  owners. Startup environment loading is now independent too. Connected-panel selection rules now run on supplied provider snapshots in a pure forecasting module; discovery remains in the adapter. Market forecasters now leave plugin initialization to the tool runtime when the default agent is first constructed. The remaining runtime exception is quorum provider discovery/model selection; tool exceptions remain separately tracked by the import contract.

Already implemented: shared forecast review/resolution/scoring, command catalog
and aliases, configured-command validation/execution, session selection and
branching, native command handoffs before model initialization, shared goal-command transitions, shared retry preparation with validation before history mutation, shared complete-exchange undo with locked TUI admission and no model initialization, shared positive-integer agent budget selection
across configuration normalization, classic CLI, TUI and gateway environment bridges, shared configuration inspection
(including live session settings and credential-safe reporting), shared toolset/insights/
quota/platform inspection, curator operations and runtime selection, and lazy legacy worker admission.
Tool inventory and /tools list now use shared views without building an agent or classic worker. Tool changes share strict name validation; malformed RPC input is rejected before configuration access or session reset. Native /agents, /tasks and /stop now use shared background operations; hosted inspection and cancellation select the current session in both process and delegation registries. The remaining /skills slash commands now call the same Skills Hub operations as the CLI, with isolated output and no classic worker. Nested update/import installs are explicitly non-interactive. Native /debug now uses shared diagnostics with request-local dump/output capture and no agent or worker construction. Footer inspection/mutation now uses a shared application owner across CLI, gateway and native TUI; toggles read the latest global value under the writer lock and preserve platform overrides. The legacy dispatcher remains for other commands.

## 2. Finish resource ownership and recovery

- [ ] Qualify delegation dashboard controls with rendered nested-work and reconnect
  exercises. Status, pause and interruption now require the current session owner;
  nested children inherit the root owner and stale client replies are discarded.
  A real-terminal pause/new-session/resume exercise now verifies distinct backend
  pause owners and successful continued conversation.
  Ink /stop consumes the shared session-scoped operation, and legacy process.stop
  rejects missing session ownership. The hosting delegation owner now centralizes
  pause/registry state and rejects replacement or stale retirement of a live child.
  Pause flags remain process-lifetime state.
- [ ] Audit lower-level agent cleanup for concrete resource ownership.
  Tool-triggered resets now reserve host replacement before saving, dispose the
  previous agent/worker, and retain failed construction state and history. Saved
  configuration may outlive a failed reset. The macOS real-terminal harness now
  verifies successful reset and failed-reset/new-session recovery against saved
  configuration, agent ownership and durable turn receipts.
  Live market conversation agents now have an explicit owner: per-call disposal,
  batch close for cached agents, and retained failed-close handles. The CLI releases
  the owner after recording, including failures. The existing market forecaster
  timeout argument still does not enforce an execution deadline.
  Do not retry task-ID cleanup if it could close a replacement component's resources.
  Registry assignment rejects a different existing owner, including builds and
  failed cleanup. Membership now has no raw mapping removal/update APIs; callers
  must retire explicitly, and isolated fixtures verify quiescence before disposal.
- [ ] Close remaining partial-construction and shutdown failure paths with
  deterministic failure injection and retained cleanup handles. Delegated child
  close failures now retain exact handles and diagnostics; session-scoped /stop
  and session disposal retry them, with session close remaining pending on failure. Child cleanup
  retries retain exact handles; failed SDK close remains pending because HTTPX
  can mark itself closed before transport disposal fails. Safe recovery of those
  transports and terminal/browser cleanup failures is still unfinished. Browser
  supervisors now retain failed startup/stop handles and reject overlapping
  lifecycle mutations. CLI/TUI now share endpoint transitions and surface
  supervisor cleanup failures. Browser tool admission now drains before global
  endpoint changes; failed cloud/Camofox disposal retains exact handles, and
  bundled cloud disposers retain allocation credentials. Emergency bulk cleanup,
  malformed allocations and lower-level local daemon disposal remain to audit.
  Disconnect now suppresses the saved CDP
  endpoint for the running process without rewriting the profile.
- [x] Remove the legacy global goal database cache. Standalone managers own
  closable connections; CLI, gateway and TUI managers borrow their host storage.
  Manager reads refresh and writes reject stale state. Hosted goal paths never
  open an implicit fallback database.
- [ ] Extend installed remote-host/provider recovery exercises to longer sessions.

Already implemented: host-owned workers, session registry/storage, profile
configuration, device sign-in, build admission/retry, notification admission and
command subprocess cleanup. Durable turn receipts now belong to storage; the host
finalizes drained turns before session disposal and retains resources on write failure. SDK transports own socket teardown; client eviction
detaches exact handles before cleanup so concurrent replacements survive. Real
Ink/dashboard/local-provider/SQLite recovery tests exist. TUI submission callbacks
now retain their originating session: delayed file detection and request errors
cannot send into or reset a replacement session. Shell completion, interpolation
and failed steering now apply the same session ownership rule.

## 3. Complete distribution qualification

- [ ] Exercise additional supported platform combinations, especially native
  Windows and Android/Termux; POSIX PTY evidence does not establish their behavior.
- [ ] Keep a retained prior backend artifact in release qualification and run
  `verify_profiles.py --upgrade-from` against each candidate.
- [ ] Qualify upgrades between terminal versions when a successor terminal
  artifact exists; the current independent terminal package is still 0.1.0.

Already implemented: separate backend/CLI and terminal wheels, optional web
hosting, protocol/capability negotiation, backend execution without Node,
independent local/remote terminal verification, and a macOS installed
0.21.2 → 0.22.0 backend upgrade preserving forecast/evidence/session/configuration.
See the work log for artifact hashes; this is not a published-release claim.

## 4. Maintain enforceable repository hygiene

- [ ] Expand strict lint/format/type coverage as inherited owners are extracted.
  Shared tooling and the entire storage package join configuration, hosting and application packages in
  directory-wide strict coverage. New files there are covered automatically;
  older code elsewhere still has narrower checks.
- [ ] Keep ownership documentation, generated protocol references and extension
  guides aligned with code. Reconcile older website guides and compatibility names.
- [ ] Verify the final integrated batch with the shared gates before pushing.

Already implemented: `python3 scripts/dev.py bootstrap` installs hooks and runs
the same quality workflow as CI; `check` runs lint/format/types/import/protocol
checks. Every push runs the full Python suite, matching the repository development policy.
Import contracts enforce extracted owners; frozen exceptions remain explicit.

## 5. Other engineering follow-up

- [ ] Conclusively attribute the historical native SSL crash if original incident
  artifacts or a reproducer become available. Containment and native experiments
  are verified; the original cause remains unproven.
- [ ] Continue source-adapter parser/semantic separation where unsupported units,
  timestamps, revisions or identities could otherwise reach settlement.
- [ ] Complete credential-dependent integration and formal release verification
  when that work is resumed. Source pushes are not release publication.

Forecast pilots, deferred settlements and operational lesson evaluation are
tracked in the archive and ledger. They do not block this structural workstream.

Skills Hub follow-up: provide cooperative cancellation for in-progress hub I/O. Native dispatch currently retains host ownership until the operation returns. Shared parsing now accepts quoted arguments, snapshot stdout uses the caller output sink, and batch/TUI installation results reflect actual completed installs.
