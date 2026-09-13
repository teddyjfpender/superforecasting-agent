# Forecast quorum estimation

Builds estimation panels, prompts, parses estimates and combines them with shrinkage.

## Ownership and boundaries

Preserve individual estimates and panel provenance. Validate numeric outputs before aggregation and do not mistake correlated estimates for independent evidence.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)     | Quorum package façade over carved concern modules.                                          |
| [core.py](core.py)             | Quorum — a model-diverse forecast panel with a judge synthesis step.                        |
| [estimation.py](estimation.py) | Quorum call-count / preset-cap / trial-count machinery (carved from `quorum.py`).           |
| [panels.py](panels.py)         | Quorum model / provider / panel resolution (carved from `quorum.py`).                       |
| [parsing.py](parsing.py)       | Quorum response parsing + belief-trajectory coercion (carved from `quorum.py`).             |
| [prompts.py](prompts.py)       | Quorum panelist / judge / Delphi prompt builders (carved from `quorum.py`).                 |
| [shrinkage.py](shrinkage.py)   | Quorum James–Stein shrinkage + final-probability + market anchor (carved from `quorum.py`). |

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
