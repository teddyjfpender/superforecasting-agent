# Forecast signal hooks

Defines hook specifications, signal calculations, thresholds and sweeps used to detect forecast review opportunities.

## Ownership and boundaries

A signal may create an alert or proposed action; it must not silently replace an active probability. Keep signal calculation independently testable from dispatch.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                             | Responsibility                                                                                                                       |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)                       | Forecast Hooks — a git-hook-style saturation + style enforcement framework.                                                          |
| [blf_signals.py](blf_signals.py)                 | BLF gate signals — the retroactivity backbone + panel-run readers.                                                                   |
| [builtins.py](builtins.py)                       | Built-in forecast hook rules — one per legacy `create_snapshot` gate, plus `style_clean` and `lessons_applied`.                      |
| [candidate_intervals.py](candidate_intervals.py) | Compute per-candidate vote-share intervals (the honest sources, in precedence).                                                      |
| [distribution.py](distribution.py)               | Distribution / uncertainty-bounds assessment + auto-fix for forecast hooks.                                                          |
| [dsl.py](dsl.py)                                 | User-defined rule DSL — a SAFE, declarative rule language.                                                                           |
| [engine.py](engine.py)                           | Forecast Hooks engine — evaluate the rule set against a HookContext and return a SaturationReport (0-100 score + per-rule verdicts). |
| [loader.py](loader.py)                           | loader.                                                                                                                              |

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
