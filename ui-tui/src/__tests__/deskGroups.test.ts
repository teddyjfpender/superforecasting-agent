import { describe, expect, it } from 'vitest'

import { buildDeskTabs, forecastsForTab, forecastTheme } from '../lib/deskGroups.js'

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
    expect(tabs.map((t) => t.label)).toEqual(['Fed Path', 'Econ Factor', '#tech', '#untagged', 'All'])
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
