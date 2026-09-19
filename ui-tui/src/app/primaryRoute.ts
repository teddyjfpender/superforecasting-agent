/** Primary view ownership. Modal/prompt state remains independent of this route. */
import type { OverlayState } from './interfaces.js'

export const PRIMARY_VIEWS = [
  { key: 'home', label: 'Home', flag: null },
  { key: 'desk', label: 'Desk', flag: 'forecasts' },
  { key: 'markets', label: 'Markets', flag: 'markets' },
  { key: 'news', label: 'News', flag: 'news' },
  { key: 'messaging', label: 'Messaging', flag: 'messaging' },
  { key: 'calendar', label: 'Calendar', flag: 'calendar' },
  { key: 'warnings', label: 'Warnings', flag: 'alerts' },
  { key: 'calibration', label: 'Calibration', flag: 'calibration' },
  { key: 'obsidian', label: 'Docs', flag: 'obsidian' },
  { key: 'agents', label: 'Agents', flag: 'agents' },
  { key: 'demoViz', label: 'Demo Vis', flag: 'demoViz' },
  { key: 'hooks', label: 'Hooks', flag: 'hooks' },
  { key: 'help', label: 'Help', flag: 'help' }
] as const

export type PrimaryRoute = typeof PRIMARY_VIEWS[number]['key']
export type PrimaryFlag = NonNullable<typeof PRIMARY_VIEWS[number]['flag']>
export type NavigationState = {
  primaryRoute: PrimaryRoute
  overlays: Omit<OverlayState, PrimaryFlag>
}

export const PRIMARY_FLAGS = PRIMARY_VIEWS.flatMap(view => view.flag === null ? [] : [view.flag])

export function primaryFlags(route: PrimaryRoute): Record<PrimaryFlag, boolean> {
  // Every non-home view has exactly one flag, derived from the same registry.
  return Object.fromEntries(PRIMARY_VIEWS.flatMap(view => view.flag === null ? [] : [[view.flag, view.key === route]])) as Record<PrimaryFlag, boolean>
}

/** Compatibility admission: newly enabled flags select the requested view. */
export function resolvePrimaryRoute(previous: OverlayState, next: OverlayState): PrimaryRoute {
  const enabled = PRIMARY_VIEWS.filter(view => view.flag !== null && next[view.flag])
  const newlyEnabled = enabled.filter(view => view.flag !== null && !previous[view.flag])
  const selected = newlyEnabled.length ? newlyEnabled : enabled

  if (selected.length > 1) { throw new Error('A navigation change must select only one primary view') }

  return selected[0]?.key ?? 'home'
}

export function navigationState(overlays: OverlayState, primaryRoute: PrimaryRoute): NavigationState {
  // Strip compatibility flags; only the route is stored as authoritative state.
  const fields = Object.entries(overlays).filter(([key]) => !PRIMARY_FLAGS.some(flag => flag === key))

  return { primaryRoute, overlays: Object.fromEntries(fields) as NavigationState['overlays'] }
}
