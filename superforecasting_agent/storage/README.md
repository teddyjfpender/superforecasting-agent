# Durable profile storage

Owns atomic configuration and authentication updates, session databases, transcripts, snapshots and profile admission.

## Ownership and boundaries

Use shared locks and revision-aware updates. Preserve unrelated settings, verify snapshot admission, and never close or overwrite resources borrowed from another owner.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                                    |
| ------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                             | Session persistence infrastructure for the forecasting desk.                      |
| [configuration.py](configuration.py)                   | Shared profile configuration snapshots and revision-checked persistence.          |
| [auth.py](auth.py)                                     | Auth-store schema and durable file IO, with explicit profile paths.               |
| [credential_policy.py](credential_policy.py)           | Credential-pool disk-boundary sanitization helpers.                               |
| [curator_state.py](curator_state.py)                   | Curator scheduling state with serialized, atomic field updates.                   |
| [environment.py](environment.py)                       | Read profile credential files without CLI initialization or environment mutation. |
| [files.py](files.py)                                   | Atomic JSON/YAML writes that preserve symlinks and file permissions.              |
| [forecast_configuration.py](forecast_configuration.py) | Read-only layered forecast settings, independent of diagnostics and execution.    |

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
