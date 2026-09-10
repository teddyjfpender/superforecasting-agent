# Deep dive: the TUI architecture

The TUI is a React + Ink terminal app in `ui-tui/`, talking to the Python gateway
over stdio JSON-RPC (typed by `protocol/` — see
[protocol-and-gateway.md](protocol-and-gateway.md)). The
[architecture overview](../architecture.md) and the operator's guide
([operating.md](../operating.md)) cover *using* it; this page is the internals:
the forked Ink renderer, the view/store structure, the skin engine and its sync
law, the design laws the components hold to, and the keyboard/help system. The
`ui-tui/README.md` is the file-by-file map; this page is the *why*.

---

## The Ink fork (`@superforecasting/ink`)

`ui-tui/packages/forecast-ink/` is a **forked Ink renderer**, a local workspace
dependency (`@superforecasting/ink`, imported through the compatibility shim
`ui-tui/src/types/forecast-ink.d.ts`). It is forked because stock Ink is a
keyboard-and-layout renderer with no mouse and no incremental-diff control; the
desk needs both. What the fork adds lives under
`packages/forecast-ink/src/ink/`:

- **Mouse.** `parse-keypress.ts` decodes SGR mouse sequences (`\x1b[<b;x;yM`,
  `SGR_MOUSE_RE`), including a fragment-recovery regex for sequences split across
  reads. `hit-test.ts` finds the deepest rendered node containing `(col, row)`
  from the `nodeCache` populated during render, and bubbles a `ClickEvent` up
  through `parentNode` — but **`hitTest` skips `#text` nodes**. The consequence,
  stated as a rule the app relies on:

  > **A click can only land on a `<Box>`.** `<Text>` has no click zone. The
  > `homeLanding.tsx` agents-chip comment says it outright: *"this Ink fork drops
  > `<Text onClick>`"* — so every interactive seam (nav tabs, desk rows, chips)
  > wraps its target in a `<Box onClick>`. Handlers guard on `event.cellIsBlank`
  > (ignore clicks on padding) and gate themselves out while a global modal is up.

  `dispatchMouse`/`onMouseEnter`/`onMouseLeave` follow DOM semantics (enter/leave
  don't bubble). Selection (`selection.ts`) and hyperlink hover
  (`hyperlinkHover.ts`) are pure post-layout SGR passes picked up by the diff.
- **Incremental diff.** `log-update.ts` re-anchors SGR per row in the incremental
  diff so bold can't flicker across rows; `output.ts` chooses a blit path for large
  frames. This is what makes a dense, frequently-updating desk repaint cleanly.

---

## View and component structure

`src/entry.tsx` gates on a TTY, starts `GatewayClient` (which spawns
`python -m tui_gateway.entry`), and renders `App`. `src/app.tsx` composes the Ink
tree; heavy logic is split into `src/app/` (hooks + nanostores) and `src/components/`.

- **Layout.** `components/appLayout.tsx` orchestrates the top-level composition;
  `appChrome.tsx` owns the status rule / input row / completions; `appOverlays.tsx`
  routes pickers and prompts. Views are components (`deskView`, `marketsView`,
  `alertsView`, `calendarView`, `calibrationView`, `agentsOverlay`, …).
- **Stores.** State that must be shared without prop-drilling lives in nanostores
  under `src/app/` (`overlayStore`, `uiStore`, `homeFocusStore`,
  `agentsActiveStore`, `delegationStore`, `marketJobsStore`, `chordStore`,
  `turnStore`, …). React context (`gatewayContext.tsx`) carries the gateway client.
- **The one nav source of truth.** `src/app/navRoutes.ts` holds `NAV_TABS` and the
  overlay patch each route selects. `NavBar` (mouse) and `useInputHandlers`
  (the `Ctrl+G`-then-letter view chord) **both** route through
  `navPatchFor`/`selectNavView`, so a click and a `Ctrl+G d` chord land on
  byte-identical overlay state — key and click can never drift. A tab click also
  clears the global overlays, so it closes an open palette/cheat-sheet as it
  navigates. `NAV_TABS` is also where the **dev gate** is applied: it is a
  filtered view of a private `ALL_NAV_TABS` (`demoViz` ships behind
  `FORECAST_TUI_DEV_DEMO_VIZ`), and `navPatchFor` refuses any key not in it —
  so a gated route is genuinely unreachable by click *or* chord, on the same
  single membership check rather than two conditions that could diverge.
- **The event handler on generated names.** `src/app/createGatewayEventHandler.ts`
  maps gateway events to state updates, switching on `WireEvent.X` constants from
  the generated protocol module — not raw strings (see
  [protocol-and-gateway.md](protocol-and-gateway.md): a renamed event is a compile
  error, and a grep-proof test asserts no raw event-name literal survives outside
  the generated module).

---

## The skin engine and the theme sync law

Two halves render the same theme and **must** agree:

- **Python** — `superforecasting_agent/runtime/skin_engine.py` is the data-driven skin system
  (built-in presets + user YAML under `~/.superforecasting-agent/skins/`). The
  runtime default is `_BUILTIN_SKINS["default"]` — *"Standard — Aurora (lavender +
  rose)"*. The gateway resolves the active skin and ships it on `gateway.ready`.
