# Storage tests

Exercises storage behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                       | Responsibility                                                                                  |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [test_atomic_json_write.py](test_atomic_json_write.py)                     | Tests for superforecasting_agent.storage.files.atomic_json_write — crash-safe JSON file writes. |
| [test_atomic_replace_symlinks.py](test_atomic_replace_symlinks.py)         | Regression tests for GitHub #16743 — atomic writes must preserve symlinks.                      |
| [test_atomic_yaml_write.py](test_atomic_yaml_write.py)                     | Tests for superforecasting_agent.storage.files.atomic_yaml_write — crash-safe YAML file writes. |
| [test_auth_store.py](test_auth_store.py)                                   | Credential-store compatibility through the presentation-independent owner.                      |
| [test_configuration_values.py](test_configuration_values.py)               | Read-only normalized profile access without CLI lifecycle side effects.                         |
| [test_credential_service_boundary.py](test_credential_service_boundary.py) | Credential ownership must hold independently of interactive products.                           |
| [test_environment_reader.py](test_environment_reader.py)                   | Credential reads preserve current contents and never mutate profile state.                      |
| [test_file_descriptor_ownership.py](test_file_descriptor_ownership.py)     | Failure injection for descriptor ownership before text-wrapper construction.                    |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/storage/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
