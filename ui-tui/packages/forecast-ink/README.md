# Forecast terminal renderer

Packages the terminal rendering primitives used by the Ink forecast desk, including layout, terminal input and screen output.

## Ownership and boundaries

Keep the renderer independent of forecasting state. Changes must preserve upstream attribution, terminal restoration, Unicode width and resize behavior.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility |
| ---------------------------------- | -------------- |
| [ambient.d.ts](ambient.d.ts)       | ambient.d.     |
| [index.d.ts](index.d.ts)           | index.d.       |
| [text-input.d.ts](text-input.d.ts) | text-input.d.  |

## Subdirectories

- [src/](src/README.md) — Terminal renderer.

## Reader scroll behavior

Use `ScrollBox` with `followContent={false}` for article/document readers. Content
loading and viewport resizing then preserve the reading position instead of
following the tail. Explicit scroll commands still work; shrinking content clamps
the position to its new bounds. Keep the default follow behavior for chat streams.
Side-by-side panes also need `decstbm={false}` and an explicit viewport height.

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