- **TypeScript** — `ui-tui/src/theme.ts` starts from `DEFAULT_THEME` (the Aurora
  palette: `BRAND_GRADIENT` = blue → lavender-purple → rose-pink) and **merges in**
  the gateway skin data on `gateway.ready` / `skin.changed`.

> **The sync law: `theme.ts`'s `DARK_THEME` and `skin_engine.py`'s `default`
> skin must stay in sync.** They are two independent encodings of the same
> palette; a colour changed on one side and not the other produces a first-paint
> flash (the TS default) that then snaps to the merged Python skin. `theme.ts`
> also enforces a 4.5:1 dark-contrast floor (`enforceDarkContrastFloor`); on
> dark-designed palettes the floor is a no-op, which is what preserves the
> `DEFAULT_THEME === DARK_THEME` aliasing invariant other code relies on.
> Nuance since the light-terminal work: `DEFAULT_THEME` is now
> `enforceDarkContrastFloor(DEFAULT_LIGHT_MODE ? LIGHT_THEME : DARK_THEME)` —
> `detectLightMode()` picks a darker-ink `LIGHT_THEME` variant on light
> terminals, so the aliasing invariant is a property of the (default) dark
> path, not of a light-mode launch.

---

## The design laws

These are conventions the components hold to so the dense desk stays readable and
performant. Each is enforced by a component and, where noted, a named test.

- **The wrap law.** In the Desk summary panel the focused title **wraps** — it is
  never `…`-chopped — and long teasers read to their honest end (the old silent
  `slice(0, 120)` chop is gone). Guarded by the `deskView.test.tsx` `describe('sidebar
  wrap law', …)` test, which pins the contract at the component level with a
  deterministic width (see the width-pin note below).
- **2dp precision.** Probabilities **always** render at two decimals (`"32.64%"`,
  `"0.85%"`, `"98.00%"`) so a column aligns and small moves are legible
  (`lib/pmData.ts`, `lib/forecastCharts.ts`). Whole counts render without decimals;
  the split is explicit, not incidental.
- **Whole-row highlight.** A selected row's highlight carries across its **full
  width** — no half-highlighted rows. Two implementations of the one law:
  `alertsView.tsx` appends a trailing filler cell that carries the selection
  background to the row edge, while `marketsView.tsx` and
  `predictionMarketsTable.tsx` render the row as one full-width background
  ("the background IS the cursor", both noting desk-view parity).
- **Memo-safe animation with bucketed `nowMs`.** Time-derived labels ("next sweep
  in 3m", elapsed) would re-render memoized rows on every frame if fed a raw
  `Date.now()`. The desk passes a **bucketed** now — `nowMs={Math.floor(Date.now()
  / 60_000) * 60_000}` — so the value only changes once a minute, and a memoized
  row list repaints at most per-minute instead of per-tick. Short-lived local
  animations (the agents-chip sweep) run their own bounded `setInterval` and mount
  **only while active** (chip mounts only when `count > 0`), so at rest the surface
  is byte-identically animation-free.
- **The three-item status-bar law.** The Home landing's status bar is
  **deliberately sparse — exactly three items**: ready-state · the single most
  actionable count (`N to review`) · the model. The dense forecast inventory
  (forecasts/theses/factors/entities/alerts/closing) is **gone** from the landing —
  that detail lives in the Desk and the status views. The three-item core is one
  `wrap="truncate-end"` Text so, at rest with no agents chip, the line is
  byte-identical to the pre-chip bar (`homeLanding.tsx`).

---

## Keymaps and the `h`-help system

`src/content/keymaps.ts` is the static keymap registry behind the global chrome —
one small table so the cheat-sheet stays truthful without every view growing its
own help modal:

- `VIEW_CHORDS` — the `Ctrl+G`-then-letter view switches (letters prefer the tab's
  initial; hand-resolved collisions, e.g. Markets keeps `m`);
- `GLOBAL_KEYS` — the cheat-sheet's global section (`h`/`?` help, `Ctrl+K`
  palette, the chord list, click-a-tab, `/` slash);
