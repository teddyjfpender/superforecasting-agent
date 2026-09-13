# Forecasting tests

Exercises forecasting behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                           | Responsibility                                                                                                                                             |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [pm_helpers.py](pm_helpers.py)                                 | Shared helpers for the prediction-market (forecasting/pm) test suite.                                                                                      |
| [test_ablation_study.py](test_ablation_study.py)               | Panel-vs-solo ablation runner — pairing, verdicts, and the empty-ledger honesty.                                                                           |
| [test_active_lessons_origin.py](test_active_lessons_origin.py) | Origin gating for active calibration-lesson adjustments.                                                                                                   |
| [test_alert_lifecycle.py](test_alert_lifecycle.py)             | Warnings-lifecycle: enqueue dedup, the domain-error flood, condition-based auto-close reconciliation, age escalation, and the one-time collapse migration. |
| [test_alert_reconcile.py](test_alert_reconcile.py)             | Checks: alert reconcile.                                                                                                                                   |
| [test_analyst_notes.py](test_analyst_notes.py)                 | Checks: analyst notes.                                                                                                                                     |
| [test_anchor_relink.py](test_anchor_relink.py)                 | Orphaned-anchor re-link — the mechanical remediation for a reference class that EXISTS on a question but is ABSENT from its current snapshot's refs.       |
| [test_api_keys.py](test_api_keys.py)                           | Tests for the API-key registry, .env read/write/activate, and the CLI surface.                                                                             |

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
