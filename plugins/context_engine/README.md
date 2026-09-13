# Context engine integrations

Contains implementations of the context-engine extension interface used to prepare agent context.

## Ownership and boundaries

Keep provider behavior behind the context-engine interface and do not patch the agent loop for individual plugins.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                   |
| -------------------------- | -------------------------------- |
| [**init**.py](__init__.py) | Context engine plugin discovery. |

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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
