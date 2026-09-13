# Editor protocol adapter

Runs the Agent Client Protocol entrypoint for editor clients, translating sessions, tools, approvals and streaming events into backend operations.

## Ownership and boundaries

Keep editor transport and permission negotiation here. Reuse agent construction and durable session owners, and reserve stdout for protocol traffic.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility                                                              |
| ------------------------------------ | --------------------------------------------------------------------------- |
| [**init**.py](__init__.py)           | ACP (Agent Client Protocol) adapter for Superforecasting Agent.             |
| [server.py](server.py)               | ACP agent server exposing Superforecasting Agent via Agent Client Protocol. |
| [**main**.py](__main__.py)           | Allow running the ACP adapter as `python -m acp_adapter`.                   |
| [auth.py](auth.py)                   | ACP auth helpers: detect and advertise runtime authentication methods.      |
| [content.py](content.py)             | Convert ACP text, images, and attached resources into model content.        |
| [edit_approval.py](edit_approval.py) | Pre-execution ACP edit approval helpers.                                    |
| [entry.py](entry.py)                 | CLI entry point for the Superforecasting Agent ACP adapter.                 |
| [events.py](events.py)               | Callback factories for bridging AIAgent events to ACP notifications.        |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/acp_adapter/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
