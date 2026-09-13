# Terminal chart engine

Implements chart buffers, scales, color, annotation and terminal capability handling.

## Ownership and boundaries

Keep rendering deterministic for a given input and viewport. Reject non-finite data and handle zero-width or degenerate ranges.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility |
| -------------------------- | -------------- |
| [annotate.ts](annotate.ts) | annotate.      |
| [blit.ts](blit.ts)         | blit.          |
| [buffer.ts](buffer.ts)     | buffer.        |
| [caps.ts](caps.ts)         | caps.          |
| [color.ts](color.ts)       | color.         |
| [index.ts](index.ts)       | index.         |
| [protocol.ts](protocol.ts) | protocol.      |
| [scale.ts](scale.ts)       | scale.         |

## Subdirectories

- [charts/](charts/README.md) — Chart implementations.

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
