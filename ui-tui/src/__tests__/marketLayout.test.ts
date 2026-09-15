import { describe, expect, it } from 'vitest'

import { marketColumns, marketTopicWindow } from '../lib/marketLayout.js'

describe('Markets width allocation', () => {
  it.each([42, 70, 100, 160, 240])('fills %i cells with a compact trend and growing name', width => {
    const { columns, trendWidth } = marketColumns(width, true)
    expect(2 + columns.reduce((sum, column) => sum + column.w + 1, 0) + trendWidth).toBe(width)
    expect(trendWidth).toBeLessThanOrEqual(12)
    expect(columns.some(column => column.key === 'name')).toBe(true)
  })
  it('gives hidden volume and additional screen width to the name', () => {
    const compact = marketColumns(120, true)
    const noVolume = marketColumns(120, false)
    expect(noVolume.columns.some(column => column.key === 'vol')).toBe(false)

    const nameWidth = (layout: ReturnType<typeof marketColumns>) =>
      layout.columns.find(column => column.key === 'name')!.w

    expect(nameWidth(noVolume)).toBe(nameWidth(compact) + 11)
    expect(nameWidth(marketColumns(180, false))).toBe(nameWidth(noVolume) + 60)
  })
  it('shows nine topics when they fit and keeps edge selections visible', () => {
    const topics = Array.from({ length: 18 }, (_, i) => `Topic ${i}`)

    for (let active = 0; active < topics.length; active += 1) {
      const wide = marketTopicWindow(topics, active, 150)
      expect(wide.end - wide.start).toBe(9)
      expect(wide.start).toBeLessThanOrEqual(active)
      expect(wide.end).toBeGreaterThan(active)
      const narrow = marketTopicWindow(topics, active, 30)
      expect(narrow.end - narrow.start).toBeLessThan(4)
      expect(narrow.start).toBeLessThanOrEqual(active)
      expect(narrow.end).toBeGreaterThan(active)
    }
  })
})
