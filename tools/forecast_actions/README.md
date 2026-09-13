# Forecast tool actions

Maps model tool actions to forecast questions, evidence, research, resolution, calibration and review operations.

## Ownership and boundaries

Use the same application validation as CLI and TUI. Do not coerce ambiguous measurements or bypass ledger invariants to satisfy a model request.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------- |
| [**init**.py](__init__.py)               | Tool-action registry for the forecast ledger tool.                      |
| [models.py](models.py)                   | Model-run, living-model and bayes-toolkit actions.                      |
| [autopilot.py](autopilot.py)             | Autopilot and forecast-update-proposal actions.                         |
| [calibration.py](calibration.py)         | Calibration, operator, backtest, correction and lesson actions.         |
| [diagnostics.py](diagnostics.py)         | Doctor/pilot reports, exports, protocol and pipeline actions.           |
| [evidence.py](evidence.py)               | Evidence, baselines, assumptions, reference-classes and forecast-links. |
| [forecast_update.py](forecast_update.py) | The forecast-production path (full_forecast, update_forecast).          |
| [markets.py](markets.py)                 | Market-quality, prediction-market and research-audit actions.           |

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
