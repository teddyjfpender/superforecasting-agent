# Engineering backlog

Product boundaries, shared TUI/CLI operations, independent distributions and
contributor gates are delivered. This list tracks current work only; prior detail
is in [the history](docs/plans/2026-09-13-todo-history.md). See the
[ownership map](docs/architecture/ownership-map.md) for implementation boundaries.

## Delivered runtime correctness batch

- [x] Retain failed SDK cleanup and partial browser allocations; require daemon
  identity and confirmed exit before retirement.
- [x] Enforce conversation deadlines and Skills Hub HTTP cancellation, including
  parallel source search and prevention of publication after cancellation.
- [x] Exercise nested delegation and interrupted handoff recovery
  through the real TUI and repeated authenticated remote/dashboard reconnects.
- [x] Enforce shared blocking quality checks and the full Python suite before pushing.
- [x] Verify economic lexical/duplicate safeguards through settlement admission.

Implementation and focused evidence are recorded in
[the runtime closeout](docs/plans/2026-09-13-runtime-closeout.md). The pre-push hook requires the full suite;
focused checks do not substitute for that publication gate.

## Qualification follow-up

- [x] Verify installed backend and terminal on macOS ARM64 and Linux ARM64
  (Debian container on a native ARM64 Linux VM), including backend 0.19.0 →
  0.22.1 and terminal 0.1.0 → 0.1.1 upgrades and authenticated reconnects.
- [x] Fix Node 20 remote WebSocket launch and prerequisite checks; add a native
  Linux/macOS/Windows installation matrix for Node 20 and 22 with explicit skips.
- [x] Make explicitly selected live-service tests reachable through the canonical
  runner while preserving ordinary-suite credential isolation.
- [x] Prepare 0.22.1 release artifacts, validated manifest and checksums. Existing
  0.22.0 tag remains unchanged.
- [ ] Execute native Linux x86-64 and Windows installation checks; Windows terminal
  interaction still needs a ConPTY harness. Qualify a real Android/Termux device.
- [ ] Run Daytona/Modal checks with service credentials; neither is configured here.
- [ ] Merge the release candidate onto the default branch, then publish 0.22.1 through
  the formal workflow and verify downloaded assets and installation.
- [ ] Attribute the historical native SSL crash if original runtime/certificate
  artifacts or a credible reproducer become available. Recovered native evidence
  did not reproduce it; original binary and CA hashes are absent.

See [qualification evidence and commands](docs/verification/2026-09-13-products/README.md).

## Maintenance policy

Expand strict lint/format/type coverage when touching inherited owners; prefer
behavioral fixes over cosmetic file moves. New files in configuration, storage,
hosting, application, credentials and tooling receive strict checks automatically.
Keep protocol generation, extension documentation and compatibility aliases aligned
with code. Preserve forecast provenance and fail closed on unsupported source semantics.

Cancellation remains cooperative inside provider/plugin code: pending work retains
ownership until it exits. Do not report a non-cooperative call as stopped or dispose
its resources beneath it. Cross-platform evidence must identify the actual platform.

Live forecasting cohorts, settlements and learning evaluation belong in the ledger
and operational archive; they are not prerequisites for these engineering tasks.
