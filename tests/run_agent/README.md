# Run Agent tests

Exercises run agent behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                           | Responsibility                                                         |
| ------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| [**init**.py](__init__.py)                                                     | init .                                                                 |
| [conftest.py](conftest.py)                                                     | Fast-path fixtures shared across tests/run_agent/.                     |
| [test_1630_context_overflow_loop.py](test_1630_context_overflow_loop.py)       | Tests for #1630 — gateway infinite 400 failure loop prevention.        |
| [test_18028_content_policy_blocked.py](test_18028_content_policy_blocked.py)   | Checks: 18028 content policy blocked.                                  |
| [test_413_compression.py](test_413_compression.py)                             | Tests for payload/context-length → compression retry logic in AIAgent. |
| [test_860_dedup.py](test_860_dedup.py)                                         | Tests for issue #860 — SQLite session transcript deduplication.        |
| [test_agent_guardrails.py](test_agent_guardrails.py)                           | Unit tests for AIAgent pre/post-LLM-call guardrails.                   |
| [test_anthropic_prompt_cache_policy.py](test_anthropic_prompt_cache_policy.py) | Tests for AIAgent.\_anthropic_prompt_cache_policy().                   |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/run_agent/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
