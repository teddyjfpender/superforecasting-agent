# Agent tests

Exercises agent behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                               | Responsibility                                                                              |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                                         | init .                                                                                      |
| [test_anthropic_adapter.py](test_anthropic_adapter.py)             | Tests for agent/anthropic_adapter.py — Anthropic Messages API adapter.                      |
| [test_anthropic_keychain.py](test_anthropic_keychain.py)           | Tests for Bug #12905 fixes in agent/anthropic_adapter.py — macOS Keychain support.          |
| [test_anthropic_oauth_pkce.py](test_anthropic_oauth_pkce.py)       | Regression tests for the Anthropic OAuth PKCE flow.                                         |
| [test_arcee_trinity_overrides.py](test_arcee_trinity_overrides.py) | Tests for Arcee Trinity Large Thinking per-model overrides.                                 |
| [test_async_utils.py](test_async_utils.py)                         | Tests for agent.async_utils.safe_schedule_threadsafe.                                       |
| [test_aux_resilience.py](test_aux_resilience.py)                   | Resilience fixes from the 2026-06-29 provider-flakiness investigation:                      |
| [test_auxiliary_client.py](test_auxiliary_client.py)               | Tests for agent.auxiliary_client resolution chain, provider overrides, and model overrides. |

## Subdirectories

- [lsp/](lsp/README.md) — lsp.
- [transports/](transports/README.md) — transports.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/agent/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
