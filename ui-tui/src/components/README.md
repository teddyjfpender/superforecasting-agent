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

## Messaging and documents

- `messagingView.tsx` owns conversation navigation; `quickMessage.tsx` provides
  global compose and forwarding. Both use the shared send owner.
- `documentDesk.tsx` owns library selection and editing; `documentReader.tsx`
  bounds Markdown/LaTeX scrolling; `documentConnections.tsx` owns explicit sync.
- Gate background keyboard and mouse actions while a modal is open. Keep drafts
  outside component lifetime and reject stale asynchronous selection results.

See the [desk architecture](../../../../docs/architecture/messaging-docs-desk.md)
for keybindings, storage ownership and regression coverage.

## Subdirectories

- [desk/](desk/README.md) — Desk display helpers.
- [forecast/](forecast/README.md) — Forecast display helpers.
- [viz/](viz/README.md) — Terminal visualization components.

## Help and footer actions

Use `useViewInput` for a view's keyboard handler and pass its returned dispatcher
as `FooterChips.onKey`. Keep text/modal guards before browsing shortcuts. Give
compound actions explicit callbacks; combined navigation legends are non-clickable.
Update `content/keymaps.ts` with behavior changes. See the
[help audit](../../../../docs/verification/help-shortcuts.md).

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

`contactPicker.tsx` is the shared contact/chat browser for Messaging, quick
compose and group-member selection. Keep search ranking in `messagingSearch.ts`
and contact synchronization in `signalDirectory.ts`; the picker owns bounded
layout, scopes and selection only.

`messageComposer.tsx` owns the bounded message editor used by chat and quick
compose. Send attempts are shared through `messagingSend.ts`; message status
belongs in the conversation, while draft persistence remains with the caller.

## Keyboard hints

Use `FooterChips` for actionable footer buttons and `ShortcutText` for help prose
or modal hints. Keys use the theme accent plus bold weight; surrounding copy keeps
its normal color. Put ambiguous single-letter keys in backticks, for example
``Press `f` to filter``. The renderer removes those delimiters. Named keys, chords,
and bracketed hints are recognized automatically. Keep actual bindings in their
existing input handlers/keymap registry; this component only renders instructions.
Never apply it to user messages, articles, documents, or model-generated prose.
