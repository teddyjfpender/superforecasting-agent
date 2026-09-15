# Terminal test helpers

Provides deterministic helpers for settling asynchronous UI work in tests.

## Ownership and boundaries

Bound waits and make failure observable; avoid sleeps that merely hide event ordering races.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                   | Responsibility |
| ---------------------- | -------------- |
| [settle.ts](settle.ts) | settle.        |

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

`dataDesk.ts` supplies a controlled backend for product-view tests from the real
catalog manifest, keeping client-local files out of the production selection flow.
