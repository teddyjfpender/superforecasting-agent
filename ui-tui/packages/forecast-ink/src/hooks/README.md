# Terminal renderer — hooks

Public stdout and stderr integration hooks.

## Ownership and boundaries

Keep these primitives independent of forecast business logic. Preserve terminal restoration, Unicode width and exact resource ownership; test malformed input and repeated cleanup. Retain upstream attribution when changing inherited code.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility |
| ------------------------------ | -------------- |
| [use-stderr.ts](use-stderr.ts) | use-stderr.    |
| [use-stdout.ts](use-stdout.ts) | use-stdout.    |

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
