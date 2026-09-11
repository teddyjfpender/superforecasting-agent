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
  Preserve aliases, validation, error semantics and state ownership.
- [ ] Finish separating agent construction and notification wiring from RPC
  orchestration. Deferred-build admission/retry now belongs to the host.
- [ ] Reduce the remaining frozen domain-to-runtime/tool import exceptions.
  Move a capability and its tests together; directory moves alone are insufficient.

Already implemented: shared forecast review/resolution/scoring, command catalog
and aliases, configured-command validation/execution, session selection and
branching, native command handoffs before model initialization, and lazy legacy
worker admission. The legacy dispatcher itself remains.

## 2. Finish resource ownership and recovery

- [ ] Audit lower-level agent cleanup for concrete resource ownership.
  Do not retry task-ID cleanup if it could close a replacement component's resources.
- [ ] Close remaining partial-construction and shutdown failure paths with
  deterministic failure injection and retained cleanup handles.
- [ ] Extend installed remote-host/provider recovery exercises to longer sessions.

Already implemented: host-owned workers, session registry/storage, profile
configuration, device sign-in, build admission/retry, and command subprocess
cleanup. Real Ink/dashboard/local-provider/SQLite recovery tests exist.

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
  New files in strict directories are covered automatically; older code still
  has narrower checks.
- [ ] Keep ownership documentation, generated protocol references and extension
  guides aligned with code. Reconcile older website guides and compatibility names.
- [ ] Verify the final integrated batch with the shared gates before pushing.

Already implemented: `python3 scripts/dev.py bootstrap` installs hooks and runs
the same quality workflow as CI; `check` runs lint/format/types/import/protocol
checks. Python paths unknown to the push-hook mapper fall back to the full suite.
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
