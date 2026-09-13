# Batch trajectories

Runs batch conversation generation, checkpointing, compression, summaries and statistical reporting.

## Ownership and boundaries

Preserve input and output identity across retries. Keep compression I/O separate from algorithms and report partial batch failures accurately.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                       | Responsibility                                                             |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                 | Batch trajectory generation and processing support.                        |
| [algorithm.py](algorithm.py)               | Protected-turn selection and compression for completed trajectories.       |
| [batch.py](batch.py)                       | Batch Agent Runner                                                         |
| [batch_cli.py](batch_cli.py)               | Command-line options for dataset batch runs.                               |
| [batch_run.py](batch_run.py)               | Parallel orchestration, resumption, and output aggregation for batch runs. |
| [batch_statistics.py](batch_statistics.py) | Tool and reasoning statistics for generated trajectories.                  |
| [batch_worker.py](batch_worker.py)         | Picklable worker functions for batch trajectory generation.                |
| [compression.py](compression.py)           | Trajectory Compressor                                                      |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/trajectories/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
