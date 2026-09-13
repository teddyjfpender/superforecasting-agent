# Native script tests

Contains platform-native tests for installer staging and related shell behavior.

## Ownership and boundaries

Run scripts with their intended interpreter on the target platform. A syntax check on another OS is not native installation evidence.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                       | Responsibility                   |
| -------------------------------------------------------------------------- | -------------------------------- |
| [test-install-ps1-stage-protocol.ps1](test-install-ps1-stage-protocol.ps1) | test-install-ps1-stage-protocol. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/scripts/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
