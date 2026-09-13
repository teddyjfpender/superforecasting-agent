# Messaging platform plugins

Contains installable messaging adapters using the platform plugin interface.

## Ownership and boundaries

Keep platform authentication and payload translation within each plugin and reuse gateway session and command services.

## Subdirectories

- [google_chat/](google_chat/README.md) — google_chat integration.
- [irc/](irc/README.md) — irc integration.
- [line/](line/README.md) — line integration.
- [simplex/](simplex/README.md) — simplex integration.
- [teams/](teams/README.md) — teams integration.

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
