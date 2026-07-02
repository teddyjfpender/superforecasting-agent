import { Box, NoSelect, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $marketJobs, pruneStaleMarketJobs, setMarketJob, STALE_MARKET_JOB_MS } from '../app/marketJobsStore.js'
import { $globalModal, patchOverlayState } from '../app/overlayStore.js'
import { DEFAULT_SERIES, MARKET_CATEGORIES, type MarketSeries, providerByKey } from '../content/marketProviders.js'
import type { GatewayClient } from '../gatewayClient.js'
import { type FieldSpec, rankItems } from '../lib/fuzzyRank.js'
import { statusGlyph } from '../lib/icons.js'
import { fetchQuotes, type MarketQuote } from '../lib/marketFetch.js'
import { getProviderKey } from '../lib/marketKeys.js'
import {
  loadMarketConfig,
  loadQuoteCache,
  type MarketConfig,
  type QuoteCache,
  quoteKey,
  saveMarketConfig,
  saveQuoteCache
} from '../lib/marketStore.js'
import { loadModelCatalog, saveModelCatalog } from '../lib/modelStore.js'
import { openExternalUrl } from '../lib/openExternalUrl.js'
import { type MarketModelListItem, normalizeModelList, normalizePresentation, type Presentation } from '../lib/presentation.js'
import { asRpcResult } from '../lib/rpc.js'
import { blockChart, sparkline } from '../lib/sparkline.js'
import { sortIndicator, sortRows, type SortDir, type SortValue, useTableSort } from '../lib/tableSort.js'
import { dirColor, dirGlyph, pad, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { AddProviderModal } from './addProviderModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import { type InfoItem, InfoModal } from './infoModal.js'
import { MarketSearchModal } from './marketSearchModal.js'
import { type ChatMessage, ModelChat } from './modelChat.js'
import { ModelsList } from './modelsList.js'
import { NewModelModal, type NewModelParams } from './newModelModal.js'
import { PresentationView } from './presentationView.js'

export const openMarketsView = () => patchOverlayState({ markets: true })
export const closeMarketsView = () => patchOverlayState({ markets: false })

// Markets — a live tape backed by user-chosen providers, with a searchable
// universe and a rich per-line-item detail pane (sparkline + day/52-week ranges
// + heuristics). `d` adds providers/categories, `/` searches, `a` asks the agent.

const STALE_MS = 60_000
const WATCHLIST = 'Watchlist'

const fmtNum = (v: null | number | undefined, unit?: string): string => {
  if (v === null || v === undefined) {
    return '—'
  }

  const a = Math.abs(v)

  if (unit === '%') {
    return v.toFixed(2)
  }

  if (a >= 1000) {
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }

  if (a >= 1) {
    return v.toFixed(2)
  }

  return v.toFixed(4)
}

const fmtSigned = (v: null | number): string => (v === null ? '—' : `${v >= 0 ? '+' : ''}${fmtNum(v)}`)
const fmtPct = (v: null | number): string => (v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`)

const fmtVol = (v?: null | number): string => {
  if (v === null || v === undefined) {
    return '—'
  }

  const a = Math.abs(v)

  if (a >= 1e9) {
    return `${(v / 1e9).toFixed(2)}B`
  }

  if (a >= 1e6) {
    return `${(v / 1e6).toFixed(2)}M`
  }

  if (a >= 1e3) {
    return `${(v / 1e3).toFixed(1)}K`
  }

  return String(v)
}

const relTime = (ms: number): string => {
  if (!ms) {
    return '—'
  }

  const m = Math.floor((Date.now() - ms) / 60_000)

  if (m < 1) {
    return 'now'
  }

  if (m < 60) {
    return `${m}m`
  }

  const h = Math.floor(m / 60)

  if (h < 24) {
    return `${h}h`
  }

  return new Date(ms).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
}

const sameSeries = (a: MarketSeries, b: MarketSeries): boolean =>
  a.provider === b.provider && a.symbol.toLowerCase() === b.symbol.toLowerCase()

const dedupeSeries = (list: MarketSeries[]): MarketSeries[] => {
  const out: MarketSeries[] = []

  for (const s of list) {
    if (!out.some(o => sameSeries(o, s))) {
      out.push(s)
    }
  }

  return out
}

interface MarketsViewProps {
  gw?: GatewayClient
  onAsk?: (question: string) => void
  onClose: () => void
  sessionId?: string
  t: Theme
}

// Field weights for the `/` tape filter: symbol is the key, then name, then
// category — so "tes" ranks TSLA first, "energy" surfaces the energy basket.
const MARKET_SEARCH_FIELDS: FieldSpec<MarketSeries>[] = [
  { get: s => s.symbol, weight: 1 },
  { get: s => s.name, weight: 0.8 },
  { get: s => s.category, weight: 0.5 }
]

// A tape row = its series + the latest quote (which may be missing until it
// fetches). Sorting composes over the filtered rows.
type TapeRow = { quote?: MarketQuote; series: MarketSeries }

// Every quote-table column is sortable except the trailing trend spark (not a
// column). `o` cycles them in header (display) order. Kept in sync with COLS.
const MARKET_SORT_KEYS = ['sym', 'name', 'last', 'chg', 'pct', 'vol']

// The comparable value a tape row contributes for a given sort key: the symbol /
// name string, or the raw numeric quote field (missing quotes sort last).
const marketSortValue = (row: TapeRow, key: string): SortValue => {
  const { quote: q, series: s } = row

  switch (key) {
    case 'chg':
      return q?.change ?? null

    case 'last':
      return q?.value ?? null

    case 'name':
      return q?.name || s.name || s.symbol || ''

    case 'pct':
      return q?.changePct ?? null

    case 'sym':
      return s.symbol

    case 'vol':
      return q?.volume ?? null

    default:
      return null
  }
}

export function MarketsView({ gw, onAsk, onClose, sessionId = '', t }: MarketsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const sem = semantics(t)
  // While the Ctrl+K palette / `?` cheat-sheet stacks above the view, its own
  // useInput goes inert and its still-visible body mouse handlers are gated.
  const globalModal = useStore($globalModal)

  const [config, setConfig] = useState<MarketConfig>(() => loadMarketConfig())
  const [active, setActive] = useState(0)
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [modal, setModal] = useState<'' | 'help' | 'newModel' | 'providers' | 'search'>('')
  const [flash, setFlash] = useState('')

  // INSTANT inline `/` filter over the loaded tape (separate from `d` Add data,
  // which adds new series). `searchMode` routes keystrokes to the bar; the
  // visible rows are derived + ranked. No modal, no network.
  const [searchMode, setSearchMode] = useState(false)
  const [searchInput, setSearchInput] = useState('')

  // ── Market Models mode ──────────────────────────────────────────────────
  const [mode, setMode] = useState<'data' | 'models'>('data')
  const [models, setModels] = useState<MarketModelListItem[]>(() => loadModelCatalog().models)
  const [modelSel, setModelSel] = useState(0)
  const [openModelId, setOpenModelId] = useState<null | string>(null)
  const [openVersion, setOpenVersion] = useState<null | number>(null)
  const [presentation, setPresentation] = useState<null | Presentation>(null)
  const [versionCount, setVersionCount] = useState(0)
  const [progressById, setProgressById] = useState<Record<string, string>>({})
  const [chatOpen, setChatOpen] = useState(false)
  // While the chat is open, focus is either the composer ('input') or the
  // presentation reader ('reader'); Tab toggles so you can scroll the left pane.
  const [chatFocus, setChatFocus] = useState<'input' | 'reader'>('input')
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatBusy, setChatBusy] = useState(false)
  const presScrollRef = useRef<null | ScrollBoxHandle>(null)

  // App-level job tracking (survives leaving/returning the view). Merge its live
  // status into the local progress map so a refine you walked away from still
  // shows as "refining" on return, and the list/chat indicators stay correct.
  const marketJobs = useStore($marketJobs)

  // A job with no progress update for longer than the stale window is presumed
  // dead (missed terminal event — e.g. a gateway restart killed the daemon
  // thread), so it reads as inactive and a model never sticks on "refining…".
  // The periodic sweep below removes the dead entry from the store.
  const liveJob = (job: { at: number; status: string } | undefined, now: number): boolean =>
    Boolean(job && (job.status === 'building' || job.status === 'refining') && now - job.at < STALE_MARKET_JOB_MS)

  const progress = useMemo(() => {
    const now = Date.now()
    const merged: Record<string, string> = { ...progressById }

    for (const [id, job] of Object.entries(marketJobs)) {
      if (liveJob(job, now)) {
        merged[id] = job.message || job.status
      }
    }

    return merged
     
  }, [progressById, marketJobs])

  const jobActive = (id: null | string): boolean => liveJob(id ? marketJobs[id] : undefined, Date.now())

  const cacheRef = useRef<QuoteCache>(loadQuoteCache())
  const [cacheVersion, setCacheVersion] = useState(0)
  const inflightRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    const id = setInterval(() => setTick(v => v + 1), 600)
    // Sweep dead jobs (missed terminal events) every ~30s so the store + header
    // count reconcile with reality and rows can't stick on "refining…".
    const sweep = setInterval(() => pruneStaleMarketJobs(), 30_000)
    pruneStaleMarketJobs()

    return () => {
      aliveRef.current = false
      clearInterval(id)
      clearInterval(sweep)
    }
  }, [])

  const providers = useMemo(() => new Set(config.providers), [config])

  // Enabled providers that require (or strongly need) an API key but don't have
  // one set — these fetch nothing, so warn instead of showing a silent blank.
  const providersMissingKey = useMemo(
    () =>
      config.providers
        .map(providerByKey)
        .filter((p): p is NonNullable<typeof p> => Boolean((p?.needsKey || p?.keyRecommended) && p?.keyEnv && !getProviderKey(p.keyEnv)))
        .map(p => p.key),
    [config.providers]
  )

  // Detail behind the header [!], shown in the `i` Information modal so the
  // header stays a single row (no footer-stealing second line).
  const infoItems = useMemo<InfoItem[]>(
    () =>
      providersMissingKey.map(key => {
        const p = providerByKey(key)

        return {
          detail: `${p?.keyUrl ? `Get a free key at ${p.keyUrl}. ` : ''}Add it under “Add data” (press d, highlight ${p?.name ?? key}, press k) or run /api-key set ${key}.`,
          label: `${p?.name ?? key} series are blank without an API key`,
          tone: 'warn'
        }
      }),
    [providersMissingKey]
  )

  // ── Market Models data flow ────────────────────────────────────────────
  const refreshModels = () => {
    if (!gw) {
      return
    }

    gw.request('markets.model.list', {})
      .then(raw => {
        if (!aliveRef.current) {
          return
        }

        const list = normalizeModelList(asRpcResult<{ models: unknown[] }>(raw) ?? raw)
        setModels(list)
        saveModelCatalog({ models: list })
        // Reconcile the optimistic job store against server truth: if the model
        // was updated AFTER its tracked job last reported progress, the job has
        // settled (a new version landed) even if we missed its complete event —
        // clear it so the row reflects the real, finished state.
        const jobs = $marketJobs.get()

        for (const m of list) {
          const job = jobs[m.id]

          if (job && (job.status === 'building' || job.status === 'refining')) {
            const updated = Date.parse(m.updated_at ?? '')

            if (Number.isFinite(updated) && updated > job.at) {
              setMarketJob(m.id, { status: 'done', version: m.current_version })
            }
          }
        }
      })
      .catch(() => undefined)
  }

  // Re-run a model's build (reusing its stored question + depth) — for a failed
  // or partial model, so the user never has to re-prompt. Progress flows through
  // the existing event subscription + the app-level job store.
  const retryModel = (id: null | string) => {
    if (!gw || !id) {
      return
    }

    setFlash('retrying…')
    // Seed the app-level store immediately so the job is tracked even if you Esc
    // away before the first progress event lands (it keeps running regardless).
    setMarketJob(id, { message: 'retrying…', status: 'building' })
    gw.request('markets.model.retry', { id, session_id: sessionId })
      .then(() => refreshModels())
      .catch(() => setFlash('retry failed'))
  }

  const loadModel = (id: string, version?: number) => {
    if (!gw) {
      return
    }

    setOpenModelId(id)
    setOpenVersion(version ?? null)
    setChatOpen(false)
    presScrollRef.current?.scrollTo?.(0)
    gw.request('markets.model.get', { id, session_id: sessionId, version })
      .then(raw => {
        if (!aliveRef.current) {
          return
        }

        const packet = (asRpcResult<{ packet: Record<string, unknown> }>(raw) ?? {}).packet ?? {}
        const presRaw = (packet as Record<string, unknown>).presentation
        const pres = normalizePresentation((presRaw as Record<string, unknown>)?.presentation ?? presRaw)
        setPresentation(pres)
        setVersionCount(Array.isArray((packet as Record<string, unknown>).versions) ? ((packet as Record<string, unknown>).versions as unknown[]).length : pres?.version ?? 0)
        const msgs = Array.isArray((packet as Record<string, unknown>).messages) ? ((packet as Record<string, unknown>).messages as Record<string, unknown>[]) : []
        setChatMessages(msgs.map(m => ({ content: String(m.content ?? ''), role: String(m.role ?? 'user') })))
        setChatBusy(false)
      })
      .catch(() => undefined)
  }

  // Initial + on-enter-models catalog refresh from the gateway.
  useEffect(() => {
    if (mode === 'models') {
      refreshModels()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  // Subscribe to background build/refresh events.
  useEffect(() => {
    if (!gw?.on) {
      return
    }

    const onProgress = (p: { id?: string; message?: string; phase?: string }) => {
      if (!aliveRef.current || !p?.id) {
        return
      }

      setProgressById(prev => ({ ...prev, [p.id!]: p.message || p.phase || 'working' }))
    }

    const onComplete = (p: { id?: string; version?: number }) => {
      if (!aliveRef.current || !p?.id) {
        return
      }

      setProgressById(prev => {
        const next = { ...prev }
        delete next[p.id!]

        return next
      })
      setChatBusy(false)
      refreshModels()

      if (p.id === openModelId) {
        loadModel(p.id, p.version)
      } else {
        setFlash('model ready')
      }
    }

    const onRefreshed = (p: { id?: string; presentation?: unknown }) => {
      if (!aliveRef.current || p?.id !== openModelId) {
        return
      }

      const pres = normalizePresentation(p.presentation)

      if (pres) {
        setPresentation(pres)
      }
    }

    const onError = (p: { id?: string; message?: string }) => {
      if (!aliveRef.current) {
        return
      }

      setProgressById(prev => {
        const next = { ...prev }

        if (p?.id) {
          delete next[p.id]
        }

        return next
      })
      setChatBusy(false)
      setFlash(`model error: ${p?.message ?? 'failed'}`)
      refreshModels()
    }

    gw.on('markets.model.progress', onProgress)
    gw.on('markets.model.complete', onComplete)
    gw.on('markets.model.refreshed', onRefreshed)
    gw.on('markets.model.error', onError)

    return () => {
      gw.off?.('markets.model.progress', onProgress)
      gw.off?.('markets.model.complete', onComplete)
      gw.off?.('markets.model.refreshed', onRefreshed)
      gw.off?.('markets.model.error', onError)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, openModelId])

  // Reopen the active model when ITS background job finishes — covers returning
  // to a refine you walked away from (the completion event fired while unmounted).
  useEffect(() => {
    const j = openModelId ? marketJobs[openModelId] : undefined

    if (j?.status === 'done' && (j.version ?? 0) !== (openVersion ?? -1)) {
      loadModel(openModelId!, j.version)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketJobs, openModelId])

  // Poll the catalog while any model is still building OR has an in-flight job
  // (incl. refines of already-built models), so a missed completion event can
  // never leave a row stuck (server-truth reconcile).
  const buildingCount = models.filter(
    m => ((m.current_version ?? 0) < 1 && m.status !== 'error') || jobActive(m.id)
  ).length

  useEffect(() => {
    if (mode !== 'models' || buildingCount === 0) {
      return
    }

    const id = setInterval(() => refreshModels(), 4000)

    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, buildingCount])

  const submitNewModel = (params: NewModelParams) => {
    setModal('')

    if (!gw) {
      return setFlash('models need the gateway')
    }

    setMode('models')
    gw.request('markets.model.create', { params, question: params.question, session_id: sessionId })
      .then(raw => {
        const res = asRpcResult<{ model_id?: string }>(raw)

        if (res?.model_id) {
          setMarketJob(res.model_id, { message: 'starting', status: 'building' })

          if (aliveRef.current) {
            setProgressById(prev => ({ ...prev, [res.model_id!]: 'starting' }))
            refreshModels()
          }
        }
      })
      .catch(() => setFlash('create failed'))
  }

  const sendChat = () => {
    const msg = chatInput.trim()

    if (!gw || !openModelId || !msg) {
      return
    }

    setChatMessages(prev => [...prev, { content: msg, role: 'user' }])
    setChatInput('')
    setChatBusy(true)
    setProgressById(prev => ({ ...prev, [openModelId]: 'refining' }))
    setMarketJob(openModelId, { message: 'refining…', status: 'refining' })
    gw.request('markets.model.chat', { id: openModelId, message: msg, session_id: sessionId }).catch(() => {
      setChatBusy(false)
      setFlash('refine failed')
    })
  }

  const watchlist = config.watchlist
  const custom = config.custom

  // Tabs: a Watchlist tab (if any) plus the selected provider categories.
  const categories = useMemo(() => {
    const base = MARKET_CATEGORIES.filter(c => config.categories.includes(c))

    return [...(watchlist.length ? [WATCHLIST] : []), ...base]
  }, [config, watchlist])

  const activeCategory = categories[Math.min(active, Math.max(0, categories.length - 1))]

  const seriesFor = (category: string | undefined): MarketSeries[] => {
    if (!category) {
      return []
    }

    if (category === WATCHLIST) {
      return watchlist
    }

    // Curated provider series + the user's own additions in this category.
    return dedupeSeries([
      ...DEFAULT_SERIES.filter(s => providers.has(s.provider) && s.category === category),
      ...custom.filter(s => s.category === category)
    ])
  }

  // Everything we fetch: watchlist + custom + enabled-provider series in
  // selected categories.
  const allSeries = useMemo(
    () =>
      dedupeSeries([
        ...watchlist,
        ...custom,
        ...DEFAULT_SERIES.filter(s => providers.has(s.provider) && config.categories.includes(s.category))
      ]),
    [watchlist, custom, providers, config]
  )

  const refresh = async (force: boolean) => {
    if (inflightRef.current || allSeries.length === 0) {
      return
    }

    const targets = force
      ? allSeries
      : allSeries.filter(s => {
          const q = cacheRef.current[quoteKey(s.provider, s.symbol)]

          return !q || Date.now() - q.asOf > STALE_MS
        })

    if (targets.length === 0) {
      return
    }

    inflightRef.current = true

    if (aliveRef.current) {
      setFetching(true)
    }

    await fetchQuotes(targets, {
      getKey: getProviderKey,
      onBatch: quotes => {
        for (const q of quotes) {
          cacheRef.current[quoteKey(q.provider, q.symbol)] = q
        }

        if (aliveRef.current) {
          setCacheVersion(v => v + 1)
        }
      }
    })
    saveQuoteCache(cacheRef.current)
    inflightRef.current = false

    if (aliveRef.current) {
      setFetching(false)
    }
  }

  useEffect(() => {
    void refresh(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config])

  const persist = (next: MarketConfig) => {
    saveMarketConfig(next)
    setConfig(next)
  }

  const onProvidersSaved = (next: MarketConfig) => {
    setModal('')
    persist({ ...next, custom, watchlist })
    setActive(0)
    setFlash('saved')
  }

  const withProvider = (key: string): string[] =>
    providers.has(key) ? config.providers : [...config.providers, key]

  const isAdded = (s: MarketSeries): boolean => custom.some(c => sameSeries(c, s))
  const isWatched = (s: MarketSeries): boolean => watchlist.some(w => sameSeries(w, s))

  // Default add: put the item in its own category (and surface that category +
  // its provider so it shows + fetches).
  const toggleCategory = (s: MarketSeries) => {
    const exists = isAdded(s)
    const nextCustom = exists ? custom.filter(c => !sameSeries(c, s)) : [...custom, s]
    const nextCategories = exists || config.categories.includes(s.category) ? config.categories : [...config.categories, s.category]
    persist({ ...config, categories: nextCategories, custom: nextCustom, providers: exists ? config.providers : withProvider(s.provider) })
    setFlash(exists ? `removed ${s.symbol}` : `added ${s.symbol} to ${s.category}`)
  }

  // Opt-in: add a symbol to the explicit watchlist.
  const toggleWatch = (s: MarketSeries) => {
    const exists = isWatched(s)
    const nextWatch = exists ? watchlist.filter(w => !sameSeries(w, s)) : [...watchlist, s]
    persist({ ...config, providers: exists ? config.providers : withProvider(s.provider), watchlist: nextWatch })
    setFlash(exists ? `unwatched ${s.symbol}` : `watching ${s.symbol}`)
  }

  const rows = useMemo(() => {
    return seriesFor(activeCategory).map(s => ({ quote: cacheRef.current[quoteKey(s.provider, s.symbol)], series: s }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory, providers, watchlist, custom, cacheVersion])

  // The `/` filter ranks the loaded series by relevance and hides non-matches;
  // an empty query shows the full tape. Series identity is preserved through the
  // ranker, so we re-order `rows` by the ranked positions.
  const searchActive = searchInput.trim()

  const visibleRows = useMemo(() => {
    if (!searchActive) {
      return rows
    }

    const rankOf = new Map<MarketSeries, number>()
    rankItems(
      rows.map(r => r.series),
      searchActive,
      MARKET_SEARCH_FIELDS
    ).forEach((r, i) => rankOf.set(r.item, i))

    return rows.filter(r => rankOf.has(r.series)).sort((a, b) => (rankOf.get(a.series) ?? 0) - (rankOf.get(b.series) ?? 0))
  }, [rows, searchActive])

  // Column sort (`o` cycles, `O` toggles, header click sorts). Composes ON TOP of
  // the `/` filter: sort the already-filtered `visibleRows`. Default = unsorted →
  // the loaded tape order is preserved.
  const marketSort = useTableSort(MARKET_SORT_KEYS)
  const sortedRows = useMemo(
    () => sortRows(visibleRows, marketSort.state.key, marketSort.state.dir, marketSortValue),
    [visibleRows, marketSort.state.key, marketSort.state.dir]
  )

  const clampedSel = Math.min(sel, Math.max(0, sortedRows.length - 1))
  const selectedRow = sortedRows[clampedSel]

  // Keep the SELECTED tape row selected across a re-sort (track by provider:symbol,
  // not index): a sort action stashes the current key, and once the re-sorted order
  // lands we move the cursor to wherever that row now sits. A filter/quote update
  // leaves the ref null, so it never fights the existing cursor logic.
  const pendingReselect = useRef<null | string>(null)
  useEffect(() => {
    const key = pendingReselect.current
    if (key == null) return
    pendingReselect.current = null
    const idx = sortedRows.findIndex(r => quoteKey(r.series.provider, r.series.symbol) === key)
    if (idx >= 0) setSel(idx)
  }, [sortedRows])

  const armReselect = () => {
    pendingReselect.current = selectedRow ? quoteKey(selectedRow.series.provider, selectedRow.series.symbol) : null
  }
  const onSortCycle = () => {
    armReselect()
    marketSort.cycle()
  }
  const onSortToggle = () => {
    armReselect()
    marketSort.toggle()
  }
  const onSortByKey = (key: string) => {
    armReselect()
    marketSort.sortByKey(key)
  }

  // Hand the highlighted line item to the agent as a ready-to-send question.
  const askAgent = () => {
    if (!onAsk || !selectedRow) {
      return
    }

    const { quote: qq, series: ss } = selectedRow

    const facts = [
      `${ss.name} (${ss.symbol})`,
      qq?.value != null ? `last ${fmtNum(qq.value, ss.unit)}${qq.currency ? ` ${qq.currency}` : ''}` : '',
      qq?.changePct != null ? `${fmtPct(qq.changePct)} today` : ''
    ]
      .filter(Boolean)
      .join(', ')

    onAsk(`Give me a brief, current read on ${facts}. What's notable, what's driving it, and what should I watch?`)
    setFlash('asked agent')
  }

  const navVersion = (delta: number) => {
    if (!openModelId || versionCount <= 1) {
      return
    }

    const cur = openVersion ?? versionCount
    const target = Math.max(1, Math.min(versionCount, cur + delta))

    if (target !== cur) {
      loadModel(openModelId, target)
    }
  }

  useInput((ch, key) => {
    if (modal) {
      return
    }

    // While the `/` filter bar is focused, keystrokes edit the query. Filtering
    // is live; Enter drops focus so ↑↓ navigate matches, Esc clears + closes.
    if (searchMode) {
      if (key.escape) {
        setSearchMode(false)
        setSearchInput('')

        return
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

    // While the model chat is open it captures input FIRST (so single-letter
    // shortcuts can be typed into the message). Tab toggles focus between the
    // composer and the presentation reader so the left pane stays scrollable;
    // the mouse wheel always scrolls the reader regardless of focus.
    if (mode === 'models' && chatOpen) {
      if (key.tab) {
        return setChatFocus(f => (f === 'input' ? 'reader' : 'input'))
      }

      if (key.escape) {
        setChatFocus('input')

        return setChatOpen(false)
      }

      // Wheel scrolls the reader from either focus (single-line composer has no
      // use for it).
      if (key.wheelUp) {
        return presScrollRef.current?.scrollBy?.(-2)
      }

      if (key.wheelDown) {
        return presScrollRef.current?.scrollBy?.(2)
      }

      if (chatFocus === 'reader') {
        // Reader focus: scroll the presentation; Enter/printable jumps back to the
        // composer so typing is never "stuck".
        if (key.upArrow || ch === 'k') {
          return presScrollRef.current?.scrollBy?.(-2)
        }

        if (key.downArrow || ch === 'j') {
          return presScrollRef.current?.scrollBy?.(2)
        }

        if (key.pageUp) {
          return presScrollRef.current?.scrollBy?.(-(10))
        }

        if (key.pageDown) {
          return presScrollRef.current?.scrollBy?.(10)
        }

        if (ch === 'g') {
          return presScrollRef.current?.scrollTo?.(0)
        }

        if (ch === 'G') {
          return presScrollRef.current?.scrollToBottom?.()
        }

        if (key.return) {
          return setChatFocus('input')
        }

        return
      }

      // Composer focus: type the message.
      if (key.return) {
        return sendChat()
      }

      if (key.backspace || key.delete) {
        return setChatInput(s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setChatInput(s => s + printable)
        }
      }

      return
    }

    // `m` toggles Data | Models; `h` opens Help — both available everywhere.
    if (ch === 'm') {
      setSel(0)
      setModelSel(0)

      return setMode(p => (p === 'data' ? 'models' : 'data'))
    }

    if (ch === 'h') {
      return setModal('help')
    }

    if (mode === 'models') {
      // (Chat-open input is captured at the top of useInput, before shortcuts.)
      // An open presentation.
      if (openModelId) {
        if (key.escape || ch === 'q') {
          setOpenModelId(null)
          setPresentation(null)

          return
        }

        if (ch === 'c') {
          setChatFocus('input')

          return setChatOpen(true)
        }

        if (ch === 'w') {
          setFlash('rewriting…')
          gw?.request('markets.model.renarrate', { id: openModelId })
            .then(() => loadModel(openModelId))
            .catch(() => setFlash('rewrite failed'))

          return
        }

        if (ch === 'e') {
          gw?.request('markets.model.export', { id: openModelId })
            .then(raw => {
              const r = asRpcResult<{ path?: string }>(raw)
              setFlash(r?.path ? `exported → ${r.path}` : 'export failed')
            })
            .catch(() => setFlash('export failed'))

          return
        }

        if (ch === 'F') {
          gw?.request('markets.model.to_forecast', { id: openModelId })
            .then(() => setFlash('forecast seed created'))
            .catch(() => setFlash('failed'))

          return
        }

        if (ch === 'R') {
          return retryModel(openModelId)
        }

        if (key.leftArrow) {
          return navVersion(-1)
        }

        if (key.rightArrow) {
          return navVersion(1)
        }

        if (key.upArrow || ch === 'k' || key.wheelUp) {
          return presScrollRef.current?.scrollBy?.(-2)
        }

        if (key.downArrow || ch === 'j' || key.wheelDown) {
          return presScrollRef.current?.scrollBy?.(2)
        }

        return
      }

      // The models list.
      if (key.escape || ch === 'q') {
        return onClose()
      }

      if (ch === 'n') {
        return setModal('newModel')
      }

      if (ch === 'r') {
        setFlash('refreshing…')

        return refreshModels()
      }

      if (ch === 'R') {
        const m = models[modelSel]

        if (m) {
          return retryModel(m.id)
        }

        return
      }

      if (key.return) {
        const m = models[modelSel]

        if (m) {
          return loadModel(m.id)
        }

        return
      }

      if (ch === 'x') {
        const m = models[modelSel]

        if (m && gw) {
          gw.request('markets.model.delete', { id: m.id }).then(() => refreshModels()).catch(() => undefined)
          setFlash(`deleted ${m.title}`)
        }

        return
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return setModelSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return setModelSel(i => Math.min(Math.max(0, models.length - 1), i + 1))
      }

      return
    }

    // ── Data mode ──────────────────────────────────────────────────────────
    if (ch === 'q' || key.escape) {
      // Esc backs out of an active `/` filter first, then leaves the view.
      if (key.escape && searchActive) {
        setSearchInput('')

        return
      }

      return onClose()
    }

    if (ch === 'a') {
      return askAgent()
    }

    if (ch === 'd') {
      return setModal('providers')
    }

    if (ch === '/') {
      setSearchMode(true)
      setSel(0)

      return
    }

    if (ch === 'r') {
      setFlash('refreshing…')

      return void refresh(true)
    }

    // `o` cycles the sort column (header order → unsorted); `O` toggles asc/desc.
    if (ch === 'o') {
      return onSortCycle()
    }

    if (ch === 'O') {
      return onSortToggle()
    }

    if (key.return && selectedRow?.series.provider === 'yahoo') {
      if (openExternalUrl(`https://finance.yahoo.com/quote/${encodeURIComponent(selectedRow.series.symbol)}`)) {
        setFlash('opened in browser')
      }

      return
    }

    if (key.tab || key.rightArrow) {
      setSel(0)

      return setActive(i => (i + 1) % Math.max(1, categories.length))
    }

    if (key.leftArrow) {
      setSel(0)

      return setActive(i => (i - 1 + Math.max(1, categories.length)) % Math.max(1, categories.length))
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, sortedRows.length - 1), i + 1))
    }
  }, { isActive: !globalModal })

  const width = Math.max(40, cols - 4)
  const hasContent = providers.size > 0 || watchlist.length > 0
  const contentHeight = Math.max(8, termRows - 8)

  // Header is a single row: title · Data|Models toggle (m) · status · key-warning.
  // Folding the mode toggle here (rather than its own strip) keeps the footer on
  // screen.
  const header = (
    <Box flexShrink={0} marginBottom={1}>
      {searchMode || searchActive ? (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            MARKETS
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          <Text color={t.color.primary}>{'⌕ '}</Text>
          <Text color={t.color.text}>{searchInput}</Text>
          {searchMode ? (
            <Text color={t.color.primary} inverse>
              {' '}
            </Text>
          ) : null}
          <Text color={t.color.muted}>
            {`   ${searchActive ? `${visibleRows.length} matches · ` : ''}${searchMode ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
          </Text>
        </Text>
      ) : (
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          MARKETS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text bold={mode === 'data'} color={mode === 'data' ? t.color.primary : t.color.muted}>
          {mode === 'data' ? '[Data]' : 'Data'}
        </Text>
        <Text color={t.color.muted}>{'  '}</Text>
        <Text bold={mode === 'models'} color={mode === 'models' ? t.color.primary : t.color.muted}>
          {mode === 'models' ? '[Models]' : 'Models'}
        </Text>
        <Text color={t.color.muted}>{'   ·   '}</Text>
        <Text color={fetching ? sem.star : hasContent ? sem.up : sem.subtle}>
          {statusGlyph(fetching ? 'busy' : hasContent ? 'live' : 'idle', tick)}
        </Text>
        {mode === 'models' ? (
          <Text color={t.color.muted}> {`${models.length} model${models.length === 1 ? '' : 's'}${buildingCount ? ` · ${buildingCount} building` : ''}`}</Text>
        ) : (
          <>
            <Text color={t.color.muted}> {fetching ? 'updating…' : hasContent ? 'live quotes' : 'no providers'} · </Text>
            <Text color={t.color.text}>
              {hasContent ? `${config.providers.length} providers · ${watchlist.length} watched` : 'press a to add data'}
            </Text>
          </>
        )}
        {providersMissingKey.length ? (
          <Text color={sem.star}>
            {'   [!] '}
            <Text color={t.color.muted}>press </Text>
            <Text color={sem.star}>h</Text>
          </Text>
        ) : null}
      </Text>
      )}
    </Box>
  )

  // Empty (Data mode only): no providers and no watchlist. The modal (when set)
  // paints ABOVE this body as an absolute overlay, so the guard intentionally no
  // longer hides the empty body.
  const isEmpty = mode === 'data' && !hasContent

  const emptyBody = isEmpty ? (
    <Box alignItems="center" flexGrow={1} justifyContent="center">
      <Box flexDirection="column" width={Math.min(74, width)}>
        <Text bold color={t.color.text}>
          Build your market tape.
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            Enable data providers (Yahoo, Frankfurter, CoinGecko and FRED need no key; BLS optional; BEA uses a
            free key) and pick categories — or search for any ticker and add it to your watchlist.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text bold color={t.color.accent}>
            Press d
          </Text>
          <Text color={t.color.text}> to add providers · </Text>
          <Text bold color={t.color.accent}>
            /
          </Text>
          <Text color={t.color.text}> to search for a ticker.</Text>
        </Box>
      </Box>
    </Box>
  ) : null

  // The four modals paint THROUGH the shared overlay, stacked as the LAST child of
  // the view root so the body stays mounted beneath them (deskView pattern).
  const helpItems: InfoItem[] = [
    { detail: 'Two modes: Data (live quotes by category) and Models (agentic quant-research). Press m to switch.', label: 'Markets', tone: 'info' },
    { detail: 'Define a quant question (n). The desk researches data + the web, computes a real model, and presents findings. Open one to read it; c to chat/refine; w to rewrite the writeup on fresh data; e to export the data as JSON; ←/→ for versions; F to spin off a Desk forecast.', label: 'Market Models', tone: 'info' },
    ...infoItems,
  ]

  const modalOverlay =
    modal === 'providers' ? (
      <AddProviderModal
        cols={cols}
        initial={config}
        onCancel={() => setModal('')}
        onSaved={onProvidersSaved}
        onSearchSymbols={() => setModal('search')}
        rows={termRows}
        t={t}
      />
    ) : modal === 'help' ? (
      <InfoModal
        cols={cols}
        items={helpItems}
        onClose={() => setModal('')}
        rows={termRows}
        subtitle="What this view does, the keys, and how to fix anything that's blank."
        t={t}
        title="Markets · Help"
      />
    ) : modal === 'newModel' ? (
      <NewModelModal
        cols={cols}
        initialAsset={mode === 'data' ? selectedRow?.series.symbol ?? '' : ''}
        onCancel={() => setModal('')}
        onSubmit={submitNewModel}
        rows={termRows}
        t={t}
      />
    ) : modal === 'search' ? (
      <MarketSearchModal
        cols={cols}
        isAdded={isAdded}
        isWatched={isWatched}
        onClose={() => setModal('providers')}
        onToggleCategory={toggleCategory}
        onToggleWatch={toggleWatch}
        rows={termRows}
        t={t}
      />
    ) : null

  const tabs = (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box>
        {categories.map((cat, i) => (
          <Box key={cat} onClick={() => { if (!modal && !globalModal) { setActive(i); setSel(0) } }}>
            {i > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
            <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
              {cat}
            </Text>
          </Box>
        ))}
      </Box>
    </NoSelect>
  )

  // ---- left: dense, selectable quote table -------------------------------
  // Reserve room for the table's core columns; only give the detail pane the
  // slack beyond that (capped), so a narrower terminal keeps NAME/LAST/CHG%.
  const detailWidth = Math.max(30, Math.min(44, width - 54))
  const tableWidth = Math.max(28, width - detailWidth - 2)
  const avail = Math.max(20, tableWidth - 2) // inside border + paddingRight
  const listRows = Math.max(3, contentHeight - 2)
  const listStart = Math.max(0, Math.min(clampedSel - Math.floor(listRows / 2), sortedRows.length - listRows))
  const windowed = sortedRows.slice(Math.max(0, listStart), Math.max(0, listStart) + listRows)

  const cellColor = (v: null | number | undefined): string => dirColor(sem, v)

  // Fixed columns packed from the left; the 1-month trend sparkline fills the
  // leftover width so each row saturates the pane (overflow clips the trend,
  // never the numbers, since the trend is last). CHG% leads with a ▲/▼ so
  // direction reads without colour too.
  const COLS: { align: 'left' | 'right'; key: string; label: string; w: number }[] = [
    { align: 'left', key: 'sym', label: 'SYMBOL', w: 9 },
    { align: 'left', key: 'name', label: 'NAME', w: 24 },
    { align: 'right', key: 'last', label: 'LAST', w: 12 },
    { align: 'right', key: 'chg', label: 'CHG', w: 11 },
    { align: 'right', key: 'pct', label: 'CHG%', w: 10 },
    { align: 'right', key: 'vol', label: 'VOL', w: 10 }
  ]

  // Keep columns by PRIORITY when the pane is tight (NAME/LAST/CHG% matter most),
  // but render them in display order. So a narrow table still shows the essentials
  // rather than just SYMBOL + LAST.
  const PRIORITY = ['name', 'last', 'pct', 'chg', 'sym', 'vol']
  const keep = new Set<string>()
  let usedW = 2 // marker

  for (const key of PRIORITY) {
    const c = COLS.find(col => col.key === key)

    if (c && usedW + c.w + 1 <= avail) {
      keep.add(key)
      usedW += c.w + 1
    }
  }

  const keptCols = COLS.filter(c => keep.has(c.key))

  const trendW = Math.max(0, avail - usedW)
  const showTrend = trendW >= 10

  const cellText = (key: string, q: MarketQuote | undefined, ser: MarketSeries): { color: string; text: string } => {
    switch (key) {
      case 'chg':
        return { color: cellColor(q?.change ?? null), text: q ? fmtSigned(q.change) : '—' }

      case 'last':
        return { color: t.color.text, text: fmtNum(q?.value, ser.unit) }

      case 'name':
        return { color: t.color.label, text: q?.name || ser.name || ser.symbol || '' }

      case 'pct':
        return { color: cellColor(q?.changePct ?? null), text: q ? `${dirGlyph(q.changePct)} ${fmtPct(q.changePct)}` : '—' }

      case 'sym':
        return { color: sem.subtle, text: ser.symbol }

      case 'vol':
        return { color: sem.subtle, text: q ? fmtVol(q.volume) : '—' }

      default:
        return { color: t.color.text, text: '' }
    }
  }

  const table = (
    <Box
      borderBottom={false}
      borderColor={t.color.border}
      borderLeft={false}
      borderStyle="single"
      borderTop={false}
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      overflow="hidden"
      paddingRight={1}
      width={tableWidth}
    >
      {/* The header row: each column label is a click target that sorts by it
          (gated while a modal covers the body). The active column shows a ▲/▼
          direction glyph and paints in accent; the rest stay the plain heading. */}
      <Box>
        <Text bold color={sem.heading}>{'  '}</Text>
        {keptCols.map(c => {
          const active = marketSort.state.key === c.key
          const ind = active ? ` ${sortIndicator(marketSort.state, c.key)}` : ''

          return (
            <Box key={c.key} onClick={!modal && !globalModal ? () => onSortByKey(c.key) : undefined}>
              <Text bold color={active ? t.color.accent : sem.heading}>
                {`${pad(`${c.label}${ind}`, c.w, c.align)} `}
              </Text>
            </Box>
          )
        })}
        {showTrend ? <Text bold color={sem.heading}>{pad('1MO', trendW, 'left')}</Text> : null}
      </Box>
      <Text color={sem.rule}>{'─'.repeat(avail)}</Text>
      <Box flexDirection="column">
        {sortedRows.length === 0 ? (
          <Text color={t.color.muted} wrap="wrap">
            {searchActive
              ? `No matches for “${searchActive}” in the loaded tape — press d to add data and pull in what you're looking for.`
              : fetching
                ? 'Fetching…'
                : `No ${activeCategory ?? ''} series. Press d to add data.`}
          </Text>
        ) : (
          windowed.map(({ quote, series }, i) => {
            const idx = listStart + i
            const on = idx === clampedSel
            const trend = showTrend && quote?.history ? sparkline(quote.history, trendW) : ''

            return (
              <Box key={`${series.provider}:${series.symbol}`} onClick={() => { if (!modal && !globalModal) { setSel(idx) } }} width="100%">
                <Text wrap="truncate-end">
                  <Text color={on ? sem.cursor : sem.faint}>{on ? '▸ ' : '  '}</Text>
                  {keptCols.map(c => {
                    const cell = cellText(c.key, quote, series)
                    const highlight = on && (c.key === 'name' || c.key === 'last')

                    return (
                      <Text bold={on && c.key === 'name'} color={highlight ? sem.selectionFg : cell.color} key={c.key}>
                        {`${pad(cell.text, c.w, c.align)} `}
                      </Text>
                    )
                  })}
                  {showTrend ? <Text color={dirColor(sem, quote?.changePct)}>{trend}</Text> : null}
                </Text>
              </Box>
            )
          })
        )}
      </Box>
    </Box>
  )

  // ---- right: security detail card ----------------------------------------
  const q = selectedRow?.quote
  const s = selectedRow?.series
  const chartW = Math.max(12, detailWidth - 2)
  const chart = q?.history ? blockChart(q.history, chartW, 7) : []
  const fromHigh = q?.value != null && q.week52High ? ((q.value - q.week52High) / q.week52High) * 100 : null
  const fromLow = q?.value != null && q.week52Low ? ((q.value - q.week52Low) / q.week52Low) * 100 : null
  const trendColor = dirColor(sem, q?.changePct)
  const colW = Math.max(10, Math.floor(detailWidth / 2) - 8)

  // If the selected series' provider needs (or benefits from) an API key that
  // isn't set, tell the user how to add it — otherwise the value is silently "—".
  const detailKeyHint = ((): null | { required: boolean; text: string } => {
    if (!s) {
      return null
    }

    const prov = providerByKey(s.provider)

    if (!prov?.keyEnv || getProviderKey(prov.keyEnv)) {
      return null
    }

    return prov.needsKey || prov.keyRecommended
      ? { required: true, text: `Needs an API key — run /api-key set ${prov.key}${prov.keyUrl ? ` (free: ${prov.keyUrl})` : ''}` }
      : { required: false, text: `No API key — /api-key set ${prov.key} raises rate limits${prov.keyUrl ? ` (free: ${prov.keyUrl})` : ''}` }
  })()

  const statRow = (l1: string, v1: string, l2: string, v2: string, c1?: string, c2?: string) => (
    <Text wrap="truncate-end">
      <Text color={sem.heading}>{l1.padEnd(8)}</Text>
      <Text color={c1 ?? t.color.text}>{v1.padEnd(colW)}</Text>
      <Text color={sem.heading}>{l2.padEnd(8)}</Text>
      <Text color={c2 ?? t.color.text}>{v2}</Text>
    </Text>
  )

  const detail = (
    <Box flexDirection="column" flexShrink={0} height={contentHeight} marginLeft={1} overflow="hidden" width={detailWidth}>
      {s ? (
        <Box flexDirection="column">
          <Text bold color={t.color.text} wrap="truncate-end">
            {q?.name || s.name}
          </Text>
          <Text color={sem.subtle} wrap="truncate-end">
            {s.symbol}
            {q?.exchange ? ` · ${q.exchange}` : ''} · {s.category}
            {q?.currency ? ` · ${q.currency}` : ''}
          </Text>

          <Box marginTop={1}>
            <Text bold color={t.color.text}>
              {fmtNum(q?.value ?? null, s.unit)}
            </Text>
            <Text color={dirColor(sem, q?.change)}>
              {'   '}
              {q ? `${dirGlyph(q.change)} ${fmtSigned(q.change)}  ${fmtPct(q.changePct)}` : '—'}
            </Text>
          </Box>

          {chart.length ? (
            <Box flexDirection="column" marginTop={1}>
              {chart.map((line, i) => (
                <Text color={trendColor} key={i}>
                  {line}
                </Text>
              ))}
              <Text color={sem.subtle}>1-month</Text>
            </Box>
          ) : null}

          <Box flexShrink={0} marginTop={1}>
            <Text color={sem.rule}>{'─'.repeat(chartW)}</Text>
          </Box>
          <Box flexDirection="column">
            {statRow('Last', fmtNum(q?.value ?? null, s.unit), 'Prev', fmtNum(q?.prevClose ?? null))}
            {statRow('Day Hi', fmtNum(q?.dayHigh ?? null), 'Day Lo', fmtNum(q?.dayLow ?? null))}
            {statRow('52w Hi', fmtNum(q?.week52High ?? null), '52w Lo', fmtNum(q?.week52Low ?? null))}
            {statRow(
              '% Hi',
              fromHigh != null ? fmtPct(fromHigh) : '—',
              '% Lo',
              fromLow != null ? fmtPct(fromLow) : '—',
              fromHigh != null ? cellColor(fromHigh) : undefined,
              fromLow != null ? cellColor(fromLow) : undefined
            )}
            {statRow('Volume', q ? fmtVol(q.volume) : '—', 'Updated', q ? relTime(q.asOf) : '—')}
          </Box>

          <Box flexShrink={0} marginTop={1}>
            <Text color={sem.subtle} wrap="truncate-end">
              {s.provider}
              {s.provider === 'yahoo' ? ' · ⏎ open on Yahoo Finance' : ''}
            </Text>
          </Box>

          {detailKeyHint ? (
            <Box flexShrink={0} marginTop={1}>
              <Text color={detailKeyHint.required ? sem.down : sem.subtle} wrap="wrap">
                {detailKeyHint.text}
              </Text>
            </Box>
          ) : null}
        </Box>
      ) : (
        <Text color={sem.subtle}>Select a row to see details.</Text>
      )}
    </Box>
  )

  const dataChips: FooterChip[] = [
    { k: '↑↓', label: 'Select' },
    { k: '⇥', label: 'Category', run: () => { setSel(0); setActive(i => (i + 1) % Math.max(1, categories.length)) } },
    { k: 'a', label: 'Ask agent', run: askAgent },
    { k: 'o', label: 'Sort', run: () => onSortCycle() },
    { k: 'm', label: 'Models', run: () => { setSel(0); setMode('models') } },
    { k: '/', label: 'Filter', run: () => { setSel(0); setSearchMode(true) } },
    { k: 'd', label: 'Add data', run: () => setModal('providers') },
    { k: 'h', label: 'Help', run: () => setModal('help') },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const modelsListChips: FooterChip[] = [
    { k: '↑↓', label: 'Select' },
    { k: '⏎', label: 'Open' },
    { k: 'n', label: 'New model', run: () => setModal('newModel') },
    { k: 'R', label: 'Retry', run: () => retryModel(models[modelSel]?.id ?? null) },
    { k: 'x', label: 'Delete' },
    { k: 'm', label: 'Data', run: () => setMode('data') },
    { k: 'h', label: 'Help', run: () => setModal('help') },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const modelOpenChips: FooterChip[] = [
    { k: 'c', label: 'Chat' },
    { k: 'w', label: 'Rewrite' },
    { k: 'R', label: 'Retry', run: () => retryModel(openModelId) },
    { k: 'e', label: 'Export' },
    { k: 'F', label: 'Forecast' },
    { k: '←→', label: 'Version' },
    { k: 'Esc', label: 'Back' }
  ]

  const emptyChips: FooterChip[] = [
    { k: 'd', label: 'Add data', run: () => setModal('providers') },
    { k: '/', label: 'Filter', run: () => { setSel(0); setSearchMode(true) } },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const chips = isEmpty ? emptyChips : mode === 'data' ? dataChips : openModelId ? modelOpenChips : modelsListChips

  // The FooterChips are the ONE canonical shortcuts row (the old always-on prose
  // duplicate below them was removed). The only surviving prose is a CONTEXTUAL
  // hint for the chat composer/reader — a mode whose keys (⏎ send, Tab focus,
  // scroll) the chips don't spell out — plus the transient flash. Every other
  // state is fully covered by the chips, so no second shortcuts row is drawn.
  const contextHint =
    openModelId && chatOpen
      ? chatFocus === 'input'
        ? '⏎ send · Tab focus reader · wheel scrolls · Esc close chat'
        : '↑↓/jk/PgUp/PgDn/g/G scroll · Tab focus chat · Esc close chat'
      : ''

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} disabled={!!modal || globalModal} t={t} />
      {flash || contextHint ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {flash ? <Text color={t.color.accent}>{`${flash}${contextHint ? ' · ' : ''}`}</Text> : null}
          {contextHint}
        </Text>
      ) : null}
    </Box>
  )

  const modelsBody =
    openModelId && presentation ? (
      <Box flexDirection="row" flexShrink={0} height={contentHeight}>
        <Box flexDirection="column" flexGrow={1} flexShrink={1}>
          <PresentationView
            height={contentHeight}
            now={tick}
            presentation={presentation}
            scrollRef={presScrollRef}
            t={t}
            versionLabel={versionCount > 1 ? `v${openVersion ?? versionCount}/${versionCount}` : undefined}
            width={chatOpen ? Math.floor(width * 0.6) : width}
          />
        </Box>
        {chatOpen ? (
          <Box flexShrink={0} height={contentHeight} marginLeft={2} width={Math.floor(width * 0.38)}>
            <ModelChat
              busy={chatBusy || jobActive(openModelId)}
              focused={chatFocus === 'input'}
              input={chatInput}
              messages={chatMessages}
              status={openModelId ? progress[openModelId] : ''}
              t={t}
              tick={tick}
              width={Math.floor(width * 0.38)}
            />
          </Box>
        ) : null}
      </Box>
    ) : openModelId ? (
      <Box alignItems="center" height={contentHeight} justifyContent="center">
        <Text color={t.color.muted}>
          {statusGlyph('busy', tick)} {progress[openModelId] || 'building the analysis…'}
        </Text>
      </Box>
    ) : (
      <ModelsList height={contentHeight} models={models} progressById={progress} sel={modelSel} t={t} tick={tick} width={width} />
    )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {isEmpty ? (
        emptyBody
      ) : mode === 'data' ? (
        <>
          {tabs}
          <Box flexDirection="row" flexShrink={0} height={contentHeight}>
            {table}
            {detail}
          </Box>
        </>
      ) : (
        modelsBody
      )}
      {footer}
      {/* The body stays mounted; the modal paints ABOVE it as an absolute overlay.
          Body clicks are gated while the modal is open (tab/row onClick early-
          return) so the still-visible tabs/rows can't leak interaction — the
          keyboard is already trapped by the `if (modal) return` in useInput. */}
      {modalOverlay}
    </Box>
  )
}
