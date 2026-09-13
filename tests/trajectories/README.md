# Trajectories tests

Exercises trajectories behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                                                                   |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| [test_batch_checkpoint.py](test_batch_checkpoint.py)   | Tests for superforecasting_agent.trajectories.batch checkpoint behavior — incremental writes, resume, atomicity. |
| [test_batch_exit_status.py](test_batch_exit_status.py) | Batch command failures must be visible to shell automation.                                                      |
| [test_batch_factory.py](test_batch_factory.py)         | Batch workers preserve explicit configuration through the shared factory.                                        |
| [test_compression.py](test_compression.py)             | Tests for superforecasting_agent/trajectories/compression.py — config, metrics, and compression logic.           |
| [test_compression_async.py](test_compression_async.py) | Tests for superforecasting_agent.trajectories.compression AsyncOpenAI event loop binding.                        |
| [test_distributions.py](test_distributions.py)         | Tests for trajectory toolset distributions — distribution CRUD, sampling, validation.                            |

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
