# Plugins / Browser tests

Exercises plugins/browser behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                       | Responsibility                                                                |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                                 | init .                                                                        |
| [check_parity_vs_main.py](check_parity_vs_main.py)                         | Behavior-parity check for the browser-provider plugin migration (#25214).     |
| [test_browser_disposal_provenance.py](test_browser_disposal_provenance.py) | Provider cleanup uses allocation configuration and never exports credentials. |
| [test_browser_provider_plugins.py](test_browser_provider_plugins.py)       | Plugin-side tests for the browser provider migration (PR #25214).             |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/browser/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
