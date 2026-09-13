# Client data interpretation

Contains pure helpers for message roles, paths, providers, viewport data and slash input.

## Ownership and boundaries

Validate external values before rendering and retain distinctions such as missing versus empty data.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                         | Responsibility |
| ---------------------------- | -------------- |
| [details.ts](details.ts)     | details.       |
| [fileDrop.ts](fileDrop.ts)   | fileDrop.      |
| [messages.ts](messages.ts)   | messages.      |
| [paths.ts](paths.ts)         | paths.         |
| [providers.ts](providers.ts) | providers.     |
| [roles.ts](roles.ts)         | roles.         |
| [slash.ts](slash.ts)         | slash.         |
| [usage.ts](usage.ts)         | usage.         |

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
