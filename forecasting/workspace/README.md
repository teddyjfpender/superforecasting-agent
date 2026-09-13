# Portable forecast workspaces

Builds and validates Git-backed workspace manifests and projections for portable forecasting records.

## Ownership and boundaries

Validate versioned schemas and provenance on import. Transferred evidence retains its verification status; a matching digest alone does not establish local verification.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                          |
| ------------------------------ | ----------------------------------------------------------------------- |
| [**init**.py](__init__.py)     | Portable Git workspace projection and validation.                       |
| [bootstrap.py](bootstrap.py)   | Validated staging reconstruction from a portable forecast workspace.    |
| [git.py](git.py)               | Conservative argv-only Git operations for managed forecast workspaces.  |
| [manifest.py](manifest.py)     | Canonical forecast workspace manifest.                                  |
| [projection.py](projection.py) | Deterministic portable projection of the authoritative forecast ledger. |
| [validation.py](validation.py) | Fail-closed validation for portable forecast repositories.              |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
