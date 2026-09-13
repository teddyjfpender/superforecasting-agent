# Acp tests

Exercises acp behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                     | Responsibility                                                              |
| -------------------------------------------------------- | --------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                               | init .                                                                      |
| [test_approval_isolation.py](test_approval_isolation.py) | Tests for GHSA-96vc-wcxf-jjff and GHSA-qg5c-hvr5-hjgr.                      |
| [test_auth.py](test_auth.py)                             | Tests for acp_adapter.auth — provider detection.                            |
| [test_edit_approval.py](test_edit_approval.py)           | Tests for ACP pre-edit approval gating.                                     |
| [test_entry.py](test_entry.py)                           | Tests for acp_adapter.entry startup wiring.                                 |
| [test_events.py](test_events.py)                         | Tests for acp_adapter.events — callback factories for ACP notifications.    |
| [test_mcp_e2e.py](test_mcp_e2e.py)                       | End-to-end tests for ACP MCP server registration and tool-result reporting. |
| [test_permissions.py](test_permissions.py)               | Tests for acp_adapter.permissions.                                          |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/acp/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
