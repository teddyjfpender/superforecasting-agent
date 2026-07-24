import { describe, expect, it } from 'vitest'

import { buildDeskTabs, forecastsForTab, isBenchForecast, shortLensLabel, tabWindow } from '../lib/deskGroups.js'

const item = (id: string, extra: Record<string, unknown> = {}) => ({ id, title: id, ...extra })

const payload = {
  forecasts: [
    item('q1', { topics: ['Politics'] }),
    item('q2', { topics: [], domain: 'econ' }),
    item('q3'), // no topic/domain
    item('q4', { topics: ['Politics'] }),
    item('q5', { topics: ['Tech'] }),
  ],
  theses: [{ id: 'th1', title: 'Fed Path', question_ids: ['q1', 'q4', 'gone'] }],
  // Factors are NO LONGER a lens — they must not produce a tab.
  factors: [{ id: 'fa1', title: 'Econ Factor', question_ids: ['q2'] }],
} as never

describe('deskGroups', () => {
  const tabs = buildDeskTabs(payload)

  it('keeps real theses, the operations cockpit, and a single All catch-all', () => {
    expect(tabs.map((t) => t.kind)).toEqual(['thesis', 'all', 'operations'])
    // Labels are SHORT (kind-noise stripped). No "#tag" or factor lens survives.
    expect(tabs.map((t) => t.label)).toEqual(['Fed Path', 'All', 'Operations'])
    expect(tabs.some((t) => t.kind === 'factor')).toBe(false)
    expect(tabs.some((t) => t.kind === 'tag')).toBe(false)
    expect(tabs.some((t) => t.label.startsWith('#'))).toBe(false)
  })

  it('thesis tab keeps only present members (drops missing ids)', () => {
    expect(tabs[0].forecastIds).toEqual(['q1', 'q4'])
    expect(tabs[0].refId).toBe('th1')
  })

  it('All tab has every forecast in order (factor/ungrouped members included)', () => {
    const all = tabs.find(tab => tab.kind === 'all')!
    expect(all.kind).toBe('all')
    expect(all.forecastIds).toEqual(['q1', 'q2', 'q3', 'q4', 'q5'])
  })

  it('orders theses by member count DESC — the "major" thesis leads', () => {
    const t = buildDeskTabs({
      forecasts: [item('a1'), item('a2'), item('a3'), item('b1')],
      theses: [
        { id: 'minor', title: 'Minor thesis', question_ids: ['b1'] },
        { id: 'major', title: 'Major thesis', question_ids: ['a1', 'a2', 'a3'] },
      ],
    } as never)

    expect(t.map((x) => x.kind)).toEqual(['thesis', 'thesis', 'all', 'operations'])
    expect(t.map((x) => x.refId)).toEqual(['major', 'minor', undefined, undefined])
  })

  it('member_count field wins over present-id count for ordering', () => {
    const t = buildDeskTabs({
      forecasts: [item('a1'), item('b1'), item('b2')],
      theses: [
        { id: 'small', title: 'Small', question_ids: ['b1', 'b2'] }, // 2 present ids
        { id: 'big', title: 'Big', question_ids: ['a1'], member_count: 9 }, // fewer present, bigger book
      ],
    } as never)

    expect(t.map((x) => x.refId)).toEqual(['big', 'small', undefined, undefined])
  })

  it('forecastsForTab resolves ids to items in order', () => {
    expect(forecastsForTab(tabs[0], payload.forecasts).map((i) => i.id)).toEqual(['q1', 'q4'])
  })

  it('empty payload still yields Operations and All', () => {
    const t = buildDeskTabs({ forecasts: [] } as never)
    expect(t.map((x) => x.kind)).toEqual(['all', 'operations'])
  })
})

describe('bench forecasts (no lens, still carved out of All)', () => {
  it('isBenchForecast matches domain forecastbench OR bench/forecastbench tags', () => {
    expect(isBenchForecast({ domain: 'forecastbench' } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'markets', topics: ['bench'] } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'markets', topics: ['forecastbench'] } as never)).toBe(true)
    expect(isBenchForecast({ domain: 'politics', topics: ['elections'] } as never)).toBe(false)
  })

  it('bench replays get NO lens tab and stay OUT of the All catch-all', () => {
    const benchPayload = {
      forecasts: [
        item('q1', { topics: ['Politics'] }),
        item('b1', { domain: 'forecastbench', topics: ['manifold'] }),
        item('b2', { domain: 'markets', topics: ['bench'] }), // tag fallback
        item('q5', { topics: ['Tech'] }),
      ],
      bench_count: 2,
    } as never

    const t = buildDeskTabs(benchPayload)
    // Only a single All lens (no theses here) — no Bench tab any more.
    expect(t.map((x) => x.kind)).toEqual(['all', 'operations'])
    expect(t.some((x) => x.kind === 'bench')).toBe(false)
    // Bench replays are still excluded from All (live desk = organic forecasts only).
    expect(t.find(tab => tab.kind === 'all')!.forecastIds).toEqual(['q1', 'q5'])
  })
})

describe('short labels', () => {
  it('shortLensLabel strips kind-noise + stopwords and shortens long titles', () => {
    expect(shortLensLabel('Democrats take the Senate back tracker thesis')).not.toContain('thesis')
    expect(shortLensLabel('Democrats take the Senate back tracker thesis').length).toBeLessThanOrEqual(18)
    expect(shortLensLabel('AI infrastructure scarcity thesis')).toBe('AI infrastructure')
    expect(shortLensLabel('Fed Path')).toBe('Fed Path')
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
