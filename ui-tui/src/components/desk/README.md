# Desk display helpers

Builds desk table cells and job display information.

## Ownership and boundaries

Distinguish absent data from zero and durable completion from local activity.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                 | Responsibility |
| -------------------- | -------------- |
| [cells.ts](cells.ts) | cells.         |
| [jobs.ts](jobs.ts)   | jobs.          |

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
