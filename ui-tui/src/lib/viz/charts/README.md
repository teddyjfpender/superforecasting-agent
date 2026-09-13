# Chart implementations

Implements distribution, depth, fan, heatmap, candle and other chart layouts.

## Ownership and boundaries

Reuse shared buffers and scales; preserve uncertainty and avoid misleading normalization.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility |
| ---------------------------------- | -------------- |
| [\_layout.ts](_layout.ts)          | layout.        |
| [candles.ts](candles.ts)           | candles.       |
| [depth.ts](depth.ts)               | depth.         |
| [distribution.ts](distribution.ts) | distribution.  |
| [fan.ts](fan.ts)                   | fan.           |
| [heatmap.ts](heatmap.ts)           | heatmap.       |
| [scatter.ts](scatter.ts)           | scatter.       |
| [sparkgrid.ts](sparkgrid.ts)       | sparkgrid.     |

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
