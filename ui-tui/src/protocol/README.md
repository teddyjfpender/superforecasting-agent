# Client protocol support

Contains generated gateway types and terminal paste/interpolation protocol helpers.

## Ownership and boundaries

Regenerate gateway types from the root protocol package. Keep terminal escape parsing separate from backend RPC semantics.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility |
| ------------------------------------ | -------------- |
| [generated.ts](generated.ts)         | generated.     |
| [interpolation.ts](interpolation.ts) | interpolation. |
| [paste.ts](paste.ts)                 | paste.         |

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
