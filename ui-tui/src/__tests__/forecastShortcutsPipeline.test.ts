import { describe, expect, it } from 'vitest'

import { InputEvent } from '../../packages/forecast-ink/src/ink/events/input-event.js'
import { parseMultipleKeypresses } from '../../packages/forecast-ink/src/ink/parse-keypress.js'
import { shouldPassThroughToGlobalHandler } from '../components/textInput.js'
import { forecastShortcutForKey } from '../lib/forecastShortcuts.js'

// The unit tests in forecastShortcuts.test.ts exercise forecastShortcutForKey
// with synthetic key objects. This file closes the loop end-to-end: it feeds
// the actual byte sequences a macOS terminal emits for Opt+1..9 through the
// real keypress tokenizer + InputEvent, then asserts both that the resolved
// shortcut is correct AND that the composer's textInput passes the event
// through to the global handler (so the shortcut actually dispatches). This is
// the layer that "Opt+1..9 don't work on macOS" reports live in, and it can't
// be covered by the pure-function unit test alone.
const parseFirstKey = (bytes: string) => {
  const [keys] = parseMultipleKeypresses({} as never, Buffer.from(bytes, 'utf8'))
  const key = keys.find(k => (k as { kind?: string }).kind === 'key')

  if (!key) {
    throw new Error(`no keypress parsed from ${JSON.stringify(bytes)}`)
  }

  return new InputEvent(key as never)
}

const resolve = (bytes: string, composer = '') => {
  const ev = parseFirstKey(bytes)

  return {
    passThrough: shouldPassThroughToGlobalHandler(ev.input, ev.key as never, undefined, composer, ev.keypress.raw),
    shortcut: forecastShortcutForKey(ev.input, ev.key as never, composer, ev.keypress.raw)
  }
}

describe('forecast Opt+number shortcuts (real terminal byte pipeline)', () => {
  // macOS US-layout Option glyphs (Terminal.app / iTerm2 default: Option is
  // NOT a Meta key, so Opt+digit emits these glyphs).
  const glyphCases: Array<[string, string, string]> = [
    ['Opt+1', '¡', '/questions'],
    ['Opt+2', '™', '/ledger review'],
    ['Opt+3', '£', '/ledger alerts'],
    ['Opt+4', '¢', '/ledger evidence'],
    ['Opt+5', '∞', '/ledger learning'],
    ['Opt+6', '§', '/ledger schedules'],
    ['Opt+7', '¶', '/ledger calibration'],
    ['Opt+8', '•', '/ledger backtests'],
    ['Opt+9', 'ª', '/ledger all']
  ]

  it.each(glyphCases)('%s glyph resolves and passes through', (_label, bytes, command) => {
    const { passThrough, shortcut } = resolve(bytes)
    expect(shortcut?.command).toBe(command)
    expect(passThrough).toBe(true)
  })

  // "Use Option as Meta key" enabled: Opt+digit emits ESC + digit.
  const metaCases: Array<[string, string, string]> = [
    ['Opt+1', '\x1b1', '/questions'],
    ['Opt+5', '\x1b5', '/ledger learning'],
    ['Opt+9', '\x1b9', '/ledger all']
  ]

  it.each(metaCases)('%s meta (ESC+digit) resolves and passes through', (_label, bytes, command) => {
    const { passThrough, shortcut } = resolve(bytes)
    expect(shortcut?.command).toBe(command)
    expect(passThrough).toBe(true)
  })

  // Kitty keyboard protocol CSI-u encoding (Ghostty / kitty / WezTerm):
  // ESC [ <codepoint> ; <modifier> u, where modifier 3 = Alt/Option.
  it('Opt+1 via Kitty CSI-u resolves and passes through', () => {
    const { passThrough, shortcut } = resolve('\x1b[49;3u')
    expect(shortcut?.command).toBe('/questions')
    expect(passThrough).toBe(true)
  })

  it('does not steal the chord (and does not pass through) while drafting text', () => {
    const { passThrough, shortcut } = resolve('¡', 'draft note')
    expect(shortcut).toBeNull()
    expect(passThrough).toBe(false)
  })
})
