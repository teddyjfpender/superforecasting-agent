import { atom, computed } from 'nanostores'

import { MOUSE_TRACKING } from '../config/env.js'
import { ZERO } from '../domain/usage.js'
import { DEFAULT_THEME } from '../theme.js'

import { DEFAULT_INDICATOR_STYLE, type UiState } from './interfaces.js'

const buildUiState = (): UiState => ({
  bgTasks: new Set(),
  busy: false,
  busyInputMode: 'queue',
  compact: false,
  detailsMode: 'collapsed',
  detailsModeCommandOverride: false,
  forecastContestedCount: 0,
  forecastDeskRailSections: [],
  forecastDeskStatus: '',
  indicatorStyle: DEFAULT_INDICATOR_STYLE,
  info: null,
  inlineDiffs: true,
  mouseTracking: MOUSE_TRACKING,
  reviewSweep: null,
  sections: {},
  showCost: false,
  showReasoning: false,
  sid: null,
  status: 'starting forecast desk...',
  statusBar: 'top',
  streaming: true,
  theme: DEFAULT_THEME,
  usage: ZERO
})

export const $uiState = atom<UiState>(buildUiState())

export const $uiTheme = computed($uiState, state => state.theme)
export const $uiSessionId = computed($uiState, state => state.sid)
// The review-sweep in-flight marker, scoped so the Desk subscribes to JUST this
// (not every status flash) — it re-renders only when a sweep starts/finishes.
export const $reviewSweep = computed($uiState, state => state.reviewSweep)

// The exact slice the transcript pane renders from — the display-shaping fields
// ONLY, never the live status/usage/busy/agents churn. TranscriptPane subscribes
// to these (each notifies only on a real reference change) instead of the whole
// $uiState. Without this, a background $uiState notify (a config-sync poll, a
// usage/status heartbeat) re-rendered the transcript; concurrent with a composer
// keystroke that re-render walks the virtualized window through a transient
// full-history mount and re-blits the entire transcript region under the two-pane
// decstbm={false} + stickyScroll geometry — the visible "right chat blinks while
// I type" flash. Same fix as the Recents rail ($uiSessionId/$uiTheme).
export const $uiCompact = computed($uiState, state => state.compact)
export const $uiDetailsMode = computed($uiState, state => state.detailsMode)
export const $uiDetailsCommandOverride = computed($uiState, state => state.detailsModeCommandOverride)
export const $uiSections = computed($uiState, state => state.sections)

export const getUiState = () => $uiState.get()

export const patchUiState = (next: Partial<UiState> | ((state: UiState) => UiState)) =>
  $uiState.set(typeof next === 'function' ? next($uiState.get()) : { ...$uiState.get(), ...next })

export const resetUiState = () => $uiState.set(buildUiState())
