import { DEV_DEMO_VIZ } from '../config/env.js'

import type { OverlayState } from './interfaces.js'
import { patchOverlayState } from './overlayStore.js'
import { PRIMARY_VIEWS, primaryFlags } from './primaryRoute.js'

// Single source of truth for the top-bar routes AND the keyboard/Ctrl+G chord
// that switches between them. NavBar (mouse) and useInputHandlers (keyboard)
// BOTH route through `navPatchFor` / `selectNavView` so a click and a Ctrl+G d
// chord land on byte-identical overlay state — key and click never drift.

export type NavTab = { key: string; label: string }

// Routes that ship ONLY behind a dev flag, keyed by NAV tab key. Off by default
// means the route is ABSENT, not hidden: it drops out of NAV_TABS, and NAV_TABS
// is the ONE gate every entry point reads — NavBar renders it, `navPatchFor`
// refuses a key that is not in it (so a mouse click AND a Ctrl+G chord die on
// the same check, never on two conditions that can drift), and the Help modal
// builds its "all views" wall from it. There is no second route in.
const DEV_GATED_NAV: Record<string, boolean> = { demoViz: DEV_DEMO_VIZ }

// The names of every dev-gated route, independent of whether its flag is on.
// The keymap registry keeps honest help rows for these views (they still ship —
// just behind a flag), so it needs to say which entries are legitimately absent
// from the shipped tab list. See __tests__/keymapTruthfulness.test.ts.
export const DEV_GATED_NAV_KEYS: readonly string[] = Object.keys(DEV_GATED_NAV)

// Every route the app knows how to render, in top-bar order.
const ALL_NAV_TABS: NavTab[] = PRIMARY_VIEWS.map(({ key, label }) => ({ key, label }))

// The routes this process actually offers.
export const NAV_TABS: NavTab[] = ALL_NAV_TABS.filter(tab => DEV_GATED_NAV[tab.key] ?? true)

const NAV_KEYS = new Set(NAV_TABS.map(tab => tab.key))

// Clearing every view flag returns to the chat/home route.
export const HOME_PATCH = {
  ...primaryFlags('home'),
  alertsInitialFocus: null,
  // Clear the global overlays too: a NavBar click routes through here even while
  // the palette / cheat-sheet is open (the top bar sits above that modal and its
  // mouse target is never gated), so a tab click must CLOSE the modal as it
  // navigates instead of silently mutating the route underneath it.
  cheatSheet: false,
  forecastsInitialId: null,
  palette: false
} as const

// The overlay patch a route selects. Returns null for a key NAV_TABS does not
// ship — a typo, or a dev-gated route whose flag is off. Every entry point (a
// NavBar click, a Ctrl+G chord, `selectNavView` from anywhere) funnels through
// this one membership check, which is what keeps mouse and keyboard from ever
// disagreeing about which routes exist.
export const navPatchFor = (key: string): null | Partial<OverlayState> => {
  if (!NAV_KEYS.has(key)) {
    return null
  }

  const view = PRIMARY_VIEWS.find(item => item.key === key)

  if (!view) { return null }

  return {
    ...HOME_PATCH,
    ...(view.flag === null ? {} : { [view.flag]: true }),
    ...(key === 'agents' ? { agentsInitialHistoryIndex: 0 } : {})
  }
}

export const selectNavView = (key: string): boolean => {
  const patch = navPatchFor(key)

  if (!patch) {
    return false
  }

  patchOverlayState(patch)

  return true
}

// May the global interaction chrome (palette / cheat-sheet / view chords) open
// right now? Suppressed while an input-owning prompt or floating picker holds
// the keyboard (approval/clarify/confirm/sudo/secret, pager, session picker,
// model/theme picker, skills hub, onboarding) or while the palette/cheat-sheet
// is already up. A plain fullscreen VIEW (Desk, Markets, …) does NOT suppress
// it — the chrome opens over it as its own modal.
export const canOpenGlobalOverlay = (overlay: OverlayState): boolean =>
  !(
    overlay.approval ||
    overlay.clarify ||
    overlay.confirm ||
    overlay.sudo ||
    overlay.secret ||
    overlay.pager ||
    overlay.picker ||
    overlay.modelPicker ||
    overlay.themePicker ||
    overlay.skillsHub ||
    overlay.onboard ||
    overlay.palette ||
    overlay.cheatSheet
  )

// Which route is the active one, derived from the live overlay flags. Shared by
// NavBar's highlight and the cheat-sheet's "current view" section.
export const activeNavKey = (overlay: OverlayState): string =>
  PRIMARY_VIEWS.find(view => view.flag !== null && overlay[view.flag])?.key ?? 'home'
