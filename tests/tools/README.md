# Tools tests

Exercises tools behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                           | Responsibility                                                                               |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                     | init .                                                                                       |
| [test_accretion_caps.py](test_accretion_caps.py)               | Accretion caps for \_read_tracker (file_tools) and \_completion_consumed (process_registry). |
| [test_ansi_strip.py](test_ansi_strip.py)                       | Comprehensive tests for ANSI escape sequence stripping (ECMA-48).                            |
| [test_approval.py](test_approval.py)                           | Tests for the dangerous command approval module.                                             |
| [test_approval_heartbeat.py](test_approval_heartbeat.py)       | Tests for the activity-heartbeat behavior of the blocking gateway approval wait.             |
| [test_approval_plugin_hooks.py](test_approval_plugin_hooks.py) | Tests for pre_approval_request / post_approval_response plugin hooks.                        |
| [test_async_delegation.py](test_async_delegation.py)           | Tests for async (background) delegation — tools/async_delegation.py.                         |
| [test_base_environment.py](test_base_environment.py)           | Tests for BaseEnvironment unified execution model.                                           |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tools/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
