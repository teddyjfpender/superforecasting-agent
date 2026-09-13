# Provider proxy runtime

Runs the local provider proxy and its command-line entrypoint around provider-specific adapters.

## Ownership and boundaries

Validate request boundaries and own server shutdown. Keep provider protocol translation in adapters and avoid leaking credentials through proxy diagnostics.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                 |
| -------------------------- | ------------------------------------------------------------------------------ |
| [**init**.py](__init__.py) | Local OpenAI-compatible proxy that forwards to OAuth-authenticated upstreams.  |
| [server.py](server.py)     | HTTP server that forwards OpenAI-compatible requests to a configured upstream. |
| [cli.py](cli.py)           | CLI handlers for the `superforecasting-agent proxy` subcommand.                |

## Subdirectories

- [adapters/](adapters/README.md) — Proxy provider adapters.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/runtime_cli/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
