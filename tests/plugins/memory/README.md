# Plugins / Memory tests

Exercises plugins/memory behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                         | Responsibility                                                                    |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                   | init .                                                                            |
| [test_hindsight_provider.py](test_hindsight_provider.py)     | Tests for the Hindsight memory provider plugin.                                   |
| [test_holographic_provider.py](test_holographic_provider.py) | Checks: holographic provider.                                                     |
| [test_mem0_v2.py](test_mem0_v2.py)                           | Tests for Mem0 API v2 compatibility — filters param and dict response unwrapping. |
| [test_openviking_provider.py](test_openviking_provider.py)   | Checks: openviking provider.                                                      |
| [test_supermemory_provider.py](test_supermemory_provider.py) | Checks: supermemory provider.                                                     |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/memory/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
