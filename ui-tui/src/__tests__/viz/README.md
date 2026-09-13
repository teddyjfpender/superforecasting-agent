# Visualization tests

Checks chart output, robustness, width handling and rendering behavior.

## Ownership and boundaries

Include malformed numeric data and constrained viewports; snapshots alone must not conceal incorrect measurement meaning.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility    |
| ---------------------------------------- | ----------------- |
| [charts.test.ts](charts.test.ts)         | charts tests.     |
| [charts2.test.ts](charts2.test.ts)       | charts2 tests.    |
| [engine.test.ts](engine.test.ts)         | engine tests.     |
| [phase3.test.ts](phase3.test.ts)         | phase3 tests.     |
| [render.test.tsx](render.test.tsx)       | render tests.     |
| [robustness.test.ts](robustness.test.ts) | robustness tests. |
| [width.test.ts](width.test.ts)           | width tests.      |

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
