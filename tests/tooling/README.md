# Tooling tests

Exercises tooling behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                     | Responsibility                                                                                                          |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| [test_arguments.py](test_arguments.py)                                   | Tests for tool argument type coercion.                                                                                  |
| [test_async_bridge.py](test_async_bridge.py)                             | Regression tests for the \_run_async() event-loop lifecycle.                                                            |
| [test_definitions_cache.py](test_definitions_cache.py)                   | Regression tests for issue #17335.                                                                                      |
| [test_errors.py](test_errors.py)                                         | Tests for `_sanitize_tool_error` in model_tools.                                                                        |
| [test_plugin_platform_core_tools.py](test_plugin_platform_core_tools.py) | Registered plugin platforms inherit core and platform-specific tools.                                                   |
| [test_runtime.py](test_runtime.py)                                       | Tests for superforecasting_agent/tooling/runtime.py — function call dispatch, agent-loop interception, legacy toolsets. |
| [test_toolsets.py](test_toolsets.py)                                     | Tests for toolsets.py — toolset resolution, validation, and composition.                                                |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tooling/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
