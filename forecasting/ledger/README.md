# Forecast ledger

Owns durable questions, evidence, resolutions, scores, lessons and workflow state through the ledger facade and focused storage modules.

## Ownership and boundaries

This is the admission boundary for persistent forecasting state. Enforce semantic contracts before writes, preserve provenance, and make lifecycle retries atomic and idempotent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                   | Responsibility                                                                |
| -------------------------------------- | ----------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)             | Forecast ledger package (façade over carved domain modules).                  |
| [core.py](core.py)                     | SQLite forecast ledger for the forecasting fork.                              |
| [alerts.py](alerts.py)                 | Alerts domain (D7 carve — the desk's health engine + alert_events lifecycle). |
| [anchors.py](anchors.py)               | Outside-view anchor re-linking — the mechanical orphaned-anchor remediation.  |
| [autopilot.py](autopilot.py)           | Autopilot + forecast-update-proposal domain (carved from core).               |
| [backtest.py](backtest.py)             | Baseline / benchmark / backtest scoring domain (carved from core).            |
| [deviation_bets.py](deviation_bets.py) | Deviation-bet domain (UPGRADE 2 — the deviation ledger).                      |
| [evidence.py](evidence.py)             | Evidence + information-triage domain (D3 carve).                              |

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
