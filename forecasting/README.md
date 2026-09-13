# Forecasting domain

Owns scoreable questions, evidence, probability histories, settlement, scoring and calibration learning. This package is the durable forecasting system consumed by each product.

## Ownership and boundaries

Route writes through the ledger and application operations. Acquisition labels are not semantic domains; imported claims are not locally verified observations. Preserve explicit distribution and censoring semantics.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                             | Responsibility                                                                    |
| ------------------------------------------------ | --------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                       | Forecast-native domain package for the Superforecasting Agent fork.               |
| [models.py](models.py)                           | Core forecast ledger domain models.                                               |
| [ablation_study.py](ablation_study.py)           | Panel-vs-solo ablation — does the panel machinery earn its cost?                  |
| [agent_protocol.py](agent_protocol.py)           | Agent-protocol probability source for historical forecast replay.                 |
| [api_keys.py](api_keys.py)                       | API-key registry + .env read/write/activate for the forecast desk.                |
| [appconfig.py](appconfig.py)                     | Typed, layered configuration for the forecast desk (architecture review item #8). |
| [applicability_facts.py](applicability_facts.py) | Source-bound, timestamped applicability facts extracted from archived JSON.       |
| [argv.py](argv.py)                               | Argument splitting helpers for forecast CLI command strings.                      |

## Subdirectories

- [application/](application/README.md) — Forecast application operations.
- [change_control/](change_control/README.md) — Auditable forecast changes.
- [cli/](cli/README.md) — Forecast CLI adapters.
- [collab/](collab/README.md) — Forecast collaboration.
- [configuration/](configuration/README.md) — Forecast configuration.
- [dashboard/](dashboard/README.md) — Forecast dashboard projections.
- [github/](github/README.md) — GitHub collaboration integration.
- [hooks/](hooks/README.md) — Forecast signal hooks.
- [interfaces/](interfaces/README.md) — Forecast interface contracts.
- [jobs/](jobs/README.md) — Forecast job runtime.
- [ledger/](ledger/README.md) — Forecast ledger.
- [marketdata/](marketdata/README.md) — Market-data service.
- [pm/](pm/README.md) — Prediction-market integration.
- [quorum/](quorum/README.md) — Forecast quorum estimation.
- [sources/](sources/README.md) — Evidence source adapters and parsers.
- [transports/](transports/README.md) — Forecast collaboration transports.
- [workspace/](workspace/README.md) — Portable forecast workspaces.

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
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
