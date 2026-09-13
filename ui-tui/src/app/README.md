# Terminal application state

Coordinates submissions, gateway events, view state, command activity and overlays.

## Ownership and boundaries

State stores are presentation projections. Reconnect and cancellation must not invent successful completion or discard durable session identity.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                         | Responsibility             |
| ------------------------------------------------------------ | -------------------------- |
| [agentsActiveStore.ts](agentsActiveStore.ts)                 | agentsActiveStore.         |
| [chordStore.ts](chordStore.ts)                               | chordStore.                |
| [commandStore.ts](commandStore.ts)                           | commandStore.              |
| [composerTextStore.ts](composerTextStore.ts)                 | composerTextStore.         |
| [createGatewayEventHandler.ts](createGatewayEventHandler.ts) | createGatewayEventHandler. |
| [createSlashHandler.ts](createSlashHandler.ts)               | createSlashHandler.        |
| [delegationStore.ts](delegationStore.ts)                     | delegationStore.           |
| [forecastPanel.ts](forecastPanel.ts)                         | forecastPanel.             |

## Subdirectories

- [forecast/](forecast/README.md) — Forecast view helpers.
- [slash/](slash/README.md) — Terminal slash routing.

## Working in this directory

From the repository root, run:

```sh
npm --prefix ui-tui run type-check
npm --prefix ui-tui run lint
npm --prefix ui-tui test
```

For input, resize or shutdown changes, also run the relevant installed-terminal
verification on the affected native platform; renderer tests do not establish
ConPTY or PTY behavior.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
