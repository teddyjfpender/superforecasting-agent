import { useCallback, useEffect, useRef, useState } from 'react'

import type { RpcRequest } from '../protocol/generated.js'
// Data hooks for the Prediction Markets pane: they keep the network + streaming
// lifecycle out of the view component (which stays under the non-monolithic
// line budget and reads as pure layout + input). One list fetch per refresh;
// book/history fetch on demand for the selection; ONE multiplexed ws
// subscription per selected event, folded in place on pm.tick.
import { WireEvent } from '../protocol/generated.js'

import { gatewayCacheOwner } from './deskViewCache.js'
import type { fetchPMListResult } from './pmData.js'
import {
  applyBookTick,
  bookMarketId,
  fetchPMBook,
  fetchPMDetail,
  fetchPMHistory,
  type PMHistoryPointDTO,
  type PMHistoryRange,
  type PMListItem,
  type PMMarketDTO,
  type PMOrderBookDTO,
  type PMOutcomeDTO,
  type PMTickPayload,
  type PMVenue,
  seriesTickerFor,
  startPMStream,
  stopPMStream,
  tickEstimate
} from './pmData.js'
import { peekPMList, retainedPMList } from './pmListCache.js'

export interface PMHookGateway {
  off?: (event: string, listener: (...args: unknown[]) => void) => void
  on?: (event: string, listener: (...args: unknown[]) => void) => void
  request: RpcRequest
}

// ── list ─────────────────────────────────────────────────────────────────────

export function usePmList(gw: PMHookGateway | undefined, active: boolean, venue: 'all' | PMVenue) {
  const cacheOwner = gw ? gatewayCacheOwner(gw) : undefined
  const [items, setItems] = useState<PMListItem[]>(() => peekPMList(gw, venue)?.value.items ?? [])
  const [loading, setLoading] = useState(false)
  // Cold-start tape: rows served instantly from the gateway's disk cache while
  // the live revalidate runs — surfaced so the UI can mark the tape stale.
  const [stale, setStale] = useState(() => peekPMList(gw, venue)?.value.stale ?? false)

  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof fetchPMListResult>>['catalog']>(
    () => peekPMList(gw, venue)?.value.catalog ?? null
  )

  const [error, setError] = useState('')
  // Has the FIRST list fetch settled (either way)? Lets the section show an
  // honest "loading venues…" line on first open instead of flashing "0 events"
  // before any items land. Distinct from `loading`, which toggles per refresh.
  const [loaded, setLoaded] = useState(() => Boolean(peekPMList(gw, venue)))
  const listGeneration = useRef(0)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true

    return () => {
      aliveRef.current = false
    }
  }, [])

  const reload = useCallback(
    (force = true) => {
      if (!gw) {
        return
      }

      const generation = ++listGeneration.current
      const cached = peekPMList(gw, venue)
      setItems(cached?.value.items ?? [])
      setCatalog(cached?.value.catalog ?? null)
      setLoaded(Boolean(cached))
      setStale(cached?.value.stale ?? false)
      setLoading(true)
      setError('')
      retainedPMList(gw, venue, force)
        .then(next => {
          if (aliveRef.current && generation === listGeneration.current && cacheOwner === gatewayCacheOwner(gw)) {
            setCatalog(next.catalog)
            setItems(next.items)
            setStale(next.stale)
            setLoading(false)
            setLoaded(true)
          }
        })
        .catch(err => {
          if (aliveRef.current && generation === listGeneration.current && cacheOwner === gatewayCacheOwner(gw)) {
            setError(err instanceof Error ? err.message : String(err))
            setLoading(false)
            setLoaded(true)
          }
        })
    },
    [gw, venue, cacheOwner]
  )

  useEffect(() => {
    if (active) {
      reload(false)
    }

    return () => {
      listGeneration.current += 1
    }
  }, [active, reload])

  return { catalog, error, items, loaded, loading, reload, stale }
}

// ── selection detail + streaming ──────────────────────────────────────────────

export interface PMSelectionData {
  activeMarket: PMMarketDTO | undefined
  book: null | PMOrderBookDTO
  bookId: null | string
  detailItem: null | PMListItem
  history: PMHistoryPointDTO[]
  livePrices: Record<string, number>
  streamNote: string
  streaming: boolean
}

