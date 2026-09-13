# Messaging gateway

Coordinates messaging sessions, platform adapters, command routing, delivery and recovery around the shared agent and host services.

## Ownership and boundaries

Keep platform transport concerns separate from shared command behavior. Persist execution state before reporting completion and retain exact resource ownership through shutdown.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                         | Responsibility                                                               |
| -------------------------------------------- | ---------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                   | Superforecasting Agent Gateway - Multi-platform messaging integration.       |
| [channel_directory.py](channel_directory.py) | Channel directory -- cached map of reachable channels/contacts per platform. |
| [command_dispatch.py](command_dispatch.py)   | Gateway command-hook protocol and authorization after command rewrites.      |
| [config.py](config.py)                       | Gateway configuration management.                                            |
| [credential_broker.py](credential_broker.py) | Credential-safe request construction for hosted tool workers.                |
| [delivery.py](delivery.py)                   | Delivery routing for cron job outputs and agent responses.                   |
| [display_config.py](display_config.py)       | Per-platform display/verbosity configuration resolver.                       |
| [execution_store.py](execution_store.py)     | Durable execution and delivery state for hosted gateway runs.                |

## Subdirectories

- [builtin_hooks/](builtin_hooks/README.md) — Built-in gateway hooks.
- [platforms/](platforms/README.md) — Messaging platform adapters.

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
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
