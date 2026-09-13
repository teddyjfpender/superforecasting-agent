# teams_pipeline integration

Implements the teams_pipeline plugin. Microsoft Teams meeting pipeline plugin with durable runtime state and operator CLI flows for Graph-backed transcript-first meeting summaries.

## Ownership and boundaries

Register capabilities through the plugin interface. Keep optional dependencies optional and preserve active-profile isolation. Core runtime must not contain branches specific to this plugin.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                |
| -------------------------- | ------------------------------------------------------------- |
| [**init**.py](__init__.py) | Teams meeting pipeline plugin.                                |
| [models.py](models.py)     | Normalized models for the Teams meeting pipeline plugin.      |
| [runtime.py](runtime.py)   | Gateway runtime wiring for the Teams meeting pipeline plugin. |
| [cli.py](cli.py)           | CLI commands for the Teams meeting pipeline plugin.           |
| [meetings.py](meetings.py) | Graph-backed Teams meeting helpers for the plugin runtime.    |
| [pipeline.py](pipeline.py) | Pipeline orchestration for Microsoft Teams meeting summaries. |
| [plugin.yaml](plugin.yaml) | plugin.                                                       |
| [store.py](store.py)       | Durable local state for the Teams pipeline plugin.            |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
