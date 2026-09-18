import { useStore } from '@nanostores/react'
import { Box, NoSelect, type ScrollBoxHandle, Text, useStdout } from '@superforecasting/ink'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $marketJobs, pruneStaleMarketJobs, setMarketJob, STALE_MARKET_JOB_MS } from '../app/marketJobsStore.js'
import { $globalModal, openHelpOverlay, patchOverlayState } from '../app/overlayStore.js'
import { openForecastInterview } from '../app/overlayStore.js'
import type { MarketSeries } from '../content/marketProviders.js'
import type { GatewayClient } from '../gatewayClient.js'
import { catalogSeries, deskConfig, saveDeskFields } from '../lib/dataDesk.js'
import { deskViewCache } from '../lib/deskViewCache.js'
import { shareQuote } from '../lib/feedShare.js'
import { predictionForecastSeed, seriesForecastSeed } from '../lib/forecastSeeds.js'
import { type FieldSpec, rankItems } from '../lib/fuzzyRank.js'
import { statusGlyph } from '../lib/icons.js'
import { changeReference, displayedChange, formatMarketChange, lastMovement } from '../lib/marketChange.js'
import { fetchQuotes, type MarketQuote } from '../lib/marketFetch.js'
import { marketColumns, marketTopicWindow } from '../lib/marketLayout.js'
import { type MarketConfig, type QuoteCache, quoteKey } from '../lib/marketStore.js'
import { openQuickMessage } from '../lib/messagingState.js'
import { loadModelCatalog, saveModelCatalog } from '../lib/modelStore.js'
import { openExternalUrl } from '../lib/openExternalUrl.js'
import { venueLabel } from '../lib/pmData.js'
import { pmWindow } from '../lib/pmRows.js'
import {
  type MarketModelListItem,
  normalizeModelList,
  normalizePresentation,
  type Presentation
} from '../lib/presentation.js'
import { asRpcResult } from '../lib/rpc.js'
import { blockChart, sparkline } from '../lib/sparkline.js'
import { sortIndicator, sortRows, type SortValue, useTableSort } from '../lib/tableSort.js'
import { usePmSection } from '../lib/usePmSection.js'
import { useShareItem } from '../lib/useShareItem.js'
import { useViewInput } from '../lib/useViewInput.js'
import { dirColor, dirGlyph, pad, semantics } from '../lib/visualSemantics.js'
import type { DataEvents, MarketCatalogResponse, MarketProviderStatus } from '../protocol/generated.js'
import { WireEvent } from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { AddProviderModal } from './addProviderModal.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import { type InfoItem, InfoModal } from './infoModal.js'
import { MarketSearchModal } from './marketSearchModal.js'
import { type ChatMessage, ModelChat } from './modelChat.js'
import { ModelsList } from './modelsList.js'
import { NewModelModal, type NewModelParams } from './newModelModal.js'
import { PmFilterModal } from './pmFilterModal.js'
import { PredictionMarketDetail } from './predictionMarketDetail.js'
import { PredictionMarketsTable } from './predictionMarketsTable.js'
import { PresentationView } from './presentationView.js'

export const openMarketsView = () => patchOverlayState({ markets: true })
export const closeMarketsView = () => patchOverlayState({ markets: false })

// The Prediction Markets pseudo-category. It rides the Data-mode tab strip
// alongside the quote categories (Indices, FX, …) — NOT a separate mode — and
// its section renders PM-shaped rows + a PM detail pane in the same tape.
const PREDICTION = 'Prediction'

// Markets — a live tape backed by user-chosen providers, with a searchable
// universe and a rich per-line-item detail pane (sparkline + day/52-week ranges
// + heuristics). `d` adds providers/categories, `/` searches, `a` asks the agent.

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

const fmtSigned = formatMarketChange

