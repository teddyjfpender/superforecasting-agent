# Terminal renderer — ink / events

Typed input, focus, paste, resize and pointer event dispatch.

## Ownership and boundaries

Keep these primitives independent of forecast business logic. Preserve terminal restoration, Unicode width and exact resource ownership; test malformed input and repeated cleanup. Retain upstream attribution when changing inherited code.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                           | Responsibility       |
| ---------------------------------------------- | -------------------- |
| [click-event.ts](click-event.ts)               | click-event.         |
| [cmd-shortcuts.test.ts](cmd-shortcuts.test.ts) | cmd-shortcuts tests. |
| [dispatcher.ts](dispatcher.ts)                 | dispatcher.          |
| [emitter.ts](emitter.ts)                       | emitter.             |
| [event-handlers.ts](event-handlers.ts)         | event-handlers.      |
| [event.ts](event.ts)                           | event.               |
| [focus-event.ts](focus-event.ts)               | focus-event.         |
| [input-event.ts](input-event.ts)               | input-event.         |

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
[ownership map](../../../../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
