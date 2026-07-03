// The Prediction Markets SECTION of the Data-mode tape. This hook keeps the PM
// network + streaming lifecycle and the row model out of marketsView (which owns
// the single tape cursor + the `/` filter trap) while still exposing a
// `handleKey` the view's ONE useInput delegates to. There is deliberately NO
// useInput here: the section rides the parent's keyboard so the `/` focus trap
// and the shared selection hold across both quote sections and PM rows.

import { useCallback, useEffect, useMemo, useState } from 'react'

import { openExternalUrl } from './openExternalUrl.js'
import { type PMHistoryRange, type PMOutcomeDTO, type PMVenue } from './pmData.js'
import {
  DEFAULT_PM_FILTER,
  filterPMItems,
  filterPMSection,
  flattenPMRows,
  PM_SORT_KEYS,
  type PMDisplayRow,
  pmExpandable,
  type PmFilter,
  pmFilterActive,
  pmFilterSummary,
  pmSortValue
} from './pmRows.js'
import { sortRows, type TableSortState, useTableSort } from './tableSort.js'
import { type PMHookGateway, usePmList, usePmSelectionData } from './usePmMarkets.js'

export type PmSectionGateway = PMHookGateway

const VENUE_CYCLE: ('all' | PMVenue)[] = ['all', 'polymarket', 'kalshi']

const nextVenue = (cur: 'all' | PMVenue): 'all' | PMVenue =>
  VENUE_CYCLE[(VENUE_CYCLE.indexOf(cur) + 1) % VENUE_CYCLE.length]

// Exact command surfaced when Kalshi streaming is asked for without a key —
// key hints only where they're live (the read-only tape works keyless).
const KALSHI_KEY_HINT =
  'Kalshi streaming needs a key — run  forecast api-key set kalshi <key-id> --pem-file key.pem  (REST tape works keyless).'

const POLL_MS = 30_000

export interface PmSection {
  activeOutcome: null | PMOutcomeDTO
  book: ReturnType<typeof usePmSelectionData>['book']
  clampedSel: number
  cycleSort: () => void
  cycleVenue: () => void
  detailItem: ReturnType<typeof usePmSelectionData>['detailItem']
  expanded: ReadonlySet<string>
  filter: PmFilter
  filterActive: boolean
  filterSummary: string
  filteredCount: number
  handleKey: (ch: string, key: KeyLike) => boolean
  history: ReturnType<typeof usePmSelectionData>['history']
  itemsCount: number
  keyHint: null | string
  livePrices: Record<string, number>
  loading: boolean
  matchCount: number
  openMarket: () => void
  reload: () => void
  rowCount: number
  rows: PMDisplayRow[]
  sel: number
  selectedItem: ReturnType<typeof usePmSelectionData>['detailItem']
  setFilter: (next: PmFilter) => void
  setHistoryRange: (r: PMHistoryRange) => void
  setSel: (updater: (i: number) => number) => void
  sortByKey: (key: string) => void
  sortState: TableSortState
  streamNote: string
  streaming: boolean
  venue: 'all' | PMVenue
  historyRange: PMHistoryRange
}

// A minimal structural shape of the Ink key object we branch on (kept local so
// the hook has no Ink import).
interface KeyLike {
  delete?: boolean
  downArrow?: boolean
  leftArrow?: boolean
  return?: boolean
  rightArrow?: boolean
  upArrow?: boolean
  wheelDown?: boolean
  wheelUp?: boolean
}

