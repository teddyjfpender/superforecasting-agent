# alibaba-coding-plan integration

Defines the alibaba-coding-plan model-provider registration. Alibaba Cloud Coding Plan

## Ownership and boundaries

Provider discovery loads this profile separately from general plugins. Keep aliases, authentication hints and transport selection consistent with the provider registry; use controlled transport tests before live credentials.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                              |
| -------------------------- | ------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | Alibaba Cloud Coding Plan provider profile. |
| [plugin.yaml](plugin.yaml) | plugin.                                     |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
