# Forecast job runtime

Owns durable forecast job models, admission policy, execution context, storage and detached execution.

## Ownership and boundaries

Cancellation, retries and completion must agree with persisted job state. Register task behavior in types and retain provenance across recovery.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                                                                         |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py) | One detached-job runtime (Arc B).                                                                                                      |
| [runtime.py](runtime.py)   | The runtime: resolve a job's registered TYPE, execute it with a JobContext, and write the terminal `done`/`cancelled`/`error` state.   |
| [**main**.py](__main__.py) | Compatibility entrypoint for the backend forecast worker.                                                                              |
| [context.py](context.py)   | JobContext — the execution-time handle a job type gets: progress (with BUILT-IN coalescing), cooperative cancellation, and annotation. |
| [detached.py](detached.py) | Detached forecast-job process launcher.                                                                                                |
| [model.py](model.py)       | The one durable job record for the detached-job runtime (Arc B).                                                                       |
| [policy.py](policy.py)     | The APPROVAL / SPEND POLICY MATRIX (architecture review item #9).                                                                      |
| [store.py](store.py)       | JSON-file-per-job store for the detached-job runtime (Arc B).                                                                          |

## Subdirectories

- [types/](types/README.md) — Forecast job implementations.

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
