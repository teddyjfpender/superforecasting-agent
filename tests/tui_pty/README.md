# Tui Pty tests

Exercises tui pty behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                 | Responsibility                                                               |
| ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                           | Real-terminal (pty) tests for the Ink TUI.                                   |
| [conftest.py](conftest.py)                           | Skip policy + hermetic environment for the real-terminal TUI tests.          |
| [ledger_probe.py](ledger_probe.py)                   | Count the SQLite work a ledger operation does.                               |
| [pty_session.py](pty_session.py)                     | Drive a child process behind a real pseudo-terminal.                         |
| [synthetic_ledger.py](synthetic_ledger.py)           | Generate a synthetic forecast ledger for load-shaped tests.                  |
| [test_configured_chat.py](test_configured_chat.py)   | Exercise the real composer, gateway, agent and streamed transcript together. |
| [test_desk_at_scale.py](test_desk_at_scale.py)       | Open the real Desk, in a real terminal, against a large ledger.              |
| [test_desk_load_budget.py](test_desk_load_budget.py) | A load budget for the Desk's `forecast.workspace` fetch.                     |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tui_pty/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