export function usePmSection(
  gw: PmSectionGateway | undefined,
  tabActive: boolean,
  searchInput: string,
  setFlash: (s: string) => void
): PmSection {
  // The structured `f` filter is the single source of truth for venue (it also
  // drives the per-venue fetch), so the `v` chip and the modal's venue field
  // never diverge.
  const [filter, setFilterState] = useState<PmFilter>(DEFAULT_PM_FILTER)
  const venue = filter.venue
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set())
  const [sel, setSelState] = useState(0)
  const [historyRange, setHistoryRange] = useState<PMHistoryRange>('1w')

  const { items, loading, reload } = usePmList(gw, tabActive, venue)

  // Structured filter first (venue · topic · vol · prob · sports), then rank by
  // the `/` text query — the two compose, and sort rides on top of both.
  const structured = useMemo(() => filterPMSection(items, filter), [items, filter])
  const filtered = useMemo(() => filterPMItems(structured, searchInput), [structured, searchInput])
  const sort = useTableSort(PM_SORT_KEYS)

  const sorted = useMemo(
    () => sortRows(filtered, sort.state.key, sort.state.dir, pmSortValue),
    [filtered, sort.state.key, sort.state.dir]
  )

  const rows = useMemo(() => flattenPMRows(sorted, expanded), [sorted, expanded])

  const clampedSel = Math.min(sel, Math.max(0, rows.length - 1))
  const selectedRow = rows[clampedSel]
  const selectedItem = selectedRow ? (selectedRow.kind === 'headline' ? selectedRow.item : selectedRow.parent) : null

  const activeOutcome =
    selectedRow?.kind === 'outcome' ? selectedRow.outcome : (selectedItem?.distribution.outcomes?.[0] ?? null)

  const { book, detailItem, history, livePrices, streamNote, streaming } = usePmSelectionData(
    gw,
    tabActive,
    selectedItem,
    activeOutcome,
    historyRange
  )

  // Bounded REST re-poll while streaming is OFF (30s, list only, cleared on leave).
  useEffect(() => {
    if (!tabActive || streaming) {
      return
    }

    const id = setInterval(() => reload(), POLL_MS)

    return () => clearInterval(id)
  }, [tabActive, streaming, reload])

  const activeVenue = selectedItem?.event.venue ?? 'polymarket'
  const kalshiKeyless = (venue === 'kalshi' || activeVenue === 'kalshi') && !streaming && /key/i.test(streamNote)
  const keyHint = kalshiKeyless ? KALSHI_KEY_HINT : null

  const setSel = useCallback((updater: (i: number) => number) => setSelState(updater), [])

  const toggleExpand = useCallback((id: string, expand: boolean) => {
    setExpanded(prev => {
      if (expand === prev.has(id)) {
        return prev
      }

      const next = new Set(prev)
      expand ? next.add(id) : next.delete(id)

      return next
    })
  }, [])

  const openMarket = useCallback(() => {
    const url = selectedItem?.distribution.url || selectedItem?.event.url

    setFlash(url && openExternalUrl(url) ? 'opened in browser' : 'no market URL')
  }, [selectedItem, setFlash])

  const cycleVenue = useCallback(() => {
    setSelState(0)
    setFilterState(f => ({ ...f, venue: nextVenue(f.venue) }))
  }, [])

  // Apply a filter from the modal (resets the cursor so the newly-narrowed list
  // starts at the top).
  const setFilter = useCallback((next: PmFilter) => {
    setSelState(0)
    setFilterState(next)
  }, [])

  // Every key the PM section owns. Returns true when consumed so the parent
  // useInput stops; false lets shared keys (Tab, d, m, h, /, q) fall through.
  const handleKey = (ch: string, key: KeyLike): boolean => {
    if (key.return) {
      openMarket()

      return true
    }

    // ▸ expand / ◂ collapse — consumed on the PM tab even when the row can't
    // expand, so arrow keys never leak into a category switch.
    if (key.rightArrow || ch === ' ') {
      if (selectedRow?.kind === 'headline' && pmExpandable(selectedRow.item)) {
        toggleExpand(selectedRow.id, !expanded.has(selectedRow.id))
      }

      return true
    }

    if (key.leftArrow) {
      if (selectedRow) {
        toggleExpand(selectedRow.kind === 'headline' ? selectedRow.id : selectedRow.parentId, false)
      }

      return true
    }

    if (ch === 'v') {
      cycleVenue()

      return true
    }

    if (ch === 'r') {
      setFlash('refreshing…')
      reload()

      return true
    }

    if (ch === 'o') {
      sort.cycle()

      return true
    }

    if (ch === 'O') {
      sort.toggle()

      return true
    }

    if (ch === '1') {
      setHistoryRange('1d')

      return true
    }

    if (ch === '2') {
      setHistoryRange('1w')

      return true
    }

    if (ch === '3') {
      setHistoryRange('all')

      return true
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      setSelState(i => Math.max(0, i - 1))

      return true
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      setSelState(i => Math.min(Math.max(0, rows.length - 1), i + 1))

      return true
    }

    return false
  }

  return {
    activeOutcome,
    book,
    clampedSel,
    cycleSort: sort.cycle,
    cycleVenue,
    detailItem,
    expanded,
    filter,
    filterActive: pmFilterActive(filter),
    filterSummary: pmFilterSummary(filter),
    filteredCount: filtered.length,
    handleKey,
    history,
    historyRange,
    itemsCount: items.length,
    keyHint,
    livePrices,
    loading,
    matchCount: filtered.length,
    openMarket,
    reload,
    rowCount: rows.length,
    rows,
    sel: clampedSel,
    selectedItem: detailItem,
    setFilter,
    setHistoryRange,
    setSel,
    sortByKey: sort.sortByKey,
    sortState: sort.state,
    streamNote,
    streaming,
    venue
  }
}
