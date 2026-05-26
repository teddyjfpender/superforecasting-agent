import { describe, expect, it } from 'vitest'

import { forecastFindDraft, forecastShortcutForKey } from '../lib/forecastShortcuts.js'

const key = (overrides: Record<string, unknown> = {}) =>
  ({ alt: false, ctrl: false, meta: false, shift: false, super: false, ...overrides }) as any

describe('forecast TUI keyboard shortcuts', () => {
  it('maps Alt+number chords to ledger views when the composer is empty', () => {
    expect(forecastShortcutForKey('1', key({ meta: true }))?.command).toBe('/questions')
    expect(forecastShortcutForKey('2', key({ meta: true }))?.command).toBe('/ledger review')
    expect(forecastShortcutForKey('4', key({ meta: true }))?.command).toBe('/ledger evidence')
    expect(forecastShortcutForKey('8', key({ alt: true }))?.command).toBe('/ledger backtests')
    expect(forecastShortcutForKey('9', key({ meta: true }))?.command).toBe('/ledger all')
  })

  it('does not steal Alt+number chords while the user is drafting text', () => {
    expect(forecastShortcutForKey('1', key({ meta: true }), 'draft note')).toBeNull()
  })

  it('maps Ctrl+F to forecast search and can promote a typed phrase into /find', () => {
    expect(forecastShortcutForKey('f', key({ ctrl: true }))?.command).toBe('/find ')
    expect(forecastShortcutForKey('f', key({ ctrl: true }), '/find')?.command).toBe('/find ')
    expect(forecastFindDraft('inflation energy')).toBe('/find inflation energy')
    expect(forecastFindDraft('/find inflation')).toBe('/find inflation')
  })

  it('leaves non-find slash drafts alone so Ctrl+F does not erase commands', () => {
    expect(forecastShortcutForKey('f', key({ ctrl: true }), '/forecast review')).toBeNull()
    expect(forecastFindDraft('/forecast review')).toBe('/find ')
  })
})
