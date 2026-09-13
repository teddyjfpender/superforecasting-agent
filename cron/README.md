# Scheduled execution

Stores and executes scheduled tasks in isolated sessions, with scheduler admission and delivery integration.

## Ownership and boundaries

Retain job identity across retries and use shared locks to prevent duplicate execution. Scheduled research may create evidence and alerts but must not silently alter active forecast probabilities.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                         | Responsibility                                         |
| ---------------------------- | ------------------------------------------------------ |
| [**init**.py](__init__.py)   | Cron job scheduling system for Superforecasting Agent. |
| [jobs.py](jobs.py)           | Cron job storage and management.                       |
| [scheduler.py](scheduler.py) | Cron job scheduler - executes due jobs.                |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/cron/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
