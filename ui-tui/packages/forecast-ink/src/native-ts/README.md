# Native layout bridge

Groups the TypeScript interface to the Yoga layout binding used by the terminal renderer.

## Ownership and boundaries

Keep binding exports and enums aligned with the actual layout implementation. Business logic and terminal event routing belong elsewhere.

## Subdirectories

- [yoga-layout/](yoga-layout/README.md) — Terminal renderer — native-ts / yoga-layout.

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
