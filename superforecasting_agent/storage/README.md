# Durable profile storage

Owns atomic configuration and authentication updates, session databases, transcripts, snapshots and profile admission.

## Ownership and boundaries

Use shared locks and revision-aware updates. Preserve unrelated settings, verify snapshot admission, and never close or overwrite resources borrowed from another owner.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                         | Responsibility                                               |
| -------------------------------------------- | ------------------------------------------------------------ |
| [configuration.py](configuration.py)         | Revision-checked configuration snapshots and atomic updates. |
| [auth.py](auth.py)                           | Credential-store schema and durable persistence.             |
| [files.py](files.py)                         | Atomic file replacement preserving permissions and symlinks. |
| [session.py](session.py)                     | Public SessionDB facade.                                     |
| [sqlite.py](sqlite.py)                       | Shared SQLite storage support.                               |
| [snapshots.py](snapshots.py)                 | Backup and snapshot restore operations.                      |
| [profile_lease.py](profile_lease.py)         | Exclusive profile admission for offline operations.          |
| [credential_policy.py](credential_policy.py) | Secret ownership policy at the persistence boundary.         |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/storage/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

## SQLite filesystem admission

[sqlite_filesystem.py](sqlite_filesystem.py) resolves the containing Linux mount
from fresh mountinfo on each database admission. [sqlite.py](sqlite.py) applies
the shared journal policy for sessions, the forecast ledger and kanban. Known
virtiofs/9p mounts use rollback journaling for new databases. An existing WAL
database on such a mount fails closed with offline relocation guidance: opening
another connection must never convert a live database's journal mode. Unknown
mounts retain the reactive compatibility fallback.

Regression coverage: `tests/test_storage_sqlite.py`,
`tests/forecasting/test_cross_vm_sqlite.py` and
`tests/forecasting/test_ledger_wal.py`.

## Context usage baselines

[context_usage.py](context_usage.py) stores a versioned context baseline under a
reserved session-model metadata key. Updates run inside the existing SQLite
write transaction and preserve unrelated settings. Reads reject malformed
metadata, and a missing session is never recreated solely for accounting. The
agent owner validates the entire priced prefix and request identity before
using a restored baseline; storage does not infer that an old count still applies.

## Background research journal

[background_research.py](background_research.py) stores batch admission, member
outcomes and pending delivery events in the active profile's
`background-research.db`. Admission freezes every member before execution;
completion and its notification commit together. Independent members can deliver
immediately, grouped members retain their input order and wait for their group,
and failures generate an early event even while siblings run.

Execution adapters own redaction, capacity, worker liveness and cancellation.
The journal requires the original owner token to start or finish a task and
never re-executes a model call. An accepted/running record after a restart is
unconfirmed work, not proof of live execution. Consumers acknowledge an event
only after durable delivery; querying pending events never acknowledges them.
These primitives are being integrated into background dispatch and TUI recovery.
