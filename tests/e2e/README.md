# E2E tests

Exercises e2e behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                        |
| ------------------------------------------------------ | --------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                         | init .                                                                |
| [conftest.py](conftest.py)                             | Shared fixtures for gateway e2e tests (Telegram, Discord).            |
| [test_discord_adapter.py](test_discord_adapter.py)     | Minimal e2e tests for Discord mention stripping + /command detection. |
| [test_platform_commands.py](test_platform_commands.py) | E2E tests for gateway slash commands (Telegram, Discord).             |

## Subdirectories

- [matrix_xsign_bootstrap/](matrix_xsign_bootstrap/README.md) — matrix xsign bootstrap.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh
```

The ordinary runner excludes external integration and end-to-end suites. The
command above checks the isolated repository suite; it does not claim live-service
coverage. For configured services, select the supported explicit paths:

```sh
scripts/run_tests.sh --live-service daytona
scripts/run_tests.sh --live-service modal
```

Those selections require their own credentials and fail when they are absent.
Other external scenarios need a dedicated harness and prerequisite setup.

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
