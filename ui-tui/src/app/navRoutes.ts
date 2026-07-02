import type { OverlayState } from './interfaces.js'
import { patchOverlayState } from './overlayStore.js'

// Single source of truth for the top-bar routes AND the keyboard/g-chord that
// switches between them. NavBar (mouse) and useInputHandlers (keyboard) BOTH
// route through `navPatchFor` / `selectNavView` so a click and a `g d` chord
// land on byte-identical overlay state — key and click never drift.

export type NavTab = { key: string; label: string }

export const NAV_TABS: NavTab[] = [
  { key: 'home', label: 'Home' },
  { key: 'desk', label: 'Desk' },
  { key: 'markets', label: 'Markets' },
  { key: 'news', label: 'News' },
  { key: 'messaging', label: 'Messaging' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'warnings', label: 'Warnings' },
  { key: 'calibration', label: 'Calibration' },
  { key: 'obsidian', label: 'Docs' },
  { key: 'agents', label: 'Agents' },
  { key: 'demoViz', label: 'Demo Vis' },
  { key: 'hooks', label: 'Hooks' },
  { key: 'help', label: 'Help' }
]

// Clearing every view flag returns to the chat/home route.
export const HOME_PATCH = {
  agents: false,
  alerts: false,
  calendar: false,
  calibration: false,
  // Clear the global overlays too: a NavBar click routes through here even while
  // the palette / cheat-sheet is open (the top bar sits above that modal and its
  // mouse target is never gated), so a tab click must CLOSE the modal as it
  // navigates instead of silently mutating the route underneath it.
  cheatSheet: false,
  demoViz: false,
  forecasts: false,
  forecastsInitialId: null,
  help: false,
  hooks: false,
  markets: false,
  messaging: false,
  news: false,
  obsidian: false,
  palette: false
} as const

// The overlay patch a route selects. Returns null for an unknown key so the
// caller can no-op safely (chords derive their key set from NAV_TABS, so this
// only guards typos).
export const navPatchFor = (key: string): null | Partial<OverlayState> => {
  switch (key) {
    case 'home':
      return { ...HOME_PATCH }

    case 'desk':
      return { ...HOME_PATCH, forecasts: true }

    case 'markets':
      return { ...HOME_PATCH, markets: true }

    case 'news':
      return { ...HOME_PATCH, news: true }

    case 'messaging':
      return { ...HOME_PATCH, messaging: true }

    case 'calendar':
      return { ...HOME_PATCH, calendar: true }

    case 'warnings':
      return { ...HOME_PATCH, alerts: true }

    case 'calibration':
      return { ...HOME_PATCH, calibration: true }

    case 'obsidian':
      return { ...HOME_PATCH, obsidian: true }

    case 'agents':
      return { ...HOME_PATCH, agents: true, agentsInitialHistoryIndex: 0 }

    case 'demoViz':
      return { ...HOME_PATCH, demoViz: true }

    case 'hooks':
      return { ...HOME_PATCH, hooks: true }

    case 'help':
      return { ...HOME_PATCH, help: true }

    default:
      return null
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
  overlay.forecasts
    ? 'desk'
    : overlay.markets
      ? 'markets'
      : overlay.news
        ? 'news'
        : overlay.messaging
          ? 'messaging'
          : overlay.calendar
            ? 'calendar'
            : overlay.calibration
              ? 'calibration'
              : overlay.alerts
                ? 'warnings'
                : overlay.obsidian
                  ? 'obsidian'
                  : overlay.agents
                    ? 'agents'
                    : overlay.demoViz
                      ? 'demoViz'
                      : overlay.hooks
                        ? 'hooks'
                        : overlay.help
                          ? 'help'
                          : 'home'
