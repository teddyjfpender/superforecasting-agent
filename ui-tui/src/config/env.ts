import { tuiEnvValue } from '../lib/envAlias.js'
import { isTermuxTuiMode } from '../lib/termux.js'

const truthy = (v?: string) => /^(?:1|true|yes|on)$/i.test((v ?? '').trim())
const falsy = (v?: string) => /^(?:0|false|no|off)$/i.test((v ?? '').trim())

export { tuiEnvValue }

const parseToggle = (v?: string): boolean | null => {
  const raw = (v ?? '').trim()

  if (!raw) {
    return null
  }

  if (truthy(raw)) {
    return true
  }

  if (falsy(raw)) {
    return false
  }

  return null
}

export const TERMUX_TUI_MODE = isTermuxTuiMode()

export const STARTUP_RESUME_ID = tuiEnvValue('RESUME')
export const STARTUP_QUERY = tuiEnvValue('QUERY')
export const STARTUP_IMAGE = tuiEnvValue('IMAGE')

const mouseTrackingOverride = parseToggle(tuiEnvValue('MOUSE_TRACKING'))
const mouseTrackingDisabledLegacy = truthy(tuiEnvValue('DISABLE_MOUSE'))
// Mobile selection UX: on Termux default mouse tracking OFF so touch selection
// is less likely to be intercepted by terminal mouse protocols. Desktop keeps
// prior behavior unless explicitly overridden.
export const MOUSE_TRACKING = mouseTrackingOverride ?? (TERMUX_TUI_MODE ? false : !mouseTrackingDisabledLegacy)

export const NO_CONFIRM_DESTRUCTIVE = truthy(tuiEnvValue('NO_CONFIRM'))

const inlineOverride = parseToggle(tuiEnvValue('INLINE'))

// Skip AlternateScreen — TUI renders into the primary buffer so the host
// terminal's native scrollback captures whatever scrolls off the top.
//
// On Termux we default this on: users often background/foreground the app,
// and primary-buffer rendering makes long-thread review and copy/paste much
// less fragile. Override explicitly with FORECAST_TUI_INLINE=0/1 or
// compatibility HERMES_TUI_INLINE=0/1.
export const INLINE_MODE = inlineOverride ?? TERMUX_TUI_MODE

// Live FPS counter overlay, fed by ink's onFrame (real render rate, not a
// synthetic timer).
export const SHOW_FPS = truthy(tuiEnvValue('FPS'))

// Dev-only: the "Demo Vis" gallery of the terminal chart engine. It is
// scaffolding for the viz engine — a place to eyeball rendering across terminals
// — not an operator surface, so it is OFF by default and the route is genuinely
// ABSENT rather than hidden (see app/navRoutes: it drops out of NAV_TABS, which
// is the one gate the nav bar, the Ctrl+G chords and the Help wall all read).
//
// Turn it on with FORECAST_TUI_DEV_DEMO_VIZ=1 (or the
// SUPERFORECASTING_AGENT_TUI_ / HERMES_TUI_ aliases).
export const DEV_DEMO_VIZ = truthy(tuiEnvValue('DEV_DEMO_VIZ'))
