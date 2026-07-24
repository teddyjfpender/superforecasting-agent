import { describe, expect, it } from 'vitest'

import { expandTokens, type FieldSpec, filterRanked, rankItems, tokenize } from '../lib/fuzzyRank.js'

type Item = { title: string; body?: string; tags?: string[] }

const FIELDS: FieldSpec<Item>[] = [
  { get: i => i.title, weight: 1 },
  { get: i => i.tags, weight: 0.5 },
  { get: i => i.body, weight: 0.3 }
]

describe('tokenize', () => {
  it('lowercases, splits on whitespace, drops empties', () => {
    expect(tokenize('  Tesla   Q3  ')).toEqual(['tesla', 'q3'])
    expect(tokenize('')).toEqual([])
  })
})

describe('expandTokens', () => {
  it('adds synonyms and never echoes a literal token back', () => {
    const out = expandTokens(['investing'])
    expect(out).toContain('markets')
    expect(out).not.toContain('investing')
  })

  it('returns nothing for a token with no synonyms', () => {
    expect(expandTokens(['zzzznotaword'])).toEqual([])
  })
})

describe('rankItems', () => {
  const items: Item[] = [
    { title: 'Tesla deliveries beat estimates' },
    { title: 'Apple earnings', body: 'tesla mentioned once in passing' },
    { title: 'Weather report' }
  ]

  it('ranks a title hit above a body-only hit and drops non-matches', () => {
    const ranked = rankItems(items, 'tesla', FIELDS)
    expect(ranked.map(r => r.item.title)).toEqual(['Tesla deliveries beat estimates', 'Apple earnings'])
    expect(ranked.every(r => r.score > 0)).toBe(true)
    expect(ranked[0].score).toBeGreaterThan(ranked[1].score)
  })

  it('passes everything through (score 0) for an empty query', () => {
    const ranked = rankItems(items, '   ', FIELDS)
    expect(ranked).toHaveLength(items.length)
    expect(ranked.every(r => r.score === 0)).toBe(true)
  })

  it('recalls via synonym expansion when the literal word is absent', () => {
    const pool: Item[] = [{ title: 'Markets wrap' }, { title: 'Cooking tips' }]
    const ranked = rankItems(pool, 'investing', FIELDS)
    expect(ranked.map(r => r.item.title)).toEqual(['Markets wrap'])
  })

  it('matches array fields (tags) and keeps a stable order on score ties', () => {
    const pool: Item[] = [
      { title: 'A', tags: ['macro'] },
      { title: 'B', tags: ['macro'] }
    ]

    const ranked = rankItems(pool, 'macro', FIELDS)
    expect(ranked.map(r => r.item.title)).toEqual(['A', 'B'])
  })
})

describe('filterRanked', () => {
  const items: Item[] = [{ title: 'Tesla' }, { title: 'Apple' }]

  it('returns the full list unchanged for an empty query', () => {
    expect(filterRanked(items, '', FIELDS)).toBe(items)
  })

  it('returns only matches, ranked, for a real query', () => {
    expect(filterRanked(items, 'tesla', FIELDS).map(i => i.title)).toEqual(['Tesla'])
  })
})
