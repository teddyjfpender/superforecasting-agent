# Forecast collaboration

Builds collaboration cards and routes directory/import operations for shared forecasting work.

## Ownership and boundaries

Treat imported identities and claims as untrusted until verified. Transport-specific delivery belongs in transports; durable changes retain their author and provenance.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                         | Responsibility                                                                |
| ---------------------------- | ----------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)   | Cross-instance collaboration — the `sfp/1` cards (M2) + import pipeline (M3). |
| [cards.py](cards.py)         | Card renderers — turn a ledger object into an `sfp/1` payload + Block Kit.    |
| [directory.py](directory.py) | The collab DIRECTORY — who is in the org, and who is authorised.              |
| [imports.py](imports.py)     | The IMPORT PIPELINE — a peer's sfp/1 payload lands in this ledger as a GUEST. |
| [router.py](router.py)       | The collab ROUTER — a Slack metadata event → the right honest handler.        |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
