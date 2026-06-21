import { describe, expect, it } from 'vitest'

import { normalizeModelList, normalizePresentation } from '../lib/presentation.js'

describe('normalizePresentation', () => {
  it('coerces a well-formed payload and backfills block ids', () => {
    const p = normalizePresentation({
      title: 'GPU vs NVDA',
      summary: 's',
      status: 'complete',
      blocks: [
        { type: 'narrative', body: 'x' },
        { type: 'regression', r2: 0.9 }
      ]
    })
    expect(p).not.toBeNull()
    expect(p!.title).toBe('GPU vs NVDA')
    expect(p!.blocks).toHaveLength(2)
    expect(p!.blocks[0]!.id).toBeTruthy()
  })

  it('drops malformed blocks (no string type)', () => {
    const p = normalizePresentation({ title: 't', blocks: [{ type: 'metric' }, null, { foo: 1 }, 5] })
    expect(p!.blocks).toHaveLength(1)
  })

  it('returns null for non-objects', () => {
    expect(normalizePresentation(null)).toBeNull()
    expect(normalizePresentation('nope')).toBeNull()
    expect(normalizePresentation(42)).toBeNull()
  })

  it('defaults title + status when missing', () => {
    const p = normalizePresentation({ blocks: [] })
    expect(p!.title).toBe('Untitled model')
    expect(p!.status).toBe('complete')
  })
})

describe('normalizeModelList', () => {
  it('reads {models:[...]} and filters bad rows', () => {
    const list = normalizeModelList({ models: [{ id: 'mm_1', title: 'A' }, { title: 'no id' }, null] })
    expect(list).toHaveLength(1)
    expect(list[0]!.id).toBe('mm_1')
  })

  it('accepts a bare array too', () => {
    expect(normalizeModelList([{ id: 'mm_2', title: 'B' }])).toHaveLength(1)
  })

  it('returns [] for junk', () => {
    expect(normalizeModelList('x')).toEqual([])
  })
})
