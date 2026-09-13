# Terminal UI source

Owns the Ink application, gateway connection, transcript, composer and user interaction.

## Ownership and boundaries

Keep forecasting and persistence policy in Python. Render pending, failed and completed state from backend evidence and reject stale connection events.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility |
| ------------------------------------ | -------------- |
| [entry.tsx](entry.tsx)               | entry.         |
| [app.tsx](app.tsx)                   | app.           |
| [banner.ts](banner.ts)               | banner.        |
| [gatewayClient.ts](gatewayClient.ts) | gatewayClient. |
| [gatewayTypes.ts](gatewayTypes.ts)   | gatewayTypes.  |
| [theme.ts](theme.ts)                 | theme.         |
| [types.ts](types.ts)                 | types.         |

## Subdirectories

- [**tests**/](__tests__/README.md) — Terminal behavior tests.
- [app/](app/README.md) — Terminal application state.
- [components/](components/README.md) — Terminal components.
- [config/](config/README.md) — Terminal configuration constants.
- [content/](content/README.md) — Terminal copy and catalogs.
- [domain/](domain/README.md) — Client data interpretation.
- [hooks/](hooks/README.md) — Terminal React hooks.
- [lib/](lib/README.md) — Terminal support functions.
- [protocol/](protocol/README.md) — Client protocol support.
- [testing/](testing/README.md) — Terminal test helpers.
- [types/](types/README.md) — Terminal type declarations.

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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
