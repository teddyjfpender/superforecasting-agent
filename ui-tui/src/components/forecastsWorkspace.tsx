import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { forecastQuestionDetailSections } from '../app/forecastPanel.js'
import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastAnalystNote,
  ForecastFactor,
  ForecastFactorConstituent,
  ForecastQuestionPacket,
  ForecastQuestionPacketResponse,
  ForecastRelated,
  ForecastTailAudit,
  ForecastTailOutcome,
  ForecastThesis,
  ForecastThesisComponent,
  ForecastThesisEntity,
  ForecastThesisTrigger,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspacePanelEstimate,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'
import {
  bandChart,
  type BandPoint,
  boxWhisker,
  clamp01,
  compactNumber,
  deltaGlyph,
  dotTrack,
  histogram,
  type HistogramBar,
  levelSparkline,
  pct,
  pctDelta,
  shortDate,
  timeAxis,
  wrapLines
} from '../lib/forecastCharts.js'
import {
  looksLikeMarketSource,
  nullModelLine,
  outcomeSeverity,
  packetTailAudit,
  tailAuditChip,
  tailAuditFails,
  tailPct,
  type TailSeverity,
  unearnedHeadline
} from '../lib/forecastTail.js'
import { type FieldSpec, filterRanked, rankItems } from '../lib/fuzzyRank.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'
import type { PanelSection } from '../types.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { windowItems } from './overlayControls.js'

export const openForecastsWorkspace = (initialId: string | null = null) =>
  patchOverlayState({ forecasts: true, forecastsInitialId: initialId })

export const closeForecastsWorkspace = () =>
  patchOverlayState({ forecasts: false, forecastsInitialId: null })

const WIDE_COLS = 100

// Packet sections rendered under the visual summary. Intentionally excludes the
// header facts (question/Current Forecast/Ledger State), Recent Evidence, and
// Resolution — ForecastDetail already shows those — so the tail is purely the
// long-form content the desk view omits.
const TAIL_SECTION_TITLES = new Set<string>([
  'Forecast History',
  'Assumptions And References',
  'Model Runs',
  'Actions'
])

interface ForecastsWorkspaceProps {
  gw: GatewayClient
  initialId?: null | string
  onClose: () => void
  t: Theme
}

// One row of the navigable left column: the ALL lens-clear row, one row per
// thesis (the lens filter), then the (lens-filtered) forecast rows below. A
// single cursor walks all three kinds.
type LeftRow =
  | { kind: 'all' }
  | { kind: 'thesis'; thesis: ForecastThesis }
  | { factor: ForecastFactor; kind: 'factor' }
  | { item: ForecastWorkspaceItem; kind: 'forecast' }

export const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// Distribution values (μ, σ, median, CI bounds, Δμ) are abbreviated with
// k/M/B/T so a Bitcoin mean reads "73k", not "73000", and the master-list and
// detail values stay short. Percentages and small values pass through unchanged.
export const trimNum = (value: number): string => compactNumber(value)

export const unitSuffix = (units: null | string | undefined): string => {
  const u = (units ?? '').toLowerCase()

  if (u.includes('percent') || u.includes('%')) {
    return '%'
  }

  return ''
}

/**
 * Headline label for a forecast.
 *   probability/categorical → a percent ("59%")
 *   distribution            → a continuous summary ("μ 4.23% · σ 0.10")
 * so a CPI mean never renders as a misleading "310%" or a raw JSON dump.
 */
export const headlineLabel = (item: ForecastWorkspaceItem): string => {
  const dist = item.distribution

  if (item.headline_kind === 'distribution' && dist && finite(dist.mean)) {
    const suffix = unitSuffix(item.units)
    const parts = [`μ ${trimNum(dist.mean)}${suffix}`]

    if (finite(dist.sd)) {
      parts.push(`σ ${trimNum(dist.sd)}`)
    }

    return parts.join(' · ')
  }

  const headline = item.headline_probability

  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline)
  }

  if (finite(headline)) {
    return item.probability_display ?? String(headline)
  }

  return item.probability_display ?? '—'
}

/** Compact one-token headline for the master list (e.g. "59%" or "μ4.23%"). */
export const headlineCompact = (item: ForecastWorkspaceItem, probDigits = 0): string => {
  if (item.headline_kind === 'distribution' && item.distribution && finite(item.distribution.mean)) {
    return `μ${trimNum(item.distribution.mean)}${unitSuffix(item.units)}`
  }

  const headline = item.headline_probability

  if (finite(headline) && headline >= 0 && headline <= 1) {
    return pct(headline, probDigits)
  }

  return finite(headline) ? String(headline) : '—'
}

/** Delta in headline units: percent-points for probabilities, outcome units (Δμ) for distributions. */
export const deltaLabel = (item: ForecastWorkspaceItem): string => {
  const d = item.delta

  if (!finite(d) || Math.abs(d) < (item.headline_kind === 'distribution' ? 1e-6 : 0.005)) {
    return '· flat'
  }

  if (item.headline_kind === 'distribution') {
    return `${deltaGlyph(d)} Δμ ${d > 0 ? '+' : ''}${trimNum(d)}${unitSuffix(item.units)}`
  }

  return pctDelta(d)
}

export const truncate = (value: string, max: number): string =>
  value.length <= max ? value : `${value.slice(0, Math.max(0, max - 1))}…`

// Field weights for the desk `/` filter: title dominates, then domain/topics,
// then the id. Shared between the boolean test and the ranked list below so they
// always agree on what matches.
const FORECAST_SEARCH_FIELDS: FieldSpec<ForecastWorkspaceItem>[] = [
  { get: i => i.title, weight: 1 },
  { get: i => i.domain, weight: 0.6 },
  { get: i => i.topics, weight: 0.5 },
  { get: i => i.id, weight: 0.3 }
]

export const matchesFilter = (item: ForecastWorkspaceItem, query: string): boolean =>
  !query.trim() || rankItems([item], query, FORECAST_SEARCH_FIELDS).length > 0

/** Categorical / bucket distribution → sorted bars; null for scalar or mean/sd shapes. */
/** Per-candidate interval lookup that tolerates case/whitespace divergence between the
 * share keys and the interval keys (the scorer + commit hook normalize candidate keys,
 * so the dashboard must too — else an interval silently drops). */
export const intervalForLabel = (
  intervals: ForecastWorkspaceItem['candidate_intervals'] | undefined,
  label: string
): { hi: number; lo: number } | null => {
  if (!intervals) return null
  if (intervals[label]) return intervals[label]
  const norm = label.trim().toLowerCase()
  for (const key of Object.keys(intervals)) {
    if (key.trim().toLowerCase() === norm) return intervals[key]
  }
  return null
}

export const distributionBars = (
  probability: ForecastWorkspaceItem['probability'],
  intervals?: ForecastWorkspaceItem['candidate_intervals']
): HistogramBar[] | null => {
  if (!probability || typeof probability !== 'object' || Array.isArray(probability)) {
    return null
  }

  const entries = Object.entries(probability).filter(([, value]) => finite(value)) as [string, number][]

  // Drop distribution-summary fields (mean / median / sd / quantiles / intervals) so a
  // HYBRID payload (candidate shares + a bolted-on leader distribution, e.g. from a
  // vote-share repair) renders ONLY the candidate bars — never q05 / q25 / interval_*
  // as spurious "candidates". Candidate labels are kept; stat keys are filtered.
  const distributionalKeys = new Set([
    'mean', 'mu', 'sd', 'sigma', 'std', 'stdev', 'variance', 'expected', 'value',
    'median', 'mode', 'lower', 'upper', 'low', 'high', 'min', 'max',
  ])
  const isStatKey = (key: string): boolean => {
    const k = key.toLowerCase()
    return distributionalKeys.has(k) || /^[qp]\d/.test(k) || k.startsWith('ci') || k.startsWith('interval')
  }

  const bars = entries.filter(([key]) => !isStatKey(key))

  if (bars.length < 2) {
    return null
  }

  return bars
    .map(([label, value]) => ({ label, value, interval: intervalForLabel(intervals, label) }))
    .sort((a, b) => b.value - a.value)
}

/** Confidence/spread band for one history point. Latest point prefers the panel spread. */
const bandForPoint = (
  isLatest: boolean,
  panel: ForecastWorkspacePanel | null | undefined
): { hi?: number; lo?: number } => {
  if (isLatest && panel?.spread && finite(panel.spread.min) && finite(panel.spread.max)) {
    return { hi: panel.spread.max, lo: panel.spread.min }
  }

  // Never SYNTHESIZE a band from `confidence`. The old `clamp01(1 - confidence) * K`
  // fallback assumed a 0-1 probability scale, so on a vote-share point (e.g. 44.7 on a
  // 0-100 axis) it clamped to ~[0,1] and rendered the band detached at the bottom of
  // the chart — disconnected from the point. A forecast's band must come from its OWN
  // interval (distribution ci90) or a real panel spread; otherwise show no band.
  return {}
}

export const historyToBandPoints = (item: ForecastWorkspaceItem): BandPoint[] => {
  const history = item.history ?? []
  const isDistribution = item.headline_kind === 'distribution'

  return history.map((point, index) => {
    const y = point.headline_probability

    if (!finite(y)) {
      return { y: null }
    }

    // Distribution snapshots carry their own 90% interval (in outcome units);
    // use it directly and never the panel's probability spread.
    if (finite(point.band_low) && finite(point.band_high)) {
      return { hi: point.band_high, lo: point.band_low, y }
    }

    const isLatest = index === history.length - 1

    const band = bandForPoint(!isDistribution && isLatest, isDistribution ? null : item.panel)

    return { hi: band.hi ?? null, lo: band.lo ?? null, y }
  })
}

const MIN_CHART_SPAN = 0.12

/**
 * Auto-zoom the y-axis to the data + band range so small probability moves and
 * the confidence band are actually visible (a fixed 0..1 axis squashes a
 * 0.49→0.58 series into one row). A minimum span stops a flat series from
 * exploding into noise; probability series stay clamped to [0,1]; the axis
 * labels report the real bounds so the zoom is honest.
 */
export const chartScale = (points: BandPoint[]): { yMax: number; yMin: number } => {
  const values: number[] = []

  for (const point of points) {
    if (finite(point.y)) {
      values.push(point.y)
    }

    if (finite(point.lo)) {
      values.push(point.lo)
    }

    if (finite(point.hi)) {
      values.push(point.hi)
    }
  }

  if (!values.length) {
    return { yMax: 1, yMin: 0 }
  }

  const probabilityLike = values.every(value => value >= 0 && value <= 1)
  let lo = Math.min(...values)
  let hi = Math.max(...values)

  if (hi - lo < MIN_CHART_SPAN) {
    const mid = (lo + hi) / 2
    lo = mid - MIN_CHART_SPAN / 2
    hi = mid + MIN_CHART_SPAN / 2
  }

  const pad = (hi - lo) * 0.15
  lo -= pad
  hi += pad

  if (probabilityLike) {
    lo = Math.max(0, lo)
    hi = Math.min(1, hi)
  }

  if (hi - lo < 1e-6) {
    hi = lo + 1
  }

  return { yMax: hi, yMin: lo }
}

// ── Panel / ensemble spread fallback (from the forecast.question packet) ─────

const probabilityLike = (value: unknown): value is number => finite(value) && value >= 0 && value <= 1

/**
 * Ensemble components dict → panel-style estimates. Mirrors the ledger's
 * `_ensemble_component_rows`: either `{components: [{name, probability,
 * weight}, …]}` or a plain `{name: probability|{probability, weight}}` map.
 */
const ensembleEstimates = (components: Record<string, unknown> | null | undefined): ForecastWorkspacePanelEstimate[] => {
  if (!components || typeof components !== 'object') {
    return []
  }

  const rawRows: Record<string, unknown>[] = Array.isArray(components.components)
    ? (components.components.filter(row => row && typeof row === 'object') as Record<string, unknown>[])
    : Object.entries(components).map(([name, value]) =>
        value && typeof value === 'object' && !Array.isArray(value)
          ? { name, ...(value as Record<string, unknown>) }
          : { name, probability: value }
      )

  const estimates: ForecastWorkspacePanelEstimate[] = []

  rawRows.forEach((row, index) => {
    const probability = row.probability

    if (!probabilityLike(probability)) {
      return
    }

    const weight = row.weight

    estimates.push({
      perspective: String(row.name ?? row.source ?? `component_${index + 1}`),
      probability,
      trimmed: false,
      weight: finite(weight) && weight >= 0 ? weight : 1
    })
  })

  return estimates
}

// One pooled ensemble component, with its source slug preserved (the panel-style
// `ensembleEstimates` above drops `source`; the detail pane needs it to flag a
// down-weighted market).
export interface EnsembleComponentRow {
  name: string
  probability: number
  source: null | string
  weight: number
}

/**
 * The current snapshot's pooled ensemble components as rows, preserving the
 * source slug. Mirrors the ledger's `_ensemble_component_rows`: either
 * `{components: [{name, probability, weight, source}, …]}` or a plain
 * `{name: probability|{probability, weight}}` map. Returns [] when the snapshot
 * carries no usable components.
 */
export const ensembleComponentRows = (
  packet: ForecastQuestionPacket | null | undefined
): EnsembleComponentRow[] => {
  const history = packet?.forecast_history ?? []
  const latest = history.length ? history[history.length - 1] : null
  const components = latest?.ensemble_components

  if (!components || typeof components !== 'object') {
    return []
  }

  const rawRows: Record<string, unknown>[] = Array.isArray(
    (components as { components?: unknown }).components
  )
    ? ((components as { components: unknown[] }).components.filter(
        row => row && typeof row === 'object'
      ) as Record<string, unknown>[])
    : Object.entries(components as Record<string, unknown>).map(([name, value]) =>
        value && typeof value === 'object' && !Array.isArray(value)
          ? { name, ...(value as Record<string, unknown>) }
          : { name, probability: value }
      )

  const rows: EnsembleComponentRow[] = []

  rawRows.forEach((raw, index) => {
    const probability = raw.probability

    if (!probabilityLike(probability)) {
      return
    }

    const weight = raw.weight
    const source = typeof raw.source === 'string' ? raw.source : null

    rows.push({
      name: String(raw.name ?? raw.source ?? `component_${index + 1}`),
      probability,
      source,
      weight: finite(weight) && weight >= 0 ? weight : 1
    })
  })

  return rows
}

