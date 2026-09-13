# Terminal renderer — ink

Terminal rendering, reconciliation, layout, output and interaction primitives.

## Ownership and boundaries

Keep these primitives independent of forecast business logic. Preserve terminal restoration, Unicode width and exact resource ownership; test malformed input and repeated cleanup. Retain upstream attribution when changing inherited code.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                   | Responsibility  |
| -------------------------------------- | --------------- |
| [Ansi.tsx](Ansi.tsx)                   | Ansi.           |
| [bidi.ts](bidi.ts)                     | bidi.           |
| [cache-eviction.ts](cache-eviction.ts) | cache-eviction. |
| [clearTerminal.ts](clearTerminal.ts)   | clearTerminal.  |
| [colorize.test.ts](colorize.test.ts)   | colorize tests. |
| [colorize.ts](colorize.ts)             | colorize.       |
| [constants.ts](constants.ts)           | constants.      |
| [cursor.ts](cursor.ts)                 | cursor.         |

## Subdirectories

- [components/](components/README.md) — Terminal renderer — ink / components.
- [events/](events/README.md) — Terminal renderer — ink / events.
- [hooks/](hooks/README.md) — Terminal renderer — ink / hooks.
- [layout/](layout/README.md) — Terminal renderer — ink / layout.
- [termio/](termio/README.md) — Terminal renderer — ink / termio.

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
[ownership map](../../../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
