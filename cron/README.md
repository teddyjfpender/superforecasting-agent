# Scheduled execution

Stores and executes scheduled tasks in isolated sessions, with scheduler admission and delivery integration.

## Ownership and boundaries

Retain job identity across retries and use shared locks to prevent duplicate execution. Scheduled research may create evidence and alerts but must not silently alter active forecast probabilities.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                         | Responsibility                                         |
| ---------------------------- | ------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)   | Cron job scheduling system for Superforecasting Agent. |
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

## Event-triggered research

Authenticated webhook routes may bind `cron_job` to an existing exact job ID and
optionally select `profile`. Admission snapshots the stored job and records the
route/delivery identity and body digest; it does not substitute the route prompt
or payload for the job prompt. The owning profile's scheduler drains accepted
triggers through the same `process_job` operation as scheduled runs. That profile
needs an active scheduler; HTTP acceptance means durably queued, not executed.

Event runs record outcomes but preserve the scheduled recurrence and repetition
counter. `storage_home()` binds job files and outputs without global path mutation.
Trigger receipts live in the profile's `research-job-triggers.db`; a confirmed dead
execution owner becomes interrupted and is never automatically rerun. Operators
must inspect possible external effects before starting a new trigger.

All scheduler-launched scripts, including pre-checks and script-only jobs, inherit
`FORECAST_COMMIT_POLICY=proposal_only`. The shared runner overrides a permissive
launch-shell value so ledger APIs refuse unattended probability commits, just as
they do for scheduled agents. This policy is not a sandbox for arbitrary scripts.