/**
 * The panel-spread data for a question whose lighter workspace item carries no
 * `panel`: prefer the packet's latest recorded panel run; otherwise reconstruct
 * the spread from the current snapshot's ensemble components (method `panel`/
 * ensemble pools store their inputs there). Returns null when neither exists —
 * the detail pane simply omits the section, never fakes a spread.
 */
export const panelFromPacket = (packet: ForecastQuestionPacket | null | undefined): ForecastWorkspacePanel | null => {
  if (!packet) {
    return null
  }

  const run = packet.panel_runs?.[0]

  if (run && (run.estimates?.length || finite(run.aggregate_probability))) {
    return {
      aggregate_probability: run.aggregate_probability,
      aggregation_method: run.aggregation_method,
      created_at: run.created_at,
      estimates: run.estimates ?? [],
      id: run.id,
      kind: 'panel',
      spread: run.spread_summary ?? {},
      trim: run.trim
    }
  }

  const history = packet.forecast_history ?? []
  const latest = history[history.length - 1]

  if (!latest) {
    return null
  }

  const estimates = ensembleEstimates(latest.ensemble_components)

  if (estimates.length < 2) {
    return null
  }

  return {
    aggregate_probability: probabilityLike(latest.probability_or_distribution) ? latest.probability_or_distribution : null,
    aggregation_method: latest.method ?? 'ensemble',
    created_at: latest.as_of,
    estimates,
    kind: 'ensemble',
    spread: {},
    trim: 0
  }
}

