# Providers tests

Exercises providers behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility                                                                            |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                             | init .                                                                                    |
| [test_e2e_wiring.py](test_e2e_wiring.py)               | E2E tests: verify \_build_kwargs_from_profile produces correct output.                    |
| [test_plugin_discovery.py](test_plugin_discovery.py)   | Tests for the model-providers plugin discovery system.                                    |
| [test_profile_wiring.py](test_profile_wiring.py)       | Profile-path parity tests: verify profile path produces identical output to legacy flags. |
| [test_provider_profiles.py](test_provider_profiles.py) | Tests for the provider module registry and profiles.                                      |
| [test_transport_parity.py](test_transport_parity.py)   | Parity tests: pin the exact current transport behavior per provider.                      |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/providers/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
