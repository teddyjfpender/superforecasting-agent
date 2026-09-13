# Memory provider integrations

Contains the existing bundled memory backends implementing the shared memory-provider interface.

## Ownership and boundaries

New backends ship as standalone plugins. Preserve provider shutdown ownership and keep credentials and active-profile data isolated.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                    |
| -------------------------- | --------------------------------- |
| [**init**.py](__init__.py) | Memory provider plugin discovery. |

## Subdirectories

- [byterover/](byterover/README.md) — byterover integration.
- [hindsight/](hindsight/README.md) — hindsight integration.
- [holographic/](holographic/README.md) — holographic integration.
- [honcho/](honcho/README.md) — honcho integration.
- [mem0/](mem0/README.md) — mem0 integration.
- [openviking/](openviking/README.md) — openviking integration.
- [retaindb/](retaindb/README.md) — retaindb integration.
- [supermemory/](supermemory/README.md) — supermemory integration.

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
