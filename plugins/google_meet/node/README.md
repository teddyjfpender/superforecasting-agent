# Meeting browser bridge

Contains the Node-side browser bridge used by the meeting plugin.

## Ownership and boundaries

Keep browser allocation and audio transport ownership explicit. On interruption, release only the meeting resources acquired by this bridge.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                           |
| -------------------------- | -------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | Remote 'node host' primitive for the google_meet plugin. |
| [server.py](server.py)     | Remote node server.                                      |
| [cli.py](cli.py)           | `superforecasting-agent meet node ...` subcommand tree.  |
| [client.py](client.py)     | Gateway-side RPC client for a remote meet node.          |
| [protocol.py](protocol.py) | Wire protocol for gateway ↔ node RPC.                    |
| [registry.py](registry.py) | Local JSON registry of approved remote meet nodes.       |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
