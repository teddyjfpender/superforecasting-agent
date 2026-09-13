# Gateway tests

Exercises gateway behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                                   | Responsibility                                                                                         |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| [**init**.py](__init__.py)                                                             | init .                                                                                                 |
| [\_plugin_adapter_loader.py](_plugin_adapter_loader.py)                                | Shared helper for loading platform-plugin `adapter.py` modules in tests.                               |
| [conftest.py](conftest.py)                                                             | Shared fixtures for gateway tests.                                                                     |
| [feishu_helpers.py](feishu_helpers.py)                                                 | Shared fixtures for Feishu adapter tests (admission, group policy, dispatch).                          |
| [restart_test_helpers.py](restart_test_helpers.py)                                     | restart Checks: helpers.                                                                               |
| [test_7100_transient_failure_transcript.py](test_7100_transient_failure_transcript.py) | Tests for #7100 — transient failures (429/timeout) must not drop the user message from the transcript. |
| [test_active_session_text_merge.py](test_active_session_text_merge.py)                 | Regression test for #4469.                                                                             |
| [test_agent_cache.py](test_agent_cache.py)                                             | Integration tests for gateway AIAgent caching.                                                         |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/gateway/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
