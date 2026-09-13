# Acp Adapter tests

Exercises acp adapter behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                           | Responsibility                                                            |
| -------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [test_acp_commands.py](test_acp_commands.py)                   | Checks: acp commands.                                                     |
| [test_acp_images.py](test_acp_images.py)                       | Checks: acp images.                                                       |
| [test_detect_provider_entra.py](test_detect_provider_entra.py) | Regression tests for ACP adapter detection under Azure Foundry Entra ID.  |
| [test_resource_limits.py](test_resource_limits.py)             | Attachment limits apply even if a local image grows after its size check. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/acp_adapter/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
