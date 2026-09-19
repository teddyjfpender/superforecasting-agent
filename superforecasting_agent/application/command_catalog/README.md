# Command catalog

Defines command metadata, aliases, capabilities and shared command lookup operations.

## Ownership and boundaries

Register canonical names and aliases once. Consumers derive menus and routing from this catalog rather than maintaining parallel command lists.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                       |
| ------------------------------ | -------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)     | Shared command metadata and resolution, independent of presentation. |
| [operations.py](operations.py) | Configuration, integration and operator-support commands.            |
| [types.py](types.py)           | Shared immutable command definition.                                 |
| [workflow.py](workflow.py)     | Forecast-desk and session workflow commands.                         |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/application/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite remains a separate qualification tier; pushes run the bounded
integration tier.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)


## Identity admission and generated inventory

Canonical names and aliases use lowercase letters, digits, hyphens or underscores.
The catalog rejects duplicate names/aliases (including an alias equal to its own
canonical name), contradictory CLI-only/gateway-only flags and gateway overrides
without a CLI-only restriction. A collision must never silently change routing.
Aliases retain the canonical command ID; selection order is not an identifier.

[`command-surfaces.md`](../../../docs/reference/command-surfaces.md) is generated
from this catalog and the terminal routing owner. Update definitions here and run
`python -m scripts.docgen`; the canonical quality command enforces freshness.
It records advertised slash-command surfaces and aliases. Argparse forecast
commands have their own generated reference; runtime root/plugin inventories and
behavioral parity are separate requirements, not inferred from this table.
