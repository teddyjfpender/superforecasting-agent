# Dashboard

Dashboard application entrypoints and routing.

## Ownership and boundaries

The primary transcript and composer remain in the embedded Ink TUI. Supporting panels must fail independently of the PTY session. Preserve authentication and reject stale connection events.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                 | Responsibility |
| -------------------- | -------------- |
| [main.tsx](main.tsx) | main.          |
| [App.tsx](App.tsx)   | App.           |

## Subdirectories

- [components/](components/README.md) — Dashboard — components.
- [contexts/](contexts/README.md) — Dashboard — contexts.
- [hooks/](hooks/README.md) — Dashboard — hooks.
- [i18n/](i18n/README.md) — Dashboard — i18n.
- [lib/](lib/README.md) — Dashboard — lib.
- [pages/](pages/README.md) — Dashboard — pages.
- [plugins/](plugins/README.md) — Dashboard — plugins.
- [themes/](themes/README.md) — Dashboard — themes.

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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
