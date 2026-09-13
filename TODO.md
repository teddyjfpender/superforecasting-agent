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

## Further qualification

- [ ] Verify installed products on native Linux, Windows and Android/Termux.
- [ ] Verify a successor independent terminal package upgrade when one exists.
- [ ] Complete live credential-dependent integrations and release publication.
- [ ] Attribute the historical native SSL crash if original runtime/certificate
  artifacts or a credible reproducer become available. Containment is implemented;
  the original cause remains unproven.

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