const fmtPct = (v: null | number): string =>
  v === null ? '—' : Math.abs(v) < 0.01 ? `${formatMarketChange(v)}%` : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`

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
      return q ? displayedChange(q).change : null

    case 'last':
      return q?.value ?? null

    case 'name':
      return q?.name || s.name || s.symbol || ''

    case 'pct':
      return q ? displayedChange(q).percent : null

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

  const [standaloneCache] = useState(() => deskViewCache())
  const retained = gw ? deskViewCache(gw) : standaloneCache

  const [config, setConfig] = useState<MarketConfig>(() =>
    retained.marketDesk
      ? deskConfig(retained.marketDesk.catalog, retained.marketDesk.selection)
      : { categories: [], custom: [], providers: [], watchlist: [] }
  )

  const [desk, setDesk] = useState<MarketCatalogResponse | null>(retained.marketDesk ?? null)
  const eventCacheRef = useRef<Record<string, DataEvents>>(retained.events)
  const [providerStatus, setProviderStatus] = useState<Record<string, MarketProviderStatus>>(retained.statuses)
  const [active, setActive] = useState(0)
  const [sel, setSel] = useState(0)
  const [tick, setTick] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [modal, setModal] = useState<'' | 'info' | 'newModel' | 'pmFilter' | 'providers' | 'search'>('')
  const [flash, setFlash] = useState('')

  // INSTANT inline `/` filter over the loaded tape (separate from `d` Add data,
  // which adds new series). `searchMode` routes keystrokes to the bar; the
  // visible rows are derived + ranked. No modal, no network.
  const [searchMode, setSearchMode] = useState(false)
  const [searchInput, setSearchInput] = useState('')

  // ── Market Models mode ──────────────────────────────────────────────────
  // Two modes only — Prediction is a Data-mode tab (native, like Stocks/FX), not
  // a mode of its own.
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

  const cacheRef = useRef<QuoteCache>(retained.quotes)
  const [cacheVersion, setCacheVersion] = useState(0)
  const inflightRef = useRef(false)
  const refreshOwner = useRef<AbortController | null>(null)
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
  const pmEnabled = providers.has('predictionmarkets')

  useEffect(() => {
    let alive = true
    refreshOwner.current?.abort()
    refreshOwner.current = null
    inflightRef.current = false
    cacheRef.current = retained.quotes
    eventCacheRef.current = retained.events
    setDesk(retained.marketDesk ?? null)
    setConfig(
      retained.marketDesk
        ? deskConfig(retained.marketDesk.catalog, retained.marketDesk.selection)
        : { providers: [], categories: [], custom: [], watchlist: [] }
    )
    setProviderStatus(retained.statuses)

    if (!gw) {
      return
    }

    gw.request('market.catalog', {})
      .then(result => {
        if (!alive) {
          return
        }

        retained.marketDesk = result
        const next = deskConfig(result.catalog, result.selection)
        setDesk(result)
        setConfig(next)
      })
      .catch(() => {
        if (alive) {
          setFlash('Unable to load data settings. Reconnect and reopen Markets.')
        }
      })

    return () => {
      alive = false
    }
  }, [gw, retained])

  const searchableSeries = useMemo(() => (desk ? catalogSeries(desk.catalog) : []), [desk])

  const infoItems = useMemo<InfoItem[]>(
    () =>
      (desk?.catalog.providers ?? [])
        .filter(
          provider =>
            config.providers.includes(provider.id) &&
            provider.auth === 'required' &&
            !desk?.configured_providers.includes(provider.id)
        )
        .map(provider => ({
          detail: `Open Add data → Sources to connect ${provider.name}. ${provider.access_note}`,
          label: `${provider.name}: ${provider.auth === 'required' ? 'credentials required' : 'optional connection'}`,
          tone: 'warn' as const
        }))
        .concat(
          Object.values(providerStatus)
            .filter(
              status => config.providers.includes(status.provider) && !['ready', 'refreshing'].includes(status.status)
            )
            .map(status => ({
              label: `${status.provider}: ${status.status.replaceAll('_', ' ')}`,
              detail: status.message ?? 'Try refreshing this source.',
              tone: 'warn' as const
            }))
        ),
    [desk, config.providers, providerStatus]
  )

  const dataWarnings = infoItems

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
        setVersionCount(
          Array.isArray((packet as Record<string, unknown>).versions)
            ? ((packet as Record<string, unknown>).versions as unknown[]).length
            : (pres?.version ?? 0)
        )

        const msgs = Array.isArray((packet as Record<string, unknown>).messages)
          ? ((packet as Record<string, unknown>).messages as Record<string, unknown>[])
          : []

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

    gw.on(WireEvent.MARKETS_MODEL_PROGRESS, onProgress)
    gw.on(WireEvent.MARKETS_MODEL_COMPLETE, onComplete)
    gw.on(WireEvent.MARKETS_MODEL_REFRESHED, onRefreshed)
    gw.on(WireEvent.MARKETS_MODEL_ERROR, onError)

    return () => {
      gw.off?.(WireEvent.MARKETS_MODEL_PROGRESS, onProgress)
      gw.off?.(WireEvent.MARKETS_MODEL_COMPLETE, onComplete)
      gw.off?.(WireEvent.MARKETS_MODEL_REFRESHED, onRefreshed)
      gw.off?.(WireEvent.MARKETS_MODEL_ERROR, onError)
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

  // Tabs: a Watchlist tab (if any), the selected provider categories, then the
  // Prediction section (last) when the predictionmarkets provider is enabled.
  const categories = useMemo(() => {
    const base = config.categories

    return [...(watchlist.length ? [WATCHLIST] : []), ...base, ...(pmEnabled ? [PREDICTION] : [])]
  }, [config, watchlist, pmEnabled])

  const activeCategory = categories[Math.min(active, Math.max(0, categories.length - 1))]
  const pmTabActive = mode === 'data' && activeCategory === PREDICTION

  // The Prediction section's data + row model + key handler. Always called
  // (hooks rule); it no-ops until its tab is active. It rides the parent's
  // single useInput + `/` filter, so the focus trap holds across PM rows too.
  const pm = usePmSection(gw, pmTabActive, searchInput, setFlash)

  // First-open PM fetch (no items yet) drives the header spinner + "loading
  // venues…" line so the tape never flashes "0 events" before the venues land.
  const pmBusy = pmTabActive && pm.loading && pm.itemsCount === 0

  // The index the Prediction tab occupies for a given category set. It is always
  // appended LAST (after the optional Watchlist tab + the enabled quote
  // categories), so enabling the provider never shifts it — the index computed
  // from the CURRENT categories is already correct, no post-enable render hop.
  const predictionTabIndex = (cats: string[]) => (watchlist.length ? 1 : 0) + cats.length

  // Jump to (and, if needed, enable) the Prediction section. `p` from any mode,
  // and the add-data flow when the provider is newly turned on.
  const jumpToPrediction = () => {
    setSel(0)
    setMode('data')

    if (!pmEnabled) {
      persist({ ...config, providers: [...config.providers, 'predictionmarkets'] })
    }

    setActive(predictionTabIndex(config.categories))
  }

  const seriesFor = (category: string | undefined): MarketSeries[] => {
    if (!category) {
      return []
    }

    if (category === WATCHLIST) {
      return watchlist
    }

    // Curated provider series + the user's own additions in this category.
    return dedupeSeries([
      ...(config.catalogSeries ?? []).filter(s => providers.has(s.provider) && s.category === category),
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
        ...(config.catalogSeries ?? []).filter(s => providers.has(s.provider) && config.categories.includes(s.category))
      ]),
    [watchlist, custom, providers, config]
  )

  // A broad desk must not fetch every annual country series at startup.
  // Topic navigation warms just that topic; already loaded values stay cached.
  const refreshSeries = dedupeSeries([...allSeries.filter(s => s.category === activeCategory), ...watchlist])

  const refresh = async (force: boolean) => {
    if (inflightRef.current || refreshSeries.length === 0) {
      return
    }

    const targets = force
      ? refreshSeries
      : refreshSeries.filter(s => {
          if (s.kind === 'event' && s.catalog_id) {
            const events = eventCacheRef.current[s.catalog_id]

            return !events || Date.now() - Date.parse(events.retrieved_at) > (s.refresh_seconds ?? 300) * 1000
          }

          const q = cacheRef.current[quoteKey(s.provider, s.symbol)]

          return !q?.retrieved_at || Date.now() - Date.parse(q.retrieved_at) > (q.refresh_seconds ?? 60) * 1000
        })

    if (targets.length === 0) {
      return
    }

    const controller = new AbortController()
    refreshOwner.current = controller
    inflightRef.current = true

    if (aliveRef.current) {
      setFetching(true)
    }

    await fetchQuotes(targets, {
      // Requests belong to this view/backend generation. Late replies cannot
      // populate a different connection's display or selection.
      gw,
      signal: controller.signal,
      serverSide: config.serverSide,
      onEvents: data => {
        eventCacheRef.current[data.series_id] = data

        if (aliveRef.current) {
          setCacheVersion(value => value + 1)
        }
      },
      onStatus: statuses => {
        if (aliveRef.current) {
          setProviderStatus(current => ({
            ...current,
            ...Object.fromEntries(statuses.map(status => [status.provider, status]))
          }))
        }
      },
      onBatch: quotes => {
        for (const q of quotes) {
          cacheRef.current[quoteKey(q.provider, q.symbol)] = q
        }

        if (aliveRef.current) {
          setCacheVersion(v => v + 1)
        }
      }
    })

    if (refreshOwner.current !== controller || controller.signal.aborted) {
      return
    }

    refreshOwner.current = null
    inflightRef.current = false

    if (aliveRef.current) {
      setFetching(false)
    }
  }

  useEffect(() => {
    void refresh(false)

    const timer = setInterval(() => {
      void refresh(false)
    }, 30_000)

    return () => {
      clearInterval(timer)
      refreshOwner.current?.abort()
      refreshOwner.current = null
      inflightRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, gw, activeCategory])

  const persist = (next: MarketConfig) => {
    if (!gw || !desk || !config.revision) {
      return setFlash('Data settings are not loaded. Reopen Markets to retry.')
    }

    void saveDeskFields(gw, config, next)
      .then(setConfig)
      .catch(cause =>
        setFlash(cause instanceof Error ? cause.message : 'Could not save data settings. Reopen Markets and retry.')
      )
  }

  const onProvidersSaved = (next: MarketConfig) => {
    setModal('')
    setConfig(next)
    setActive(0)

    // Enabling the Prediction Markets entry in Add-data jumps straight to the
    // Prediction section of the Data tape — the operator's discovery path is the
    // provider list, and a saved provider that changed nothing visible would read
    // as a no-op. Landing on the section (once its tab exists) IS the feedback.
    const pmNewlyEnabled =
      next.providers.includes('predictionmarkets') && !config.providers.includes('predictionmarkets')

    if (pmNewlyEnabled) {
      setSel(0)
      setMode('data')
      // `next` may also have flipped on quote categories — land on the Prediction
      // tab, which the memo appends after them.
      setActive(predictionTabIndex(next.categories))

      return
    }

    setFlash('saved')
  }

  const withProvider = (key: string): string[] => (providers.has(key) ? config.providers : [...config.providers, key])

  const isAdded = (s: MarketSeries): boolean => custom.some(c => sameSeries(c, s))
  const isWatched = (s: MarketSeries): boolean => watchlist.some(w => sameSeries(w, s))

  // Default add: put the item in its own category (and surface that category +
  // its provider so it shows + fetches).
  const toggleCategory = (s: MarketSeries) => {
    const exists = isAdded(s)
    const nextCustom = exists ? custom.filter(c => !sameSeries(c, s)) : [...custom, s]

    const nextCategories =
      exists || config.categories.includes(s.category) ? config.categories : [...config.categories, s.category]

    persist({
      ...config,
      categories: nextCategories,
      custom: nextCustom,
      providers: exists ? config.providers : withProvider(s.provider)
    })
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

    return rows
      .filter(r => rankOf.has(r.series))
      .sort((a, b) => (rankOf.get(a.series) ?? 0) - (rankOf.get(b.series) ?? 0))
  }, [rows, searchActive])

  // Column sort (`o` cycles, `O` toggles, header click sorts). Composes ON TOP of
  // the `/` filter: sort the already-filtered `visibleRows`. Default = unsorted →
  // the loaded tape order is preserved.
  const hasVolume = visibleRows.some(row => row.quote?.volume != null && Number.isFinite(row.quote.volume))
  const sortKeys = useMemo(() => MARKET_SORT_KEYS.filter(key => key !== 'vol' || hasVolume), [hasVolume])
  const marketSort = useTableSort(sortKeys)

  const sortedRows = useMemo(
    () => sortRows(visibleRows, marketSort.state.key, marketSort.state.dir, marketSortValue),
    [visibleRows, marketSort.state.key, marketSort.state.dir]
  )

  const clampedSel = Math.min(sel, Math.max(0, sortedRows.length - 1))
  const selectedRow = sortedRows[clampedSel]

  const forecastSelected = () => {
    if (!gw) {
      setFlash('Connect the gateway before creating a forecast')

      return
    }

    try {
      if (pmTabActive) {
        const row = pm.rows[pm.clampedSel]

        if (row) {openForecastInterview({ seed: predictionForecastSeed(row) })}
      } else if (selectedRow) {
        openForecastInterview({ seed: seriesForecastSeed(selectedRow.series, selectedRow.quote ?? undefined) })
      }
    } catch (cause) {
      setFlash(cause instanceof Error ? cause.message : String(cause))
    }
  }

  // Keep the SELECTED tape row selected across a re-sort (track by provider:symbol,
  // not index): a sort action stashes the current key, and once the re-sorted order
  // lands we move the cursor to wherever that row now sits. A filter/quote update
  // leaves the ref null, so it never fights the existing cursor logic.
  const pendingReselect = useRef<null | string>(null)
  useEffect(() => {
    const key = pendingReselect.current

    if (key == null) {
      return
    }

    pendingReselect.current = null
    const idx = sortedRows.findIndex(r => quoteKey(r.series.provider, r.series.symbol) === key)

    if (idx >= 0) {
      setSel(idx)
    }
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
      qq?.changePct != null ? `${fmtPct(qq.changePct)} vs prior reference` : ''
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

  const handleFooterKey = useViewInput(
    (ch, key) => {
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
            return presScrollRef.current?.scrollBy?.(-10)
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

      // `p` jumps to the Prediction section (enabling the provider if it's off);
      // `M` toggles Data | Models; `h` opens the unified Help modal (consistent on
      // every view); `i` opens the Data-warnings modal (the header [!] detail) —
      // all available in every mode.
      if (ch === 'p') {
        return jumpToPrediction()
      }

      if (ch === 'm') {
        return openQuickMessage()
      }

      if (ch === 'M') {
        setSel(0)
        setModelSel(0)

        return setMode(prev => (prev === 'models' ? 'data' : 'models'))
      }

      if (ch === 'h' || ch === '?') {
        return openHelpOverlay()
      }

      if (ch === 'i') {
        return setModal('info')
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
            gw.request('markets.model.delete', { id: m.id })
              .then(() => refreshModels())
              .catch(() => undefined)
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
      // On the Prediction tab, the section owns its keys (open / expand / venue /
      // range / sort / select). It returns false for the shared keys (q/Esc, d,
      // /, m, h, Tab) so they still fall through to the handlers below.
      if (ch === 'F') {
        forecastSelected()

        return
      }

      if (pmTabActive && pm.handleKey(ch, key)) {
        return
      }

      // `f` opens the structured PM filter (the section owns it; the quote tape has
      // no equivalent). Trapped here so it never leaks into a category switch.
      if (pmTabActive && ch === 'f') {
        return setModal('pmFilter')
      }

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

      if (key.return && selectedRow?.series.kind === 'event') {
        const entry = desk?.catalog.series.find(entry => entry.id === selectedRow.series.catalog_id)

        if (entry) {
          openExternalUrl(entry.source_url)
        }

        return
      }

      if (key.return && selectedRow?.series.provider === 'yahoo') {
        if (openExternalUrl(`https://finance.yahoo.com/quote/${encodeURIComponent(selectedRow.series.symbol)}`)) {
          setFlash('opened in browser')
        }

        return
      }

      if ((key.tab && !key.shift) || key.rightArrow) {
        setSel(0)

        return setActive(i => (i + 1) % Math.max(1, categories.length))
      }

      if (key.leftArrow || (key.tab && key.shift)) {
        setSel(0)

        return setActive(i => (i - 1 + Math.max(1, categories.length)) % Math.max(1, categories.length))
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return setSel(i => Math.max(0, i - 1))
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return setSel(i => Math.min(Math.max(0, sortedRows.length - 1), i + 1))
      }
    },
    { isActive: !globalModal }
  )

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
            {`   ${searchActive ? `${pmTabActive ? pm.matchCount : visibleRows.length} matches${pmTabActive && pm.searching ? ' · ⌕ searching venues…' : ''} · ` : ''}${searchMode ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
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
          <Text color={fetching || pmBusy ? sem.star : hasContent ? sem.up : sem.subtle}>
            {statusGlyph(fetching || pmBusy ? 'busy' : hasContent ? 'live' : 'idle', tick)}
          </Text>
          {mode === 'models' ? (
            <Text color={t.color.muted}>
              {' '}
              {`${models.length} model${models.length === 1 ? '' : 's'}${buildingCount ? ` · ${buildingCount} building` : ''}`}
            </Text>
          ) : pmTabActive ? (
            pm.loading && pm.itemsCount === 0 ? (
              // First open: an honest spinner + "loading venues…" instead of a
              // "0 events" flash before the first list fetch lands.
              <Text color={t.color.muted}>{` ${statusGlyph('busy', tick)} loading venues…`}</Text>
            ) : (
              <Text color={t.color.muted}>
                {` Polymarket + Kalshi · ${pm.itemsCount} shown${pm.catalog?.ready ? ` · ${pm.catalog.events} indexed` : pm.catalog?.refreshing ? ' · ◌ indexing catalogs' : ''}${pm.stale ? ' · ◌ refreshing' : pm.streaming ? ' · ● live' : ''}`}
                {pm.filterActive ? (
                  <Text
                    color={t.color.muted}
                  >{`  ·  ${pm.filterSummary} · ${pm.filteredCount} of ${pm.itemsCount} shown`}</Text>
                ) : null}
              </Text>
            )
          ) : (
            <>
              <Text color={t.color.muted}>
                {' '}
                {fetching ? 'updating…' : hasContent ? 'latest data' : 'no providers'} ·{' '}
              </Text>
              <Text color={t.color.text}>
                {hasContent
                  ? `${config.providers.length} providers · ${watchlist.length} watched`
                  : 'press d to add data'}
              </Text>
            </>
          )}
          {dataWarnings.length ? (
            <Text color={sem.star}>
              {'   [!] '}
              <Text color={t.color.muted}>press </Text>
              <Text color={sem.star}>i · Data status</Text>
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
          Build your global data desk.
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            Load the global starter set or browse individual series by topic and region. Starting empty is fine — your
            selection will stay empty until you add data.
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text wrap="wrap">
            <Text bold color={t.color.accent}>
              Press d
            </Text>{' '}
            to search data or load a starter set.{' '}
            <Text bold color={t.color.accent}>
              /
            </Text>{' '}
            filters the current topic.
          </Text>
        </Box>
      </Box>
    </Box>
  ) : null

  // The modals paint THROUGH the shared overlay, stacked as the LAST child of the
  // view root so the body stays mounted beneath them (deskView pattern). The old
  // `h` help modal folded into the unified Help overlay (its prose now lives in
  // the Markets guide); `i` keeps the dynamic Data-warnings surface behind [!].
  const modalOverlay =
    modal === 'providers' ? (
      <AddProviderModal
        cols={cols}
        gw={gw}
        initial={config}
        onCancel={() => setModal('')}
        onSaved={onProvidersSaved}
        onSearchSymbols={() => setModal('search')}
        rows={termRows}
        sessionId={sessionId}
        t={t}
      />
    ) : modal === 'info' ? (
      <InfoModal
        cols={cols}
        items={infoItems}
        onClose={() => setModal('')}
        rows={termRows}
        subtitle="Blank series usually mean a missing API key. Press h for the full Markets guide + shortcuts."
        t={t}
        title="Markets · Data warnings"
      />
    ) : modal === 'newModel' ? (
      <NewModelModal
        cols={cols}
        initialAsset={mode === 'data' ? (selectedRow?.series.symbol ?? '') : ''}
        onCancel={() => setModal('')}
        onSubmit={submitNewModel}
        rows={termRows}
        t={t}
      />
    ) : modal === 'search' ? (
      <MarketSearchModal
        catalog={searchableSeries}
        cols={cols}
        gw={gw}
        isAdded={isAdded}
        isWatched={isWatched}
        onClose={() => setModal('providers')}
        onToggleCategory={toggleCategory}
        onToggleWatch={toggleWatch}
        rows={termRows}
        t={t}
      />
    ) : modal === 'pmFilter' ? (
      <PmFilterModal
        cols={cols}
        filter={pm.filter}
        onApply={next => {
          pm.setFilter(next)
          setModal('')
        }}
        onCancel={() => setModal('')}
        rows={termRows}
        t={t}
      />
    ) : null

  const topicWindow = marketTopicWindow(categories, active, Math.max(12, width - 22))
  const tabStart = topicWindow.start
  const visibleTabs = categories.slice(tabStart, topicWindow.end)

  const tabs = (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box>
        <Text color={t.color.muted}>{categories.length ? `${active + 1}/${categories.length}  ` : ''}</Text>
        {visibleTabs.map((cat, offset) => {
          const i = tabStart + offset

          return (
            <Box
              key={cat}
              onClick={() => {
                if (!modal && !globalModal) {
                  setActive(i)
                  setSel(0)
                }
              }}
            >
              {offset > 0 ? <Text color={t.color.border}>{'  ·  '}</Text> : null}
              <Text bold={i === active} color={i === active ? t.color.accent : t.color.muted}>
                {cat}
              </Text>
            </Box>
          )
        })}
        {visibleTabs.length < categories.length ? <Text color={t.color.muted}> ← → Topics</Text> : null}
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

  const { columns: keptCols, trendWidth: trendW } = marketColumns(avail, hasVolume)
  const showTrend = trendW > 0

  const cellText = (key: string, q: MarketQuote | undefined, ser: MarketSeries): { color: string; text: string } => {
    const display = q ? displayedChange(q) : null

    switch (key) {
      case 'chg':
        return {
          color: cellColor(display?.change ?? null),
          text: display ? `${fmtSigned(display.change)}${display.historical ? '*' : ''}` : '—'
        }
      case 'last': {
        const events = ser.catalog_id ? eventCacheRef.current[ser.catalog_id] : undefined

        return {
          color: t.color.text,
          text:
            ser.kind === 'event'
              ? events
                ? `${events.truncated ? '≥' : ''}${events.events.length} alerts`
                : '—'
              : fmtNum(q?.value, ser.unit)
        }
      }

      case 'name':
        return { color: t.color.label, text: q?.name || ser.name || ser.symbol || '' }

      case 'pct':
        return {
          color: cellColor(display?.percent ?? null),
          text: display
            ? `${dirGlyph(display.percent)} ${fmtPct(display.percent)}${display.historical ? '*' : ''}`
            : '—'
        }

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
        <Text bold color={sem.heading}>
          {'  '}
        </Text>
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
        {showTrend ? (
          <Text bold color={sem.heading}>
            {pad('TREND', trendW, 'left')}
          </Text>
        ) : null}
      </Box>
      <Text color={sem.subtle} wrap="truncate-end">
        {sortedRows.some(row => row.quote && displayedChange(row.quote).historical)
          ? 'CHG: prior period · * last observed move'
          : 'CHG: prior available period'}
      </Text>
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
            const trend = pad(showTrend && quote?.history ? sparkline(quote.history, trendW) : '', trendW, 'left')

            return (
              <Box
                key={`${series.provider}:${series.symbol}`}
                onClick={() => {
                  if (!modal && !globalModal) {
                    setSel(idx)
                  }
                }}
                width="100%"
              >
                {/* Full-row selection highlight (desk-view parity across the whole
                    Data tape): the background IS the cursor. */}
                <Text backgroundColor={on ? t.color.selectionBg : undefined} wrap="truncate-end">
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
  const feedShare = useMemo(() => (q && !pmTabActive ? shareQuote(q) : null), [q, pmTabActive])
  useShareItem(
    pmTabActive ? pm.detailItem?.event.title || '' : q?.name || q?.symbol || '',
    pmTabActive
      ? `Prediction market · ${pm.detailItem?.event.title || ''}\n${pm.detailItem?.event.url || ''}`
      : q
        ? `${q.value ?? 'Unavailable'} ${q.unit || ''} · CHG ${q.change ?? 'unavailable'} · ${q.provider} · observed ${q.asOf ? new Date(q.asOf).toISOString() : 'unknown'}`
        : '',
    feedShare
  )
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

    const provider = desk?.catalog.providers.find(provider => provider.id === s.provider)

    if (!provider?.key_env || desk?.configured_providers.includes(provider.id)) {
      return null
    }

    return {
      required: provider.auth === 'required',
      text: `${provider.auth === 'required' ? 'Requires a connection' : 'Optional connection available'} — open Add data → Sources → ${provider.name}`
    }
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
    <Box
      flexDirection="column"
      flexShrink={0}
      height={contentHeight}
      marginLeft={1}
      overflow="hidden"
      width={detailWidth}
    >
      {s?.kind === 'event' ? (
        <Box flexDirection="column">
          <Text bold color={t.color.text}>
            {s.name}
          </Text>
          <Text color={sem.subtle}>Official alerts · Enter opens the source</Text>
          {(eventCacheRef.current[s.catalog_id ?? '']?.events ?? [])
            .slice(0, Math.max(1, Math.floor((contentHeight - 3) / 4)))
            .map(event => (
              <Box flexDirection="column" key={event.event_id} marginTop={1}>
                <Text bold color={sem.heading} wrap="truncate-end">
                  {event.severity ?? 'Alert'} · {event.title}
                </Text>
                <Text wrap="truncate-end">{event.area}</Text>
                <Text color={sem.subtle} wrap="truncate-end">
                  Expires {event.expires_at ?? 'not supplied'}
                </Text>
              </Box>
            ))}
          {eventCacheRef.current[s.catalog_id ?? '']?.events.length === 0 ? (
            <Text>No active alerts returned.</Text>
          ) : null}
        </Box>
      ) : s ? (
        <Box flexDirection="column" flexShrink={0}>
          <Text bold color={t.color.text} wrap="truncate-end">
            {q?.name || s.name}
          </Text>
          <Text color={sem.subtle} wrap="truncate-end">
            {s.symbol}
            {q?.exchange ? ` · ${q.exchange}` : ''} · {s.category}
            {q?.currency ? ` · ${q.currency}` : ''}
          </Text>

          {providerStatus[s.provider]?.message ? (
            <Text color={sem.subtle} wrap="wrap">
              {providerStatus[s.provider].message} · r Retry · d Sources
            </Text>
          ) : q?.value == null ? (
            <Text color={sem.subtle}>
              {fetching
                ? 'Retrieving source data…'
                : 'No measurement returned. Press r to retry or d for source access.'}
            </Text>
          ) : null}
          <Box marginTop={1}>
            <Text bold color={t.color.text}>
              {fmtNum(q?.value ?? null, s.unit)}
            </Text>
            <Text color={dirColor(sem, q?.change)}>
              {'   '}
              {q ? `${dirGlyph(q.change)} ${fmtSigned(q.change)}  ${fmtPct(q.changePct)}` : '—'}
            </Text>
          </Box>

          {q ? (
            <Text color={sem.subtle} wrap="wrap">
              {changeReference(q)}
            </Text>
          ) : null}

          {q && lastMovement(q) ? (
            <Text color={sem.subtle} wrap="wrap">
              {lastMovement(q)}
            </Text>
          ) : null}

          {chart.length ? (
            <Box flexDirection="column" marginTop={1}>
              {chart.map((line, i) => (
                <Text color={trendColor} key={i}>
                  {line}
                </Text>
              ))}
              <Text color={sem.subtle}>
                {q?.dated_history?.length
                  ? `${q.dated_history[0]?.period_start} → ${q.dated_history.at(-1)?.period_end}`
                  : 'Recent available values'}
              </Text>
            </Box>
          ) : null}

          <Box flexShrink={0} marginTop={1}>
            <Text color={sem.rule}>{'─'.repeat(chartW)}</Text>
          </Box>
          <Box flexDirection="column">
            {!q?.kind || q.kind === 'quote' ? (
              <>
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
                {statRow('Volume', q ? fmtVol(q.volume) : '—', 'As of', q ? relTime(q.asOf) : '—')}
              </>
            ) : null}
            {q?.kind && q.kind !== 'quote' ? (
              <>
                <Text color={sem.subtle}>
                  {q.kind} · revision: {q.revision_policy ?? 'unknown'}
                </Text>
                {q.valid_from ? (
                  <Text color={sem.subtle}>
                    Valid: {q.valid_from} → {q.valid_until ?? 'unknown'}
                  </Text>
                ) : null}
                <Text color={sem.subtle}>
                  {q.kind === 'forecast'
                    ? `Issued: ${q.issue_time ?? 'not supplied'}`
                    : `Published: ${q.published_at ?? 'not supplied'}`}
                </Text>
              </>
            ) : null}
            {q?.retrieved_at ? <Text color={sem.subtle}>Retrieved {relTime(Date.parse(q.retrieved_at))}</Text> : null}
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

  // ── the Prediction section (Data-mode tab): PM-shaped table + detail, rendered
  // in place of the quote table/detail when the Prediction tab is active. Its own
  // layout budget (a slightly wider detail pane for the book + distribution). ──
  const pmDetailWidth = Math.max(34, Math.min(48, width - 52))
  const pmTableWidth = Math.max(30, width - pmDetailWidth - 2)
  const pmAvail = Math.max(24, pmTableWidth - 2)
  const pmListRows = Math.max(3, contentHeight - 2)
  // Variable-height windowing: an expanded outcome's first sub-row draws an extra
  // header line, so a naive row-count window let the cursor walk off the clipped
  // viewport. pmWindow scrolls in visual-line space and keeps the selection on
  // screen (headline OR sub-row) every frame.
  const pmWin = pmWindow(pm.rows, pm.clampedSel, pmListRows)
  const pmListStart = pmWin.start
  const pmWindowed = pm.rows.slice(pmWin.start, pmWin.end)

  const pmEmptyText = pm.loading
    ? 'Loading prediction markets…'
    : pm.error
      ? `Prediction-market load failed: ${pm.error}. Press r to retry.`
      : searchActive
        ? `No markets match “${searchInput}”.`
        : gw
          ? 'No open markets right now. Press r to refresh or v to switch venue.'
          : 'Prediction markets need the gateway. Polymarket + Kalshi headlines and books load read-only, no key. Press v to filter venue.'

  const pmTable = (
    <PredictionMarketsTable
      active={!modal && !globalModal}
      avail={pmAvail}
      clampedSel={pm.clampedSel}
      discoveredKeys={pm.discoveredKeys}
      emptyText={pmEmptyText}
      expanded={pm.expanded}
      height={contentHeight}
      listStart={pmListStart}
      livePrices={pm.livePrices}
      onSelect={idx => pm.setSel(() => idx)}
      onSortByKey={pm.sortByKey}
      rowsLength={pm.rowCount}
      sem={sem}
      sortState={pm.sortState}
      t={t}
      tableWidth={pmTableWidth}
      windowed={pmWindowed}
    />
  )

  const pmDetail = (
    <PredictionMarketDetail
      book={pm.book}
      bookLabel={pm.activeOutcome?.label ?? '—'}
      history={pm.history}
      historyRange={pm.historyRange}
      item={pm.detailItem}
      keyHint={pm.keyHint}
      selectedMarketId={pm.activeOutcome?.market_id ?? null}
      streaming={pm.streaming}
      t={t}
      width={pmDetailWidth}
    />
  )

  const dataChips: FooterChip[] = [
    { k: 'F', label: 'Forecast', run: forecastSelected },
    { k: '↑↓', label: 'Select' },
    {
      k: '⇥',
      label: 'Category',
      run: () => {
        setSel(0)
        setActive(i => (i + 1) % Math.max(1, categories.length))
      }
    },
    { k: 'a', label: 'Ask agent', run: askAgent },
    { k: 'o', label: 'Sort', run: () => onSortCycle() },
    {
      k: 'M',
      label: 'Models',
      run: () => {
        setSel(0)
        setMode('models')
      }
    },
    {
      k: '/',
      label: 'Filter',
      run: () => {
        setSel(0)
        setSearchMode(true)
      }
    },
    { k: 'd', label: 'Add data', run: () => setModal('providers') },
    ...(infoItems.length ? [{ k: 'i', label: 'Warnings', run: () => setModal('info') }] : []),
    { k: 'h', label: 'Help', run: openHelpOverlay },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const modelsListChips: FooterChip[] = [
    { k: '↑↓', label: 'Select' },
    { k: '⏎', label: 'Open' },
    { k: 'n', label: 'New model', run: () => setModal('newModel') },
    { k: 'R', label: 'Retry', run: () => retryModel(models[modelSel]?.id ?? null) },
    { k: 'x', label: 'Delete' },
    { k: 'M', label: 'Data', run: () => setMode('data') },
    ...(infoItems.length ? [{ k: 'i', label: 'Warnings', run: () => setModal('info') }] : []),
    { k: 'h', label: 'Help', run: openHelpOverlay },
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
    {
      k: '/',
      label: 'Filter',
      run: () => {
        setSel(0)
        setSearchMode(true)
      }
    },
    { k: 'h', label: 'Help', run: openHelpOverlay },
    { k: 'q', label: 'Close', run: onClose }
  ]

  // The Prediction section's own chip row (it owns venue/range/expand where the
  // quote tape has none), still sharing Filter / Models / Help / Close.
  const pmChips: FooterChip[] = [
    { k: 'F', label: 'Forecast', run: forecastSelected },
    { k: '↑↓', label: 'Select' },
    { k: '←→/Tab', label: 'Topics' },
    { k: 'Space', label: 'Expand' },
    { k: '⏎', label: 'Open', run: pm.openMarket },
    { k: 'v', label: `Venue: ${pm.venue === 'all' ? 'All' : venueLabel(pm.venue)}`, run: pm.cycleVenue },
    { k: 'o', label: 'Sort', run: pm.cycleSort },
    { k: 'f', label: pm.filterActive ? 'Filter ●' : 'Filter', run: () => setModal('pmFilter') },
    // Live-keys-only: the Remove chip appears ONLY when the cursor is on a saved
    // (+) discovered row — nothing to remove on a browse row.
    ...(pm.selectedIsDiscovered ? [{ k: 'x', label: 'Remove', run: pm.removeDiscovered }] : []),
    {
      k: '/',
      label: 'Search',
      run: () => {
        pm.setSel(() => 0)
        setSearchMode(true)
      }
    },
    {
      k: 'M',
      label: 'Models',
      run: () => {
        setSel(0)
        setMode('models')
      }
    },
    ...(infoItems.length ? [{ k: 'i', label: 'Warnings', run: () => setModal('info') }] : []),
    { k: 'h', label: 'Help', run: openHelpOverlay },
    { k: 'q', label: 'Close', run: onClose }
  ]

  const chips = isEmpty
    ? emptyChips
    : mode === 'data'
      ? pmTabActive
        ? pmChips
        : dataChips
      : openModelId
        ? modelOpenChips
        : modelsListChips

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
      : pmTabActive
        ? pm.streamNote
        : ''

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} disabled={!!modal || globalModal} onKey={handleFooterKey} t={t} />
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
      <ModelsList
        height={contentHeight}
        models={models}
        progressById={progress}
        sel={modelSel}
        t={t}
        tick={tick}
        width={width}
      />
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
            {pmTabActive ? pmTable : table}
            {pmTabActive ? pmDetail : detail}
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
