// The Prediction Markets SECTION of the Data-mode tape. This hook keeps the PM
// network + streaming lifecycle and the row model out of marketsView (which owns
// the single tape cursor + the `/` filter trap) while still exposing a
// `handleKey` the view's ONE useInput delegates to. There is deliberately NO
// useInput here: the section rides the parent's keyboard so the `/` focus trap
// and the shared selection hold across both quote sections and PM rows.

import { useCallback, useEffect, useMemo, useState } from 'react'

import { openExternalUrl } from './openExternalUrl.js'
import { type PMHistoryRange, type PMOutcomeDTO, type PMVenue,
  fetchPMList,
  type PMListItem
} from './pmData.js'
import {
  DEFAULT_PM_FILTER,
  filterPMItems,
  filterPMSection,
  flattenPMRows,
  PM_SORT_KEYS,
  type PMDisplayRow,
  pmExpandable,
  pmRowId,
  type PmFilter,
  pmFilterActive,
  pmFilterSummary,
  pmSortValue
} from './pmRows.js'
import { sortRows, type TableSortState, useTableSort } from './tableSort.js'
import { usePmDiscovered } from './usePmDiscovered.js'
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
  // Row ids (venue:event_id) present in the tape ONLY because the operator
  // discovered them via '/' search — i.e. not on the browse page. The table
  // marks them; `x` removes them.
  discoveredKeys: ReadonlySet<string>
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
  stale: boolean
  matchCount: number
  openMarket: () => void
  // Drop the discovered event under the cursor from the pool + markets.json (or
  // flash a refusal on a browse row). Wired to `x` and the gated footer chip.
  removeDiscovered: () => void
  searching: boolean
  reload: () => void
  rowCount: number
  rows: PMDisplayRow[]
  sel: number
  selectedItem: ReturnType<typeof usePmSelectionData>['detailItem']
  // Whether the selected row is a removable discovered headline (live-keys-only
  // rule: the `x` chip shows only when this is true).
  selectedIsDiscovered: boolean
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

  const { items, loaded, loading, reload, stale } = usePmList(gw, tabActive, venue)

  // DISCOVERED events persist across sessions (deep '/' search compounds the
  // tape's coverage): the fold / persist / chunked-hydrate lifecycle lives in
  // its own hook, so this section stays layout + input.
  const { discovered, foldDiscovered, removeDiscovered: dropDiscovered } = usePmDiscovered(gw, tabActive)

  // DEEP venue search: the browse list is one liquidity-ranked page, so the
  // local '/' filter can only ever match what happens to be loaded — the
  // operator kept "not seeing the weather markets" even after the server
  // learned to search the FULL catalogs (Gamma public-search + the Kalshi
  // series scan). A debounced pm.list {query} makes '/' reach them: results
  // merge (deduped) into the pool and vanish when the query clears.
  const [searchItems, setSearchItems] = useState<null | PMListItem[]>(null)
  const [searching, setSearching] = useState(false)

  const query = searchInput.trim()
  useEffect(() => {
    if (!gw || !tabActive || query.length < 3) {
      setSearchItems(null)
      setSearching(false)

      return
    }

    setSearching(true)
    let cancelled = false
    const id = setTimeout(() => {
      fetchPMList(gw, { limit: 30, query, ...(venue === 'all' ? {} : { venue }) })
        .then(found => {
          if (!cancelled) {
            setSearchItems(found)
            setSearching(false)
            foldDiscovered(found)
          }
        })
        .catch(() => {
          if (!cancelled) {
            setSearchItems(null)
            setSearching(false)
          }
        })
    }, 450)

    return () => {
      cancelled = true
      clearTimeout(id)
    }
  }, [gw, tabActive, query, venue])

  const pool = useMemo(() => {
    const seen = new Set(items.map(i => i.event.event_id))
    const merged = [...items]
    for (const item of discovered.values()) {
      if (!seen.has(item.event.event_id)) {
        seen.add(item.event.event_id)
        merged.push(item)
      }
    }
    for (const item of searchItems ?? []) {
      if (!seen.has(item.event.event_id)) {
        seen.add(item.event.event_id)
        merged.push(item)
      }
    }

    return merged
  }, [items, discovered, searchItems])

  // Row ids that are in the tape SOLELY because the operator discovered them via
  // '/' search — a discovered event that ALSO rode in on the browse page is not
  // marked (it isn't distinct from the browse feed). These get the subtle "+"
  // marker in the table and are the only rows `x` can remove.
  const discoveredKeys = useMemo(() => {
    const browse = new Set(items.map(i => i.event.event_id))
    const keys = new Set<string>()
    for (const item of discovered.values()) {
      if (!browse.has(item.event.event_id)) {
        keys.add(pmRowId(item))
      }
    }

    return keys
  }, [items, discovered])

  // Structured filter first (venue · topic · vol · prob · sports), then rank by
  // the `/` text query — the two compose, and sort rides on top of both.
  const structured = useMemo(() => filterPMSection(pool, filter), [pool, filter])
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

  const selectedIsDiscovered = selectedRow?.kind === 'headline' && discoveredKeys.has(selectedRow.id)

  // `x` on a discovered headline drops it from the session pool + markets.json's
  // pmSaved (a mis-search must not pollute the tape); on any other row it refuses
  // with a hint that only saved (+) rows are removable.
  const removeDiscovered = () => {
    if (!(selectedRow?.kind === 'headline' && selectedIsDiscovered)) {
      setFlash('only saved (+) rows can be removed')

      return
    }

    dropDiscovered(selectedRow.item.event.event_id)
    setFlash('removed from saved markets')
  }

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

    // Remove the saved (+) market under the cursor — consumed on the PM tab
    // either way (a refusal flash on a browse row) so `x` never leaks elsewhere.
    if (ch === 'x') {
      removeDiscovered()

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
    discoveredKeys,
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
    // Disk-served cold tape awaiting its live revalidate — the UI shows this
    // subtly rather than pretending the rows are fresh.
    stale,
    // Honest first-open state: stay "loading" until the very first list fetch
    // settles (with a gateway), so the tape never flashes "0 events" / an empty
    // frame before any items land. Later refreshes just ride the per-fetch flag.
    loading: loading || (!loaded && Boolean(gw)),
    matchCount: filtered.length,
    openMarket,
    removeDiscovered,
    reload,
    searching,
    rowCount: rows.length,
    rows,
    sel: clampedSel,
    selectedItem: detailItem,
    selectedIsDiscovered: Boolean(selectedIsDiscovered),
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
