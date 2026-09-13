# Dashboard — contexts

Shared React context for dashboard page headers and system actions.

## Ownership and boundaries

The primary transcript and composer remain in the embedded Ink TUI. Supporting panels must fail independently of the PTY session. Preserve authentication and reject stale connection events.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                   | Responsibility          |
| ------------------------------------------------------ | ----------------------- |
| [PageHeaderProvider.tsx](PageHeaderProvider.tsx)       | PageHeaderProvider.     |
| [SystemActions.tsx](SystemActions.tsx)                 | SystemActions.          |
| [page-header-context.ts](page-header-context.ts)       | page-header-context.    |
| [system-actions-context.ts](system-actions-context.ts) | system-actions-context. |
| [usePageHeader.ts](usePageHeader.ts)                   | usePageHeader.          |
| [useSystemActions.ts](useSystemActions.ts)             | useSystemActions.       |

## Working in this directory

From the repository root, run:

```sh
npm --prefix web run lint
npm --prefix web run build
npm --prefix web test
```

Exercise the affected page in a browser. For desk changes, include PTY reconnect
and resize behavior and confirm supporting-panel failures leave the terminal usable.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
