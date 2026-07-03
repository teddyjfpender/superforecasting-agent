// Data hooks for the Prediction Markets pane: they keep the network + streaming
// lifecycle out of the view component (which stays under the non-monolithic
// line budget and reads as pure layout + input). One list fetch per refresh;
// book/history fetch on demand for the selection; ONE multiplexed ws
// subscription per selected event, folded in place on pm.tick.

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  applyBookTick,
  bookMarketId,
  fetchPMBook,
  fetchPMDetail,
  fetchPMHistory,
  fetchPMList,
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

export interface PMHookGateway {
  off?: (event: string, listener: (...args: unknown[]) => void) => void
  on?: (event: string, listener: (...args: unknown[]) => void) => void
  request: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
}

// ── list ─────────────────────────────────────────────────────────────────────

export function usePmList(gw: PMHookGateway | undefined, active: boolean, venue: 'all' | PMVenue) {
  const [items, setItems] = useState<PMListItem[]>([])
  const [loading, setLoading] = useState(false)
  // Has the FIRST list fetch settled (either way)? Lets the section show an
  // honest "loading venues…" line on first open instead of flashing "0 events"
  // before any items land. Distinct from `loading`, which toggles per refresh.
  const [loaded, setLoaded] = useState(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true

    return () => {
      aliveRef.current = false
    }
  }, [])

  const reload = useCallback(() => {
    if (!gw) {
      return
    }

    setLoading(true)
    fetchPMList(gw, { limit: 40, ...(venue === 'all' ? {} : { venue }) })
      .then(next => {
        if (aliveRef.current) {
          setItems(next)
          setLoading(false)
          setLoaded(true)
        }
      })
      .catch(() => {
        if (aliveRef.current) {
          setLoading(false)
          setLoaded(true)
        }
      })
  }, [gw, venue])

  useEffect(() => {
    if (active) {
      reload()
    }
  }, [active, reload])

  return { items, loaded, loading, reload }
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
  const [detail, setDetail] = useState<null | PMListItem>(null)
  const [book, setBook] = useState<null | PMOrderBookDTO>(null)
  const [history, setHistory] = useState<PMHistoryPointDTO[]>([])
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

  // Full event (markets + token ids) on event change.
  useEffect(() => {
    if (!gw || !active || !selectedItem) {
      setDetail(null)

      return
    }

    let cancelled = false
    fetchPMDetail(gw, selectedItem.event.venue, selectedItem.event.event_id)
      .then(d => !cancelled && aliveRef.current && setDetail(d ?? selectedItem))
      .catch(() => !cancelled && aliveRef.current && setDetail(selectedItem))

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, active, selectedEventId])

  const detailItem =
    detail && selectedItem && detail.event.event_id === selectedItem.event.event_id ? detail : selectedItem

  const activeVenue = selectedItem?.event.venue ?? 'polymarket'
  const activeMarket = detailItem?.event.markets.find(m => m.market_id === activeOutcome?.market_id)
  const bookId = activeOutcome ? bookMarketId(activeVenue, activeMarket, activeOutcome.market_id) : null

  // Book + history on outcome / range change (on demand).
  useEffect(() => {
    if (!gw || !active || !bookId) {
      setBook(null)
      setHistory([])

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
      .then(pts => !cancelled && aliveRef.current && setHistory(pts))
      .catch(() => !cancelled && aliveRef.current && setHistory([]))

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, active, activeVenue, bookId, historyRange])

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

      if (ev?.type !== 'pm.tick' || !ev.payload) {
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
