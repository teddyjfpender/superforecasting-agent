# Built-in gateway hooks

Reserves the package for gateway hooks that are registered with the gateway itself. No built-in hook implementation is currently shipped.

## Ownership and boundaries

Use the existing hook registration surface. Product-specific extensions should not add hardcoded branches to the gateway runtime.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                     |
| -------------------------- | -------------------------------------------------- |
| [**init**.py](__init__.py) | Built-in gateway hooks that are always registered. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/gateway/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
