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
  Preserve aliases, validation, error semantics and state ownership. Snapshot
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
  owners. Startup environment loading is now independent too. Remaining exceptions
  are plugin discovery and quorum model construction.

Already implemented: shared forecast review/resolution/scoring, command catalog
and aliases, configured-command validation/execution, session selection and
branching, native command handoffs before model initialization, shared goal-command transitions, shared retry preparation with validation before history mutation, shared complete-exchange undo with locked TUI admission and no model initialization, shared positive-integer agent budget selection
across configuration normalization, classic CLI, TUI and gateway environment bridges, shared configuration inspection
(including live session settings and credential-safe reporting), shared toolset/insights/
quota/platform inspection, curator operations and runtime selection, and lazy legacy worker admission.
The legacy dispatcher itself remains.

## 2. Finish resource ownership and recovery

- [ ] Audit lower-level agent cleanup for concrete resource ownership.
  Live market conversation agents now have an explicit owner: per-call disposal,
  batch close for cached agents, and retained failed-close handles. The CLI releases
  the owner after recording, including failures. The existing market forecaster
  timeout argument still does not enforce an execution deadline.
  Do not retry task-ID cleanup if it could close a replacement component's resources.
  Registry assignment rejects a different existing owner, including builds and
  failed cleanup. Membership now has no raw mapping removal/update APIs; callers
  must retire explicitly, and isolated fixtures verify quiescence before disposal.
- [ ] Close remaining partial-construction and shutdown failure paths with
  deterministic failure injection and retained cleanup handles. Child cleanup
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
  Shared tooling now joins configuration, hosting and application packages in
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
