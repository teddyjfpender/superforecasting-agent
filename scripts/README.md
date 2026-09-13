# Engineering automation

Contains contributor checks, test runners, release assembly, installation verification, runtime investigations and maintenance utilities.

## Ownership and boundaries

Use dev.py for shared quality gates and run_tests.sh for Python tests. Qualification reports must identify the actual artifacts and platform; a generated report is not evidence of a run.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                          |
| ------------------------------------------------------ | ----------------------------------------------------------------------- |
| [dev.py](dev.py)                                       | Bootstrap and run the repository's shared, blocking quality checks.     |
| [run_tests.sh](run_tests.sh)                           | run tests.                                                              |
| [verify_profiles.py](verify_profiles.py)               | Verify built product wheels outside the checkout in fresh environments. |
| [benchmark_browser_eval.py](benchmark_browser_eval.py) | Quick benchmark: subprocess eval vs supervisor-WS eval.                 |
| [benchmark_tui_perf.py](benchmark_tui_perf.py)         | Desk-load performance benchmark for the superforecasting-agent TUI.     |
| [build-release.sh](build-release.sh)                   | build-release.                                                          |
| [build_model_catalog.py](build_model_catalog.py)       | Build the Superforecasting Agent Model Catalog.                         |
| [build_profiles.py](build_profiles.py)                 | Build independently installable backend and terminal wheels.            |

For upgrade qualification, [prepare_upgrade_baselines.py](prepare_upgrade_baselines.py)
verifies published baseline bytes and builds historical terminal source.
[verify_profile_migrations.py](verify_profile_migrations.py) runs under each
installed backend, checking real skill synchronization and plugin execution.

## Subdirectories

- [carve/](carve/README.md) — carve.
- [data_generation/](data_generation/README.md) — data generation.
- [docgen/](docgen/README.md) — Reference documentation generation.
- [lib/](lib/README.md) — Shared shell bootstrap.
- [tests/](tests/README.md) — Native script tests.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/scripts/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
