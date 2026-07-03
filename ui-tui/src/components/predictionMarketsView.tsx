import { Box, Text, useInput } from '@hermes/ink'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { openExternalUrl } from '../lib/openExternalUrl.js'
import { fmtProb, type PMHistoryRange, type PMVenue, venueLabel } from '../lib/pmData.js'
import { filterPMItems, flattenPMRows, PM_SORT_KEYS, pmExpandable, pmSortValue } from '../lib/pmRows.js'
import { sortRows, useTableSort } from '../lib/tableSort.js'
import { type PMHookGateway, usePmList, usePmSelectionData } from '../lib/usePmMarkets.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'
import { PredictionMarketDetail } from './predictionMarketDetail.js'
import { PredictionMarketsTable } from './predictionMarketsTable.js'

export type PMViewGateway = PMHookGateway

interface PMViewProps {
  active: boolean
  gw?: PMViewGateway
  height: number
  onLeave: () => void
  t: Theme
  width: number
}

const VENUE_CYCLE: ('all' | PMVenue)[] = ['all', 'polymarket', 'kalshi']

// Exact command surfaced when Kalshi streaming is asked for without a key —
// key hints only where they're live (the read-only tape works keyless).
const KALSHI_KEY_HINT =
  'Kalshi streaming needs a key — run  forecast api-key set kalshi <key-id> --pem-file key.pem  (REST tape works keyless).'

const POLL_MS = 30_000

const nextVenue = (cur: 'all' | PMVenue): 'all' | PMVenue =>
  VENUE_CYCLE[(VENUE_CYCLE.indexOf(cur) + 1) % VENUE_CYCLE.length]

// A bounded list re-poll used only while streaming is off. Tiny local hook so
// the view body stays declarative; the timer is cleared on leave/unmount.
function usePollWhenIdle(enabled: boolean, reload: () => void) {
  useEffect(() => {
    if (!enabled) {
      return
    }

    const id = setInterval(() => reload(), POLL_MS)

    return () => clearInterval(id)
  }, [enabled, reload])
}