- per-view key rows, keyed by `NAV_TABS` key, assembled into the "This view"
  section.

**`h` opens one Help modal on every view** (`?` is the alias). `helpOverlay.tsx`
renders per-view GUIDE prose above the grouped shortcut table; `helpHint.tsx` /
`helpView.tsx` are the surfaces. The three formerly-drifting help surfaces (the
keymaps cheat-sheet, the `?` overlay, and Markets' `InfoModal`) were **unified** —
`cheatSheetOverlay.tsx` is now a thin re-export: `export { HelpOverlay as
CheatSheetOverlay } from './helpOverlay.js'`. When `h` conflicted with a vim-left
`h` (desk prev-lens, warnings collapse, calendar day-left, docs/agents pane-left),
those were remapped to `←`; the `h Help` chip appears in every footer.

---

## Footer chips and `flexWrap`

`components/footerChips.tsx` renders the per-view shortcut chips. The container is
`<Box flexWrap="wrap">` — a deliberate change: a crowded row (the Desk's ~dozen
chips plus the new `h Help` chip) would clip at ~120 cols (the Desk's 12th chip was
truncating `"Lens"` → `"Len"`), so the chips now **flow onto a second line** rather
than truncate. Each chip is a `flexShrink={0}` Box (a click zone, per the Ink-fork
rule above).

---

## Sources

- Ink fork: `ui-tui/packages/forecast-ink/src/ink/hit-test.ts`, `parse-keypress.ts`,
  `log-update.ts`, `output.ts`, `selection.ts`, `hyperlinkHover.ts`;
  `ui-tui/packages/forecast-ink/package.json` (`@superforecasting/ink`)
- Structure: `ui-tui/src/entry.tsx`, `app.tsx`, `app/navRoutes.ts`,
  `app/createGatewayEventHandler.ts`, `components/appLayout.tsx`, `appChrome.tsx`;
  `ui-tui/README.md`
- Theme: `superforecasting_agent/runtime/skin_engine.py` (`_BUILTIN_SKINS["default"]`),
  `ui-tui/src/theme.ts` (`DEFAULT_THEME`, `BRAND_GRADIENT`,
  `enforceDarkContrastFloor`)
- Design laws: `components/deskView.tsx` (bucketed `nowMs`),
  `components/homeLanding.tsx` (three-item bar, chip mounting),
  `lib/pmData.ts`/`lib/forecastCharts.ts` (2dp), `components/predictionMarketsTable.tsx`/
  `alertsView.tsx`/`marketsView.tsx` (whole-row); `__tests__/deskView.test.tsx`
  ("sidebar wrap law")
- Help/chips: `src/content/keymaps.ts`, `components/helpOverlay.tsx`,
  `cheatSheetOverlay.tsx`, `footerChips.tsx`
- Background: ARC A2 commit `6b13707a2` (help unification, `FooterChips` flexWrap),
  the Aurora theme change, `docs/plans/2026-07-03-architecture-delivery-plan.md`

## Dashboard transport recovery

The dashboard embeds the same Ink process via a POSIX PTY. Both launch paths use
`superforecasting_agent/runtime/tui_environment.py` for interpreter, source-root
and working-directory settings. The web server owns transport authentication;
`pty_sessions.py` owns process lifetime and bounded replay.

A transient WebSocket loss retains the child for 30 seconds. The browser keeps
its terminal buffer and reconnects with its received byte cursor and an explicit
reconnect flag. The latter prevents a zero-output expired session from silently
starting a replacement. Replay is capped at 1 MiB and 16 retained/attached desks.
An expired session, missing bytes or competing attachment requires explicit
resume through Forecast Sessions. Input is paused while disconnected. Normal
close ends the child; application shutdown reaps retained children.

Cancellation preserves separate durable user turns. Provider role-sequence
repair operates on request copies, because merging stored user turns after an
interruption would move the SQLite append cursor past the follow-up prompt.
The real PTY regression covers a stalled stream, cancellation, resize, a new
successful turn, process exit, and hydration from the session database.
