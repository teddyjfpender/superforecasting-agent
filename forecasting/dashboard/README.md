# Forecast dashboard projections

Builds scoreboard, thesis, headline and panel summaries from forecasting state for display consumers.

## Ownership and boundaries

These are projections of durable records. Do not settle questions or change probabilities while generating a dashboard view.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                                |
| ------------------------------ | ----------------------------------------------------------------------------- |
| [**init**.py](__init__.py)     | Dashboard package façade over carved section modules.                         |
| [core.py](core.py)             | Forecast dashboard summaries shared by CLI, TUI, and web surfaces.            |
| [headline.py](headline.py)     | Forecast headline formatting and compatibility exports for summary consumers. |
| [panel.py](panel.py)           | Workspace panel-detail section (carved from `dashboard.py`).                  |
| [scoreboard.py](scoreboard.py) | Benchmark scoreboard section (carved from `dashboard.py`).                    |
| [thesis.py](thesis.py)         | Thesis / factor dashboard sections (carved from `dashboard.py`).              |

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