// The Prediction Markets pane: ONE filter over both venues (venue shown as a
// dim chip per row), event headline rows + expandable outcome sub-rows, a
// detail pane (distribution bars + order book + history sparkline), Enter opens
// the market page, and pm.tick streaming folds ticks in place with a keyless
// REST fallback.
export function PredictionMarketsView({ active, gw, height, onLeave, t, width }: PMViewProps) {
  const sem = semantics(t)

  const [venue, setVenue] = useState<'all' | PMVenue>('all')
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set())
  const [sel, setSel] = useState(0)
  const [searchMode, setSearchMode] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [historyRange, setHistoryRange] = useState<PMHistoryRange>('1w')
  const [flash, setFlash] = useState('')

  const { items, loading, reload } = usePmList(gw, active, venue)

  // filter → sort → flatten. Sort is over headline events; sub-rows stay
  // attached under their parent.
  const filtered = useMemo(() => filterPMItems(items, searchInput), [items, searchInput])
  const sortState = useTableSort(PM_SORT_KEYS)

  const sorted = useMemo(
    () => sortRows(filtered, sortState.state.key, sortState.state.dir, pmSortValue),
    [filtered, sortState.state.key, sortState.state.dir]
  )

  const rows = useMemo(() => flattenPMRows(sorted, expanded), [sorted, expanded])

  const clampedSel = Math.min(sel, Math.max(0, rows.length - 1))
  const selectedRow = rows[clampedSel]
  const selectedItem = selectedRow ? (selectedRow.kind === 'headline' ? selectedRow.item : selectedRow.parent) : null

  const activeOutcome =
    selectedRow?.kind === 'outcome' ? selectedRow.outcome : (selectedItem?.distribution.outcomes?.[0] ?? null)

  const { book, detailItem, history, livePrices, streamNote, streaming } = usePmSelectionData(
    gw,
    active,
    selectedItem,
    activeOutcome,
    historyRange
  )

  // Bounded REST re-poll while streaming is OFF (30s, list only, cleared on leave).
  usePollWhenIdle(active && !streaming, reload)

  // The transient status line ('refreshing…', 'opened in browser', 'no market
  // URL') is a momentary confirmation — auto-clear it so a stale 'refreshing…'
  // never pins itself in the footer after the op has settled.
  useEffect(() => {
    if (!flash) {
      return
    }

    const id = setTimeout(() => setFlash(''), 2500)

    return () => clearTimeout(id)
  }, [flash])

  const activeVenue = selectedItem?.event.venue ?? 'polymarket'
  const kalshiKeyless = (venue === 'kalshi' || activeVenue === 'kalshi') && !streaming && /key/i.test(streamNote)
  const keyHint = kalshiKeyless ? KALSHI_KEY_HINT : null

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
  }, [selectedItem])

  const cycleVenue = useCallback(() => {
    setSel(0)
    setSearchInput('')
    setVenue(nextVenue)
  }, [])

  useInput(
    (ch, key) => {
      if (searchMode) {
        if (key.escape) {
          setSearchMode(false)

          return setSearchInput('')
        }

        if (key.return) {
          return setSearchMode(false)
        }

        if (key.backspace || key.delete) {
          return setSearchInput(s => s.slice(0, -1))
        }

        if (ch && !key.ctrl && !key.meta) {
          const printable = [...ch].filter(c => c >= ' ').join('')

          if (printable) {
            setSearchInput(s => s + printable)
            setSel(0)
          }
        }

        return
      }

      if (key.escape) {
        return searchInput ? setSearchInput('') : onLeave()
      }

      if (ch === 'q') {
        return onLeave()
      }

      if (ch === '/') {
        setSel(0)

        return setSearchMode(true)
      }

      if (ch === 'v') {
        return cycleVenue()
      }

      if (ch === 'r') {
        setFlash('refreshing…')

        return reload()
      }

      if (ch === 'o') {
        return sortState.cycle()
      }

      if (ch === 'O') {
        return sortState.toggle()
      }

      if (ch === '1') {
        return setHistoryRange('1d')
      }

      if (ch === '2') {
        return setHistoryRange('1w')
      }

      if (ch === '3') {
        return setHistoryRange('all')
      }

      if (key.return) {
        return openMarket()
      }

      if ((key.rightArrow || ch === ' ') && selectedRow?.kind === 'headline' && pmExpandable(selectedRow.item)) {
        return toggleExpand(selectedRow.id, !expanded.has(selectedRow.id))
      }

      if (key.leftArrow && selectedRow) {
        return toggleExpand(selectedRow.kind === 'headline' ? selectedRow.id : selectedRow.parentId, false)
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return setSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return setSel(i => Math.min(Math.max(0, rows.length - 1), i + 1))
      }
    },
    { isActive: active }
  )

  // ── layout ─────────────────────────────────────────────────────────────────
  const detailWidth = Math.max(34, Math.min(48, width - 52))
  const tableWidth = Math.max(30, width - detailWidth - 2)
  const avail = Math.max(24, tableWidth - 2)
  const labelCol = Math.max(16, avail - 26)
  const listRows = Math.max(3, height - 3)
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(listRows / 2), rows.length - listRows))
  const windowed = rows.slice(Math.max(0, listStart), Math.max(0, listStart) + listRows)

  const emptyText = loading
    ? 'Loading prediction markets…'
    : searchInput
      ? `No markets match “${searchInput}”.`
      : gw
        ? 'No open markets right now. Press r to refresh or v to switch venue.'
        : 'Prediction markets need the gateway. Polymarket + Kalshi headlines and books load read-only, no key. Press v to filter venue.'

  const chips: FooterChip[] = [
    { k: '↑↓', label: 'Select' },
    { k: '→', label: 'Expand' },
    { k: '⏎', label: 'Open', run: openMarket },
    { k: 'v', label: `Venue: ${venue === 'all' ? 'All' : venueLabel(venue)}`, run: cycleVenue },
    { k: '/', label: 'Filter', run: () => { setSel(0); setSearchMode(true) } },
    { k: 'o', label: 'Sort', run: () => sortState.cycle() },
    { k: '1/2/3', label: 'Range' },
    { k: 'r', label: 'Refresh', run: reload },
    { k: 'q', label: 'Back', run: onLeave }
  ]

  const streamState = streaming ? '● live' : gw ? 'polling · 30s' : ''

  return (
    <Box flexDirection="column" flexGrow={1}>
      <Box flexShrink={0} marginBottom={1}>
        {searchMode || searchInput ? (
          <Text wrap="truncate-end">
            <Text bold color={t.color.primary}>PREDICTION MARKETS</Text>
            <Text color={t.color.primary}>{'   ⌕ '}</Text>
            <Text color={t.color.text}>{searchInput}</Text>
            {searchMode ? <Text color={t.color.primary} inverse>{' '}</Text> : null}
            <Text color={sem.subtle}>
              {`   ${filtered.length} matches · ${searchMode ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
            </Text>
          </Text>
        ) : (
          <Text wrap="truncate-end">
            <Text bold color={t.color.primary}>PREDICTION MARKETS</Text>
            <Text color={sem.subtle}>{'   Polymarket + Kalshi · '}</Text>
            <Text color={t.color.text}>{venue === 'all' ? 'all venues' : venueLabel(venue)}</Text>
            <Text color={sem.subtle}>{` · ${items.length} events`}</Text>
            {streamState ? <Text color={streaming ? sem.up : sem.subtle}>{`   ${streamState}`}</Text> : null}
            {activeOutcome ? <Text color={sem.faint}>{`   top ${fmtProb(activeOutcome.prob)}`}</Text> : null}
          </Text>
        )}
      </Box>
      <Box flexDirection="row" flexShrink={0} height={height}>
        <PredictionMarketsTable
          active={active}
          avail={avail}
          clampedSel={clampedSel}
          emptyText={emptyText}
          expanded={expanded}
          height={height}
          labelCol={labelCol}
          listStart={listStart}
          livePrices={livePrices}
          onSelect={setSel}
          onSortByKey={sortState.sortByKey}
          rowsLength={rows.length}
          sem={sem}
          sortState={sortState.state}
          t={t}
          tableWidth={tableWidth}
          windowed={windowed}
        />
        <PredictionMarketDetail
          book={book}
          bookLabel={activeOutcome?.label ?? '—'}
          history={history}
          historyRange={historyRange}
          item={detailItem}
          keyHint={keyHint}
          selectedMarketId={activeOutcome?.market_id ?? null}
          streaming={streaming}
          t={t}
          width={detailWidth}
        />
      </Box>
      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        <FooterChips chips={chips} t={t} />
        {flash || streamNote ? (
          <Text color={sem.subtle} wrap="truncate-end">
            {flash ? <Text color={t.color.accent}>{`${flash}${streamNote ? ' · ' : ''}`}</Text> : null}
            {streamNote}
          </Text>
        ) : null}
      </Box>
    </Box>
  )
}
