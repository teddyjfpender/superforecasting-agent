# Terminal visualization components

Connects terminal chart rendering to theme and viewport capabilities.

## Ownership and boundaries

Handle small terminals and unsupported display capabilities without hiding the underlying values.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility   |
| ---------------------------------------- | ---------------- |
| [Canvas.tsx](Canvas.tsx)                 | Canvas.          |
| [Chart.tsx](Chart.tsx)                   | Chart.           |
| [chartTheme.ts](chartTheme.ts)           | chartTheme.      |
| [useViewportCaps.ts](useViewportCaps.ts) | useViewportCaps. |

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
[ownership map](../../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
