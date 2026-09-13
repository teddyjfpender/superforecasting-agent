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
