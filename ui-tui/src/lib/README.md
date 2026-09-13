# Terminal support functions

Contains reusable terminal formatting, caches, grouping and platform helpers.

## Ownership and boundaries

Prefer focused pure helpers. Keep durable business state and provider calls outside this directory.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                       | Responsibility    |
| ------------------------------------------ | ----------------- |
| [accentSweep.ts](accentSweep.ts)           | accentSweep.      |
| [audiogram.ts](audiogram.ts)               | audiogram.        |
| [buildInfo.ts](buildInfo.ts)               | buildInfo.        |
| [circularBuffer.ts](circularBuffer.ts)     | circularBuffer.   |
| [clipboard.ts](clipboard.ts)               | clipboard.        |
| [cursorVisibility.ts](cursorVisibility.ts) | cursorVisibility. |
| [deskGroups.ts](deskGroups.ts)             | deskGroups.       |
| [docsCli.ts](docsCli.ts)                   | docsCli.          |

## Subdirectories

- [viz/](viz/README.md) — Terminal chart engine.

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
