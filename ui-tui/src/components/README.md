# Terminal components

Renders transcript lines, composer inputs, prompts, overlays and forecasting desk views.

## Ownership and boundaries

Keep the primary desk here so the dashboard can embed the same experience. Components consume state instead of owning backend workflows.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                         | Responsibility    |
| -------------------------------------------- | ----------------- |
| [addFeedModal.tsx](addFeedModal.tsx)         | addFeedModal.     |
| [addProviderModal.tsx](addProviderModal.tsx) | addProviderModal. |
| [agentsOverlay.tsx](agentsOverlay.tsx)       | agentsOverlay.    |
| [alertsView.tsx](alertsView.tsx)             | alertsView.       |
| [appChrome.tsx](appChrome.tsx)               | appChrome.        |
| [appLayout.tsx](appLayout.tsx)               | appLayout.        |
| [appOverlays.tsx](appOverlays.tsx)           | appOverlays.      |
| [asciiAnimation.tsx](asciiAnimation.tsx)     | asciiAnimation.   |

## Subdirectories

- [desk/](desk/README.md) — Desk display helpers.
- [forecast/](forecast/README.md) — Forecast display helpers.
- [viz/](viz/README.md) — Terminal visualization components.

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
