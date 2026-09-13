# Terminal copy and catalogs

Contains interface copy, keymaps, setup text and presentation catalogs.

## Ownership and boundaries

Use canonical product language and keep instructions consistent with registered commands and actual capabilities.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                       | Responsibility    |
| ------------------------------------------ | ----------------- |
| [auth.ts](auth.ts)                         | auth.             |
| [bernardAnimation.ts](bernardAnimation.ts) | bernardAnimation. |
| [charms.ts](charms.ts)                     | charms.           |
| [faces.ts](faces.ts)                       | faces.            |
| [fortunes.ts](fortunes.ts)                 | fortunes.         |
| [gatewayLost.ts](gatewayLost.ts)           | gatewayLost.      |
| [hotkeys.ts](hotkeys.ts)                   | hotkeys.          |
| [keymaps.ts](keymaps.ts)                   | keymaps.          |

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
