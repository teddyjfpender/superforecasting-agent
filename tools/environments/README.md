# Execution environments

Implements local, container, SSH and hosted terminal backends with shared configuration and file synchronization.

## Ownership and boundaries

Track the exact remote or local allocation and confirm termination before retiring it. Keep credentials and working directories profile-aware.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility                                                         |
| ------------------------------------ | ---------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)           | Superforecasting Agent execution environment backends.                 |
| [configuration.py](configuration.py) | Pure configuration mapping shared by terminal and file-tool sandboxes. |
| [base.py](base.py)                   | base.                                                                  |
| [daytona.py](daytona.py)             | Daytona cloud execution environment.                                   |
| [docker.py](docker.py)               | Docker execution environment for sandboxed command execution.          |
| [file_sync.py](file_sync.py)         | Shared file sync manager for remote execution backends.                |
| [local.py](local.py)                 | Local execution environment — spawn-per-call with session snapshot.    |
| [managed_modal.py](managed_modal.py) | Managed Modal environment backed by tool-gateway.                      |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tools/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
