# Installed terminal launcher

Provides the Python entrypoint that locates the compiled terminal bundle and launches Node against a local or remote backend.

## Ownership and boundaries

Keep startup diagnostics actionable when Node, bundle assets or a compatible backend are missing. Backend data and credentials remain in the selected profile.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                   |
| -------------------------- | ---------------------------------------------------------------- |
| [**init**.py](__init__.py) | Standalone terminal product: no backend imports or dependencies. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
