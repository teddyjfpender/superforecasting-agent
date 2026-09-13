# Local slash handlers

Implements terminal session, setup, operations and debugging commands.

## Ownership and boundaries

Local handlers own navigation and presentation. Shared validation and durable mutation belong to backend application owners.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                     | Responsibility |
| ------------------------ | -------------- |
| [core.ts](core.ts)       | core.          |
| [debug.ts](debug.ts)     | debug.         |
| [ops.ts](ops.ts)         | ops.           |
| [session.ts](session.ts) | session.       |
| [setup.ts](setup.ts)     | setup.         |

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
