# Application tests

Exercises application behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                       | Responsibility                                                              |
| -------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [test_aggregate_summary_ownership.py](test_aggregate_summary_ownership.py) | Summary reads are shared application operations, independent of dashboard.  |
| [test_benchmark_ownership.py](test_benchmark_ownership.py)                 | Shared benchmark operations reject unsafe sources before doing any work.    |
| [test_command_catalog.py](test_command_catalog.py)                         | The shared command catalog works independently of all product presentation. |
| [test_forecast_operations.py](test_forecast_operations.py)                 | Product adapters agree on durable forecast operations and errors.           |
| [test_session_selection.py](test_session_selection.py)                     | Resume selection works beyond a bounded internal-session backlog.           |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/application/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
