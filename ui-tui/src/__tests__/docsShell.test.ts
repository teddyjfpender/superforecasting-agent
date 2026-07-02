import { describe, expect, it } from 'vitest'

import { docAge, sizeChip, titlePath } from '../components/docsShell.js'
import { PER_VIEW_KEYS } from '../content/keymaps.js'

describe('docAge', () => {
  it('returns empty for missing / unparseable input', () => {
    expect(docAge(undefined)).toBe('')
    expect(docAge('')).toBe('')
    expect(docAge('not a date')).toBe('')
    expect(docAge(0)).toBe('')
  })

  it('reads epoch SECONDS (below ~1e12) and formats a compact age', () => {
    const nowS = Date.now() / 1000

    expect(docAge(nowS - 10)).toBe('now')
    expect(docAge(nowS - 120)).toBe('2m')
    expect(docAge(nowS - 2 * 3600)).toBe('2h')
    expect(docAge(nowS - 3 * 86400)).toBe('3d')
  })

  it('reads epoch MILLISECONDS (mtimeMs) too', () => {
    expect(docAge(Date.now() - 3600 * 1000)).toBe('1h')
  })

  it('accepts an ISO date string', () => {
    const iso = new Date(Date.now() - 5 * 86400 * 1000).toISOString()

    expect(docAge(iso)).toBe('5d')
  })
})

describe('sizeChip', () => {
  it('formats bytes / KiB / MiB and hides zero', () => {
    expect(sizeChip(0)).toBe('')
    expect(sizeChip(undefined)).toBe('')
    expect(sizeChip(820)).toBe('820 B')
    expect(sizeChip(2048)).toBe('2.0K')
    expect(sizeChip(5 * 1024 * 1024)).toBe('5.0M')
  })
})

describe('titlePath (title-priority truncation)', () => {
  it('protects the leaf title and shrinks the parent directory from the left', () => {
    const { base, dir } = titlePath('latex/examples/symbols', 10)

    expect(base).toBe('symbols') // the leaf survives whole
    expect(dir.startsWith('…')).toBe(true) // the dir is what gets ellipsised
    expect(`${dir}${base}`.length).toBeLessThanOrEqual(10)
  })

  it('keeps the whole path when it already fits', () => {
    expect(titlePath('a/b/c', 20)).toEqual({ base: 'c', dir: 'a/b/' })
  })

  it('truncates the leaf itself only when it cannot fit', () => {
    const { base, dir } = titlePath('really-long-filename', 6)

    expect(dir).toBe('')
    expect(base.endsWith('…')).toBe(true)
    expect(base.length).toBeLessThanOrEqual(6)
  })
})

describe('keymap registration', () => {
  it('the Docs view advertises its unified keys (kinds, filter, sort)', () => {
    const rows = PER_VIEW_KEYS.obsidian.map(r => `${r[0]} ${r[1]}`).join(' | ')

    expect(rows).toContain('1 / 2') // switch collection
    expect(rows).toContain('/') // filter
    expect(rows.toLowerCase()).toContain('sort')

    // Tab cycles wikilinks — it does NOT move across panes (←→ / h l do). Guard
    // against the label/binding divergence: no cheat-sheet row may pair the Tab
    // key with a pane-movement description.
    const tabRow = PER_VIEW_KEYS.obsidian.find(r => r[0].includes('Tab'))

    expect(tabRow?.[1].toLowerCase()).toContain('wikilink')
    expect(tabRow?.[1].toLowerCase()).not.toContain('pane')
  })
})
