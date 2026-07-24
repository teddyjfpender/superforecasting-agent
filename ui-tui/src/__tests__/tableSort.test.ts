import { describe, expect, it } from 'vitest'

import {
  nextByKeyState,
  nextCycleState,
  nextToggleState,
  sortIndicator,
  sortRows,
  type TableSortState
} from '../lib/tableSort.js'

interface Row {
  id: string
  n: number | null
  s: string | null | undefined
}

const rows: Row[] = [
  { id: 'a', n: 3, s: 'banana' },
  { id: 'b', n: 1, s: 'Apple' },
  { id: 'c', n: null, s: 'cherry' },
  { id: 'd', n: 2, s: null },
  { id: 'e', n: 3, s: 'apple' } // duplicate n:3 to test stability against 'a'
]

const num = (r: Row) => r.n
const str = (r: Row) => r.s

describe('sortRows (pure comparison)', () => {
  it('returns a fresh copy in original order when key is null', () => {
    const out = sortRows(rows, null, 'asc', num)
    expect(out.map(r => r.id)).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(out).not.toBe(rows) // copy, not the same reference
  })

  it('does not mutate the input array', () => {
    const before = rows.map(r => r.id)
    sortRows(rows, 'x', 'asc', () => 1)
    expect(rows.map(r => r.id)).toEqual(before)
  })

  it('sorts numbers ascending with nulls last', () => {
    const out = sortRows(rows, 'x', 'asc', num)
    // 1(b), 2(d), 3(a), 3(e), then null(c) last
    expect(out.map(r => r.id)).toEqual(['b', 'd', 'a', 'e', 'c'])
  })

  it('sorts numbers descending but STILL keeps nulls last', () => {
    const out = sortRows(rows, 'x', 'desc', num)
    // 3(a), 3(e), 2(d), 1(b), then null(c) last — nulls are NOT flipped to front
    expect(out.map(r => r.id)).toEqual(['a', 'e', 'd', 'b', 'c'])
  })

  it('is stable for equal values (a before e stays a before e in both directions)', () => {
    expect(sortRows(rows, 'x', 'asc', num).filter(r => r.n === 3).map(r => r.id)).toEqual(['a', 'e'])
    expect(sortRows(rows, 'x', 'desc', num).filter(r => r.n === 3).map(r => r.id)).toEqual(['a', 'e'])
  })

  it('sorts strings case-insensitively with null/undefined last', () => {
    const out = sortRows(rows, 'x', 'asc', str)
    // Apple/apple (b,e) tie case-insensitively → stable order b before e, then
    // banana(a), cherry(c); null(d) last.
    expect(out.map(r => r.id)).toEqual(['b', 'e', 'a', 'c', 'd'])
  })

  it('keeps undefined AND null both trailing (missing bucket)', () => {
    const mixed: Row[] = [
      { id: 'p', n: 1, s: undefined },
      { id: 'q', n: 1, s: 'x' },
      { id: 'r', n: 1, s: null }
    ]

    const out = sortRows(mixed, 'x', 'desc', str)
    // present 'x'(q) first; the two missing (p undefined, r null) trail in original order
    expect(out.map(r => r.id)).toEqual(['q', 'p', 'r'])
  })

  it('treats NaN / non-finite numbers as missing (sorted last)', () => {
    const mixed = [
      { id: 'a', v: 5 },
      { id: 'b', v: NaN },
      { id: 'c', v: 2 },
      { id: 'd', v: Infinity }
    ]

    const out = sortRows(mixed, 'x', 'asc', r => r.v)
    expect(out.map(r => r.id)).toEqual(['c', 'a', 'b', 'd'])
  })

  it('gives a total, stable order on a mixed number/string column (numbers first)', () => {
    const mixed = [
      { id: 'a', v: 'zed' as number | string },
      { id: 'b', v: 10 },
      { id: 'c', v: 'alpha' },
      { id: 'd', v: 2 }
    ]

    const out = sortRows(mixed, 'x', 'asc', r => r.v)
    expect(out.map(r => r.id)).toEqual(['d', 'b', 'c', 'a'])
  })
})

describe('sort-state transitions', () => {
  const keys = ['a', 'b', 'c']

  it('cycles forward through the columns then back to unsorted', () => {
    let s: TableSortState = { dir: 'asc', key: null }
    s = nextCycleState(s, keys)
    expect(s).toEqual({ dir: 'asc', key: 'a' })
    s = nextCycleState(s, keys)
    expect(s).toEqual({ dir: 'asc', key: 'b' })
    s = nextCycleState(s, keys)
    expect(s).toEqual({ dir: 'asc', key: 'c' })
    s = nextCycleState(s, keys)
    expect(s).toEqual({ dir: 'asc', key: null }) // wrap → unsorted
  })

  it('resets direction to asc when cycling onto a new column', () => {
    const s = nextCycleState({ dir: 'desc', key: 'a' }, keys)
    expect(s).toEqual({ dir: 'asc', key: 'b' })
  })

  it('toggles direction on the current column, and is a no-op when unsorted', () => {
    expect(nextToggleState({ dir: 'asc', key: 'b' })).toEqual({ dir: 'desc', key: 'b' })
    expect(nextToggleState({ dir: 'desc', key: 'b' })).toEqual({ dir: 'asc', key: 'b' })
    expect(nextToggleState({ dir: 'asc', key: null })).toEqual({ dir: 'asc', key: null })
  })

  it('sorts by a clicked key (asc), toggling direction on repeat clicks of the same key', () => {
    expect(nextByKeyState({ dir: 'asc', key: null }, 'c')).toEqual({ dir: 'asc', key: 'c' })
    expect(nextByKeyState({ dir: 'asc', key: 'c' }, 'c')).toEqual({ dir: 'desc', key: 'c' })
    // clicking a DIFFERENT column restarts ascending
    expect(nextByKeyState({ dir: 'desc', key: 'c' }, 'a')).toEqual({ dir: 'asc', key: 'a' })
  })

  it('renders the direction indicator only on the active column', () => {
    expect(sortIndicator({ dir: 'asc', key: 'a' }, 'a')).toBe('▲')
    expect(sortIndicator({ dir: 'desc', key: 'a' }, 'a')).toBe('▼')
    expect(sortIndicator({ dir: 'asc', key: 'a' }, 'b')).toBe('')
    expect(sortIndicator({ dir: 'asc', key: null }, 'a')).toBe('')
  })
})
