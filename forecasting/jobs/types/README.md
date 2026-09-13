# Forecast job implementations

Implements refresh, reforecast, warning, quorum, backup and maintenance tasks using the shared job context.

## Ownership and boundaries

Keep scheduling and durable state transitions in the parent runtime. Task implementations must respect cancellation and avoid publishing late results.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                                                                                                                                    |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)     | init .                                                                                                                                                                            |
| [backup.py](backup.py)         | The BACKUP job type: a durable, online SQLite backup + integrity check of the forecast ledger on the one detached-job runtime (Arc B).                                            |
| [quorum.py](quorum.py)         | The QUORUM job type: the multi-model Delphi forecast on the one detached-job runtime (Arc B3).                                                                                    |
| [reforecast.py](reforecast.py) | The REFORECAST job type: the operator's Desk "mass LLM re-run" on the one detached-job runtime (Arc B2).                                                                          |
| [refresh.py](refresh.py)       | The REFRESH job type: the operator's Desk "Update now" (`U` / mass-`U`) on the one detached-job runtime (Arc B) — the runtime's FIRST net-new capability, the Arc-B payoff proof. |
| [task.py](task.py)             | The TASK job type: the operator's Desk free-text "fix loop" on the one detached-job runtime (Arc B2).                                                                             |
| [warnings.py](warnings.py)     | The WARNINGS job type: a background sweep of the open `alert_events` backlog.                                                                                                     |
| [wiki_prune.py](wiki_prune.py) | The WIKI_PRUNE job type: the second brain's anti-rot pass on the runtime.                                                                                                         |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
