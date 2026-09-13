# Agent / Lsp tests

Exercises agent/lsp behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)                             | Pytest helpers for LSP-related tests.                                          |
| [\_mock_lsp_server.py](_mock_lsp_server.py)            | A minimal in-process LSP server used by tests.                                 |
| [test_backend_gate.py](test_backend_gate.py)           | Integration test: LSP layer is skipped on non-local backends.                  |
| [test_broken_set.py](test_broken_set.py)               | Tests for the broken-set short-circuit added to handle outer-timeout failures. |
| [test_client_e2e.py](test_client_e2e.py)               | End-to-end client tests against the in-process mock LSP server.                |
| [test_delta_key.py](test_delta_key.py)                 | Tests for cross-edit LSP delta filtering.                                      |
| [test_diagnostics_field.py](test_diagnostics_field.py) | Tests for the `lsp_diagnostics` field on WriteResult / PatchResult.            |
| [test_eventlog.py](test_eventlog.py)                   | Tests for the structured logging dedup model.                                  |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/agent/lsp/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
