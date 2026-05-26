export interface ForecastShortcutKeyEvent {
  alt?: boolean
  ctrl?: boolean
  escape?: boolean
  meta?: boolean
  shift?: boolean
  super?: boolean
}

export interface ForecastTuiShortcut {
  command: string
  description: string
  hotkey: string
  id: string
  label: string
  mode: 'prefill' | 'submit'
}

export const FORECAST_TUI_VIEW_SHORTCUTS: ForecastTuiShortcut[] = [
  {
    command: '/questions',
    description: 'active questions with headline values',
    hotkey: 'Alt+1',
    id: 'book',
    label: 'book',
    mode: 'submit'
  },
  {
    command: '/ledger review',
    description: 'stale forecasts and review queue',
    hotkey: 'Alt+2',
    id: 'review',
    label: 'review',
    mode: 'submit'
  },
  {
    command: '/ledger alerts',
    description: 'open alerts and recommended actions',
    hotkey: 'Alt+3',
    id: 'alerts',
    label: 'alerts',
    mode: 'submit'
  },
  {
    command: '/ledger evidence',
    description: 'evidence readiness and source gaps',
    hotkey: 'Alt+4',
    id: 'evidence',
    label: 'evidence',
    mode: 'submit'
  },
  {
    command: '/ledger learning',
    description: 'calibration lessons and error profiles',
    hotkey: 'Alt+5',
    id: 'learning',
    label: 'learning',
    mode: 'submit'
  },
  {
    command: '/ledger schedules',
    description: 'scheduled self-check state',
    hotkey: 'Alt+6',
    id: 'schedules',
    label: 'schedules',
    mode: 'submit'
  },
  {
    command: '/ledger calibration',
    description: 'calibration and component performance',
    hotkey: 'Alt+7',
    id: 'calibration',
    label: 'calibration',
    mode: 'submit'
  },
  {
    command: '/ledger backtests',
    description: 'recent benchmark replay results',
    hotkey: 'Alt+8',
    id: 'backtests',
    label: 'backtests',
    mode: 'submit'
  },
  {
    command: '/ledger all',
    description: 'full forecast ledger overview',
    hotkey: 'Alt+9',
    id: 'all',
    label: 'all',
    mode: 'submit'
  }
]

export const FORECAST_TUI_FIND_SHORTCUT: ForecastTuiShortcut = {
  command: '/find ',
  description: 'search forecasts by words, topics, rationale, or evidence',
  hotkey: 'Ctrl+F',
  id: 'find',
  label: 'find',
  mode: 'prefill'
}

export const forecastShortcutDisplayHotkey = (
  shortcut: ForecastTuiShortcut,
  platform = process.platform
): string => (platform === 'darwin' ? shortcut.hotkey.replace(/^Alt\+/, 'Opt+') : shortcut.hotkey)

const cleanCtrl = (key: ForecastShortcutKeyEvent) =>
  key.ctrl === true && key.alt !== true && key.meta !== true && key.shift !== true && key.super !== true

const cleanAlt = (key: ForecastShortcutKeyEvent) =>
  (key.alt === true || key.meta === true || key.escape === true) &&
  key.ctrl !== true &&
  key.shift !== true &&
  key.super !== true

const MAC_OPTION_DIGITS: Record<string, string> = {
  '¡': '1',
  '™': '2',
  '£': '3',
  '¢': '4',
  '∞': '5',
  '§': '6',
  '¶': '7',
  '•': '8',
  'ª': '9'
}

const cleanMacOptionDigit = (input: string, key: ForecastShortcutKeyEvent) =>
  key.alt !== true &&
  key.ctrl !== true &&
  key.escape !== true &&
  key.meta !== true &&
  key.shift !== true &&
  key.super !== true &&
  MAC_OPTION_DIGITS[input]

export const forecastShortcutForKey = (
  input: string,
  key: ForecastShortcutKeyEvent,
  composerValue = ''
): ForecastTuiShortcut | null => {
  const ch = input.toLowerCase()
  const trimmedComposer = composerValue.trim()

  if (cleanCtrl(key) && ch === 'f') {
    const isFindDraft = trimmedComposer === '/find' || trimmedComposer.startsWith('/find ')

    if (trimmedComposer.startsWith('/') && !isFindDraft) {
      return null
    }

    return FORECAST_TUI_FIND_SHORTCUT
  }

  const altDigit = cleanAlt(key) ? ch : cleanMacOptionDigit(input, key)

  if (!altDigit || trimmedComposer) {
    return null
  }

  return FORECAST_TUI_VIEW_SHORTCUTS.find(shortcut => shortcut.hotkey.endsWith(altDigit)) ?? null
}

export const forecastFindDraft = (currentValue: string) => {
  const trimmed = currentValue.trim()

  if (!trimmed) {
    return FORECAST_TUI_FIND_SHORTCUT.command
  }

  if (trimmed.startsWith('/find ')) {
    return trimmed
  }

  if (trimmed.startsWith('/')) {
    return FORECAST_TUI_FIND_SHORTCUT.command
  }

  return `${FORECAST_TUI_FIND_SHORTCUT.command}${trimmed}`
}
