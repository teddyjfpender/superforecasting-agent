import { describe, expect, it } from 'vitest'

import { buildDeskTabs, cleanTagLabel, forecastsForTab, forecastTheme, isBenchForecast, shortLensLabel, tabWindow } from '../lib/deskGroups.js'

const item = (id: string, extra: Record<string, unknown> = {}) => ({ id, title: id, ...extra })

const payload = {
  forecasts: [
    item('q1', { topics: ['Politics'] }),
    item('q2', { topics: [], domain: 'econ' }),
    item('q3'), // no topic/domain -> untagged
    item('q4', { topics: ['Politics'] }),
    item('q5', { topics: ['Tech'] }),
  ],
  theses: [{ id: 'th1', title: 'Fed Path', question_ids: ['q1', 'q4', 'gone'] }],
  factors: [{ id: 'fa1', title: 'Econ Factor', question_ids: ['q2'] }],
} as never

describe('deskGroups', () => {
  const tabs = buildDeskTabs(payload)

  it('orders theses -> factors -> tag-groups -> All', () => {
    expect(tabs.map((t) => t.kind)).toEqual(['thesis', 'factor', 'tag', 'tag', 'all'])
    // Labels are SHORT (kind-noise stripped: "Econ Factor" -> "Econ").
    expect(tabs.map((t) => t.label)).toEqual(['Fed Path', 'Econ', '#tech', '#untagged', 'All'])
  })

  it('thesis tab keeps only present members (drops missing ids)', () => {
    expect(tabs[0].forecastIds).toEqual(['q1', 'q4'])
    expect(tabs[0].refId).toBe('th1')
  })

  it('tag groups ONLY un-grouped forecasts, bucketed by theme', () => {
    const tagTabs = tabs.filter((t) => t.kind === 'tag')
    const tagged = tagTabs.flatMap((t) => t.forecastIds)
    expect(tagged.sort()).toEqual(['q3', 'q5']) // q1/q4 in thesis, q2 in factor -> excluded
  })

  it('All tab has every forecast in order', () => {
    const all = tabs[tabs.length - 1]
    expect(all.kind).toBe('all')
    expect(all.forecastIds).toEqual(['q1', 'q2', 'q3', 'q4', 'q5'])
  })

  it('forecastTheme: topic > domain > untagged', () => {
    expect(forecastTheme({ topics: ['Politics'], domain: 'econ' } as never)).toBe('politics')
    expect(forecastTheme({ topics: [], domain: 'Econ' } as never)).toBe('econ')
    expect(forecastTheme({} as never)).toBe('untagged')
  })

  it('forecastsForTab resolves ids to items in order', () => {
    expect(forecastsForTab(tabs[0], payload.forecasts).map((i) => i.id)).toEqual(['q1', 'q4'])
  })

  it('empty payload yields just an All tab', () => {
    const t = buildDeskTabs({ forecasts: [] } as never)
    expect(t).toHaveLength(1)
    expect(t[0].kind).toBe('all')
  })
})

describe('bench lens', () => {
  it('isBenchForecast matches domain forecastbench OR bench/forecastbench tags', () => {
    expect(isBenchForecast({ domain: 'forecastbench' } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'markets', topics: ['bench'] } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'markets', topics: ['forecastbench'] } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'politics', topics: ['elections'] } as never)).toBe(false)
  })

  it('carves bench forecasts into a separate Bench tab, before All, and OUT of All/tag groups', () => {
    const benchPayload = {
      forecasts: [
        item('q1', { topics: ['Politics'] }),
        item('b1', { domain: 'forecastbench', topics: ['manifold'] }),
        item('b2', { domain: 'markets', topics: ['bench'] }), // tag fallback
        item('q5', { topics: ['Tech'] }),
      ],
    } as never
    const t = buildDeskTabs(benchPayload)
    const kinds = t.map((x) => x.kind)
    // Bench sits just before the final All catch-all.
    expect(kinds[kinds.length - 2]).toBe('bench')
    expect(kinds[kinds.length - 1]).toBe('all')

    const bench = t.find((x) => x.kind === 'bench')!
    expect(bench.forecastIds.sort()).toEqual(['b1', 'b2'])
    expect(bench.label).toContain('Bench')

    // Bench questions never appear in the tag groups…
    const tagged = t.filter((x) => x.kind === 'tag').flatMap((x) => x.forecastIds)
    expect(tagged).not.toContain('b1')
    expect(tagged).not.toContain('b2')

    // …nor in the All catch-all (live desk = organic forecasts only).
    const all = t[t.length - 1]
    expect(all.forecastIds).toEqual(['q1', 'q5'])
  })

  it('no Bench tab when no bench forecasts exist', () => {
    const t = buildDeskTabs({ forecasts: [item('q1', { topics: ['Tech'] })] } as never)
    expect(t.some((x) => x.kind === 'bench')).toBe(false)
  })
})

describe('short labels', () => {
  it('shortLensLabel strips kind-noise + stopwords and shortens long titles', () => {
    expect(shortLensLabel('Democrats take the Senate back tracker thesis')).not.toContain('thesis')
    expect(shortLensLabel('Democrats take the Senate back tracker thesis').length).toBeLessThanOrEqual(18)
    expect(shortLensLabel('AI infrastructure scarcity thesis')).toBe('AI infrastructure')
    expect(shortLensLabel('Fed Path')).toBe('Fed Path')
  })

  it('cleanTagLabel drops years/short tokens and keeps the significant word', () => {
    expect(cleanTagLabel('2026 u.s. primary election')).toBe('primary')
    expect(cleanTagLabel('nbis')).toBe('nbis')
    expect(cleanTagLabel('tech').length).toBeLessThanOrEqual(14)
  })
})

describe('tabWindow', () => {
  it('shows all tabs when they fit', () => {
    expect(tabWindow([5, 5, 5], 0, 100)).toEqual({ start: 0, end: 3 })
  })

  it('keeps the active tab visible when the strip is narrow', () => {
    const { start, end } = tabWindow([10, 10, 10, 10, 10], 4, 30)
    expect(start).toBeLessThanOrEqual(4)
    expect(end).toBeGreaterThan(4)
    expect(end).toBe(5) // active sits at the right edge
  })

  it('empty -> {0,0}', () => {
    expect(tabWindow([], 0, 50)).toEqual({ start: 0, end: 0 })
  })
})
