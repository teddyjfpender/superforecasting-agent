# Honcho Plugin tests

Exercises honcho plugin behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                     | Responsibility                                                           |
| -------------------------------------------------------- | ------------------------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)                               | init .                                                                   |
| [test_async_memory.py](test_async_memory.py)             | Tests for the async-memory Honcho improvements.                          |
| [test_cli.py](test_cli.py)                               | Tests for plugins/memory/honcho/cli.py.                                  |
| [test_client.py](test_client.py)                         | Tests for plugins/memory/honcho/client.py — Honcho client configuration. |
| [test_empty_profile_hint.py](test_empty_profile_hint.py) | Tests for honcho_profile's empty-card hint (#5137 follow-up).            |
| [test_pin_peer_name.py](test_pin_peer_name.py)           | Tests for the `pinPeerName` config flag (#14984).                        |
| [test_session.py](test_session.py)                       | Tests for plugins/memory/honcho/session.py — HonchoSession and helpers.  |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/honcho_plugin/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
