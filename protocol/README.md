# Versioned product protocol

Defines shared RPC types, events, protocol versions and generation of client contracts.

## Ownership and boundaries

Change declarations here before regenerating consumers. Negotiate required capabilities and preserve backward compatibility rather than editing generated client types directly.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| [**init**.py](__init__.py) | Protocol-first gateway contract: one source of truth for every RPC and event crossing the gateway wire, with TypeScript types generated from it. |
| [codegen.py](codegen.py)   | Emit `ui-tui/src/protocol/generated.ts` from the protocol registry.                                                                              |
| [collab.py](collab.py)     | `sfp/1` — the SuperForecast Protocol carried over Slack message metadata.                                                                        |
| [types.py](types.py)       | Shared primitives and the base model for every wire-crossing schema.                                                                             |
| [version.py](version.py)   | The single wire-protocol version for the gateway.                                                                                                |

## Subdirectories

- [events/](events/README.md) — Gateway event declarations.
- [rpc/](rpc/README.md) — RPC declarations.

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
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