export function ForecastsWorkspace({ gw, initialId = null, onClose, t }: ForecastsWorkspaceProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  // Hydrate from the last workspace payload so reopening the desk is instant
  // (it then refreshes in the background). The cache survives unmount.
  const cachedWs = getOverlayCache<ForecastWorkspaceResponse>('forecast.workspace')

  const [items, setItems] = useState<ForecastWorkspaceItem[]>(() => cachedWs?.forecasts ?? [])
  const [theses, setTheses] = useState<ForecastThesis[]>(() => cachedWs?.theses ?? [])
  const [factors, setFactors] = useState<ForecastFactor[]>(() => cachedWs?.factors ?? [])
  // The active thesis lens: null = ALL FORECASTS (no lens). When set to a thesis
  // id, the forecast rows in the left column are filtered to that thesis's
  // members and the right pane leads with the thesis read.
  const [lensId, setLensId] = useState<null | string>(null)
  // The active factor lens (mutually exclusive with the thesis lens): when set
  // to a factor id, the forecast rows collapse to that factor's constituent ids.
  const [factorLensId, setFactorLensId] = useState<null | string>(null)

  const [desk, setDesk] = useState<{ active: number; alerts: number; closing: number; generatedAt?: string }>(() =>
    cachedWs
      ? {
          active: cachedWs.active_count ?? (cachedWs.forecasts ?? []).length,
          alerts: cachedWs.open_alert_count ?? 0,
          closing: cachedWs.closing_soon_count ?? 0,
          generatedAt: cachedWs.generated_at
        }
      : { active: 0, alerts: 0, closing: 0 }
  )

  const [loading, setLoading] = useState(!cachedWs)
  const [error, setError] = useState<null | string>(null)
  const [cursor, setCursor] = useState(0)
  const [focus, setFocus] = useState<'detail' | 'list'>('list')
  const [query, setQuery] = useState('')
  const [filtering, setFiltering] = useState(false)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  // The "tail end" detail (forecast history, assumptions, model runs, the action
  // playbook) lives in the `forecast.question` packet, not the lighter
  // `forecast.workspace` item. Fetch it per-selection and render it under the
  // visual summary inside the detail pane's own ScrollBox.
  const [packet, setPacket] = useState<ForecastQuestionPacketResponse | null>(null)
  const [packetId, setPacketId] = useState<null | string>(null)
  const initialIdRef = useRef(initialId)
  const detailScrollRef = useRef<null | ScrollBoxHandle>(null)

  const wide = cols >= WIDE_COLS

  const load = (announce = false) => {
    setLoading(!cachedWs)
    // Load the FULL active book so the list + `/` filter cover every question
    // (a small cap silently drops the oldest forecasts once the book grows).
    gw.request<unknown>('forecast.workspace', { limit: 1000 })
      .then(raw => {
        const result = asRpcResult<ForecastWorkspaceResponse>(raw)

        if (!result) {
          setError('forecast.workspace returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('forecast.workspace', result)
        const forecasts = result.forecasts ?? []
        setItems(forecasts)
        setTheses(result.theses ?? [])
        setFactors(result.factors ?? [])
        setDesk({
          active: result.active_count ?? forecasts.length,
          alerts: result.open_alert_count ?? 0,
          closing: result.closing_soon_count ?? 0,
          generatedAt: result.generated_at
        })
        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
        // The cursor now indexes the union [ALL, …theses, …forecasts], so the
        // jump to an initial forecast id is resolved by the leftRows effect once
        // the rows are built — not by a raw forecasts[] index here.
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  useEffect(() => {
    // Drives OverlayScrollbar reflow detection while the user scrolls the
    // detail pane (the content height changes per selected forecast).
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    // Re-opening the workspace on a different forecast (e.g. `/forecast <id>`
    // while it is already open) must jump the cursor. useRef alone never sees
    // the prop change, so record the pending id here; the leftRows effect below
    // navigates to its row once the (lens-aware) union list is built.
    if (initialId) {
      initialIdRef.current = initialId
    }
  }, [initialId])

  // The active thesis (the lens). Members are the question ids in its components.
  const activeThesis = useMemo(
    () => (lensId ? (theses.find(thesis => thesis.id === lensId) ?? null) : null),
    [lensId, theses]
  )

  // The active factor (the lens). Members are the question ids in its
  // constituents. Mutually exclusive with the thesis lens.
  const activeFactor = useMemo(
    () => (factorLensId ? (factors.find(factor => factor.id === factorLensId) ?? null) : null),
    [factorLensId, factors]
  )

  // The forecast rows, filtered by the active lens (thesis members, factor
  // constituents) and the text query. With no lens active (ALL), every forecast
  // matching the query is shown — the prior behavior.
  const filtered = useMemo(() => {
    if (activeThesis) {
      // The full ecosystem (members + entity-weighted questions); fall back to the
      // health-driver members when question_ids isn't present.
      const ecosystem =
        activeThesis.question_ids ?? (activeThesis.components ?? []).map(component => component.id ?? '')

      const memberIds = new Set(ecosystem.filter((id): id is string => Boolean(id)))

      // Scope to the lens FIRST, then rank by relevance within it (an empty query
      // keeps the lens order). Ranking can't leak items from outside the lens.
      return filterRanked(items.filter(item => item.id != null && memberIds.has(item.id)), query, FORECAST_SEARCH_FIELDS)
    }

    if (activeFactor) {
      const ecosystem =
        activeFactor.question_ids ?? (activeFactor.constituents ?? []).map(constituent => constituent.id ?? '')

      const memberIds = new Set(ecosystem.filter((id): id is string => Boolean(id)))

      return filterRanked(items.filter(item => item.id != null && memberIds.has(item.id)), query, FORECAST_SEARCH_FIELDS)
    }

    return filterRanked(items, query, FORECAST_SEARCH_FIELDS)
  }, [items, query, activeThesis, activeFactor])

  // The single navigable column is the union of the lens filter rows (ALL +
  // every thesis + every factor) and the forecast rows below. One cursor walks
  // all of them: an ALL/thesis/factor row drives the lens + the thesis/factor
  // read; a forecast row drives the existing detail.
  const leftRows = useMemo<LeftRow[]>(() => {
    // Only surface the lens rows (ALL + each thesis + each factor) when at least
    // one thesis or factor exists; otherwise the column is exactly the prior
    // forecast book. Factor rows sit AFTER the thesis rows, BEFORE the book.
    const hasLens = theses.length > 0 || factors.length > 0

    const lensRows: LeftRow[] = hasLens
      ? [
          { kind: 'all' },
          ...theses.map((thesis): LeftRow => ({ kind: 'thesis', thesis })),
          ...factors.map((factor): LeftRow => ({ factor, kind: 'factor' }))
        ]
      : []

    return [...lensRows, ...filtered.map((item): LeftRow => ({ item, kind: 'forecast' }))]
  }, [theses, factors, filtered])

  // The index of the first forecast row in leftRows (after ALL + thesis +
  // factor rows). One ALL row + one row per thesis + one row per factor.
  const hasLens = theses.length > 0 || factors.length > 0
  const firstForecastRow = hasLens ? 1 + theses.length + factors.length : 0

  useEffect(() => {
    // Keep the cursor inside the (possibly filtered) union list.
    if (cursor > leftRows.length - 1) {
      setCursor(Math.max(0, leftRows.length - 1))
    }
  }, [cursor, leftRows.length])

  useEffect(() => {
    // Resolve a pending `/forecast <id>` jump against the union list. The target
    // is a forecast (question id), so search the forecast rows and park the
    // cursor on it. A thesis lens may hide it; clear the lens so it is visible.
    const pending = initialIdRef.current

    if (!pending) {
      return
    }

    const rowIndex = leftRows.findIndex(row => row.kind === 'forecast' && row.item.id === pending)

    if (rowIndex >= 0) {
      initialIdRef.current = null
      setCursor(rowIndex)
      setFocus('list')
    } else if ((lensId || factorLensId) && items.some(item => item.id === pending)) {
      // The forecast exists but is filtered out by the active lens — drop both
      // lenses so the next render rebuilds leftRows with the target visible.
      setLensId(null)
      setFactorLensId(null)
    }
  }, [leftRows, lensId, factorLensId, items])

  const currentRow = leftRows[cursor] ?? null
  const cursorThesis = currentRow?.kind === 'thesis' ? currentRow.thesis : null
  const cursorFactor = currentRow?.kind === 'factor' ? currentRow.factor : null
  const selected = currentRow?.kind === 'forecast' ? currentRow.item : null
  const selectedId = selected?.id ?? null

  // Reset the detail pane to the top whenever the SELECTED ENTITY changes —
  // keyed on identity, not the cursor index: lens toggles and list reorders
  // can put a different entity under the same index, which kept the previous
  // entity's scroll offset (detail "sometimes" opened mid-scroll).
  const detailIdentity =
    currentRow?.kind === 'forecast'
      ? currentRow.item.id
      : currentRow?.kind === 'thesis'
        ? `thesis:${currentRow.thesis.id}`
        : currentRow?.kind === 'factor'
          ? `factor:${currentRow.factor.id}`
          : (currentRow?.kind ?? null)

  // The detail packet (tail audit, ensemble, packet-tail sections) loads ASYNC
  // and grows the pane AFTER selection, so a one-shot reset on identity change
  // can fire before the tall content arrives and leave the question + header
  // scrolled out of view on a fast/cached load. Pin to top on identity change,
  // then re-pin once THIS entity's packet settles. Same-entity refreshes don't
  // reset (pinnedDetail already matches), so the user's scroll is preserved.
  const pinnedDetail = useRef<null | string>(null)

  useEffect(() => {
    detailScrollRef.current?.scrollTo(0)
    pinnedDetail.current = null
  }, [detailIdentity])

  useEffect(() => {
    if (detailIdentity && packetId === selectedId && pinnedDetail.current !== detailIdentity) {
      detailScrollRef.current?.scrollTo(0)
      pinnedDetail.current = detailIdentity
    }
  }, [detailIdentity, packetId, selectedId])

  useEffect(() => {
    if (!selectedId) {
      setPacket(null)
      setPacketId(null)

      return
    }

    // Race guard: if the cursor moves before this resolves, drop the stale
    // result so the tail never shows a previous forecast's history/evidence.
    let cancelled = false
    gw.request<unknown>('forecast.question', { id: selectedId })
      .then(raw => {
        if (cancelled) {
          return
        }

        const result = asRpcResult<ForecastQuestionPacketResponse>(raw)
        setPacket(result ?? null)
        setPacketId(result ? selectedId : null)
      })
      .catch(() => {
        if (cancelled) {
          return
        }

        setPacket(null)
        setPacketId(null)
      })

    return () => {
      cancelled = true
    }
  }, [selectedId, gw])

  // Only the sections the visual summary does NOT already cover — history,
  // assumptions/references, model runs, and the action playbook.
  const packetTail = useMemo(() => {
    if (!packet || packetId !== selectedId) {
      return null
    }

    return forecastQuestionDetailSections(packet).filter(
      section => section.title && TAIL_SECTION_TITLES.has(section.title)
    )
  }, [packet, packetId, selectedId])

  // The panel-spread fallback: when the lighter workspace item has no `panel`,
  // derive one from the packet (latest panel run, else the current snapshot's
  // ensemble components) so panel-method forecasts still show their spread.
  const packetPanel = useMemo(
    () => (packet && packetId === selectedId ? panelFromPacket(packet.packet) : null),
    [packet, packetId, selectedId]
  )

  // The current snapshot's tail audit (categorical only). Null on
  // binary/distribution questions and on older snapshots — the detail pane then
  // omits the Tail Audit section rather than fake a zero-mass audit.
  const tailAudit = useMemo(
    () => (packet && packetId === selectedId ? packetTailAudit(packet.packet) : null),
    [packet, packetId, selectedId]
  )

  // The current snapshot's pooled ensemble components (raw rows, so source slugs
  // and discounted weights survive). Null when the snapshot has no components.
  const ensembleRows = useMemo(
    () => (packet && packetId === selectedId ? ensembleComponentRows(packet.packet) : []),
    [packet, packetId, selectedId]
  )

  const tailLoading = !!selectedId && packetId !== selectedId

  // The analyst write-up time series (oldest-first). Driven by the SELECTED ITEM,
  // not the async forecast.question packet, so the quick read paints immediately
  // on selection change instead of blanking out (flashing) while the packet
  // fetch is in flight. The most recent note is the desk quick-read; the rest are
  // the reviewable log.
  const analystNotes = selected?.analyst_notes ?? []
  const latestNote = analystNotes.length ? analystNotes[analystNotes.length - 1] : null
  const priorNotes = analystNotes.slice(0, -1).reverse()

  const closeWith = () => {
    onClose()
  }

  const detailPageSize = Math.max(4, termRows - 12)

  useInput((ch, key) => {
    // Filter text-entry mode swallows printable keys.
    if (filtering) {
      if (key.return) {
        return setFiltering(false)
      }

      if (key.escape) {
        setQuery('')

        return setFiltering(false)
      }

      if (key.backspace || key.delete) {
        return setQuery(q => q.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta && ch.length === 1 && ch >= ' ') {
        return setQuery(q => q + ch)
      }

      return
    }

    if (ch === 'q') {
      return closeWith()
    }

    if (key.escape) {
      return focus === 'detail' ? setFocus('list') : closeWith()
    }

    if (ch === 'r') {
      return load(true)
    }

    if (ch === '/') {
      setQuery('')

      return setFiltering(true)
    }

    if (focus === 'detail') {
      if (key.leftArrow || ch === 'h') {
        return setFocus('list')
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return detailScrollRef.current?.scrollBy(-2)
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return detailScrollRef.current?.scrollBy(2)
      }

      if (key.pageUp || (key.ctrl && ch === 'u')) {
        return detailScrollRef.current?.scrollBy(-detailPageSize)
      }

      if (key.pageDown || (key.ctrl && ch === 'd')) {
        return detailScrollRef.current?.scrollBy(detailPageSize)
      }

      if (ch === 'g') {
        return detailScrollRef.current?.scrollTo(0)
      }

      if (ch === 'G') {
        return detailScrollRef.current?.scrollToBottom?.()
      }

      return
    }

    // List focus. The cursor walks the union [ALL, …theses, …factors, …forecasts].
    // → / l always jumps INTO the right pane to read + scroll it (the forecast
    // detail, or the thesis/factor read — both are scrollable). Enter is the
    // primary action: open a forecast, or DRILL a thesis/factor (collapse the
    // book to its members). The ALL row has no scrollable read, so both clear
    // the lens and jump to the first forecast.
    if (key.rightArrow || ch === 'l') {
      if (currentRow?.kind === 'all') {
        setLensId(null)
        setFactorLensId(null)

        return setCursor(firstForecastRow)
      }

      if (currentRow) {
        return setFocus('detail')
      }

      return
    }

    if (key.return) {
      if (currentRow?.kind === 'forecast') {
        return setFocus('detail')
      }

      if (currentRow?.kind === 'all') {
        // ALL FORECASTS row clears every lens. Park the cursor on the first
        // forecast row so the book is immediately scannable.
        setLensId(null)
        setFactorLensId(null)

        return setCursor(firstForecastRow)
      }

      if (currentRow?.kind === 'thesis' && currentRow.thesis.id) {
        // Activate this thesis as the lens: the forecast rows below collapse to
        // its members. Keep the cursor on the thesis row so its read stays up
        // and the user can arrow down into the members. Thesis + factor lenses
        // are mutually exclusive.
        setFactorLensId(null)

        return setLensId(currentRow.thesis.id)
      }

      if (currentRow?.kind === 'factor' && currentRow.factor.id) {
        // Activate this factor as the lens: the forecast rows below collapse to
        // its constituents. Keep the cursor on the factor row so its read stays
        // up and the user can arrow down into the constituents.
        setLensId(null)

        return setFactorLensId(currentRow.factor.id)
      }

      return
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setCursor(c => Math.max(0, c - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setCursor(c => Math.min(Math.max(0, leftRows.length - 1), c + 1))
    }

    if (ch === 'g') {
      return setCursor(0)
    }

    if (ch === 'G') {
      return setCursor(Math.max(0, leftRows.length - 1))
    }
  })

  // ── Header ──────────────────────────────────────────────────────────
  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          FORECASTS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={t.color.text}>{desk.active}</Text>
        <Text color={t.color.muted}> active · </Text>
        <Text color={desk.closing > 0 ? t.color.warn : t.color.label}>{desk.closing}</Text>
        <Text color={t.color.muted}> closing soon · </Text>
        <Text color={desk.alerts > 0 ? t.color.statusBad : t.color.label}>{desk.alerts}</Text>
        <Text color={t.color.muted}>
          {` open alert${desk.alerts === 1 ? '' : 's'}`}
          {desk.generatedAt ? ` · as of ${shortDate(desk.generatedAt)}` : ''}
        </Text>
      </Text>
    </Box>
  )

  // ── Body ────────────────────────────────────────────────────────────
  let body: ReactNode

  if (loading && !items.length) {
    body = (
      <Box flexGrow={1}>
        <Text color={t.color.muted}>Loading forecast desk…</Text>
      </Box>
    )
  } else if (error) {
    body = (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.error}>Failed to load forecasts: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (!filtered.length && !theses.length && !factors.length) {
    body = (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted}>
          {items.length ? `No forecasts match "${query}".` : 'No active forecasts. Create one with /forecast new …'}
        </Text>
      </Box>
    )
  } else {
    const listW = wide ? Math.max(34, Math.floor(cols * 0.4)) : cols - 2
    const detailW = wide ? cols - listW - 3 : cols - 2
    const visibleRows = Math.max(1, termRows - 11)

    const list = (
      <ForecastList
        cursor={cursor}
        factorLensId={factorLensId}
        focus={focus === 'list'}
        lensId={lensId}
        rows={leftRows}
        t={t}
        visibleRows={visibleRows}
        width={listW}
      />
    )

    // The right pane leads with the thesis read when the cursor is on a thesis
    // row, the existing forecast detail when on a forecast row, and a hint on the
    // ALL row.
    const thesisRead = cursorThesis ? (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={detailScrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <ThesisDeskRead t={t} thesis={cursorThesis} width={detailW} />
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={detailScrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    ) : null

    const factorRead = cursorFactor ? (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={detailScrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <FactorDeskRead factor={cursorFactor} t={t} width={detailW} />
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={detailScrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    ) : null

    const allHint =
      currentRow?.kind === 'all' ? (
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          <Text color={t.color.muted} wrap="wrap">
            {theses.length
              ? 'All forecasts. Pick a thesis above to filter the book to its members and read the thesis health.'
              : 'All forecasts.'}
          </Text>
        </Box>
      ) : null

    const detail = selected ? (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={detailScrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            <ForecastDetail
              afterChart={
                latestNote ? (
                  <>
                    <Rule t={t} width={detailW} />
                    <AnalystNote
                      note={latestNote}
                      showStance={selected.headline_kind !== 'distribution'}
                      t={t}
                      variant={latestNote.kind === 'retrospective' ? 'retrospective' : 'quickread'}
                      width={detailW}
                    />
                    <TailAuditChip audit={tailAudit} t={t} />
                    {selected.related?.informed_by?.length ? (
                      <WrapText color={t.color.muted} t={t}>
                        {`informed by ${selected.related.informed_by.length} related forecast${
                          selected.related.informed_by.length === 1 ? '' : 's'
                        }: ${selected.related.informed_by.join(', ')}`}
                      </WrapText>
                    ) : null}
                    <Rule t={t} width={detailW} />
                  </>
                ) : null
              }
              ensembleRows={ensembleRows}
              item={selected}
              packetPanel={packetPanel}
              t={t}
              tailAudit={tailAudit}
              width={detailW}
            />
            {packetTail && packetTail.length ? (
              <ForecastPacketTail sections={packetTail} t={t} width={detailW} />
            ) : tailLoading ? (
              <Box marginTop={1}>
                <Text color={t.color.muted}>loading detail…</Text>
              </Box>
            ) : null}
            <AnalystLog notes={priorNotes} t={t} />
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={detailScrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    ) : null

    // Cursor on a thesis row → thesis read; on a factor row → factor read; on a
    // forecast row → forecast detail; on the ALL row → a short hint.
    const rightPane = thesisRead ?? factorRead ?? detail ?? allHint

    if (wide) {
      body = (
        <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
          <Box flexDirection="column" flexShrink={0} width={listW}>
            {list}
          </Box>
          <Box flexDirection="column" flexShrink={0} marginLeft={1}>
            <Text color={t.color.border}>{'│'}</Text>
          </Box>
          <Box flexDirection="column" flexGrow={1} flexShrink={1} marginLeft={1} minHeight={0}>
            {rightPane}
          </Box>
        </Box>
      )
    } else {
      body = (
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          {focus === 'list' ? list : rightPane}
        </Box>
      )
    }
  }

  // ── Footer ──────────────────────────────────────────────────────────
  const listHint =
    currentRow?.kind === 'thesis'
      ? `↑↓/jk move · Enter members · → read · / filter · r refresh · Esc/q close`
      : currentRow?.kind === 'factor'
        ? `↑↓/jk move · Enter constituents · → read · / filter · r refresh · Esc/q close`
        : currentRow?.kind === 'all'
          ? `↑↓/jk move · Enter/→ all forecasts · / filter · r refresh · Esc/q close`
          : `↑↓/jk move · Enter/→ focus detail · / filter${query ? ` (${filtered.length}/${items.length})` : ''} · r refresh · Esc/q close`

  const footerHint = filtering
    ? `filter: ${truncate(query, Math.max(8, cols - 30))}▌  · Enter apply · Esc clear`
    : focus === 'detail'
      ? '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · ←/Esc back to list · r refresh · q close'
      : listHint

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        {footerHint}
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
    </Box>
  )
}

// ── Master list (lens rows + forecast book over one cursor) ─────────────────

interface ForecastListProps {
  cursor: number
  factorLensId: null | string
  focus: boolean
  lensId: null | string
  rows: LeftRow[]
  t: Theme
  visibleRows: number
  width: number
}

// A faint section divider in the left column (LENS / BOOK).
function LeftSectionLabel({ children, t }: { children: string; t: Theme }) {
  return (
    <Box>
      <Text bold color={t.color.accent} wrap="truncate-end">
        {children}
      </Text>
    </Box>
  )
}

function ForecastList({ cursor, factorLensId, focus, lensId, rows, t, visibleRows, width }: ForecastListProps) {
  const { items: windowed, offset } = windowItems(rows, cursor, visibleRows)

  return (
    <Box flexDirection="column" flexGrow={0} flexShrink={0} minHeight={0} overflow="hidden">
      {windowed.map((row, i) => {
        const index = offset + i
        const active = index === cursor && focus
        const prev = windowed[i - 1]
        // Section dividers: "LENS" above the first lens row (ALL/thesis) in view,
        // "FACTORS" at the thesis/all→factor boundary, "BOOK" at the
        // lens→forecast boundary.
        const showLens = i === 0 && (row.kind === 'all' || row.kind === 'thesis')

        const showFactors = row.kind === 'factor' && (i === 0 || prev?.kind !== 'factor')

        const showBook =
          row.kind === 'forecast' && (i === 0 || prev?.kind === 'all' || prev?.kind === 'thesis' || prev?.kind === 'factor')

        if (row.kind === 'all') {
          return (
            <Fragment key="all">
              {showLens ? <LeftSectionLabel t={t}>LENS</LeftSectionLabel> : null}
              <LensRow
                active={active}
                count={countForLens(rows, null)}
                label="ALL FORECASTS"
                selected={lensId === null && factorLensId === null}
                t={t}
                width={width}
              />
            </Fragment>
          )
        }

        if (row.kind === 'thesis') {
          return (
            <Fragment key={`th:${row.thesis.id ?? index}`}>
              {showLens ? <LeftSectionLabel t={t}>LENS</LeftSectionLabel> : null}
              <ThesisListRow
                active={active}
                selected={lensId === row.thesis.id}
                t={t}
                thesis={row.thesis}
                width={width}
              />
            </Fragment>
          )
        }

        if (row.kind === 'factor') {
          return (
            <Fragment key={`fx:${row.factor.id ?? index}`}>
              {showFactors ? <LeftSectionLabel t={t}>FACTORS</LeftSectionLabel> : null}
              <FactorListRow
                active={active}
                factor={row.factor}
                selected={factorLensId === row.factor.id}
                t={t}
                width={width}
              />
            </Fragment>
          )
        }

        return (
          <Fragment key={row.item.id ?? `fc:${index}`}>
            {showBook ? <LeftSectionLabel t={t}>BOOK</LeftSectionLabel> : null}
            <ForecastListRow active={active} item={row.item} t={t} width={width} />
          </Fragment>
        )
      })}
      {rows.length > windowed.length ? (
        <Text color={t.color.muted}>
          {'  '}
          {offset + windowed.length}/{rows.length}
        </Text>
      ) : null}
    </Box>
  )
}

// Members in the book for a given lens (null = ALL). Used only for the ALL row's
// count badge.
const countForLens = (rows: LeftRow[], _lens: null): number =>
  rows.filter(row => row.kind === 'forecast').length

// Health color: green ≥60%, amber ≥45%, red below; withheld (null) → muted.
export const healthColor = (t: Theme, health?: null | number): string =>
  !finite(health) ? t.color.muted : health >= 0.6 ? t.color.ok : health >= 0.45 ? t.color.warn : t.color.error

// The ALL FORECASTS lens-clear row.
function LensRow({
  active,
  count,
  label,
  selected,
  t,
  width
}: {
  active: boolean
  count: number
  label: string
  selected: boolean
  t: Theme
  width: number
}) {
  const titleW = Math.max(8, width - 8)

  return (
    <Box width={width}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
        <Text bold={active} color={active ? t.color.primary : t.color.muted}>
          {active ? '▸ ' : selected ? '● ' : '  '}
        </Text>
        <Text bold={active || selected} color={selected ? t.color.primary : active ? t.color.text : t.color.label}>
          {label.padEnd(titleW)}
        </Text>
        <Text color={t.color.muted}>{String(count).padStart(4)}</Text>
      </Text>
    </Box>
  )
}

// One thesis row in the lens: "health% · title · (members)", active-highlighted.
// A withheld health (no snapshot) reads "—", never a fake number.
function ThesisListRow({
  active,
  selected,
  t,
  thesis,
  width
}: {
  active: boolean
  selected: boolean
  t: Theme
  thesis: ForecastThesis
  width: number
}) {
  const health = thesis.health_probability
  const healthText = (thesis.health_display ?? (finite(health) ? pct(health) : '—')).padStart(4)
  const members = thesis.member_count ?? thesis.components?.length ?? 0
  const memberText = `(${members})`
  // marker(2) health(4) gap(1) members + gaps → reserve ~ 4 + 2 + memberText.length
  const titleW = Math.max(6, width - 4 - 2 - memberText.length - 2)
  const title = truncate(thesis.title ?? thesis.id ?? 'thesis', titleW).padEnd(titleW)

  return (
    <Box width={width}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
        <Text bold={active} color={active ? t.color.primary : t.color.muted}>
          {active ? '▸ ' : selected ? '● ' : '  '}
        </Text>
        <Text bold color={healthColor(t, health)}>
          {healthText}
        </Text>
        <Text bold={active || selected} color={selected ? t.color.primary : active ? t.color.text : t.color.label}>
          {' '}
          {title}
        </Text>
        <Text color={t.color.muted}> {memberText}</Text>
      </Text>
    </Box>
  )
}

// Sign color for a factor return / contribution: green ≥0, red <0; withheld
// (null) → muted. A return basket's mean is the headline, so a positive
// expected return reads green and a negative one red.
export const signColor = (t: Theme, value?: null | number): string =>
  !finite(value) ? t.color.muted : value >= 0 ? t.color.ok : t.color.error

// One factor row in the lens: "μ<mean> · title · (constituents)". The mean is
// the basket's aggregate return, abbreviated (k/M/B/T) and unit-suffixed, and
// colored by sign. A withheld mean (no snapshot) reads "μ—", never a fake number.
function FactorListRow({
  active,
  factor,
  selected,
  t,
  width
}: {
  active: boolean
  factor: ForecastFactor
  selected: boolean
  t: Theme
  width: number
}) {
  const mean = factor.mean
  const meanText = (finite(mean) ? `μ${trimNum(mean)}${unitSuffix(factor.units)}` : 'μ—').padStart(6)
  const members = factor.member_count ?? factor.constituents?.length ?? 0
  const memberText = `(${members})`
  // marker(2) mean(6) gap(1) members + gaps → reserve ~ 6 + 2 + memberText.length
  const titleW = Math.max(6, width - 4 - 6 - memberText.length - 2)
  const title = truncate(factor.title ?? factor.id ?? 'factor', titleW).padEnd(titleW)

  return (
    <Box width={width}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
        <Text bold={active} color={active ? t.color.primary : t.color.muted}>
          {active ? '▸ ' : selected ? '● ' : '  '}
        </Text>
        <Text bold color={signColor(t, mean)}>
          {meanText}
        </Text>
        <Text bold={active || selected} color={selected ? t.color.primary : active ? t.color.text : t.color.label}>
          {' '}
          {title}
        </Text>
        <Text color={t.color.muted}> {memberText}</Text>
      </Text>
    </Box>
  )
}

function ForecastListRow({
  active,
  item,
  t,
  width
}: {
  active: boolean
  item: ForecastWorkspaceItem
  t: Theme
  width: number
}) {
  const delta = item.delta
  const glyph = deltaGlyph(delta)
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const sparkValues = (item.history ?? []).slice(-8).map(point => point.headline_probability ?? null)

  // Probabilities use the fixed 0..1 scale; distribution means (e.g. ~4.2%)
  // are scaled to their own data range so the trend is visible, not clamped flat.
  const sparkOpts =
    item.headline_kind === 'distribution'
      ? (() => {
          const finiteVals = sparkValues.filter((v): v is number => finite(v))

          return finiteVals.length ? { yMax: Math.max(...finiteVals), yMin: Math.min(...finiteVals) } : {}
        })()
      : {}

  const spark = levelSparkline(sparkValues, sparkOpts)
  const probText = headlineCompact(item)
  // Reserve: marker(2) prob(6) gap(1) glyph(1) gap(1) spark(8) → ~20; rest for title.
  const titleW = Math.max(10, width - 21)
  const title = truncate(item.title ?? item.id ?? 'untitled', titleW).padEnd(titleW)
  const alertBadge = (item.open_alert_count ?? 0) > 0 ? `!${item.open_alert_count}` : ''

  return (
    <Box width={width}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
        <Text bold={active} color={active ? t.color.primary : t.color.muted}>
          {active ? '▸ ' : '  '}
        </Text>
        <Text bold={active} color={active ? t.color.text : t.color.label}>
          {title}
        </Text>
        <Text color={t.color.text}> {probText.padStart(6)}</Text>
        <Text color={deltaColor}> {glyph}</Text>
        <Text color={t.color.border}> {spark}</Text>
        {alertBadge ? <Text color={t.color.statusBad}> {alertBadge}</Text> : null}
      </Text>
    </Box>
  )
}

// ── Detail pane ─────────────────────────────────────────────────────────────

function SectionTitle({ children, t }: { children: string; t: Theme }) {
  return (
    <Box marginTop={1}>
      <Text bold color={t.color.accent}>
        {children}
      </Text>
    </Box>
  )
}

function KV({ k, t, v }: { k: string; t: Theme; v: string }) {
  return (
    <Text wrap="truncate-end">
      <Text color={t.color.label}>{k.padEnd(13)}</Text>
      <Text color={t.color.text}>{v}</Text>
    </Text>
  )
}

export function ForecastDetail({
  afterChart,
  ensembleRows = [],
  item,
  packetPanel = null,
  t,
  tailAudit = null,
  width
}: {
  afterChart?: ReactNode
  ensembleRows?: EnsembleComponentRow[]
  item: ForecastWorkspaceItem
  packetPanel?: ForecastWorkspacePanel | null
  t: Theme
  tailAudit?: ForecastTailAudit | null
  width: number
}) {
  const delta = item.delta
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const bandPoints = useMemo(() => historyToBandPoints(item), [item])
  const hasSeries = bandPoints.some(point => finite(point.y))
  const scale = useMemo(() => chartScale(bandPoints), [bandPoints])

  const chart = useMemo(
    // Never exceed the pane width (clamps the chart on very narrow terminals so
    // the line-drawn axis/markers don't wrap and shred the layout).
    () => (hasSeries ? bandChart(bandPoints, { height: 9, width: Math.min(56, Math.max(1, width - 1)), ...scale }) : null),
    [bandPoints, hasSeries, scale, width]
  )

  // The x-axis: real tick marks + deduped date labels spread across the actual
  // snapshot time range (the dates of the finite-headline points, in order, so
  // they line up with the chart's own column placement).
  const axis = useMemo(() => {
    if (!chart) {
      return null
    }
    const dates = (item.history ?? [])
      .filter(point => finite(point.headline_probability))
      .map(point => point.as_of ?? null)
    return timeAxis(dates, { gutterW: chart.gutterW, plotW: chart.plotW })
  }, [chart, item.history])

  // Prefer the server-classified PMF (buckets only, moments/intervals stripped);
  // fall back to the raw dict for plain categorical forecasts.
  const bars = useMemo(() => {
    const pmf = item.distribution?.pmf

    if (pmf && pmf.length) {
      // fraction-scale vote shares are classified as a PMF here, so intervals must
      // attach on THIS branch too (not only the distributionBars fallback).
      return pmf.map(row => ({ label: row.label, value: row.probability, interval: intervalForLabel(item.candidate_intervals, row.label) }))
    }

    return distributionBars(item.probability, item.candidate_intervals)
  }, [item.distribution, item.probability, item.candidate_intervals])

  const dist = item.distribution
  const isDistribution = item.headline_kind === 'distribution'
  const unit = unitSuffix(item.units)
  // Panel spread: the workspace item's own panel run, else the packet-derived
  // fallback. Distribution forecasts never borrow it — their components live
  // on the outcome scale, not the probability scale.
  const panel = item.panel ?? (isDistribution ? null : packetPanel)
  const topics = (item.topics ?? []).join(', ')

  return (
    <Box flexDirection="column">
      {/* The ONE question title — it WRAPS (a modal has room), up to 3 lines, then
          tail-truncates. The old duplicate modal-title line was removed. */}
      {wrapLines(item.title ?? item.id ?? 'untitled', width, 3).map((line, i) => (
        <Text bold color={t.color.primary} key={`title:${i}`}>
          {line}
        </Text>
      ))}
      {/* Meta beneath the title — politics · impact · status · tags, wrapping so
          the tag list never truncates. */}
      <Text wrap="wrap">
        {item.domain ? <Text color={t.color.label}>{item.domain}</Text> : null}
        {item.impact ? (
          <Text color={t.color.muted}>
            {item.domain ? ' · ' : ''}impact <Text color={t.color.warn}>{item.impact}</Text>
          </Text>
        ) : null}
        {item.status ? (
          <Text color={item.status === 'active' ? t.color.ok : t.color.label}> · {item.status}</Text>
        ) : null}
        {topics ? <Text color={t.color.muted}> · {topics}</Text> : null}
      </Text>

      <Box marginTop={1}>
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            {isDistribution ? '' : 'P '}
            {headlineLabel(item)}
          </Text>
          <Text color={t.color.muted}>{'  conf '}</Text>
          <Text color={t.color.label}>{finite(item.confidence) ? item.confidence.toFixed(2) : '—'}</Text>
          <Text color={t.color.muted}>{'  '}</Text>
          <Text bold color={deltaColor}>
            {deltaLabel(item)}
          </Text>
          <Text color={t.color.muted}>{'  as-of '}</Text>
          <Text color={t.color.label}>{`${shortDate(item.as_of)}${item.freshness ? ` (${item.freshness})` : ''}`}</Text>
        </Text>
      </Box>
      {isDistribution && dist && (finite(dist.median) || dist.ci90) ? (
        <Text wrap="truncate-end">
          {finite(dist.median) ? (
            <Text>
              <Text color={t.color.muted}>median </Text>
              <Text color={t.color.text}>
                {trimNum(dist.median)}
                {unit}
              </Text>
            </Text>
          ) : null}
          {dist.ci50 ? (
            <Text>
              <Text color={t.color.muted}>{'  ·  50% '}</Text>
              <Text color={t.color.text}>{`[${trimNum(dist.ci50[0]!)}, ${trimNum(dist.ci50[1]!)}]`}</Text>
            </Text>
          ) : null}
          {dist.ci90 ? (
            <Text>
              <Text color={t.color.muted}>{'  ·  90% '}</Text>
              <Text color={t.color.text}>{`[${trimNum(dist.ci90[0]!)}, ${trimNum(dist.ci90[1]!)}]`}</Text>
            </Text>
          ) : null}
        </Text>
      ) : null}
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>close </Text>
        <Text color={t.color.label}>{shortDate(item.close_time)}</Text>
        <Text color={t.color.muted}>{'  ·  ev '}</Text>
        <Text color={t.color.label}>{item.evidence_count ?? 0}</Text>
        <Text color={t.color.muted}>{'  ·  '}</Text>
        <Text color={t.color.label}>{`${item.snapshot_count ?? 0} update${(item.snapshot_count ?? 0) === 1 ? '' : 's'}`}</Text>
        {item.method ? <Text color={t.color.muted}>{`  ·  ${item.method}`}</Text> : null}
      </Text>

      {item.resolution_criteria ? (
        <Box marginTop={1}>
          <Text color={t.color.text} wrap="wrap">
            {item.resolution_criteria}
          </Text>
        </Box>
      ) : null}

      {chart ? (
        <>
          <SectionTitle t={t}>{isDistribution ? `mean over time${unit ? ` (${unit})` : ''}` : 'probability over time'}</SectionTitle>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
          {/* Real x-axis: a base rule with tick marks + deduped date labels across
              the actual snapshot range (a single line "date → date" was degenerate
              when snapshots spanned little time). */}
          {axis ? (
            <>
              <Text color={t.color.border}>{axis.ticks}</Text>
              <Text color={t.color.label} wrap="truncate-end">
                {axis.labels}
              </Text>
            </>
          ) : null}
          <Text color={t.color.label} wrap="truncate-end">
            {`  ${
              isDistribution ? '● mean  ░ 90% interval' : item.panel ? '● forecast  ░ panel spread / confidence band' : '● forecast  ░ confidence band'
            }`}
          </Text>
        </>
      ) : null}

      {/* Title + quick stats + chart lead; the analyst quick read slots in here,
          right after the chart, ahead of the deeper breakdown below. */}
      {afterChart}

      {bars ? (
        <>
          <SectionTitle t={t}>{isDistribution ? 'outcome buckets (PMF)' : 'outcome distribution'}</SectionTitle>
          {histogram(bars, {
            // Adapt label + bar widths to the pane so a narrow detail column
            // never forces the bars off-screen.
            labelWidth: Math.max(8, Math.min(16, width - 14)),
            width: Math.max(6, Math.min(width - Math.max(8, Math.min(16, width - 14)) - 8, 30))
          }).map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
        </>
      ) : null}

      <TailAuditSection audit={tailAudit} t={t} width={width} />

      <EnsembleComponentsSection rows={ensembleRows} t={t} width={width} />

      {panel ? <PanelSection panel={panel} t={t} width={width} /> : null}

      <ReasoningPaths
        breaksIf={item.change_my_mind ?? []}
        pathDown={item.reasons_down ?? []}
        pathUp={item.reasons_up ?? []}
        t={t}
      />

      {item.related ? <RelatedForecasts related={item.related} t={t} width={width} /> : null}

      {item.evidence?.length ? (
        <>
          <SectionTitle t={t}>recent evidence</SectionTitle>
          {item.evidence
            .slice()
            .reverse()
            .slice(0, 6)
            .map((evidence, i) => {
              const stanceColor =
                evidence.stance === 'increases'
                  ? t.color.ok
                  : evidence.stance === 'decreases'
                    ? t.color.error
                    : t.color.muted

              // The claim is informational — it WRAPS as a hanging indent (date +
              // stance keep their own colours in a fixed lead column) instead of
              // being cut with a trailing '…'.
              return (
                <Box flexDirection="row" key={evidence.id ?? i}>
                  <Box flexShrink={0}>
                    <Text color={t.color.label}>{shortDate(evidence.available_at)} </Text>
                    <Text bold color={stanceColor}>
                      {(evidence.stance ?? 'context').slice(0, 3)}{' '}
                    </Text>
                  </Box>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text color={t.color.text} wrap="wrap">
                      {evidence.claim || evidence.summary || evidence.source || '—'}
                    </Text>
                  </Box>
                </Box>
              )
            })}
        </>
      ) : null}

      {item.relevant_lessons?.length ? (
        <>
          <SectionTitle t={t}>active lessons (structuring this forecast)</SectionTitle>
          {item.relevant_lessons.slice(0, 5).map((lesson, i) => (
            <WrapLine
              body={lesson.lesson || '—'}
              key={lesson.id ?? i}
              prefix={`${lesson.scope_ref || lesson.scope_type || 'lesson'}: `}
              prefixColor={t.color.label}
              t={t}
            />
          ))}
        </>
      ) : null}

      <DecisionCard item={item} t={t} />

      {item.scores || item.resolution ? (
        <>
          <SectionTitle t={t}>scoring</SectionTitle>
          {item.scores ? (
            <KV
              k="calibration"
              t={t}
              v={`${item.scores.count ?? 0} scored · brier ${
                finite(item.scores.mean_brier) ? item.scores.mean_brier.toFixed(3) : '—'
              } · bucket ${item.scores.last_bucket ?? '—'}`}
            />
          ) : null}
          {item.resolution ? (
            <KV
              k="resolution"
              t={t}
              v={`${String(item.resolution.outcome ?? '—')} (${item.resolution.resolution_status ?? '—'})`}
            />
          ) : null}
        </>
      ) : null}
    </Box>
  )
}

// ── Tail audit (categorical probability-mass audit) ─────────────────────────

// Map the engine's tail-audit severity onto the workspace theme so an UNEARNED
// outcome reads error-red, a weak/unpriced one amber, a live one green, and a
// residual/negligible one muted — the same severity grammar the rest of the
// desk uses for health/delta.
const tailSeverityColor = (t: Theme, severity: TailSeverity): string =>
  severity === 'error'
    ? t.color.error
    : severity === 'warn'
      ? t.color.warn
      : severity === 'ok'
        ? t.color.ok
        : t.color.muted

// A glyph for a classification: a live path reads as a filled dot, an unearned
// outcome as a bang, the weak middle as a hollow dot, residual as a dash.
const tailGlyph = (outcome: ForecastTailOutcome): string => {
  if (outcome.unearned) {
    return '!'
  }

  const classification = outcome.classification ?? ''

  if (classification === 'live') {
    return '●'
  }

  if (classification === 'residual') {
    return '·'
  }

  return '○'
}

// The inline "tail audit: FAIL — Conway 1.7% unpriced" chip that sits next to
// the analyst quick read so the commentary and the audit never contradict each
// other. A passing audit reads a quiet green "tail audit: PASS"; no audit at all
// (non-categorical / older snapshot) renders nothing.
function TailAuditChip({ audit, t }: { audit: ForecastTailAudit | null; t: Theme }) {
  const chip = tailAuditChip(audit)

  if (!chip) {
    return null
  }

  const fails = tailAuditFails(audit)

  return (
    <Box>
      <Text bold color={fails ? t.color.error : t.color.ok} wrap="truncate-end">
        {chip}
      </Text>
    </Box>
  )
}

// The probability-mass table for a categorical question: one row per outcome
// (glyph / name / prob / classification / evidence / path), unearned rows
// coloured error, a small classification-coloured mass bar, the unearned-mass
// headline, and the null-model comparison line. Rendered only when the snapshot
// actually carries an audit (categorical only); otherwise nothing.
function TailAuditSection({ audit, t, width }: { audit: ForecastTailAudit | null; t: Theme; width: number }) {
  if (!audit || !(audit.outcomes ?? []).length) {
    return null
  }

  const fails = tailAuditFails(audit)
  const outcomes = [...(audit.outcomes ?? [])].sort((a, b) => (b.probability ?? 0) - (a.probability ?? 0))
  const headline = unearnedHeadline(audit)
  const nullLine = nullModelLine(audit)
  // Budget: glyph(2) name(flex) prob(6) gap classification(11) → keep the name
  // column wide enough to read on a narrow pane.
  const nameW = Math.max(10, Math.min(28, width - 26))
  const barW = Math.max(4, Math.min(12, width - nameW - 26))
  const maxMass = Math.max(...outcomes.map(outcome => outcome.probability ?? 0), 0.0001)

  return (
    <>
      <SectionTitle t={t}>Tail Audit</SectionTitle>
      <Text wrap="truncate-end">
        <Text bold color={fails ? t.color.error : t.color.ok}>
          {fails ? 'FAIL' : 'PASS'}
        </Text>
        <Text color={t.color.muted}>{`  total ${tailPct(audit.total_mass)}  ·  threshold ${tailPct(audit.threshold)}`}</Text>
      </Text>
      {headline ? (
        <Text bold color={fails ? t.color.error : t.color.warn} wrap="truncate-end">
          {headline}
        </Text>
      ) : null}
      {outcomes.map((outcome, i) => {
        const severity = outcomeSeverity(outcome)
        const color = tailSeverityColor(t, severity)
        const name = truncate(outcome.name ?? '—', nameW).padEnd(nameW)
        const classification = (outcome.classification ?? '—').padEnd(11)
        const fill = Math.max(0, Math.round(clamp01((outcome.probability ?? 0) / maxMass) * barW))
        const bar = `${'█'.repeat(fill)}${'░'.repeat(Math.max(0, barW - fill))}`

        return (
          <Text key={outcome.name ?? `o${i}`} wrap="truncate-end">
            <Text bold color={color}>
              {tailGlyph(outcome)}{' '}
            </Text>
            <Text color={outcome.unearned ? color : t.color.text}>{name}</Text>
            <Text color={t.color.text}> {tailPct(outcome.probability).padStart(6)}</Text>
            <Text color={color}> {bar}</Text>
            <Text color={t.color.label}> {classification}</Text>
            <Text color={t.color.muted}>
              {outcome.has_path ? `path: ${truncate(outcome.path || '—', 24)}` : 'no path'}
              {outcome.evidence_strength && outcome.evidence_strength !== 'unspecified'
                ? ` · ${outcome.evidence_strength}`
                : ''}
            </Text>
          </Text>
        )
      })}
      {nullLine ? (
        <Text color={audit.null_model?.within_tolerance ? t.color.muted : t.color.warn} wrap="truncate-end">
          {`  null model: ${nullLine}${audit.null_model?.within_tolerance ? '' : ' — owes an explanation'}`}
        </Text>
      ) : null}
      {(audit.issues ?? []).map((issue, i) => (
        <WrapLine body={issue} bodyColor={t.color.warn} key={`issue${i}`} prefix="⚠ " prefixColor={t.color.warn} t={t} />
      ))}
    </>
  )
}

// The pooled ensemble components with weights + source slugs, so a market that
// was down-weighted for being thin/stale (a fraction of a liquid component's
// weight) is visible. A market-looking source whose weight is conspicuously low
// relative to the heaviest component is hinted "discounted".
function EnsembleComponentsSection({
  rows,
  t,
  width
}: {
  rows: EnsembleComponentRow[]
  t: Theme
  width: number
}) {
  if (rows.length < 2) {
    return null
  }

  const maxWeight = Math.max(...rows.map(row => row.weight), 0)
  const totalWeight = rows.reduce((sum, row) => sum + row.weight, 0) || 1

  // TWO lines per component: line 1 = full name (wraps) + right-aligned value +
  // weight; line 2 = the FULL source slug (dim, wrapping). Value + weight sit in
  // fixed columns sized to the widest so they align across every component.
  const valueW = 6
  const weightStrs = rows.map(row => `w ${row.weight.toFixed(2)} (${pct(row.weight / totalWeight)})`)
  const weightW = Math.max(12, ...weightStrs.map(str => str.length))

  return (
    <>
      <SectionTitle t={t}>{`ensemble components (${rows.length})`}</SectionTitle>
      {rows.map((row, i) => {
        // A market component whose weight is a small fraction of the heaviest is
        // flagged: it was likely discounted for being thin/stale.
        const discounted =
          looksLikeMarketSource(row.source) && maxWeight > 0 && row.weight <= maxWeight * 0.5

        return (
          <Box flexDirection="column" key={row.source ?? row.name ?? `c${i}`}>
            <Box flexDirection="row">
              <Box flexGrow={1} flexShrink={1} minWidth={0}>
                <Text wrap="wrap">
                  <Text color={discounted ? t.color.warn : t.color.label}>{discounted ? '× ' : '  '}</Text>
                  <Text color={t.color.text}>{row.name}</Text>
                </Text>
              </Box>
              <Box flexDirection="row" flexShrink={0}>
                <Box flexShrink={0} width={valueW}>
                  <Text color={t.color.text}>{pct(row.probability).padStart(valueW)}</Text>
                </Box>
                <Box flexShrink={0} width={weightW + 2}>
                  <Text color={t.color.muted}>{`  ${weightStrs[i]}`}</Text>
                </Box>
              </Box>
            </Box>
            {row.source ? (
              <Box paddingLeft={2}>
                <Text color={t.color.muted} wrap="wrap">
                  {row.source}
                  {discounted ? <Text color={t.color.warn}>{'  · discounted'}</Text> : null}
                </Text>
              </Box>
            ) : discounted ? (
              <Box paddingLeft={2}>
                <Text color={t.color.warn} wrap="wrap">
                  discounted
                </Text>
              </Box>
            ) : null}
          </Box>
        )
      })}
    </>
  )
}

// Path-driven structured reasoning: the causal PATHS, not a generic "reasons"
// blob. "Path up" (links that push the probability up), "Path down" (links that
// push it down), and "Breaks if" (the weakest load-bearing link — what would
// change the forecaster's mind).
function ReasoningPaths({
  breaksIf,
  pathDown,
  pathUp,
  t
}: {
  breaksIf: string[]
  pathDown: string[]
  pathUp: string[]
  t: Theme
}) {
  if (!pathUp.length && !pathDown.length && !breaksIf.length) {
    return null
  }

  return (
    <>
      <SectionTitle t={t}>causal paths</SectionTitle>
      {pathUp.length ? (
        <>
          <Text bold color={t.color.ok}>
            Path up
          </Text>
          {pathUp.map((link, i) => (
            <WrapLine body={link} key={`up${i}`} prefix="▲ " prefixColor={t.color.ok} t={t} />
          ))}
        </>
      ) : null}
      {pathDown.length ? (
        <>
          <Text bold color={t.color.error}>
            Path down
          </Text>
          {pathDown.map((link, i) => (
            <WrapLine body={link} key={`dn${i}`} prefix="▼ " prefixColor={t.color.error} t={t} />
          ))}
        </>
      ) : null}
      {breaksIf.length ? (
        <>
          <Text bold color={t.color.warn}>
            Breaks if
          </Text>
          {breaksIf.map((link, i) => (
            <WrapLine body={link} key={`brk${i}`} prefix="⟳ " prefixColor={t.color.warn} t={t} />
          ))}
        </>
      ) : null}
    </>
  )
}

/** Compact perspective-vs-aggregate delta: `"+6pt"` / `"-2pt"` / `"·"`. */
const spreadDelta = (probability: null | number | undefined, aggregate: null | number | undefined): string => {
  if (!finite(probability) || !finite(aggregate)) {
    return ''
  }

  const points = Math.round((probability - aggregate) * 100)

  if (points === 0) {
    return '·'
  }

  return `${points > 0 ? '+' : ''}${points}pt`
}

// Disagreement meter — the log-odds dispersion of the panel, rendered as a
// short filled bar. A wide quorum/panel spread is epistemic uncertainty the
// aggregate hides, so the desk surfaces it as a calm→severe signal to
// investigate (not average away). The scalar is computed server-side and
// carried inside spread_summary (see forecasting/panel.disagreement_signal).
function disagreementBand(index: number): 'calm' | 'moderate' | 'high' | 'severe' {
  if (index < 0.15) {return 'calm'}

  if (index < 0.4) {return 'moderate'}

  if (index < 0.65) {return 'high'}

  return 'severe'
}

export function DisagreementMeter({ spread, t }: { spread?: Record<string, number>; t: Theme }) {
  const index = spread?.disagreement_index

  if (!finite(index)) {return null}
  const band = disagreementBand(index)

  const color =
    band === 'calm'
      ? t.color.ok
      : band === 'moderate'
        ? t.color.accent
        : band === 'high'
          ? t.color.warn
          : t.color.error

  const cells = 10
  const filled = Math.max(0, Math.min(cells, Math.round(index * cells)))
  const bar = '█'.repeat(filled) + '░'.repeat(cells - filled)

  return (
    <Text wrap="truncate-end">
      <Text color={t.color.muted}>{'disagree  '}</Text>
      <Text color={color}>{bar}</Text>
      <Text color={color}>{`  ${band}`}</Text>
      <Text color={t.color.muted}>{`  (${index.toFixed(2)})`}</Text>
    </Text>
  )
}

export function PanelSection({ panel, t, width }: { panel: ForecastWorkspacePanel; t: Theme; width: number }) {
  const estimates = panel.estimates ?? []
  const aggregate = panel.aggregate_probability
  const isEnsemble = panel.kind === 'ensemble'

  const title = isEnsemble
    ? `ensemble (${estimates.length} components)`
    : `panel (${estimates.length} perspectives)`

  // A single aligned grid shared by the header rows (aggregate / range /
  // disagree) AND every estimate: [name][value][rail][delta][trailing]. Every
  // strip starts at the SAME column and is the SAME width; values right-align in
  // their own column; the ±pt outlier markers right-align in a fixed end column.
  // The name column is sized to the LONGEST perspective (marker + up to ~24 chars
  // before it wraps to a second line — never a "polls_mar…").
  const markerW = 2
  const longest = Math.max(9, ...estimates.map(estimate => (estimate.perspective ?? '—').length))
  const nameInner = Math.min(24, longest)
  const nameW = markerW + nameInner
  const valueW = 6
  const deltaW = 6
  const railW = Math.max(0, Math.min(24, width - nameW - valueW - deltaW - 8))
  const hasRail = railW >= 8
  const whisker = hasRail ? boxWhisker(panel.spread ?? {}, { width: railW }) : ''

  const trimmedCount = estimates.filter(estimate => estimate.trimmed).length
  const weights = estimates.map(estimate => estimate.weight).filter(finite)
  const showWeights = isEnsemble && weights.length > 0 && new Set(weights).size > 1

  const disagreement = panel.spread?.disagreement_index
  const disBand = finite(disagreement) ? disagreementBand(disagreement) : null
  const disColor =
    disBand === 'calm'
      ? t.color.ok
      : disBand === 'moderate'
        ? t.color.accent
        : disBand === 'high'
          ? t.color.warn
          : t.color.error
  const disFill = finite(disagreement) ? Math.max(0, Math.min(railW, Math.round(disagreement * railW))) : 0
  const disBar = '█'.repeat(disFill) + '░'.repeat(Math.max(0, railW - disFill))

  return (
    <>
      <SectionTitle t={t}>{title}</SectionTitle>
      <Box flexDirection="row">
        <Box flexShrink={0} width={nameW}>
          <Text color={t.color.muted}>aggregate</Text>
        </Box>
        <Box flexShrink={0} width={valueW}>
          <Text bold color={t.color.primary}>
            {pct(aggregate).padStart(valueW)}
          </Text>
        </Box>
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text color={t.color.muted} wrap="truncate-end">
            {`  ${panel.aggregation_method ?? 'pool'}${isEnsemble ? '' : ` · trim ${panel.trim ?? 0}`}`}
          </Text>
        </Box>
      </Box>
      {whisker ? (
        <Box flexDirection="row">
          <Box flexShrink={0} width={nameW}>
            <Text color={t.color.muted}>range</Text>
          </Box>
          <Box flexShrink={0} width={valueW}>
            <Text color={t.color.label}>{pct(panel.spread?.min).padStart(valueW)}</Text>
          </Box>
          <Box flexShrink={0} width={railW + 2}>
            <Text color={t.color.accent}>{`  ${whisker}`}</Text>
          </Box>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text color={t.color.label}>{`  ${pct(panel.spread?.max)}`}</Text>
          </Box>
        </Box>
      ) : null}
      {finite(disagreement) ? (
        <Box flexDirection="row">
          <Box flexShrink={0} width={nameW}>
            <Text color={t.color.muted}>disagree</Text>
          </Box>
          <Box flexShrink={0} width={valueW}>
            <Text> </Text>
          </Box>
          {hasRail ? (
            <Box flexShrink={0} width={railW + 2}>
              <Text color={disColor}>{`  ${disBar}`}</Text>
            </Box>
          ) : null}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text color={disColor}>{`  ${disBand} (${disagreement.toFixed(2)})`}</Text>
          </Box>
        </Box>
      ) : null}
      {estimates.map((estimate, i) => {
        const rail = hasRail ? dotTrack(estimate.probability, aggregate, { width: railW }) : ''
        const delta = spreadDelta(estimate.probability, aggregate)
        const nameLines = wrapLines(estimate.perspective ?? '—', nameInner, 2)

        const deltaColor =
          !delta || delta === '·'
            ? t.color.muted
            : delta.startsWith('+')
              ? t.color.ok
              : t.color.error

        return (
          <Box flexDirection="row" key={estimate.perspective ?? i}>
            <Box flexShrink={0} width={nameW}>
              <Box flexShrink={0} width={markerW}>
                <Text bold={!estimate.trimmed} color={estimate.trimmed ? t.color.muted : t.color.label}>
                  {estimate.trimmed ? '× ' : '  '}
                </Text>
              </Box>
              <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
                {nameLines.map((line, li) => (
                  <Text
                    bold={!estimate.trimmed && li === 0}
                    color={estimate.trimmed ? t.color.muted : t.color.label}
                    key={li}
                  >
                    {line}
                  </Text>
                ))}
              </Box>
            </Box>
            <Box flexShrink={0} width={valueW}>
              <Text color={estimate.trimmed ? t.color.muted : t.color.text}>{pct(estimate.probability).padStart(valueW)}</Text>
            </Box>
            {hasRail ? (
              <Box flexShrink={0} width={railW + 2}>
                <Text color={estimate.trimmed ? t.color.muted : t.color.accent}>{`  ${rail}`}</Text>
              </Box>
            ) : null}
            <Box flexShrink={0} width={deltaW + 2}>
              <Text color={deltaColor}>{delta ? `  ${delta.padStart(deltaW)}` : ''}</Text>
            </Box>
            <Box flexGrow={1} flexShrink={1} minWidth={0}>
              <Text color={t.color.muted} wrap="wrap">
                {showWeights && finite(estimate.weight) ? `  w ${estimate.weight.toFixed(1)}` : ''}
                {estimate.crux ? `  ${estimate.crux}` : ''}
              </Text>
            </Box>
          </Box>
        )
      })}
      {(panel.trim ?? 0) > 0 || trimmedCount > 0 ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {`  trimmed mean: ${trimmedCount || panel.trim} outlier estimate${(trimmedCount || panel.trim) === 1 ? '' : 's'} (×) excluded before pooling`}
        </Text>
      ) : null}
    </>
  )
}

// Renders the long-form packet sections (forecast history, assumptions, model
// runs, actions) under the visual summary. Read-only — the workspace has its own
// keymap, so the action rows are shown as a reference playbook, not links. Uses
// the hanging-indent two-column pattern (fixed key column + flexGrow value with
// minWidth={0}) so long rationales / URLs wrap instead of overflowing the pane.
export function ForecastPacketTail({ sections, t, width }: { sections: PanelSection[]; t: Theme; width: number }) {
  const keyWidth = Math.min(18, Math.max(8, Math.floor(width * 0.34)))

  return (
    <>
      {sections.map((section, si) => {
        const isActions = section.title === 'Actions'

        return (
          <Fragment key={section.title ?? si}>
            {section.title ? <SectionTitle t={t}>{section.title}</SectionTitle> : null}
            {(section.rows ?? []).map((row, ri) =>
              // Action commands are long; render the command on its own wrapping
              // line with the description indented beneath, like a playbook.
              isActions ? (
                <Box flexDirection="column" key={ri}>
                  <Box flexDirection="row">
                    <Box flexShrink={0} width={2}>
                      <Text color={t.color.muted}>{'• '}</Text>
                    </Box>
                    <Box flexGrow={1} flexShrink={1} minWidth={0}>
                      <Text color={t.color.accent} wrap="wrap">
                        {row[0]}
                      </Text>
                    </Box>
                  </Box>
                  {row[1] ? (
                    <Box flexDirection="row">
                      <Box flexShrink={0} width={2}>
                        <Text> </Text>
                      </Box>
                      <Box flexGrow={1} flexShrink={1} minWidth={0}>
                        <Text color={t.color.muted} wrap="wrap">
                          {row[1]}
                        </Text>
                      </Box>
                    </Box>
                  ) : null}
                </Box>
              ) : (
                <Box flexDirection="row" key={ri}>
                  <Box flexShrink={0} width={keyWidth}>
                    <Text color={t.color.label} wrap="truncate-end">
                      {row[0]}
                    </Text>
                  </Box>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text color={t.color.text} wrap="wrap">
                      {row[1] || ' '}
                    </Text>
                  </Box>
                </Box>
              )
            )}
            {(section.items ?? []).map((item, ii) => (
              <Box flexDirection="row" key={`it${ii}`}>
                <Box flexShrink={0} width={2}>
                  <Text color={t.color.muted}>{'· '}</Text>
                </Box>
                <Box flexGrow={1} flexShrink={1} minWidth={0}>
                  <Text color={t.color.text} wrap="wrap">
                    {item}
                  </Text>
                </Box>
              </Box>
            ))}
            {section.text ? (
              <Text color={t.color.muted} wrap="wrap">
                {section.text}
              </Text>
            ) : null}
          </Fragment>
        )
      })}
    </>
  )
}

// A thin horizontal rule to separate opinion / data / history (Bloomberg feel).
function Rule({ t, width }: { t: Theme; width: number }) {
  return (
    <Box marginTop={1}>
      <Text color={t.color.border}>{'─'.repeat(Math.max(8, Math.min(width, 80)))}</Text>
    </Box>
  )
}

// A wrapping paragraph that never overflows the bounded detail ScrollBox: the
// flexGrow + flexShrink + minWidth={0} value box lets long lines wrap as a
// hanging indent instead of pushing past the pane edge.
// A wrapping, hanging-indent paragraph. Uses paddingLeft on a plain column Box
// (NOT a flexGrow row) so Ink wraps the text at (boxWidth - 2) deterministically.
// The earlier flexGrow + minWidth={0} row resolved its width against the
// ScrollBox's measured content and overflowed the pane by a column or two,
// which both clipped the last characters and made the text reflow/jump as the
// measurement settled. paddingLeft is the same mechanism the resolution-criteria
// text uses, which wraps cleanly.
function WrapText({ bold = false, children, color, t }: { bold?: boolean; children: string; color?: string; t: Theme }) {
  return (
    <Box paddingLeft={2}>
      <Text bold={bold} color={color ?? t.color.text} wrap="wrap">
        {children}
      </Text>
    </Box>
  )
}

// A wrapping line with an optional colored prefix (a glyph like "▲ " or a
// padEnd'd key label) that keeps its own color while the body wraps as a hanging
// indent. Same proven mechanism as WrapText: paddingLeft on a plain column Box
// wraps at (boxWidth - pad) deterministically, so substantive detail-pane content
// (causal paths, audit issues, decision triggers) reads in full instead of being
// cut with a trailing "...". For label-aligned key:value rows pass pad={0} and a
// padEnd'd prefix so the label itself provides the gutter.
function WrapLine({
  body,
  bodyColor,
  pad = 2,
  prefix,
  prefixColor,
  suffix,
  suffixColor,
  t
}: {
  body: string
  bodyColor?: string
  pad?: number
  prefix?: string
  prefixColor?: string
  suffix?: string
  suffixColor?: string
  t: Theme
}) {
  return (
    <Box paddingLeft={pad}>
      <Text color={bodyColor ?? t.color.text} wrap="wrap">
        {prefix ? <Text color={prefixColor ?? t.color.label}>{prefix}</Text> : null}
        {body}
        {suffix ? <Text color={suffixColor ?? t.color.label}>{suffix}</Text> : null}
      </Text>
    </Box>
  )
}

const ANALYST_ANGLES: { key: 'be_aware' | 'how_it_feels' | 'how_it_thinks' | 'looking_for'; label: string; warn?: boolean }[] = [
  { key: 'how_it_feels', label: 'how it feels' },
  { key: 'how_it_thinks', label: 'how it thinks' },
  { key: 'looking_for', label: 'watching for', warn: true },
  { key: 'be_aware', label: 'be aware', warn: true }
]

const STANCE_LABEL: Record<string, string> = {
  lean_no: 'lean no',
  lean_yes: 'lean yes',
  toss_up: 'toss-up'
}

// The prominent analyst write-up block (the desk "quick read", or the closing
// "retrospective" once resolved). Renders the four labeled angles when present,
// else falls back to the synthesized body split into paragraphs.
export function AnalystNote({
  note,
  showStance = true,
  t,
  variant
}: {
  note: ForecastAnalystNote
  showStance?: boolean
  t: Theme
  variant: 'quickread' | 'retrospective'
  width?: number
}) {
  const isRetro = variant === 'retrospective'

  const angles = ANALYST_ANGLES.map(angle => ({ ...angle, text: (note[angle.key] ?? '').trim() })).filter(
    angle => angle.text
  )

  const fallback =
    angles.length === 0
      ? (note.body ?? '')
          .split(/\n\n+/)
          .map(paragraph => paragraph.trim())
          .filter(Boolean)
      : []

  const verdictColor =
    note.verdict === 'right'
      ? t.color.ok
      : note.verdict === 'close'
        ? t.color.warn
        : note.verdict
          ? t.color.error
          : t.color.muted

  return (
    <Box flexDirection="column" marginTop={1}>
      <SectionTitle t={t}>{isRetro ? 'RETROSPECTIVE' : 'QUICK READ'}</SectionTitle>
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>{`as of ${shortDate(note.as_of)}`}</Text>
        {showStance && note.stance ? (
          <Text color={t.color.label}>{`  ·  ${STANCE_LABEL[note.stance] ?? note.stance}`}</Text>
        ) : null}
        {note.verdict ? (
          <Text bold color={verdictColor}>
            {`  ·  ${note.verdict}`}
          </Text>
        ) : null}
        {note.generator === 'template' ? <Text color={t.color.muted}>{'  ·  auto'}</Text> : null}
      </Text>
      {note.headline ? (
        <Box marginTop={1}>
          <WrapText bold color={t.color.text} t={t}>
            {note.headline}
          </WrapText>
        </Box>
      ) : null}
      {angles.map(angle => (
        <Box flexDirection="column" key={angle.key} marginTop={1}>
          <Text bold color={angle.warn ? t.color.warn : t.color.label}>
            {angle.label}
          </Text>
          <WrapText t={t}>{angle.text}</WrapText>
        </Box>
      ))}
      {fallback.map((paragraph, index) => (
        <Box key={index} marginTop={1}>
          <WrapText t={t}>{paragraph}</WrapText>
        </Box>
      ))}
    </Box>
  )
}

// The reviewable time series of prior write-ups, newest-first, as compact
// dateline + headline rows under the main quick read.
function AnalystLog({ notes, t }: { notes: ForecastAnalystNote[]; t: Theme }) {
  if (!notes.length) {
    return null
  }

  return (
    <Box flexDirection="column">
      <SectionTitle t={t}>analyst log</SectionTitle>
      {notes.map((note, index) => (
        <Box flexDirection="row" key={`${note.created_at ?? note.as_of ?? ''}:${index}`}>
          <Box flexShrink={0} width={2}>
            <Text color={t.color.muted}>{note.kind === 'retrospective' ? '◆ ' : '· '}</Text>
          </Box>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="truncate-end">
              <Text color={t.color.muted}>{`${shortDate(note.as_of)}  `}</Text>
              <Text color={t.color.text}>{note.headline || (note.body ?? '').slice(0, 90) || '(note)'}</Text>
            </Text>
          </Box>
        </Box>
      ))}
    </Box>
  )
}

// Cross-pollination: the world-views of related / parent / child forecasts, plus
// an amber heads-up where they share a source (possible non-independence). Pure
// display — never wired into this forecast's evidence or math.
const RELATIONSHIP_TAG: Record<string, { glyph: string; label: string }> = {
  child: { glyph: '▾', label: 'child' },
  correlated_sibling: { glyph: '~', label: 'sibling' },
  parent: { glyph: '▴', label: 'parent' }
}

export function RelatedForecasts({ related, t, width }: { related: ForecastRelated; t: Theme; width: number }) {
  const forecasts = related.forecasts ?? []
  const shared = related.shared_sources ?? []

  if (!forecasts.length && !shared.length) {
    return null
  }

  return (
    <>
      <SectionTitle t={t}>related forecasts</SectionTitle>
      {forecasts.map((rel, index) => {
        const tag = RELATIONSHIP_TAG[rel.relationship ?? 'correlated_sibling'] ?? RELATIONSHIP_TAG.correlated_sibling
        const lead = rel.note_headline || rel.reasons_up?.[0] || rel.be_aware || ''

        return (
          <Box flexDirection="column" key={rel.id ?? index} marginTop={index === 0 ? 0 : 1}>
            <Text wrap="truncate-end">
              <Text color={t.color.label}>{`${tag.glyph} ${tag.label}  `}</Text>
              <Text color={t.color.text}>{truncate(rel.title ?? rel.id ?? 'untitled', Math.max(16, width - 28))}</Text>
              <Text color={t.color.muted}>{`  ${rel.probability_display ?? '-'}`}</Text>
              {rel.as_of ? <Text color={t.color.muted}>{`  ${shortDate(rel.as_of)}`}</Text> : null}
              {rel.link_type === 'auto' ? <Text color={t.color.muted}>{'  · auto'}</Text> : null}
            </Text>
            {lead ? (
              <Box paddingLeft={2}>
                <Text color={t.color.muted} wrap="wrap">
                  {lead}
                </Text>
              </Box>
            ) : null}
          </Box>
        )
      })}
      {shared.map((src, index) => (
        <Box flexDirection="row" key={`shared${index}`} marginTop={index === 0 ? 1 : 0}>
          <Box flexShrink={0} width={2}>
            <Text color={t.color.warn}>{'! '}</Text>
          </Box>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text color={t.color.warn} wrap="wrap">
              {`shares ${src.source} with a related forecast — weigh as possibly non-independent`}
            </Text>
          </Box>
        </Box>
      ))}
    </>
  )
}

function DecisionCard({ item, t }: { item: ForecastWorkspaceItem; t: Theme }) {
  const issues = item.decision_readiness_issues ?? []
  const hasCard = item.decision_owner || item.action_threshold || (item.update_triggers?.length ?? 0) > 0

  if (!hasCard && !issues.length) {
    return null
  }

  return (
    <>
      <SectionTitle t={t}>decision card</SectionTitle>
      <KV k="owner" t={t} v={item.decision_owner || '—'} />
      <KV k="deadline" t={t} v={shortDate(item.decision_deadline)} />
      <KV k="action" t={t} v={item.action_threshold || '—'} />
      {(item.update_triggers ?? []).slice(0, 4).map((trigger, i) => (
        <WrapLine
          body={trigger.mechanism ?? '—'}
          key={i}
          pad={0}
          prefix={(i === 0 ? 'triggers' : '').padEnd(13)}
          prefixColor={t.color.label}
          suffix={trigger.threshold ? ` [${trigger.threshold}]` : undefined}
          suffixColor={t.color.label}
          t={t}
        />
      ))}
      {issues.length ? (
        <WrapLine
          body={issues.join(' · ')}
          bodyColor={t.color.warn}
          pad={0}
          prefix={'readiness'.padEnd(13)}
          prefixColor={t.color.warn}
          t={t}
        />
      ) : null}
    </>
  )
}

// ── Thesis read (the right pane when the cursor is on a thesis row) ──────────
// Mirrors the web ThesisTrendBlock + ThesisDeskRead + ThesisComponentRow: leads
// with the health trend (health probability series + the score band), then the
// aggregate stats (score, 90% band, coverage, n_eff, ρ), the analyst note, the
// member-contribution table, and an uncertainty caveat. Withheld values render
// as "—" / "withheld", never a fake number.

const pctOf = (value?: null | number): string => (finite(value) ? `${(value * 100).toFixed(0)}%` : '—')

const fixedOr = (value: null | number | undefined, digits: number): string =>
  finite(value) ? value.toFixed(digits) : '—'

// The THESIS SCORE is a 0–100 strength INDEX (after weighting/coverage/effective-
// breadth), NOT a probability — so it always carries its "/100" unit so a glance
// can never confuse it with the 0–100% health probability. A withheld score is
// "—" (never faked). Optionally appends the score band as "54/100 (41–100)".
export const scoreText = (
  score: null | number | undefined,
  band?: { q05?: null | number; q95?: null | number } | null
): string => {
  if (!finite(score)) {
    return '—'
  }
  const head = `${score.toFixed(0)}/100`
  if (band && finite(band.q05) && finite(band.q95)) {
    return `${head} (${band.q05.toFixed(0)}–${band.q95.toFixed(0)})`
  }
  return head
}

// The thesis health time-series as a band chart (health probability with the
// score band shown as the y-zoom). Distinct from the forecast band chart only in
// that its series is the thesis's rolling health.
export const thesisHealthBandPoints = (thesis: ForecastThesis): BandPoint[] =>
  (thesis.history ?? []).map(point => ({
    hi: null,
    lo: null,
    y: finite(point.headline_probability) ? point.headline_probability : null
  }))

function ThesisTrendBlock({ thesis, t, width }: { thesis: ForecastThesis; t: Theme; width: number }) {
  const points = useMemo(() => thesisHealthBandPoints(thesis), [thesis])
  const hasSeries = points.filter(point => finite(point.y)).length >= 2
  const scale = useMemo(() => chartScale(points), [points])

  const chart = useMemo(
    () => (hasSeries ? bandChart(points, { height: 7, width: Math.min(56, Math.max(1, width - 1)), ...scale }) : null),
    [points, hasSeries, scale, width]
  )

  const band = thesis.score_band
  const health = thesis.health_probability
  const delta = thesis.delta
  // The glyph carries the sign; the number is the magnitude in health pp.
  const deltaText = finite(delta) ? `${delta >= 0 ? '▲' : '▼'} ${Math.abs(Math.round(delta * 100))}pp` : '· flat'
  const deltaColor = !finite(delta) || Math.abs(delta) < 1e-9 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error

  return (
    <Box flexDirection="column">
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>health </Text>
        <Text bold color={healthColor(t, health)}>
          {thesis.health_display ?? (finite(health) ? pct(health) : 'withheld')}
        </Text>
        <Text color={t.color.label}> alive</Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text bold color={deltaColor}>
          {deltaText}
        </Text>
        <Text color={t.color.muted}>{'   score '}</Text>
        <Text bold color={t.color.text}>
          {scoreText(thesis.thesis_score, band)}
        </Text>
        <Text color={t.color.label}> strength</Text>
        <Text color={t.color.muted}>{`   ${thesis.freshness ?? shortDate(thesis.as_of)}`}</Text>
      </Text>
      {chart ? (
        <>
          <SectionTitle t={t}>health over time</SectionTitle>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
          <Text color={t.color.label} wrap="truncate-end">
            {`  ${shortDate(thesis.history?.[0]?.as_of)} → ${shortDate(thesis.as_of)}  ● health`}
          </Text>
        </>
      ) : (
        <Box marginTop={1}>
          <Text color={t.color.muted}>awaiting a second aggregation for a trend</Text>
        </Box>
      )}
    </Box>
  )
}

function ThesisComponentRow({ comp, t, width }: { comp: ForecastThesisComponent; t: Theme; width: number }) {
  const s = comp.s_i
  const signalColor = !finite(s) ? t.color.muted : s >= 0.5 ? t.color.ok : t.color.error
  const dir = comp.direction === 'inverted' ? '↓risk' : '↑supp'
  const dirColor = comp.direction === 'inverted' ? t.color.error : t.color.ok
  const belief = (comp.latest_belief_display ?? '—').padStart(6)
  const signal = (finite(s) ? `${(s * 100).toFixed(0)}%` : '—').padStart(5)

  const contrib = finite(comp.contribution_pts)
    ? `${comp.contribution_pts >= 0 ? '+' : ''}${comp.contribution_pts.toFixed(1)}`
    : '—'

  const stale = comp.status && comp.status !== 'ok'
  // marker gaps: dir(6) gap belief(6) gap signal(5) gap contrib(~6) → reserve ~31
  const titleW = Math.max(8, width - 32)
  const title = truncate(comp.title ?? comp.id ?? 'member', titleW).padEnd(titleW)

  return (
    <Text wrap="truncate-end">
      <Text bold color={dirColor}>
        {dir.padEnd(6)}
      </Text>
      <Text color={t.color.text}>{title}</Text>
      <Text color={t.color.label}> {belief}</Text>
      <Text color={signalColor}> {signal}</Text>
      <Text color={t.color.primary}> {contrib.padStart(6)}</Text>
      {stale ? <Text color={t.color.warn}> {comp.status}</Text> : null}
    </Text>
  )
}

// Suitability color: green ≥0.6, amber ≥0.45, red below; withheld (null) → muted.
// The §22 per-name read shares the thesis's health bands so a "well-suited" name
// reads the same green as a healthy thesis.
const suitabilityColor = (t: Theme, suitability?: null | number): string =>
  !finite(suitability) ? t.color.muted : suitability >= 0.6 ? t.color.ok : suitability >= 0.45 ? t.color.warn : t.color.error

// One ENTITY SUITABILITY row: name (+kind), the 0..1 suitability (colored by
// level), the stance/action read, the signed delta in pp, and the top driver.
// A withheld suitability shows "withheld"/"—", never a fabricated number.
function ThesisEntityRow({ entity, t, width }: { entity: ForecastThesisEntity; t: Theme; width: number }) {
  const suitability = entity.suitability
  const suitText = (entity.suitability_display ?? (finite(suitability) ? pctOf(suitability) : 'withheld')).padStart(8)
  const read = entity.action || entity.stance || entity.trend || '—'
  const delta = entity.delta
  // The glyph carries the sign; the number is the magnitude in suitability pp.
  const deltaText = finite(delta) ? `${delta >= 0 ? '▲' : '▼'}${Math.abs(Math.round(delta * 100))}pp` : '· flat'
  const deltaColor = !finite(delta) || Math.abs(delta) < 1e-9 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const driver = entity.top_driver ? truncate(entity.top_driver, Math.max(10, Math.floor(width * 0.3))) : ''
  // marker gaps: suit(8) gap read(~12) gap delta(~6) → reserve ~30 + driver tail
  const nameW = Math.max(8, width - 30 - (driver ? driver.length + 2 : 0))
  const name = truncate(entity.label ?? entity.name ?? 'entity', nameW).padEnd(nameW)

  return (
    <Text wrap="truncate-end">
      <Text color={t.color.text}>{name}</Text>
      <Text bold color={suitabilityColor(t, suitability)}>
        {' '}
        {suitText}
      </Text>
      <Text color={t.color.label}> {truncate(read, 12).padEnd(12)}</Text>
      <Text bold color={deltaColor}>
        {' '}
        {deltaText.padStart(6)}
      </Text>
      {entity.kind ? <Text color={t.color.muted}> {entity.kind}</Text> : null}
      {driver ? <Text color={t.color.muted}> · {driver}</Text> : null}
    </Text>
  )
}

// §22 per-name suitability: one row per entity (stock / candidate / sector …),
// sorted by suitability so the best-suited names lead. Only rendered when the
// thesis carries entities (empty on the first aggregation, or for theses with no
// per-name decomposition).
function ThesisEntities({ entities, t, width }: { entities: ForecastThesisEntity[]; t: Theme; width: number }) {
  if (!entities.length) {
    return null
  }

  // Sort by suitability desc; withheld (null) sinks to the bottom.
  const sorted = [...entities].sort(
    (a, b) => (finite(b.suitability) ? b.suitability : -1) - (finite(a.suitability) ? a.suitability : -1)
  )

  return (
    <>
      <SectionTitle t={t}>ENTITY SUITABILITY</SectionTitle>
      {sorted.map((entity, i) => (
        <ThesisEntityRow entity={entity} key={entity.top_driver_id ?? entity.name ?? entity.label ?? `e${i}`} t={t} width={width} />
      ))}
    </>
  )
}

// §10 trade triggers: the if-then rules a member signal move fires ("Power ▲
// +25pp → BE, IREN better suited"). The up/down glyph is colored green/red; the
// rule prose is taken verbatim from the trigger note. Empty on the first
// aggregation (no prior snapshot to diff against).
function ThesisTriggers({ triggers, t }: { triggers: ForecastThesisTrigger[]; t: Theme }) {
  if (!triggers.length) {
    return null
  }

  return (
    <>
      <SectionTitle t={t}>TRADE TRIGGERS</SectionTitle>
      {triggers.map((trigger, i) => {
        const up = trigger.direction !== 'down'
        const glyph = up ? '▲' : '▼'
        const glyphColor = up ? t.color.ok : t.color.error
        const note = trigger.note || `${trigger.signal ?? 'signal'} ${glyph}`

        return (
          <Box flexDirection="row" key={trigger.member_id ?? `tr${i}`}>
            <Box flexShrink={0} width={2}>
              <Text bold color={glyphColor}>
                {glyph}
                {' '}
              </Text>
            </Box>
            <Box flexGrow={1} flexShrink={1} minWidth={0}>
              <Text color={t.color.text} wrap="wrap">
                {note}
              </Text>
            </Box>
          </Box>
        )
      })}
    </>
  )
}

export function ThesisDeskRead({ thesis, t, width }: { thesis: ForecastThesis; t: Theme; width: number }) {
  const note = thesis.analyst_note ?? null

  const comps = [...(thesis.components ?? [])].sort(
    (a, b) => (b.contribution_pts ?? 0) - (a.contribution_pts ?? 0)
  )

  const band = thesis.score_band
  const members = thesis.member_count ?? comps.length
  const topics = (thesis.topics ?? []).join(', ')

  return (
    <Box flexDirection="column">
      <Text bold color={t.color.primary} wrap="truncate-end">
        {thesis.title ?? thesis.id}
      </Text>
      <Text wrap="truncate-end">
        {thesis.domain ? <Text color={t.color.label}>{thesis.domain}</Text> : null}
        {thesis.status ? (
          <Text color={thesis.status === 'active' ? t.color.ok : t.color.label}>
            {thesis.domain ? ' · ' : ''}
            {thesis.status}
          </Text>
        ) : null}
        <Text color={t.color.muted}>{`${thesis.domain || thesis.status ? ' · ' : ''}${members} member${members === 1 ? '' : 's'}`}</Text>
        {topics ? <Text color={t.color.muted}> · {topics}</Text> : null}
      </Text>
      {thesis.aggregate_stale ? (
        <Text color={t.color.warn} wrap="truncate-end">
          ⚠ stale — a member moved since the last aggregate; health + contributions are catching up
        </Text>
      ) : null}

      <Box marginTop={1}>
        <ThesisTrendBlock t={t} thesis={thesis} width={width} />
      </Box>

      <SectionTitle t={t}>aggregate</SectionTitle>
      <Text color={t.color.muted} wrap="truncate-end">
        {'health = probability it is still alive · score = 0–100 strength index'}
      </Text>
      <KV k="health %" t={t} v={`${thesis.health_display ?? (finite(thesis.health_probability) ? pct(thesis.health_probability) : 'withheld')} alive`} />
      <KV k="score /100" t={t} v={`${scoreText(thesis.thesis_score)} strength`} />
      <KV
        k="score band"
        t={t}
        v={band && finite(band.q05) && finite(band.q95) ? `${band.q05.toFixed(0)} – ${band.q95.toFixed(0)} /100` : '—'}
      />
      <KV k="coverage" t={t} v={pctOf(thesis.coverage)} />
      <KV k="n_eff" t={t} v={fixedOr(thesis.n_eff, 1)} />
      <KV k="rho" t={t} v={fixedOr(thesis.rho, 2)} />

      {note ? (
        <AnalystNote
          note={note}
          showStance={false}
          t={t}
          variant={note.kind === 'retrospective' ? 'retrospective' : 'quickread'}
          width={width}
        />
      ) : (
        <Box marginTop={1}>
          <Text color={t.color.muted}>no thesis note yet</Text>
        </Box>
      )}

      <SectionTitle t={t}>member contributions</SectionTitle>
      <Text color={t.color.muted} wrap="truncate-end">
        {'dir'.padEnd(6)}
        {'member'.padEnd(Math.max(8, width - 32))}
        {' '}
        {'belief'.padStart(6)}
        {' '}
        {'signal'.padStart(5)}
        {' '}
        {'contrib'.padStart(7)}
      </Text>
      {comps.length ? (
        comps.map((comp, i) => <ThesisComponentRow comp={comp} key={comp.id ?? `c${i}`} t={t} width={width} />)
      ) : (
        <Text color={t.color.muted}>no members tagged yet</Text>
      )}

      <ThesisEntities entities={thesis.entities ?? []} t={t} width={width} />

      <ThesisTriggers t={t} triggers={thesis.triggers ?? []} />

      <SectionTitle t={t}>caveats</SectionTitle>
      <Box paddingLeft={2}>
        <Text color={t.color.warn} wrap="wrap">
          {`Aggregated after the members' latest runs; members co-move (ρ ${fixedOr(thesis.rho, 2)}, n_eff ~${fixedOr(
            thesis.n_eff,
            1
          )} of ${thesis.components?.length ?? 0}). Coverage ${pctOf(thesis.coverage)}.`}
        </Text>
      </Box>
    </Box>
  )
}

// ── Factor read (the right pane when the cursor is on a factor row) ──────────
// Mirrors ThesisDeskRead but for a weighted return basket: leads with the
// return trend (the mean series with its 90% band as the chart), then the
// aggregate return stats (mean, vol σ, 90% band, downside, CVaR, coverage,
// n_eff), the analyst note, the constituent-contribution table, and an
// uncertainty caveat. Withheld values render as "—" / "withheld", never faked.

// The factor return time-series as a band chart: the mean (headline_probability)
// with the snapshot's own 90% interval (band_low=q05 / band_high=q95) shown as
// the band. Distinct from the thesis health chart only in that its series is the
// factor's rolling return rather than a health probability.
export const factorReturnBandPoints = (factor: ForecastFactor): BandPoint[] =>
  (factor.history ?? []).map(point => ({
    hi: finite(point.band_high) ? point.band_high : null,
    lo: finite(point.band_low) ? point.band_low : null,
    y: finite(point.headline_probability) ? point.headline_probability : null
  }))

function FactorTrendBlock({ factor, t, width }: { factor: ForecastFactor; t: Theme; width: number }) {
  const points = useMemo(() => factorReturnBandPoints(factor), [factor])
  const hasSeries = points.filter(point => finite(point.y)).length >= 2
  const scale = useMemo(() => chartScale(points), [points])

  const chart = useMemo(
    () => (hasSeries ? bandChart(points, { height: 7, width: Math.min(56, Math.max(1, width - 1)), ...scale }) : null),
    [points, hasSeries, scale, width]
  )

  const mean = factor.mean
  const unit = unitSuffix(factor.units)
  const delta = factor.delta
  // The glyph carries the sign; the number is the magnitude of the return move.
  const deltaText = finite(delta) ? `${delta >= 0 ? '▲' : '▼'} ${trimNum(Math.abs(delta))}${unit}` : '· flat'
  const deltaColor = !finite(delta) || Math.abs(delta) < 1e-9 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error

  return (
    <Box flexDirection="column">
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>μ </Text>
        <Text bold color={signColor(t, mean)}>
          {finite(mean) ? `${trimNum(mean)}${unit}` : 'withheld'}
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text bold color={deltaColor}>
          {deltaText}
        </Text>
        <Text color={t.color.muted}>{'   vol σ '}</Text>
        <Text color={t.color.text}>{finite(factor.volatility) ? `${trimNum(factor.volatility)}${unit}` : '—'}</Text>
        <Text color={t.color.muted}>{`   ${factor.freshness ?? shortDate(factor.as_of)}`}</Text>
      </Text>
      {chart ? (
        <>
          <SectionTitle t={t}>return over time</SectionTitle>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={i}>
              {row}
            </Text>
          ))}
          <Text color={t.color.label} wrap="truncate-end">
            {`  ${shortDate(factor.history?.[0]?.as_of)} → ${shortDate(factor.as_of)}  ● mean  ░ 90% band`}
          </Text>
        </>
      ) : (
        <Box marginTop={1}>
          <Text color={t.color.muted}>awaiting a second aggregation for a trend</Text>
        </Box>
      )}
    </Box>
  )
}

// One CONSTITUENTS row: direction (long/short, colored), title, w_norm %, μ, σ,
// and contribution (signed, colored). A withheld moment renders "—", never a
// fabricated number.
function FactorConstituentRow({ comp, t, width }: { comp: ForecastFactorConstituent; t: Theme; width: number }) {
  const short = comp.direction === 'short'
  const dir = short ? 'short' : 'long'
  const dirColor = short ? t.color.error : t.color.ok
  const weight = (finite(comp.w_norm) ? `${(comp.w_norm * 100).toFixed(0)}%` : '—').padStart(5)
  const mean = (finite(comp.mean) ? trimNum(comp.mean) : '—').padStart(6)
  const sd = (finite(comp.sd) ? trimNum(comp.sd) : '—').padStart(5)

  const contrib = finite(comp.contribution)
    ? `${comp.contribution >= 0 ? '+' : ''}${trimNum(comp.contribution)}`
    : '—'

  const contribColor = signColor(t, comp.contribution)
  const stale = comp.status && comp.status !== 'ok'
  // marker gaps: dir(6) gap weight(5) gap mean(6) gap sd(5) gap contrib(~7) → reserve ~37
  const titleW = Math.max(8, width - 38)
  const title = truncate(comp.title ?? comp.id ?? 'constituent', titleW).padEnd(titleW)

  return (
    <Text wrap="truncate-end">
      <Text bold color={dirColor}>
        {dir.padEnd(6)}
      </Text>
      <Text color={t.color.text}>{title}</Text>
      <Text color={t.color.label}> {weight}</Text>
      <Text color={t.color.label}> {mean}</Text>
      <Text color={t.color.muted}> {sd}</Text>
      <Text color={contribColor}> {contrib.padStart(7)}</Text>
      {stale ? <Text color={t.color.warn}> {comp.status}</Text> : null}
    </Text>
  )
}

export function FactorDeskRead({ factor, t, width }: { factor: ForecastFactor; t: Theme; width: number }) {
  const note = factor.analyst_note ?? null
  const unit = unitSuffix(factor.units)

  // Constituents sorted by |contribution| desc so the biggest movers lead;
  // withheld contributions sink to the bottom.
  const comps = [...(factor.constituents ?? [])].sort(
    (a, b) => (finite(b.contribution) ? Math.abs(b.contribution) : -1) - (finite(a.contribution) ? Math.abs(a.contribution) : -1)
  )

  const members = factor.member_count ?? comps.length
  const topics = (factor.topics ?? []).join(', ')

  return (
    <Box flexDirection="column">
      <Text bold color={t.color.primary} wrap="truncate-end">
        {factor.title ?? factor.id}
      </Text>
      <Text wrap="truncate-end">
        {factor.domain ? <Text color={t.color.label}>{factor.domain}</Text> : null}
        <Text color={t.color.muted}>{`${factor.domain ? ' · ' : ''}${members} constituent${members === 1 ? '' : 's'}`}</Text>
        {factor.units ? <Text color={t.color.muted}> · {factor.units}</Text> : null}
        {topics ? <Text color={t.color.muted}> · {topics}</Text> : null}
      </Text>
      {factor.aggregate_stale ? (
        <Text color={t.color.warn} wrap="truncate-end">
          ⚠ stale — a constituent moved since the last aggregate; the portfolio read is catching up
        </Text>
      ) : null}

      <Box marginTop={1}>
        <FactorTrendBlock factor={factor} t={t} width={width} />
      </Box>

      <SectionTitle t={t}>Factor Return</SectionTitle>
      <Text color={t.color.muted} wrap="truncate-end">
        {'mean μ = expected return · vol σ = its volatility'}
      </Text>
      <KV k="mean μ" t={t} v={finite(factor.mean) ? `${trimNum(factor.mean)}${unit}` : 'withheld'} />
      <KV k="vol σ" t={t} v={finite(factor.volatility) ? `${trimNum(factor.volatility)}${unit}` : '—'} />
      <KV
        k="90% band"
        t={t}
        v={finite(factor.q05) && finite(factor.q95) ? `${trimNum(factor.q05)}${unit} – ${trimNum(factor.q95)}${unit}` : '—'}
      />
      <KV k="downside" t={t} v={finite(factor.downside) ? `${trimNum(factor.downside)}${unit}` : '—'} />
      <KV k="CVaR" t={t} v={finite(factor.cvar) ? `${trimNum(factor.cvar)}${unit}` : '—'} />
      <KV k="coverage" t={t} v={pctOf(factor.coverage)} />
      <KV k="n_eff" t={t} v={fixedOr(factor.n_eff, 1)} />

      {note ? (
        <AnalystNote
          note={note}
          showStance={false}
          t={t}
          variant={note.kind === 'retrospective' ? 'retrospective' : 'quickread'}
          width={width}
        />
      ) : (
        <Box marginTop={1}>
          <Text color={t.color.muted}>no factor note yet</Text>
        </Box>
      )}

      <SectionTitle t={t}>CONSTITUENTS</SectionTitle>
      <Text color={t.color.muted} wrap="truncate-end">
        {'dir'.padEnd(6)}
        {'constituent'.padEnd(Math.max(8, width - 38))}
        {' '}
        {'w'.padStart(5)}
        {' '}
        {'μ'.padStart(6)}
        {' '}
        {'σ'.padStart(5)}
        {' '}
        {'contrib'.padStart(7)}
      </Text>
      {comps.length ? (
        comps.map((comp, i) => <FactorConstituentRow comp={comp} key={comp.id ?? `fc${i}`} t={t} width={width} />)
      ) : (
        <Text color={t.color.muted}>no constituents tagged yet</Text>
      )}

      <SectionTitle t={t}>caveats</SectionTitle>
      <Box paddingLeft={2}>
        <Text color={t.color.warn} wrap="wrap">
          {`Portfolio-aggregated after the constituents' latest runs; constituents co-move ρ (n_eff ~${fixedOr(
            factor.n_eff,
            1
          )} of ${factor.constituents?.length ?? 0}). Coverage ${pctOf(factor.coverage)}.`}
        </Text>
      </Box>
    </Box>
  )
}
