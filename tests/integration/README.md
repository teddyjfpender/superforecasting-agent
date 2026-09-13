# Integration tests

Exercises integration behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                 | Responsibility                                                                            |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                           | init .                                                                                    |
| [conftest.py](conftest.py)                                           | Explicit service credentials for live integration runs; unit tests stay hermetic.         |
| [test_batch_runner.py](test_batch_runner.py)                         | Test script for batch runner                                                              |
| [test_checkpoint_resumption.py](test_checkpoint_resumption.py)       | Test script to verify checkpoint behavior in superforecasting_agent/trajectories/batch.py |
| [test_daytona_terminal.py](test_daytona_terminal.py)                 | Integration tests for the Daytona terminal backend.                                       |
| [test_ha_integration.py](test_ha_integration.py)                     | Integration tests for Home Assistant (tool + gateway).                                    |
| [test_live_service_credentials.py](test_live_service_credentials.py) | Exercise restoration through the real hermetic fixture, without a network call.           |
| [test_modal_terminal.py](test_modal_terminal.py)                     | Test Modal Terminal Tool                                                                  |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/integration/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