export function usePmSelectionData(
  gw: PMHookGateway | undefined,
  active: boolean,
  selectedItem: null | PMListItem,
  activeOutcome: null | PMOutcomeDTO,
  historyRange: PMHistoryRange
): PMSelectionData {
  const [detailResult, setDetailResult] = useState<{ owner: object | undefined; item: PMListItem } | null>(null)
  const [book, setBook] = useState<null | PMOrderBookDTO>(null)

  const [historyResult, setHistoryResult] = useState<{
    owner: object | undefined
    key: string
    points: PMHistoryPointDTO[]
  } | null>(null)

  const owner = gw ? gatewayCacheOwner(gw) : undefined
  const [streaming, setStreaming] = useState(false)
  const [streamNote, setStreamNote] = useState('')
  const [livePrices, setLivePrices] = useState<Record<string, number>>({})
  const aliveRef = useRef(true)
  const streamRef = useRef<{ ids: string[]; venue: string } | null>(null)
  // Maps a stream subscription id (Polymarket CLOB token id / Kalshi ticker)
  // back to the OUTCOME's market_id the table rows key on. Ticks arrive keyed by
  // the subscription id; without this remap the Polymarket overlay (conditionId
  // rows vs token-id ticks) would never repaint.
  const tickKeyRef = useRef<Record<string, string>>({})

  useEffect(() => {
    aliveRef.current = true

    return () => {
      aliveRef.current = false
    }
  }, [])

  const selectedEventId = selectedItem ? `${selectedItem.event.venue}:${selectedItem.event.event_id}` : null

  const detail = detailResult?.owner === owner ? detailResult?.item : null

  // Full event (markets + token ids) on event change.
  useEffect(() => {
    if (!gw || !active || !selectedItem) {
      setDetailResult(null)

      return
    }

    let cancelled = false
    fetchPMDetail(gw, selectedItem.event.venue, selectedItem.event.event_id)
      .then(d => !cancelled && aliveRef.current && setDetailResult({ owner, item: d ?? selectedItem }))
      .catch(() => !cancelled && aliveRef.current && setDetailResult({ owner, item: selectedItem }))

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, owner, active, selectedEventId])

  const detailItem =
    detail &&
    selectedItem &&
    detail.event.event_id === selectedItem.event.event_id &&
    detail.event.venue === selectedItem.event.venue
      ? detail
      : selectedItem

  const activeVenue = selectedItem?.event.venue ?? 'polymarket'
  const activeMarket = detailItem?.event.markets.find(m => m.market_id === activeOutcome?.market_id)
  const bookId = activeOutcome ? bookMarketId(activeVenue, activeMarket, activeOutcome.market_id) : null

  const historyKey = JSON.stringify([activeVenue, selectedEventId, bookId, historyRange])

  const history =
    active && historyResult?.owner === owner && historyResult?.key === historyKey ? historyResult.points : []

  // Book + history on outcome / range change (on demand).
  useEffect(() => {
    if (!gw || !active || !bookId) {
      setBook(null)
      setHistoryResult(null)

      return
    }

    let cancelled = false
    fetchPMBook(gw, activeVenue, bookId)
      .then(b => !cancelled && aliveRef.current && setBook(b))
      .catch(() => !cancelled && aliveRef.current && setBook(null))
    fetchPMHistory(gw, activeVenue, bookId, {
      range: historyRange,
      seriesTicker: seriesTickerFor(activeVenue, detailItem?.event)
    })
      .then(pts => !cancelled && aliveRef.current && setHistoryResult({ owner, key: historyKey, points: pts }))
      .catch(() => !cancelled && aliveRef.current && setHistoryResult(null))

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, owner, active, activeVenue, bookId, historyRange, historyKey])

  // ONE ws subscription for the selected event's book ids; stop on leave.
  // Debounced so arrow-keying down the list doesn't open+close the venue socket
  // once per row — the stream only (re)subscribes once the selection settles.
  useEffect(() => {
    if (!gw || !active || !detailItem) {
      return
    }

    const v = detailItem.event.venue

    // Remap: subscription id → outcome market_id (so ticks repaint the right row).
    const keyMap: Record<string, string> = {}

    for (const m of detailItem.event.markets) {
      const sub = bookMarketId(v, m, m.market_id)

      if (sub) {
        keyMap[sub] = m.market_id
      }
    }

    tickKeyRef.current = keyMap

    const ids = Object.keys(keyMap).slice(0, 12)

    if (ids.length === 0) {
      return
    }

    const timer = setTimeout(() => {
      streamRef.current = { ids, venue: v }
      startPMStream(gw, v, ids)
        .then(res => {
          if (aliveRef.current) {
            setStreaming(res.streaming)
            setStreamNote(res.streaming ? '' : res.reason || 'polling · 30s')
          }
        })
        .catch(() => aliveRef.current && setStreaming(false))
    }, 200)

    return () => {
      clearTimeout(timer)

      if (gw && streamRef.current) {
        void stopPMStream(gw, streamRef.current.venue, streamRef.current.ids)
        streamRef.current = null
      }

      setStreaming(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, active, selectedEventId, detailItem?.event.markets.length])

  // Fold pm.tick frames into the shown book + a live-price overlay.
  useEffect(() => {
    if (!gw?.on) {
      return
    }

    const onEvent = (raw: unknown) => {
      const ev = raw as { payload?: PMTickPayload; type?: string }

      if (ev?.type !== WireEvent.PM_TICK || !ev.payload) {
        return
      }

      const tick = ev.payload
      setBook(prev => applyBookTick(prev, tick))

      // Fold ONLY the server's honest estimate. A null estimate (dead/degenerate
      // tick) changes NOTHING — the honest REST value on the row is left intact,
      // never overwritten by a fabricated mid.
      const estimate = tickEstimate(tick)

      if (estimate !== null && aliveRef.current) {
        // Ticks are keyed by the subscription id; rows key on the outcome
        // market_id — remap so the Polymarket overlay actually lands.
        const rowId = tickKeyRef.current[tick.market_id] ?? tick.market_id
        setLivePrices(prev => (prev[rowId] === estimate ? prev : { ...prev, [rowId]: estimate }))
      }
    }

    gw.on('event', onEvent)

    return () => gw.off?.('event', onEvent)
  }, [gw])

  return { activeMarket, book, bookId, detailItem, history, livePrices, streamNote, streaming }
}
