# Dashboard — components

Supporting dashboard panels, dialogs, navigation and data displays.

## Ownership and boundaries

The primary transcript and composer remain in the embedded Ink TUI. Supporting panels must fail independently of the PTY session. Preserve authentication and reject stale connection events.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                               | Responsibility       |
| -------------------------------------------------- | -------------------- |
| [AutoField.tsx](AutoField.tsx)                     | AutoField.           |
| [Backdrop.tsx](Backdrop.tsx)                       | Backdrop.            |
| [BottomPickSheet.tsx](BottomPickSheet.tsx)         | BottomPickSheet.     |
| [DeleteConfirmDialog.tsx](DeleteConfirmDialog.tsx) | DeleteConfirmDialog. |
| [ForecastSidePanel.tsx](ForecastSidePanel.tsx)     | ForecastSidePanel.   |
| [LanguageSwitcher.tsx](LanguageSwitcher.tsx)       | LanguageSwitcher.    |
| [Markdown.tsx](Markdown.tsx)                       | Markdown.            |
| [ModelInfoCard.tsx](ModelInfoCard.tsx)             | ModelInfoCard.       |

## Subdirectories

- [ui/](ui/README.md) — Dashboard — components/ui.

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
