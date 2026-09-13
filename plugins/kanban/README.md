# Task-board plugin

Implements the task board, worker dispatch and dashboard integration through plugin registration.

## Ownership and boundaries

Keep board persistence and worker execution identities consistent. Core runtime must consume the plugin interface rather than hardcoding task-board behavior.

## Subdirectories

- [dashboard/](dashboard/README.md) — dashboard.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
