# Engineering integrity follow-up

This pass concerns software behavior and isolated fixtures, not operating a
forecast cohort, settling live questions, or claiming that learning improves
accuracy. Release publication and CI monitoring remain outside scope.

## Settlement and score boundaries

`forecasting.ledger.resolutions.validate_resolution` is shared by normal
resolution writes and packet imports. Confirmed numeric outcomes cannot bypass
validation by setting `scoreable=False`. Confidence must be a finite numeric
value; resolution flags must be booleans. Existing source-specific settlement
contracts still enforce entity, units, measurement window, source and archive.
Source-bound packets without locally verified evidence fail closed; an imported
capture claim is not promoted to a local fetch receipt. Full-instance migration
should use the existing database backup rather than treating a JSON packet as
a transfer of source authority. Imports validate outcome spaces, declared censoring tails and score provenance;
invalid packets roll back as a unit. String boolean flags cannot silently become
true. Legacy integer flags are accepted only as 0 or 1.

An explicit tail key remains authoritative even beside a valid Gaussian payload.
Missing, string, boolean, nonfinite or out-of-range tails cannot fall back to a
Gaussian. Imported censored scores must match the declared threshold calculation
and remain excluded from calibration. A forced rescore now creates a correction
that invalidates the prior score and derived learning, retaining their history.
The replacement score queues its own finalization handoff, even if the original
resolution task already completed. A superseded score task cannot finalize a
different current score.

These checks enforce structured contracts. They do not infer semantic truth from
free-form resolution prose or establish that an arbitrary external source is
canonical. New source families still need explicit verified measurement bindings.

## Atomic lifecycle and repair

Resolution validation, persistence, scheduler teardown and the durable handoff
are serialized together. Identical resolution retries reuse the resolution and
handoff. Scoring and postmortem check-and-create operations use write transactions,
so concurrent ledger instances cannot create duplicate records on ordinary retry.
Postmortem and lesson writes commit together. Nested transactions use savepoints:
a caught inner failure cannot leave partial writes in a successful outer commit.

Finalization commits its score, postmortem, lesson and task completion together;
completion is returned only after commit. Existing queue leases and attempts
remain the retry authority. Historical missing lesson handoffs appear as
`lesson_missing` and can be repaired through a separately keyed task in the same
leased finalization queue. Failures retain their attempt count and error; exhausted
repairs are not silently reset. Repair uses the
stored postmortem's lesson and provenance, preserving its identity; it never
replaces an existing lesson decision, including a superseded lesson.

## Configuration and shared command behavior

`storage.files.set_nested` owns dotted mapping/list navigation.
`atomic_roundtrip_yaml_update` holds a cross-process lock throughout the read,
modify and atomic replace. Classic CLI settings, runtime `config set`, and gateway
personality changes share that behavior. Model selection uses the same file lock.
`storage.locking.file_lock` owns the existing POSIX/Windows locking algorithm;
the authentication wrapper retains its compatibility and platform injection seams.

`load_config()` returns a dict-compatible revision-bearing snapshot.
`save_config()` rejects a stale snapshot or a snapshot from another profile.
The setup wizard uses `reload_config_in_place` after a picker saves settings,
refreshing both values and revision together. Callers must reload after that explicit conflict; no automatic last-writer-wins
retry is performed. Read-only configuration loads do not create lock files.
Malformed YAML is not replaced with defaults by setting commands. Raw dictionaries
passed to `save_config()` remain explicit whole-document replacements; use a
loaded snapshot or the setting updater when modifying existing configuration.

## Runtime and TUI recovery

SQLite connection construction now closes the handle if initialization is
interrupted, including by a `BaseException`. This addresses the leaked-handle
warning reproduced when a test deadline interrupted SQLite setup. Existing
callback-exception diagnostics and cached-statement authorization protection are
retained. No authorization rule is relaxed.

The update probe enables Python's fault handler and records abnormal exit status
and interpreter identity. Real subprocess tests cover signal termination and
wall-clock timeout with child reaping. They establish containment, not the root
cause of the historical Linux CPython 3.11.15 certificate-loading crash.

Gateway client stdout, stderr and WebSocket messages are guarded by transport
identity. A replaced or stopped transport cannot complete a current RPC, publish
stale readiness, or contaminate the resumed session. The regression sends a stale
reply with the new request ID and verifies that only the current socket's reply
is accepted. Late socket opens cannot reconnect the sidecar after teardown.

## Source parsing and test isolation

`forecasting.sources.bls_parsing` is pure response parsing; `bls` owns fetching.
The parser preserves zero, requires the requested series identity, rejects
nonfinite/text values and conflicting same-period revisions, and collapses exact
duplicates. Observation months are no longer fabricated publication timestamps:
publication remains unknown unless independently supplied. The original period
and raw row remain available for provenance.

All JSON source adapters now use the existing strict JSON decoder. Duplicate
object keys, nonfinite constants and floating-point overflow literals are rejected.
A BLS observation period or latest revised series value is not proof of historical
availability; backtests still require independently admissible availability data.

The promotion CLI test now uses an isolated ledger. Historical book audits require
an explicitly supplied `FORECAST_TEST_AUDIT_DB`; ordinary test runs no longer
select the operator's real ledger via `Path.home()` in that module.

## Verification

- Canonical Python suite: **30,324 passed, 148 skipped**, 51 warnings, 599.28s.
  Command: `scripts/run_tests.sh`. Local JUnit artifact:
  `.test-results/pytest-20260911T130433Z-75098.xml`.
- Final ledger follow-up (score handoff and strict imported calibration flags):
  **52 passed**. Local JUnit artifact:
  `.test-results/pytest-20260911T131043Z-78657.xml`.

- TUI: 186 test files passed; 2,022 tests passed and one skipped. Build and
  TypeScript checks passed; packaged and development bundle SHA-256 values match.
- Real macOS terminal recovery: five configured-chat/cancellation/resize cases,
  three gateway-respawn cases and two dashboard reconnect cases passed.
- Final focused ledger/import/source regressions: 60 passed; forced-rescore and
  historical-repair checks: 35 passed; setup/picker conflict regressions: 43 passed.
- All six import-boundary contracts passed; generated documentation is current;
  configured lint and undefined-name checks passed on the changed Python files.

The canonical full Python runner excludes credential-dependent integration and
end-to-end directories. These local checks do not establish Android/Termux or
native Windows recovery, external-service availability, or forecasting skill.

