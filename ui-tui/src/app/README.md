# Terminal application state

Owns TUI composition, navigation, prompt arbitration and gateway event projection.
Python owns durable sessions and forecast records; these stores must never infer a
successful operation from cancellation acknowledgement or transport reconnection.

## Navigation and interaction ownership

- [`primaryRoute.ts`](primaryRoute.ts) defines the primary-view registry and route
  type. One private navigation atom stores exactly one route alongside independent
  modal state. Adding a view requires a registry entry and rendering/interaction tests.
- [`overlayStore.ts`](overlayStore.ts) exposes read-only `$primaryRoute` and
  `$overlayState` projections. Legacy view booleans are derived, never stored.
  Use `patchOverlayState` for compatibility changes; enabling a new view replaces
  the previous one. Ambiguous requests selecting multiple new views fail before
  mutation. Never add a second writable route store.
- [`navRoutes.ts`](navRoutes.ts) owns supported navigation, tab ordering and dev gates.
  Use `selectNavView` for mouse, keyboard and programmatic navigation. This operation
  also closes the global palette/help chrome; raw compatibility patches do not.
- Blocking prompts use `raisePrompt` and a FIFO queue in `overlayStore.ts`.
  A primary route can coexist with a modal; switching route cannot implicitly answer
  a prompt. Local component focus remains local until an explicit shared owner exists.

`resetFlowOverlays` clears completed-turn prompts while retaining the primary view and
open questionnaire identity. `resetOverlayState` is the full reset to Home. Preserve
this distinction: clearing a questionnaire identifier while retaining its open flag
can detach the UI from its durable draft.

## Other entry points

| File | Responsibility |
| --- | --- |
| [createGatewayEventHandler.ts](createGatewayEventHandler.ts) | Translate backend events into presentation updates. |
| [createSlashHandler.ts](createSlashHandler.ts) | Route client commands and backend fallthrough. |
| [commandStore.ts](commandStore.ts) | Active command state. |
| [delegationStore.ts](delegationStore.ts) | Delegated activity projection. |
| [composerTextStore.ts](composerTextStore.ts) | Shared composer text. |
| [chordStore.ts](chordStore.ts) | Pending keyboard chords. |

[forecast/](forecast/README.md) contains forecast view helpers;
[slash/](slash/README.md) contains terminal slash routing. Domain validation and
persistence belong in backend application owners, not these stores.

## Verification

Run `npm --prefix ui-tui run type-check` and `npm --prefix ui-tui run lint`.
For navigation changes, run explicit Vitest files from `ui-tui/`:

```sh
node_modules/.bin/vitest run src/__tests__/primaryRoute.test.ts \
  src/__tests__/overlayFlowReset.test.ts src/__tests__/promptQueue.test.ts \
  src/__tests__/globalChrome.test.tsx src/__tests__/keymapTruthfulness.test.ts
```

Input, resize and shutdown changes also need the relevant native installed-terminal
verification; renderer tests alone do not qualify ConPTY or PTY behavior.
See the [ownership map](../../../docs/architecture/ownership-map.md) and
[engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
