# Terminal React hooks

Provides completion, history, queue and other reusable client interactions.

## Ownership and boundaries

Clean up subscriptions and reject late asynchronous results when sessions or requests change.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                         | Responsibility     |
| -------------------------------------------- | ------------------ |
| [useCompletion.ts](useCompletion.ts)         | useCompletion.     |
| [useGitBranch.ts](useGitBranch.ts)           | useGitBranch.      |
| [useInputHistory.ts](useInputHistory.ts)     | useInputHistory.   |
| [useQueue.ts](useQueue.ts)                   | useQueue.          |
| [useVirtualHistory.ts](useVirtualHistory.ts) | useVirtualHistory. |

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
