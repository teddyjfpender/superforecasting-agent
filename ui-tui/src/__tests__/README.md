# Terminal behavior tests

Exercises application stores, rendering, recovery, input and forecast interactions.

## Ownership and boundaries

Use controlled events and providers. Assert state during failure and reconnect, not only the final successful screen.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility           |
| ------------------------------------------------------ | ------------------------ |
| [agentsActiveStore.test.ts](agentsActiveStore.test.ts) | agentsActiveStore tests. |
| [agentsChip.test.tsx](agentsChip.test.tsx)             | agentsChip tests.        |
| [alertsView.test.tsx](alertsView.test.tsx)             | alertsView tests.        |
| [approvalAction.test.ts](approvalAction.test.ts)       | approvalAction tests.    |
| [asCommandDispatch.test.ts](asCommandDispatch.test.ts) | asCommandDispatch tests. |
| [asciiAnimation.test.tsx](asciiAnimation.test.tsx)     | asciiAnimation tests.    |
| [audiogram.test.ts](audiogram.test.ts)                 | audiogram tests.         |
| [banner.test.ts](banner.test.ts)                       | banner tests.            |

## Subdirectories

- [viz/](viz/README.md) — Visualization tests.

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
