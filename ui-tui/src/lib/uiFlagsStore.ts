import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { atom } from 'nanostores'

import { forecastHomeDir } from './forecastHome.js'

// Small, TUI-owned persisted UI flags — seen-once nudges and first-run hints
// that must survive a restart. Follows the SAME forecastHomeDir() + JSON pattern
// as marketStore / newsFeedStore / newsProviderColorStore, so it reuses the
// existing local-state seam rather than adding a new persistence subsystem.
// Best-effort: a read/write failure just means the flag isn't remembered (the
// hint reappears next launch — annoying, never fatal).

export interface UiFlags {
  // The Home landing "New here?" discovery hint has been dismissed — by pressing
  // one of the keys it teaches (Ctrl+K / ? / a completed Ctrl+G chord) or the
  // explicit ✕ affordance. Once true the hint never renders again.
  firstRunHintDismissed?: boolean
}

const file = (dir = forecastHomeDir()) => join(dir, 'ui_flags.json')

export const loadUiFlags = (path = file()): UiFlags => {
  try {
    const data: unknown = JSON.parse(readFileSync(path, 'utf8'))

    return data && typeof data === 'object' ? (data as UiFlags) : {}
  } catch {
    return {}
  }
}

export const saveUiFlags = (flags: UiFlags, path = file()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(path, `${JSON.stringify(flags, null, 2)}\n`, { mode: 0o600 })

    return true
  } catch {
    return false
  }
}

// Reactive mirror of the persisted flag, hydrated once from disk at module load.
// The landing hint subscribes to this atom; dismissal flips it AND persists so a
// restart stays quiet.
export const $firstRunHintDismissed = atom<boolean>(loadUiFlags().firstRunHintDismissed === true)

// Mark the discovery hint dismissed for good. Idempotent: a no-op once dismissed,
// so it is cheap to call from every discovery keypath (Ctrl+K / ? / g-chord).
export const dismissFirstRunHint = () => {
  if ($firstRunHintDismissed.get()) {
    return
  }

  $firstRunHintDismissed.set(true)

  const flags = loadUiFlags()

  flags.firstRunHintDismissed = true
  saveUiFlags(flags)
}
