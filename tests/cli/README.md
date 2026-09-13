# Cli tests

Exercises cli behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                               | Responsibility                                                       |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                                         | init .                                                               |
| [test_branch_command.py](test_branch_command.py)                                   | Tests for the /branch (/fork) command — session branching.           |
| [test_busy_input_mode_command.py](test_busy_input_mode_command.py)                 | Tests for the /busy CLI command and busy-input-mode config handling. |
| [test_cli_approval_ui.py](test_cli_approval_ui.py)                                 | Checks: cli approval ui.                                             |
| [test_cli_background_status_indicator.py](test_cli_background_status_indicator.py) | Tests for the /background indicator in the CLI status bar.           |
| [test_cli_background_tui_refresh.py](test_cli_background_tui_refresh.py)           | Tests for CLI background command TUI refresh behavior.               |
| [test_cli_bracketed_paste_sanitizer.py](test_cli_bracketed_paste_sanitizer.py)     | Tests for defensive bracketed-paste wrapper stripping in the CLI.    |
| [test_cli_browser_connect.py](test_cli_browser_connect.py)                         | Tests for CLI browser CDP auto-launch helpers.                       |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/cli/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
