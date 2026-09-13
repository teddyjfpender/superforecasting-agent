# Forecast CLI adapters

Registers and handles forecast subcommands, translating command-line input into forecasting operations and readable or structured output.

## Ownership and boundaries

Keep argument presentation here and reusable behavior in application owners. Do not bypass source admission or duplicate transaction logic for a CLI-only path.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                             | Responsibility                                                                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                       | Forecast CLI package (façade over the carved subcommand core).                                                                                    |
| [core.py](core.py)                               | Command-line interface for forecast ledger workflows.                                                                                             |
| [benchmarks.py](benchmarks.py)                   | `forecast bench` / `backtest` — ForecastBench scoreboard + historical replay.                                                                     |
| [collaboration_admin.py](collaboration_admin.py) | Local administration for portable forecast workspaces and changesets.                                                                             |
| [connect_admin.py](connect_admin.py)             | `forecast connect <surface>` + `forecast notify` — one guided UX for wiring the desk to a chat surface, and the CLI over the notification router. |
| [curate.py](curate.py)                           | `forecast curate` — propose calibration-fuel questions from live markets.                                                                         |
| [doctor_admin.py](doctor_admin.py)               | `forecast doctor` / `backup` / `config` — operational diagnostics.                                                                                |
| [jobs_admin.py](jobs_admin.py)                   | `forecast jobs …` — administer detached background forecast jobs.                                                                                 |

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
