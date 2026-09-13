# Tool capability catalogs

Defines core and forecasting tool sets, capabilities and explicit compatibility aliases.

## Ownership and boundaries

Keep canonical tool identities here. Aliases must map to the same behavior and should not introduce duplicate tools or implicit product-specific defaults.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility                                         |
| ---------------------------------- | ------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)         | Ordered built-in toolset catalog used by the resolver. |
| [core.py](core.py)                 | Shared tool membership for inherited platform presets. |
| [aliases.py](aliases.py)           | Aliases toolset catalog.                               |
| [capabilities.py](capabilities.py) | Capabilities toolset catalog.                          |
| [forecast.py](forecast.py)         | Forecast toolset catalog.                              |
| [legacy.py](legacy.py)             | Legacy toolset catalog.                                |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/tooling/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
