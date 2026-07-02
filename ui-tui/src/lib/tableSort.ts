// One shared, pure sort mechanism for the dense column tables (Desk + Markets).
// The views own the column set + the per-cell accessor; this module owns the
// COMPARISON (numeric vs string aware, null/undefined always last regardless of
// direction, stable) and a tiny per-view sort-state hook (`o` cycles the column,
// `O` toggles direction, a header click sorts by that column).

import { useCallback, useState } from 'react'

export type SortDir = 'asc' | 'desc'

// The value a column contributes to the comparison. `null`/`undefined` (and
// non-finite numbers, which are effectively "no value") always sort LAST.
export type SortValue = null | number | string | undefined

export interface TableSortState {
  dir: SortDir
  // null → the default, server-order "unsorted" state.
  key: null | string
}

// A value counts as "missing" (→ always last) when it's null/undefined or a
// non-finite number (NaN/±Infinity read as no measurement, not as an extreme).
const isMissing = (v: SortValue): boolean =>
  v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v))

// Pure comparison of two present (non-missing) values. Numbers compare
// numerically; strings compare with locale awareness (case-insensitive, natural
// ordering); a number/string mismatch is resolved by putting numbers first so
// the order is at least TOTAL and STABLE on a mixed column.
const comparePresent = (a: SortValue, b: SortValue): number => {
  const aNum = typeof a === 'number'
  const bNum = typeof b === 'number'

  if (aNum && bNum) {
    return (a as number) - (b as number)
  }

  if (aNum !== bNum) {
    // Mixed types: numbers before strings.
    return aNum ? -1 : 1
  }

  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

// Sort `rows` by the value `accessor(row, key)` returns for the active `key`.
// - key === null → the rows are returned in their original order (a fresh copy;
//   the input is never mutated).
// - null/undefined/non-finite values ALWAYS sort last, in ascending AND
//   descending (direction only flips the ordering of the PRESENT values).
// - the sort is STABLE: equal rows (and all the trailing missing rows) keep their
//   original relative order.
export function sortRows<T>(
  rows: readonly T[],
  key: null | string,
  dir: SortDir,
  accessor: (row: T, key: string) => SortValue
): T[] {
  if (!key) {
    return rows.slice()
  }

  const factor = dir === 'desc' ? -1 : 1
  const decorated = rows.map((row, index) => ({ index, row, value: accessor(row, key) }))

  decorated.sort((a, b) => {
    const aMissing = isMissing(a.value)
    const bMissing = isMissing(b.value)

    if (aMissing && bMissing) {
      return a.index - b.index // both missing → keep original order (stable, last)
    }
    if (aMissing) {
      return 1 // missing always last, regardless of direction
    }
    if (bMissing) {
      return -1
    }

    const cmp = comparePresent(a.value, b.value)

    if (cmp !== 0) {
      return cmp * factor
    }

    return a.index - b.index // stable tiebreak (never flipped by direction)
  })

  return decorated.map(entry => entry.row)
}

// The next sort state when `o` cycles the column FORWARD: advance through
// `columnKeys` in header order, then wrap back to the unsorted default. A new
// column always starts ascending.
export const nextCycleState = (state: TableSortState, columnKeys: readonly string[]): TableSortState => {
  const idx = state.key ? columnKeys.indexOf(state.key) : -1
  const next = idx + 1

  if (next >= columnKeys.length) {
    return { dir: 'asc', key: null }
  }

  return { dir: 'asc', key: columnKeys[next] }
}

// The next state when `O` toggles direction on the current column. A no-op while
// unsorted (there is no column to toggle).
export const nextToggleState = (state: TableSortState): TableSortState =>
  state.key ? { dir: state.dir === 'asc' ? 'desc' : 'asc', key: state.key } : state

// The next state when a header for `key` is clicked: sort by it (ascending), or
// toggle direction if it is already the active column.
export const nextByKeyState = (state: TableSortState, key: string): TableSortState =>
  state.key === key ? { dir: state.dir === 'asc' ? 'desc' : 'asc', key } : { dir: 'asc', key }

// The glyph shown on the active column's header (▲ asc / ▼ desc); '' otherwise.
export const sortIndicator = (state: TableSortState, key: string): string =>
  state.key === key ? (state.dir === 'asc' ? '▲' : '▼') : ''

// A tiny per-view sort-state store. `columnKeys` MUST be referentially stable
// (a module-level constant) so the returned callbacks stay stable across renders.
export function useTableSort(columnKeys: readonly string[]) {
  const [state, setState] = useState<TableSortState>({ dir: 'asc', key: null })

  const cycle = useCallback(() => setState(s => nextCycleState(s, columnKeys)), [columnKeys])
  const toggle = useCallback(() => setState(s => nextToggleState(s)), [])
  const sortByKey = useCallback((key: string) => setState(s => nextByKeyState(s, key)), [])
  const reset = useCallback(() => setState({ dir: 'asc', key: null }), [])

  return { cycle, reset, sortByKey, state, toggle }
}
