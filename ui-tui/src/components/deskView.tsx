import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { Fragment, memo, type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from 'react'

import { forecastQuestionDetailSections } from '../app/forecastPanel.js'
import type { ReviewSweepState } from '../app/interfaces.js'
import { $globalModal, patchOverlayState } from '../app/overlayStore.js'
import { $reviewSweep } from '../app/uiStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastAnalystNote,
  ForecastBenchResponse,
  ForecastBenchRow,
  ForecastFactor,
  ForecastQuestionPacketResponse,
  ForecastReforecastStartResponse,
  ForecastReforecastStatusResponse,
  ForecastReviewsNextResponse,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'
import { sweepColor, sweepStops } from '../lib/accentSweep.js'
import {
  buildDeskTabs,
  type DeskTab,
  forecastsForTab,
  tabRefFactor,
  tabRefThesis
} from '../lib/deskGroups.js'
import { bandChart, deltaGlyph, levelSparkline, pct, shortDate, windowDelta } from '../lib/forecastCharts.js'
import { packetTailAudit } from '../lib/forecastTail.js'
import { type FieldSpec, filterRanked } from '../lib/fuzzyRank.js'
import { spinnerFrame } from '../lib/icons.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { sortIndicator, sortRows, type SortDir, type SortValue, useTableSort } from '../lib/tableSort.js'
import { dirColor, pad, readinessColor, type Semantics, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { ForecastPulse } from './appChrome.js'
import { DeskTabs as DeskTabsStrip } from './deskTabs.js'
import { ForecastSettingsModal } from './forecastSettingsModal.js'
import { ModalOverlay } from './modalOverlay.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import {
  AnalystNote,
  chartScale,
  deltaLabel,
  type EnsembleComponentRow,
  ensembleComponentRows,
  FactorDeskRead,
  finite,
  ForecastDetail,
  ForecastPacketTail,
  headlineCompact,
  healthColor,
  historyToBandPoints,
  panelFromPacket,
  scoreText,
  signColor,
  ThesisDeskRead,
  trimNum,
  truncate,
  unitSuffix
} from './forecastsWorkspace.js'
import { windowItems } from './overlayControls.js'

// ── Desk view (redesigned forecast workspace) ────────────────────────────────
// Mirrors the MARKETS view: a horizontal lens-tab strip (Tab/←/→/click) over a
// per-tab forecast LIST (Up/Down) + a SKINNY right summary panel; Enter opens a
// full-detail MODAL; '/' is an inline filter; q/Esc close. The heavy detail
// content (ForecastDetail, ThesisDeskRead, FactorDeskRead, packet tail, analyst
// log) is REUSED verbatim from forecastsWorkspace.tsx — this file owns only the
// orchestration + the skinny summary.

// Below this terminal width the desk collapses to a list-only column; Enter then
// opens a full-screen (rather than centered overlay) modal. Matches the WIDE_COLS
// threshold the old workspace used.
const WIDE_COLS = 100

// A shared frozen empty id-set: the "no agent job running" remaining set. A stable
// reference keeps the list rows byte-identical at rest (the memoised rows bail out).
const EMPTY_ID_SET: ReadonlySet<string> = new Set<string>()

// Packet sections rendered under the visual summary inside the modal — the
// long-form content the skinny panel + ForecastDetail summary omit.
const TAIL_SECTION_TITLES = new Set<string>([
  'Forecast History',
  'Assumptions And References',
  'Model Runs',
  'Actions'
])

// Field weights for the `/` filter — same as forecastsWorkspace so the two desks
// agree on what matches.
const FORECAST_SEARCH_FIELDS: FieldSpec<ForecastWorkspaceItem>[] = [
  { get: i => i.title, weight: 1 },
  { get: i => i.domain, weight: 0.6 },
  { get: i => i.topics, weight: 0.5 },
  { get: i => i.id, weight: 0.3 }
]

// ── Mass forced re-run ("run en masse") ──────────────────────────────────────
// The operator can mark a set of rows (Space toggles, Shift+↑/↓ extends) and fan
// the REAL update / re-arm over every one. Each outcome is classified HONESTLY so
// the completion summary never claims success for a row that had nothing to do.
export type MassOutcome = 'error' | 'noSources' | 'refreshed' | 'unchanged'
export type MassTally = Record<MassOutcome, number>

interface MassProgress {
  current: number
  title: string
  total: number
  verb: 're-arming' | 'updating'
}

// Classify one `forecast refresh <id> --json` result. The forecast.command RPC
// returns `{ code, output }`: a non-zero exit is an error; otherwise the --json
// payload's `status` distinguishes a committed update from a no-op (`no_change`)
// or a sourceless question (`no_watched_sources`). Anything unrecognised (or a
// non-JSON body) is treated as a real refresh — the conservative default only
// down-grades to unchanged/no-sources on an explicit honest signal.
export const classifyRefresh = (raw: unknown): MassOutcome => {
  const env = raw as { code?: unknown; output?: unknown } | null | undefined
  if (env && typeof env.code === 'number' && env.code !== 0) {
    return 'error'
  }
  const out = env && typeof env.output === 'string' ? env.output : ''
  let status: null | string = null
  if (out) {
    try {
      const parsed = JSON.parse(out) as { status?: unknown }
      status = typeof parsed.status === 'string' ? parsed.status : null
    } catch {
      // Non-JSON (or JSON with log-line noise) — scan for the status token.
      const m = /"status"\s*:\s*"([a-z_]+)"/i.exec(out)
      status = m ? m[1]! : null
    }
  }
  switch (status) {
    case 'no_watched_sources':
      return 'noSources'

    case 'no_change':
      return 'unchanged'

    default:
      return 'refreshed'
  }
}

// The honest completion summaries — "✓ 7 updated · 3 unchanged · 7 no sources".
// The updated count is always shown (even 0, so a run that refreshed nothing says
// so); the rest only when non-zero.
export const summarizeUpdate = (t: MassTally): string => {
  const parts = [`${t.refreshed} updated`]
  if (t.unchanged) {
    parts.push(`${t.unchanged} unchanged`)
  }
  if (t.noSources) {
    parts.push(`${t.noSources} no sources`)
  }
  if (t.error) {
    parts.push(`${t.error} failed`)
  }
  return `✓ ${parts.join(' · ')}`
}

export const summarizeRearm = (t: MassTally): string => {
  const parts = [`${t.refreshed} re-armed`]
  if (t.error) {
    parts.push(`${t.error} failed`)
  }
  return `✓ ${parts.join(' · ')}`
}

// ── Detached Desk agent job (A agent-run / T task) ───────────────────────────
// A single detached background job — the FULL formal reforecast flow (A) or a
// free-text task session (T) over an explicit batch — polled by run_id every ~5s.
// `targetIds` is the fixed set the job was launched over; `doneIds` accrues from
// the status `results[]`, so the remaining set (targetIds − doneIds) is the rows
// that still show the in-flight ⋯ gutter marker.
export interface AgentJob {
  runId: string
  mode: 'agent' | 'task'
  total: number
  done: number
  status: string
  current: { question_id?: string; stage?: string; title?: string } | null
  // Task mode: the latest progress[] note (the running commentary of the single
  // agent session). Agent mode drives the line from `current` instead.
  note?: string
  targetIds: Set<string>
  doneIds: Set<string>
}

// The HONEST completion toast for a detached job. Agent mode reports the gated
// outcome split parsed from results[] — committed (the commit landed), blocked
// (ran but the gate/saturation refused the commit), errors, and quorums started —
// so a run never claims a commit it didn't earn. Task mode leads with the agent's
// own task_summary (falling back to the same split when it withheld one).
export const summarizeAgentJob = (r: ForecastReforecastStatusResponse, mode: 'agent' | 'task'): string => {
  const results = r.results ?? []
  const committed = results.filter(x => x.committed).length
  const errors = results.filter(x => x.error).length
  const blocked = results.filter(x => !x.committed && !x.error).length
  const quorums = r.quorums_started ?? results.filter(x => x.quorum_autorun).length
  const parts = [`${committed} committed`]
  if (blocked) {
    parts.push(`${blocked} blocked`)
  }
  if (errors) {
    parts.push(`${errors} errors`)
  }
  if (quorums) {
    parts.push(`${quorums} quorum${quorums === 1 ? '' : 's'} started`)
  }
  const tally = `✓ ${parts.join(' · ')}`
  if (mode === 'task') {
    const summary = (r.task_summary ?? '').trim()
    return summary ? `✓ ${truncate(summary, 96)}` : tally
  }
  return tally
}

interface DeskViewProps {
  gw: GatewayClient
  initialId?: null | string
  onClose: () => void
  t: Theme
}

export function DeskView({ gw, initialId = null, onClose, t }: DeskViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const wide = cols >= WIDE_COLS
  // While the Ctrl+K palette / `?` cheat-sheet stacks above the desk, its own
  // useInput goes inert and its still-visible body mouse handlers are gated, so
  // nothing double-handles keys/clicks beneath the overlay.
  const globalModal = useStore($globalModal)
  // The gateway review due-sweeper's in-flight marker (object while running, else
  // null). Drives the spinner in the NEXT column + the summary status line. Scoped
  // so the desk re-renders only when a sweep starts/finishes, not on every status.
  const sweepRunning = useStore($reviewSweep)

  // Hydrate from the last workspace payload so reopening the desk is instant; it
  // then refreshes in the background. The cache survives unmount.
  const cachedWs = getOverlayCache<ForecastWorkspaceResponse>('forecast.workspace')

  const [payload, setPayload] = useState<ForecastWorkspaceResponse | null>(() => cachedWs ?? null)
  const [loading, setLoading] = useState(!cachedWs)
  const [error, setError] = useState<null | string>(null)
  const [tab, setTab] = useState(0)
  const [sel, setSel] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [filtering, setFiltering] = useState(false)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  // The review-sweep countdown snapshot (forecast.reviews.next): the sweeper's
  // next-tick time, the nightly fallback, and how many reviews are due. Pulled on
  // mount, lazily every ~60s while the desk is open, and on every sweep event.
  const [reviewsNext, setReviewsNext] = useState<ForecastReviewsNextResponse | null>(null)
  // `R` opens the modal and asks it to scroll to the Actions/resolve tail once
  // the packet's tail sections have loaded (async), then clears the request.
  const [resolveScroll, setResolveScroll] = useState(false)
  // Whether the OPEN modal was entered via `R` (resolve). Unlike `resolveScroll`
  // (a one-shot scroll request that clears after firing), this persists for the
  // whole modal session so the modal's own footer hint keeps pointing at the
  // Actions/resolve tail. Cleared when the modal closes.
  const [resolveContext, setResolveContext] = useState(false)

  // ── Mass selection + forced re-run (operator "run en masse") ────────────────
  // A per-lens Set of marked question ids: Space toggles the cursor row's mark
  // (mutt-style — advances after), Shift+↑/↓ extends the run. Cleared on a lens
  // switch and by the first Esc. Keyed by id (not index) so it survives the 90s
  // live re-pull / sweep reloads; ids that vanish from the book are pruned.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  // The in-flight mass run's live progress (null when idle). Drives the swept
  // progress flash; massRunningRef is the SYNC truth that gates re-triggers, and
  // unmountedRef stops the async loop from setState-after-unmount.
  const [massProgress, setMassProgress] = useState<MassProgress | null>(null)
  const massRunningRef = useRef(false)
  const unmountedRef = useRef(false)

  // ── Detached Desk agent job (A agent-run / T free-text task) ────────────────
  // ONE job at a time from this desk; agentRunningRef is the SYNC guard that gates
  // re-triggers. The job runs server-side and is polled by run_id; closing the desk
  // stops the poll (cleanup) but the job continues (detached — that is the point).
  const [agentJob, setAgentJob] = useState<AgentJob | null>(null)
  const agentRunningRef = useRef(false)
  // The T task modal: a free-text instruction over an explicit id batch. The id
  // batch is captured when T is pressed (so it can't drift from the live selection);
  // the modal owns the instruction text itself (updater-form state, safe against a
  // pasted multiline chunk) and hands it back on submit.
  const [taskOpen, setTaskOpen] = useState(false)
  const [taskTargetIds, setTaskTargetIds] = useState<string[]>([])

  // The detail packet (tail audit, ensemble, packet-tail sections) loads ASYNC
  // per selection and is rendered inside the modal only.
  const [packet, setPacket] = useState<ForecastQuestionPacketResponse | null>(null)
  const [packetId, setPacketId] = useState<null | string>(null)
  const initialIdRef = useRef(initialId)
  const modalScrollRef = useRef<null | ScrollBoxHandle>(null)

  // Stable references (the `?? []` fallbacks would otherwise allocate a fresh
  // array each render and churn every downstream memo).
  const items = useMemo(() => payload?.forecasts ?? [], [payload])
  const theses = useMemo(() => payload?.theses ?? [], [payload])
  const factors = useMemo(() => payload?.factors ?? [], [payload])

  const desk = useMemo(
    () => ({
      active: payload?.active_count ?? items.length,
      alerts: payload?.open_alert_count ?? 0,
      closing: payload?.closing_soon_count ?? 0,
      generatedAt: payload?.generated_at
    }),
    [payload, items.length]
  )

  const load = (announce = false) => {
    setLoading(!cachedWs)
    // Load the FULL active book so the list + `/` filter cover every question.
    gw.request<unknown>('forecast.workspace', { limit: 1000 })
      .then(raw => {
        const result = asRpcResult<ForecastWorkspaceResponse>(raw)

        if (!result) {
          setError('forecast.workspace returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('forecast.workspace', result)
        setPayload(result)
        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
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

  // The desk is LIVE, not mount-stale: external writers (the chat agent, the
  // nightly cron, a CLI in another terminal) commit snapshots while this view is
  // open, and a stale payload lies about AGE/PROB on rows the desk never touched
  // (the operator caught AGE frozen after a row updated). The payload build is
  // ~20ms server-side, so a quiet 90s re-pull is cheap; setLoading(!cachedWs)
  // keeps it flicker-free after the first paint and the id-tracked selection
  // keeps the cursor stable. Sweep-done / u / U reloads still fire immediately.
  useEffect(() => {
    const id = setInterval(() => load(), 90_000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // The review-sweep countdown read. Cheap + read-only, so it is safe to (re)pull
  // on mount and lazily every ~60s while the desk is open — bounded, cleared on
  // unmount (reusing the quorum-chip poll shape). A ref lets the sweep-event effect
  // below trigger the same pull without re-arming the interval.
  const pullReviewsNextRef = useRef<() => void>(() => undefined)
  useEffect(() => {
    let cancelled = false
    const pull = () => {
      gw.request<unknown>('forecast.reviews.next', {})
        .then(raw => {
          if (cancelled) return
          const r = asRpcResult<ForecastReviewsNextResponse>(raw)
          if (r) setReviewsNext(r)
        })
        .catch(() => {})
    }
    pullReviewsNextRef.current = pull
    pull()
    const id = setInterval(pull, 60_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [gw])

  // React to sweep events: whenever the running marker flips, re-pull the countdown
  // so the NEXT column / summary reflect the new state; when a sweep FINISHES (was
  // running, now cleared) also reload the workspace so the refreshed rows land.
  const prevSweepRef = useRef(sweepRunning)
  useEffect(() => {
    const was = prevSweepRef.current
    prevSweepRef.current = sweepRunning
    pullReviewsNextRef.current()
    if (was && !sweepRunning) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sweepRunning])

  useEffect(() => {
    // Drives OverlayScrollbar reflow detection while the modal is scrolled.
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (initialId) {
      initialIdRef.current = initialId
    }
  }, [initialId])

  // The ordered lens tabs (theses → factors → #tag-groups → Bench → All).
  const tabs = useMemo<DeskTab[]>(() => (payload ? buildDeskTabs(payload) : []), [payload])
  const activeTab = tabs[Math.min(tab, Math.max(0, tabs.length - 1))]
  const refThesis = tabRefThesis(activeTab, theses)
  const refFactor = tabRefFactor(activeTab, factors)

  // The Bench lens is a separate, read-only scoreboard surface — NOT the live
  // organic-forecast list. It loads its own `forecast.bench` payload (cached so
  // re-entry is instant) and renders a distinct agent-vs-market Brier table.
  const onBench = activeTab?.kind === 'bench'
  const cachedBench = getOverlayCache<ForecastBenchResponse>('forecast.bench')
  const [bench, setBench] = useState<ForecastBenchResponse | null>(() => cachedBench ?? null)
  const [benchLoading, setBenchLoading] = useState(false)

  useEffect(() => {
    if (!onBench) return
    if (!cachedBench) setBenchLoading(true)
    let cancelled = false
    gw.request<unknown>('forecast.bench', {})
      .then(raw => {
        if (cancelled) return
        const result = asRpcResult<ForecastBenchResponse>(raw)
        if (result) {
          setOverlayCache('forecast.bench', result)
          setBench(result)
        }
        setBenchLoading(false)
      })
      .catch(() => {
        if (!cancelled) setBenchLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onBench, gw])

  // The forecasts under the active tab, ranked by the `/` filter.
  const tabItems = useMemo(() => forecastsForTab(activeTab, items), [activeTab, items])
  const visible = useMemo(() => filterRanked(tabItems, query, FORECAST_SEARCH_FIELDS), [tabItems, query])

  // Column sort (`o` cycles the column, `O` toggles asc/desc, header click sorts).
  // Composes ON TOP of the `/` filter: we sort the already-filtered `visible` set.
  // Default state is unsorted → the original server/filter order is preserved.
  const sort = useTableSort(DESK_SORT_KEYS)
  // Minute-bucketed clock so the window/age/next sort values stay stable within a
  // minute (the memo doesn't re-sort on every 500ms reflow tick).
  const nowMinute = Math.floor(Date.now() / 60_000) * 60_000
  const sortedVisible = useMemo(
    () => sortRows(visible, sort.state.key, sort.state.dir, (it, k) => deskSortValue(it, k, nowMinute)),
    [visible, sort.state.key, sort.state.dir, nowMinute]
  )

  // The NEXT-column sweep context, memoised so it stays REFERENTIALLY STABLE while
  // idle (the memoised rows keep bailing out on the 500ms reflow tick) yet changes
  // every tick WHILE a sweep runs, so the spinner animates. `frame` only advances
  // while running; countdown math rides the minute-bucketed clock.
  const sweeper = reviewsNext?.sweeper
  const nightlyNextAt = reviewsNext?.nightly?.next_run_at
  const nextTickAt = sweeper?.next_tick_at
  const spinTick = sweepRunning ? now : 0
  const sweepCtx = useMemo<DeskSweepCtx>(
    () => ({
      frame: spinTick,
      nightlyNextAt: nightlyNextAt ? Date.parse(nightlyNextAt) : NaN,
      nextTickAt: nextTickAt ? Date.parse(nextTickAt) : NaN,
      nowMs: nowMinute,
      running: !!sweepRunning,
      sweeperEnabled: !!sweeper?.enabled
    }),
    [spinTick, nightlyNextAt, nextTickAt, nowMinute, sweepRunning, sweeper?.enabled]
  )

  // On a thesis/factor tab, a "lens row" leads the section (row 0) — a click/Enter
  // into the lens's own aggregate read. The cursor space is [lens?, ...forecasts].
  const hasLens = !!(refThesis || refFactor)
  const lensOffset = hasLens ? 1 : 0
  const rowCount = lensOffset + sortedVisible.length
  const clampedSel = Math.min(sel, Math.max(0, rowCount - 1))
  const lensActive = hasLens && clampedSel === 0
  const selected = lensActive ? null : sortedVisible[clampedSel - lensOffset] ?? null
  const selectedId = selected?.id ?? null

  // Keep the SELECTED forecast selected across a re-sort (track by id, not index):
  // a sort action stashes the current id, and once the re-sorted order lands we
  // move the cursor to wherever that id now sits. Only sort actions arm this — a
  // filter change / data reload leaves the ref null, so the cursor logic there is
  // untouched.
  const pendingReselectId = useRef<null | string>(null)
  useEffect(() => {
    const id = pendingReselectId.current
    if (id == null) return
    pendingReselectId.current = null
    const idx = sortedVisible.findIndex(it => it.id === id)
    if (idx >= 0) setSel(idx + lensOffset)
  }, [sortedVisible, lensOffset])

  const armReselect = () => {
    pendingReselectId.current = selectedId
  }
  const onSortCycle = () => {
    armReselect()
    sort.cycle()
  }
  const onSortToggle = () => {
    armReselect()
    sort.toggle()
  }
  const onSortByKey = (key: string) => {
    armReselect()
    sort.sortByKey(key)
  }

  useEffect(() => {
    // Resolve a pending `/forecast <id>` jump: find the first tab that holds it,
    // switch to that tab, and park the cursor on the row.
    const pending = initialIdRef.current

    if (!pending || !tabs.length) {
      return
    }

    for (let ti = 0; ti < tabs.length; ti += 1) {
      const idx = tabs[ti].forecastIds.indexOf(pending)

      if (idx >= 0) {
        // Match the render-time lensOffset exactly: only offset when the tab's ref
        // actually resolves to a thesis/factor (not just by kind), else the cursor
        // could overshoot by one on a malformed payload.
        const tk = tabs[ti]
        const off =
          (tk.kind === 'thesis' && theses.some(h => h.id === tk.refId)) ||
          (tk.kind === 'factor' && factors.some(f => f.id === tk.refId))
            ? 1
            : 0
        initialIdRef.current = null
        setTab(ti)
        setSel(idx + off)
        setModalOpen(true)

        return
      }
    }

    // Not found in any tab (filtered out / unknown) — leave the cursor be.
    initialIdRef.current = null
  }, [tabs])

  // ── Per-selection detail packet (modal-only) ──────────────────────────────
  // The packet (tail audit, ensemble, packet-tail sections, cross-refs/lessons)
  // is consumed ONLY inside the modal — the skinny summary panel reads `selected`
  // directly. So gate the fetch on `modalOpen`: it no longer fires a gateway
  // round-trip on desk MOUNT or on every cursor move (which it did before — one
  // forecast.question RPC per arrow-key press), only when the modal is actually
  // opened on a selection. The modal's existing `loading detail…` state covers the
  // brief async fill.
  useEffect(() => {
    if (!modalOpen || !selectedId) {
      setPacket(null)
      setPacketId(null)

      return
    }

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
  }, [selectedId, gw, modalOpen])

  // Reset the modal scroll to the top whenever the selected entity changes.
  useEffect(() => {
    if (modalOpen) {
      modalScrollRef.current?.scrollTo?.(0)
    } else {
      // A closed modal drops any pending resolve-scroll request so the next
      // plain Enter-open starts at the top, not at the Actions tail.
      setResolveScroll(false)
      setResolveContext(false)
    }
  }, [selectedId, modalOpen])

  const packetTail = useMemo(() => {
    if (!packet || packetId !== selectedId) {
      return null
    }

    return forecastQuestionDetailSections(packet).filter(
      section => section.title && TAIL_SECTION_TITLES.has(section.title)
    )
  }, [packet, packetId, selectedId])

  // `R` (resolve) opened the modal asking for the Actions/resolve tail: once the
  // packet's tail sections have loaded, scroll to the bottom (Actions is last),
  // then consume the request so a later plain Enter-open still starts at the top.
  useEffect(() => {
    if (modalOpen && resolveScroll && packetTail && packetTail.length) {
      modalScrollRef.current?.scrollToBottom?.()
      setResolveScroll(false)
    }
  }, [modalOpen, resolveScroll, packetTail])

  const packetPanel = useMemo<ForecastWorkspacePanel | null>(
    () => (packet && packetId === selectedId ? panelFromPacket(packet.packet) : null),
    [packet, packetId, selectedId]
  )

  const tailAudit = useMemo(
    () => (packet && packetId === selectedId ? packetTailAudit(packet.packet) : null),
    [packet, packetId, selectedId]
  )

  const ensembleRows = useMemo<EnsembleComponentRow[]>(
    () => (packet && packetId === selectedId ? ensembleComponentRows(packet.packet) : []),
    [packet, packetId, selectedId]
  )

  const tailLoading = !!selectedId && packetId !== selectedId

  const analystNotes = selected?.analyst_notes ?? []
  const latestNote = analystNotes.length ? analystNotes[analystNotes.length - 1] : null
  const priorNotes = analystNotes.slice(0, -1).reverse()

  // Cross-pollination + lessons are gated out of the workspace list for speed and
  // carried by forecast.question instead — merge them onto the item for the modal.
  // (Must live with the other hooks, ABOVE the loading/error early-returns.)
  const detailItem = useMemo(() => {
    if (!selected) return null
    if (!packet || packetId !== selectedId) return selected
    return {
      ...selected,
      related: packet.related ?? selected.related,
      relevant_lessons: packet.relevant_lessons ?? selected.relevant_lessons
    }
  }, [selected, packet, packetId, selectedId])

  // Mark the desk unmounted so the mass-run loop's async tail never setState after
  // teardown (the loop checks unmountedRef before every state write / reschedule).
  useEffect(() => {
    unmountedRef.current = false
    return () => {
      unmountedRef.current = true
    }
  }, [])

  // Prune marks whose question left the book. A payload reload (90s re-pull, sweep
  // done, r) may retire a question; drop only its id. An unchanged set returns the
  // SAME reference so live marking isn't disturbed by a quiet re-pull.
  useEffect(() => {
    setSelectedIds(prev => {
      if (prev.size === 0) {
        return prev
      }
      const live = new Set(items.map(i => i.id).filter(Boolean))
      let changed = false
      const next = new Set<string>()
      for (const id of prev) {
        if (live.has(id)) {
          next.add(id)
        } else {
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [items])

  // RE-ATTACH on mount: agent jobs are DETACHED — they keep working when the
  // desk closes or the operator switches views, and without this the row
  // indicators + progress line silently vanish on reopen while the job grinds
  // on (the operator: "unclear if those 'A' agent runs persist when we move to
  // different tabs"). One forecast.reforecast.active call rehydrates the newest
  // live job; the status poller below then takes over.
  useEffect(() => {
    if (agentJob) {
      return
    }
    let cancelled = false
    gw.request<unknown>('forecast.reforecast.active', {})
      .then(raw => {
        if (cancelled) {
          return
        }
        const r = asRpcResult<{ jobs?: {
          done_count?: number
          mode?: string
          question_ids?: string[]
          run_id?: string
          status?: string
          total?: number
        }[] }>(raw)
        const live = r?.jobs?.[0]
        if (!live?.run_id) {
          return
        }
        agentRunningRef.current = true
        setAgentJob({
          current: null,
          done: live.done_count ?? 0,
          doneIds: new Set(),
          mode: live.mode === 'task' ? 'task' : 'agent',
          runId: live.run_id,
          status: live.status ?? 'running',
          targetIds: new Set(live.question_ids ?? []),
          total: live.total ?? (live.question_ids?.length ?? 0)
        })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // Poll the detached agent job's status every ~5s while the desk is open (bounded,
  // cleaned up — the quorum-chip poll shape). An immediate poll paints the first
  // progress frame; on done/error it toasts the HONEST tally, reloads the payload,
  // and clears the job (which tears the interval down). The job keeps running
  // server-side if the desk closes — the cleanup only stops the POLL, not the work.
  useEffect(() => {
    const job = agentJob
    if (!job?.runId) {
      return
    }
    const { mode, runId } = job
    let cancelled = false
    const poll = () => {
      gw.request<unknown>('forecast.reforecast.status', { run_id: runId })
        .then(raw => {
          if (cancelled) {
            return
          }
          const r = asRpcResult<ForecastReforecastStatusResponse>(raw)
          if (!r) {
            return
          }
          const results = r.results ?? []
          const doneIds = new Set((results.map(row => row.question_id).filter(Boolean) as string[]))
          if (r.status === 'done' || r.status === 'error') {
            agentRunningRef.current = false
            setAgentJob(null)
            setFlash(
              r.status === 'error' && r.error
                ? `agent failed: ${truncate(r.error, 80)}`
                : summarizeAgentJob(r, mode)
            )
            load() // reload once so the freshly-committed rows land
            return
          }
          const progress = r.progress ?? []
          setAgentJob(prev =>
            prev && prev.runId === runId
              ? {
                  ...prev,
                  current: r.current ?? null,
                  done: r.done_count ?? results.length,
                  doneIds,
                  note: progress.length ? progress[progress.length - 1] : prev.note,
                  status: r.status ?? prev.status
                }
              : prev
          )
        })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentJob?.runId, gw])

  // The rows still in flight (targetIds − doneIds) → a dim ⋯ gutter marker. Empty
  // (stable ref) when no job runs, so the list rows are byte-identical at rest.
  const agentRemaining = useMemo<ReadonlySet<string>>(() => {
    if (!agentJob) {
      return EMPTY_ID_SET
    }
    const rem = new Set<string>()
    for (const id of agentJob.targetIds) {
      if (!agentJob.doneIds.has(id)) {
        rem.add(id)
      }
    }
    return rem
  }, [agentJob])

  // Switch tabs reset the selection to row 0 (locked decision). The mark set is
  // per-lens, so a lens switch also clears it.
  const switchTab = (next: number) => {
    const n = Math.max(1, tabs.length)
    setTab(((next % n) + n) % n)
    setSel(0)
    setModalOpen(false)
    setSelectedIds(new Set())
  }

  // `u` — RE-ARM: mark the selected forecast (or, on a lens row, the thesis/factor)
  // as review-due-now via forecast.reforecast. This does NOT run a forecast — it
  // only re-arms the schedule so NEXT flips to "now" and the autonomous cron cycle
  // reforecasts it on its next tick. Labelled honestly ("re-arm"), distinct from
  // `U` (which runs a real update in-process now).
  const runRearm = () => {
    const targetId = lensActive ? (refThesis?.id ?? refFactor?.id) : selectedId
    const targetTitle = lensActive ? (refThesis?.title ?? refFactor?.title) : selected?.title
    if (!targetId) return
    setFlash(`↻ re-armed for next cycle: ${truncate(targetTitle ?? targetId, 32)}`)
    gw.request('forecast.reforecast', { id: targetId })
      .then(() => load()) // silent refresh (no 'refreshed' flash) so NEXT flips to "now" but the re-arm message stays
      .catch(() => setFlash('re-arm failed'))
  }

  // ── Mark set + mass forced re-run ──────────────────────────────────────────
  const clearSelection = () => setSelectedIds(new Set())

  // The question id at a given cursor row (null for the lead lens row, which has
  // no markable question).
  const rowIdAt = (rowIndex: number): null | string => {
    if (hasLens && rowIndex === 0) {
      return null
    }
    return sortedVisible[rowIndex - lensOffset]?.id ?? null
  }

  // Space — toggle the cursor row's mark, then advance one row (mutt-style). On
  // the lens row (no id) it just advances.
  const toggleMark = () => {
    const id = selectedId
    if (id) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }
        return next
      })
    }
    setSel(i => Math.min(Math.max(0, rowCount - 1), i + 1))
  }

  // Shift+↑/↓ — move the cursor AND mark both the anchor row and the row it lands
  // on, so a shift-run paints a contiguous range (marking the start row too).
  const extendSelection = (dir: -1 | 1) => {
    const from = clampedSel
    const to = Math.min(Math.max(0, rowCount - 1), from + dir)
    setSelectedIds(prev => {
      const next = new Set(prev)
      const a = rowIdAt(from)
      const b = rowIdAt(to)
      if (a) {
        next.add(a)
      }
      if (b) {
        next.add(b)
      }
      return next
    })
    setSel(to)
  }

  // The ordered (id, title) targets a mass run fans out over: an explicit marked
  // set wins; else — for `U` — a lens row means "every member of the lens"; else
  // the single cursor row (the legacy single-`U`/`u` behaviour). Order follows
  // the visible list.
  const massTargets = (kind: 'rearm' | 'update'): { id: string; title: string }[] => {
    if (selectedIds.size > 0) {
      return sortedVisible
        .filter(it => it.id && selectedIds.has(it.id))
        .map(it => ({ id: it.id!, title: it.title ?? it.id! }))
    }
    if (kind === 'update' && lensActive) {
      // `U` on the thesis/factor lens row → trigger every member question.
      return sortedVisible.filter(it => it.id).map(it => ({ id: it.id!, title: it.title ?? it.id! }))
    }
    if (!lensActive && selectedId) {
      return [{ id: selectedId, title: selected?.title ?? selectedId }]
    }
    return []
  }

  // `U` — REAL UPDATE NOW (`forecast refresh <id> --json`, per row) — or `u`'s
  // cheap re-arm (`forecast.reforecast`), fanned SEQUENTIALLY over every target
  // with a live swept progress flash. On completion it reloads once and flashes an
  // HONEST tally parsed per row (refreshed / unchanged / no-sources / failed),
  // then clears the marks. Re-triggers while a run is in flight are ignored; an
  // unmount cancels the loop cleanly.
  const runMass = (kind: 'rearm' | 'update') => {
    if (massRunningRef.current) {
      const p = massProgress
      setFlash(p ? `already ${p.verb} ${p.total}…` : 'already updating…')
      return
    }
    const targets = massTargets(kind)
    if (!targets.length) {
      setFlash(kind === 'update' ? 'select a forecast to update now' : 'select a forecast to re-arm')
      return
    }
    massRunningRef.current = true
    setFlash('') // clear any stale flash so only the live progress shows during the run
    const total = targets.length
    const verb: MassProgress['verb'] = kind === 'update' ? 'updating' : 're-arming'
    const tally: MassTally = { error: 0, noSources: 0, refreshed: 0, unchanged: 0 }

    const step = (i: number) => {
      if (unmountedRef.current) return
      if (i >= total) {
        massRunningRef.current = false
        setMassProgress(null)
        clearSelection()
        load() // one reload after the whole fan-out
        setFlash(kind === 'update' ? summarizeUpdate(tally) : summarizeRearm(tally))
        return
      }
      const { id, title } = targets[i]!
      setMassProgress({ current: i + 1, title: truncate(title, 32), total, verb })
      const req =
        kind === 'update'
          ? gw.request('forecast.command', { arg: `refresh ${id} --json`, argv: ['refresh', id, '--json'] })
          : gw.request('forecast.reforecast', { id })
      req
        .then((raw: unknown) => {
          tally[kind === 'update' ? classifyRefresh(raw) : 'refreshed'] += 1
        })
        .catch(() => {
          tally.error += 1
        })
        .finally(() => step(i + 1))
    }
    step(0)
  }

  // `A` — AGENT RUN: fan the FULL formal reforecast flow over the selection (marked
  // set, or a lens row → all its members, reusing massTargets) as ONE detached
  // background job. Confirm-free but HONEST: flash the scope, start the job, then
  // the poll effect drives the progress line + the completion tally. One job at a
  // time — a re-press while a job runs just flashes the running run_id.
  const runAgent = () => {
    if (agentRunningRef.current) {
      setFlash(`agent running: ${agentJob?.runId ?? '…'}`)
      return
    }
    const targets = massTargets('update')
    if (!targets.length) {
      setFlash('select a forecast for the agent')
      return
    }
    const ids = targets.map(target => target.id)
    agentRunningRef.current = true
    setFlash(
      `🧠 agent run: ${ids.length} question${ids.length === 1 ? '' : 's'}, ~${ids.length} LLM session${ids.length === 1 ? '' : 's'}`
    )
    gw.request<unknown>('forecast.reforecast.start', { question_ids: ids })
      .then(raw => {
        const r = asRpcResult<ForecastReforecastStartResponse>(raw)
        if (!r?.run_id) {
          agentRunningRef.current = false
          setFlash('agent start failed')
          return
        }
        setAgentJob({
          current: null,
          done: 0,
          doneIds: new Set(),
          mode: 'agent',
          runId: r.run_id,
          status: 'queued',
          targetIds: new Set(ids),
          total: r.total ?? ids.length
        })
        clearSelection()
      })
      .catch(() => {
        agentRunningRef.current = false
        setFlash('agent start failed')
      })
  }

  // `T` — TASK: capture the selection's id batch and open the free-text task modal.
  // Same one-job guard as A; the modal's Enter → submitTask below.
  const openTask = () => {
    if (agentRunningRef.current) {
      setFlash(`agent running: ${agentJob?.runId ?? '…'}`)
      return
    }
    const targets = massTargets('update')
    if (!targets.length) {
      setFlash('select a forecast for a task')
      return
    }
    setTaskTargetIds(targets.map(target => target.id))
    setTaskOpen(true)
  }

  // The T modal's Enter → dispatch forecast.desk.task over the captured batch, then
  // ride the SAME progress/poll surface as A (the status RPC is shared; spec.mode
  // 'task'). The modal already rejects an empty instruction, so `instruction` is
  // non-empty here.
  const submitTask = (instruction: string) => {
    if (agentRunningRef.current || !taskTargetIds.length) {
      setTaskOpen(false)
      return
    }
    const ids = taskTargetIds
    agentRunningRef.current = true
    setTaskOpen(false)
    setFlash(`🧠 task: ${ids.length} question${ids.length === 1 ? '' : 's'}`)
    gw.request<unknown>('forecast.desk.task', { instruction, question_ids: ids })
      .then(raw => {
        const r = asRpcResult<ForecastReforecastStartResponse>(raw)
        if (!r?.run_id) {
          agentRunningRef.current = false
          setFlash('task start failed')
          return
        }
        setAgentJob({
          current: null,
          done: 0,
          doneIds: new Set(),
          mode: 'task',
          runId: r.run_id,
          status: 'queued',
          targetIds: new Set(ids),
          total: r.total ?? ids.length
        })
        clearSelection()
      })
      .catch(() => {
        agentRunningRef.current = false
        setFlash('task start failed')
      })
  }

  // `R` — RESOLVE: open the question detail modal and scroll it to the Actions
  // section (bottom), where the `/forecast resolve …` playbook row lives. There is
  // no standalone resolve modal, so this reuses the detail modal's Actions tail.
  const openResolve = () => {
    if (lensActive || !selected) {
      setFlash('select a forecast to resolve')
      return
    }
    setFlash('resolve · see the Actions section (⤓ scrolled to it)')
    setResolveScroll(true)
    setResolveContext(true)
    setModalOpen(true)
  }

  // `n` — NEW QUESTION: the desk is a fullscreen overlay and the onboard modal is
  // another, so hand off by closing the desk and opening onboarding (the seam the
  // empty-state text — "press n to track a new one" — points at).
  const openNewQuestion = () => {
    patchOverlayState({ forecasts: false, forecastsInitialId: null, onboard: true })
  }

  // The id + title the settings modal targets: the selected forecast, or (on a
  // lens row) the lens thesis/factor itself.
  const settingsTargetId = lensActive ? (refThesis?.id ?? refFactor?.id ?? null) : selectedId
  const settingsTargetTitle = lensActive
    ? (refThesis?.title ?? refFactor?.title ?? null)
    : (selected?.title ?? null)

  const openSettings = () => {
    if (!settingsTargetId) return
    setModalOpen(false)
    setSettingsOpen(true)
  }

  const modalPageSize = Math.max(4, termRows - 12)

  useInput((ch, key) => {
    // The settings / task modals own the keyboard while open (each has its own
    // useInput); trap everything here so the desk can't double-handle a key.
    if (settingsOpen || taskOpen) {
      return
    }
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

      if (ch && !key.ctrl && !key.meta) {
        // Accept multi-char chunks (paste / fast typing), printable only.
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setSel(0)

          return setQuery(q => q + printable)
        }
      }

      return
    }

    // While the modal is open it owns input: scroll + close. (Markets pattern:
    // `if (modal) return` — here the modal has its own scroll handlers first.)
    if (modalOpen) {
      if (key.escape || ch === 'q') {
        return setModalOpen(false)
      }

      if (key.upArrow || ch === 'k' || key.wheelUp) {
        return modalScrollRef.current?.scrollBy?.(-2)
      }

      if (key.downArrow || ch === 'j' || key.wheelDown) {
        return modalScrollRef.current?.scrollBy?.(2)
      }

      if (key.pageUp || (key.ctrl && ch === 'u')) {
        return modalScrollRef.current?.scrollBy?.(-modalPageSize)
      }

      if (key.pageDown || (key.ctrl && ch === 'd')) {
        return modalScrollRef.current?.scrollBy?.(modalPageSize)
      }

      if (ch === 'g') {
        return modalScrollRef.current?.scrollTo?.(0)
      }

      if (ch === 'G') {
        return modalScrollRef.current?.scrollToBottom?.()
      }

      return
    }

    // ── Main keymap ─────────────────────────────────────────────────────────
    if (ch === 'q') {
      return onClose()
    }

    if (key.escape) {
      // Esc clears a non-empty selection FIRST, then an active filter, else closes.
      if (selectedIds.size > 0) {
        return clearSelection()
      }

      if (query) {
        return setQuery('')
      }

      return onClose()
    }

    if (ch === '/' && !onBench) {
      setQuery('')

      return setFiltering(true)
    }

    if (ch === 'r') {
      return load(true)
    }

    if (key.tab || key.rightArrow || ch === 'l') {
      return switchTab(tab + 1)
    }

    // `h` / `←` steps to the previous lens — `h` is back/left everywhere now
    // (Alerts/Agents use it the same way); the `?` cheat-sheet replaced the old
    // `h`-for-help so navigation stays consistent across views.
    if (key.leftArrow || ch === 'h') {
      return switchTab(tab - 1)
    }

    if (ch === '?') {
      return patchOverlayState({ cheatSheet: true })
    }

    // The Bench lens is a read-only scoreboard: no per-row selection, modal, update,
    // settings, or filter — only tab-switching + refresh apply. Trap the rest here.
    if (onBench) {
      return
    }

    if (ch === 'u') {
      return selectedIds.size > 0 ? runMass('rearm') : runRearm()
    }

    if (ch === 'U') {
      return runMass('update')
    }

    // `A` — AGENT RUN (detached full reforecast flow); `T` — free-text TASK modal.
    // Both fan over the selection (marked set, or a lens → all its members).
    if (ch === 'A') {
      return runAgent()
    }

    if (ch === 'T') {
      return openTask()
    }

    // Space — mark the cursor row (mutt-style, advances after). Shift+↑/↓ extends
    // the marked run. Both are inert on the read-only Bench lens (trapped above).
    if (ch === ' ') {
      return toggleMark()
    }

    if (key.shift && (key.upArrow || key.downArrow)) {
      return extendSelection(key.upArrow ? -1 : 1)
    }

    if (ch === 'R') {
      return openResolve()
    }

    if (ch === 'n') {
      return openNewQuestion()
    }

    if (ch === 's') {
      if (settingsTargetId) {
        return openSettings()
      }

      return
    }

    // `o` cycles the sort column (header order → unsorted); `O` toggles asc/desc.
    if (ch === 'o') {
      return onSortCycle()
    }

    if (ch === 'O') {
      return onSortToggle()
    }

    if (key.return) {
      if (lensActive || selected) {
        return setModalOpen(true)
      }

      return
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
      return setSel(i => Math.min(Math.max(0, rowCount - 1), i + 1))
    }

    if (ch === 'g') {
      return setSel(0)
    }

    if (ch === 'G') {
      return setSel(Math.max(0, rowCount - 1))
    }
  }, { isActive: !globalModal })

  // ── Header ──────────────────────────────────────────────────────────────
  const header = (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      {filtering || query ? (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            FORECASTS
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          <Text color={t.color.primary}>{'⌕ '}</Text>
          <Text color={t.color.text}>{query}</Text>
          {filtering ? (
            <Text color={t.color.primary} inverse>
              {' '}
            </Text>
          ) : null}
          <Text color={t.color.muted}>
            {`   ${query ? `${visible.length} matches · ` : ''}${filtering ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
          </Text>
        </Text>
      ) : (
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
          {selectedIds.size > 0 ? (
            <Text bold color={t.color.accent}>{` · ${selectedIds.size} selected`}</Text>
          ) : null}
        </Text>
      )}
    </Box>
  )

  // ── Empty / loading / error states ────────────────────────────────────────
  if (loading && !items.length) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box flexGrow={1}>
          <Text color={t.color.muted}>Loading forecast desk…</Text>
        </Box>
      </Box>
    )
  }

  if (error) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box flexDirection="column" flexGrow={1}>
          <Text color={t.color.error}>Failed to load forecasts: {error}</Text>
          <Text color={t.color.muted}>Press r to retry · q to close</Text>
        </Box>
      </Box>
    )
  }

  if (!items.length) {
    return (
      <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
        {header}
        <Box flexDirection="column" flexGrow={1}>
          <Text color={t.color.muted}>
            {'No active forecasts — press '}
            <Text color={t.color.accent}>n</Text>
            {' to track a new one.'}
          </Text>
        </Box>
      </Box>
    )
  }

  // ── Layout widths ─────────────────────────────────────────────────────────
  const width = Math.max(40, cols - 4)
  // Skinny summary ~30-44 cols; the list takes the rest. Mirrors marketsView's
  // detailWidth/tableWidth clamp pattern.
  const panelWidth = Math.max(30, Math.min(44, width - 40))
  const listWidth = Math.max(28, width - panelWidth - 2)
  const visibleRows = Math.max(3, termRows - 12)

  const listW = wide ? listWidth : cols - 2
  const list = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
      {hasLens ? (
        <DeskLensRow
          active={lensActive}
          onOpen={() => {
            if (modalOpen || settingsOpen || taskOpen || globalModal) return
            setSel(0)
            setModalOpen(true)
          }}
          refFactor={refFactor}
          refThesis={refThesis}
          t={t}
          width={listW}
        />
      ) : null}
      <DeskForecastList
        cursor={lensActive ? -1 : clampedSel - lensOffset}
        empty={query ? `No forecasts match "${query}".` : 'No forecasts under this lens.'}
        items={sortedVisible}
        markedIds={selectedIds}
        nowMs={Math.floor(Date.now() / 60_000) * 60_000}
        onSelect={i => { if (!modalOpen && !settingsOpen && !taskOpen && !globalModal) setSel(i + lensOffset) }}
        // The header sorts on click, but only while nothing modal is covering the
        // body — matches the row/tab click gating.
        onSort={modalOpen || settingsOpen || taskOpen || globalModal ? undefined : onSortByKey}
        runningId={agentJob?.current?.question_id ?? null}
        runningIds={agentRemaining}
        spinTick={agentJob ? now : 0}
        sortDir={sort.state.dir}
        sortKey={sort.state.key}
        sweep={sweepCtx}
        t={t}
        visibleRows={Math.max(3, visibleRows - (hasLens ? 2 : 0))}
        width={listW}
      />
    </Box>
  )

  // The skinny right panel. A one-line sweep status rides ABOVE the summary — but
  // only when something is due or a sweep is running (otherwise the quiet desk stays
  // quiet). It lives inside the panel, so a narrow terminal (which drops the panel
  // entirely) shows the NEXT-column behaviour alone, never a stray summary line.
  const panel = (
    <Box flexDirection="column" flexShrink={0} width={panelWidth}>
      <SweepStatusLine now={now} reviews={reviewsNext} sweepRunning={sweepRunning} t={t} />
      <AgentProgressLine agent={agentJob} now={now} t={t} width={panelWidth} />
      <DeskSummary
        latestNote={latestNote}
        refFactor={refFactor}
        refThesis={refThesis}
        rows={termRows}
        selected={selected}
        t={t}
        width={panelWidth}
      />
    </Box>
  )

  // ── Detail modal content (reused heavy components) ────────────────────────
  // Built LAZILY — only when the modal is actually open. Before, this whole
  // ForecastDetail/packet-tail/analyst-log element tree was allocated on every
  // desk render (every cursor move) and then thrown away because `modal` is gated
  // on `modalOpen`. Gating the construction here keeps steady-state scrolling
  // O(viewport) and skips the heavy detail subtree entirely while the modal is shut.
  const modalBody = modalOpen && selected
    ? (() => {
        const detailW = Math.max(20, (wide ? Math.min(cols - 10, 92) : cols - 6) - 4)

        return (
          <Box flexDirection="column" paddingBottom={2} paddingRight={1}>
            <ForecastDetail
              afterChart={
                latestNote ? (
                  <AnalystNote
                    note={latestNote}
                    showStance={selected.headline_kind !== 'distribution'}
                    t={t}
                    variant={latestNote.kind === 'retrospective' ? 'retrospective' : 'quickread'}
                    width={detailW}
                  />
                ) : null
              }
              ensembleRows={ensembleRows}
              item={detailItem ?? selected}
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
            {priorNotes.length ? <DeskAnalystLog notes={priorNotes} t={t} /> : null}
          </Box>
        )
      })()
    : null

  // The thesis/factor aggregate read leads the modal ONLY when the INSPECTED row
  // IS the lens row (Enter on the thesis/factor itself → `lensActive`). For a
  // MEMBER question (a `forecast` row under the lens) the modal must lead with
  // that question's own detail — never prepend the parent thesis/factor read just
  // because a lens is ACTIVE in the tab strip.
  const refRead = !modalOpen || !lensActive ? null : refThesis ? (
    <ThesisDeskRead t={t} thesis={refThesis} width={Math.max(20, (wide ? Math.min(cols - 10, 92) : cols - 6) - 4)} />
  ) : refFactor ? (
    <FactorDeskRead factor={refFactor} t={t} width={Math.max(20, (wide ? Math.min(cols - 10, 92) : cols - 6) - 4)} />
  ) : null

  const settingsModal = settingsOpen && settingsTargetId ? (
    <ForecastSettingsModal
      cols={cols}
      gw={gw}
      onClose={() => setSettingsOpen(false)}
      onSaved={() => {
        setFlash('settings saved')
        load() // silent refresh so the NEXT column reflects a cadence change
      }}
      questionId={settingsTargetId}
      rows={termRows}
      t={t}
      title={settingsTargetTitle ?? settingsTargetId}
    />
  ) : null

  // The `T` task modal: a free-text instruction over the captured id batch. Owns
  // its own keyboard (the desk useInput traps `taskOpen`); Enter → submitTask,
  // Esc cancels. On submit it rides the same detached-job progress/poll surface as A.
  const taskModal = taskOpen ? (
    <DeskTaskModal
      cols={cols}
      count={taskTargetIds.length}
      onCancel={() => setTaskOpen(false)}
      onSubmit={submitTask}
      rows={termRows}
      t={t}
    />
  ) : null

  const modal = modalOpen ? (
    <ModalOverlay
      cols={cols}
      footerHint={
        resolveContext
          ? '↑↓ scroll · Esc/q close · resolve → see the Actions section (⤓ below)'
          : '↑↓ scroll · PgUp/PgDn page · Esc/q close'
      }
      rows={termRows}
      scrollRef={modalScrollRef}
      t={t}
      tick={now}
      title={lensActive ? (refThesis?.title ?? refFactor?.title ?? 'Lens') : (selected?.title ?? selected?.id ?? 'Forecast')}
    >
      {refRead ? (
        <Box flexDirection="column" marginBottom={1}>
          {refRead}
        </Box>
      ) : null}
      {modalBody}
    </ModalOverlay>
  ) : null

  // ── Footer ────────────────────────────────────────────────────────────────
  // While the modal is open the chips are modal-specific — the main chips' run
  // callbacks would otherwise bypass the keyboard's `if (modalOpen) return` trap.
  const chips: FooterChip[] = modalOpen
    ? [
        { k: '↑↓', label: 'Scroll' },
        { k: 'g/G', label: 'Top/Bot' },
        { k: 'Esc', label: 'Close', run: () => setModalOpen(false) }
      ]
    : onBench
      ? [
          { k: '⇥', label: 'Lens', run: () => switchTab(tab + 1) },
          { k: 'r', label: 'Refresh', run: () => { setBenchLoading(true); gw.request<unknown>('forecast.bench', {}).then(raw => { const r = asRpcResult<ForecastBenchResponse>(raw); if (r) { setOverlayCache('forecast.bench', r); setBench(r) } setBenchLoading(false) }).catch(() => setBenchLoading(false)) } },
          { k: 'q', label: 'Close', run: onClose }
        ]
      : selectedIds.size > 0
        ? // With a selection the footer focuses on the mass actions (live-keys-only):
          // Update/Re-arm carry the live count, plus Mark/extend and the Esc clear.
          [
            { k: 'U', label: `Update (${selectedIds.size})`, run: () => runMass('update') },
            { k: 'u', label: `Re-arm (${selectedIds.size})`, run: () => runMass('rearm') },
            { k: 'A', label: `Agent (${selectedIds.size})`, run: () => runAgent() },
            { k: 'T', label: `Task (${selectedIds.size})`, run: () => openTask() },
            { k: 'Spc', label: 'Mark', run: () => toggleMark() },
            { k: '⇧↑↓', label: 'Extend' },
            { k: 'Esc', label: 'Clear', run: () => clearSelection() },
            { k: 'q', label: 'Close', run: onClose }
          ]
        : [
            { k: '↑↓', label: 'Select' },
            { k: '⇥', label: 'Lens', run: () => switchTab(tab + 1) },
            { k: '⏎', label: 'Open', run: () => (lensActive || selected) && setModalOpen(true) },
            { k: 'U', label: 'Update', run: () => runMass('update') },
            { k: 'u', label: 'Re-arm', run: () => runRearm() },
            { k: 'R', label: 'Resolve', run: () => openResolve() },
            { k: 'n', label: 'New', run: () => openNewQuestion() },
            { k: 's', label: 'Settings', run: () => openSettings() },
            { k: 'o', label: 'Sort', run: () => onSortCycle() },
            { k: '/', label: 'Filter', run: () => { setSel(0); setQuery(''); setFiltering(true) } },
            { k: 'q', label: 'Close', run: onClose }
          ]

  // When the selected row's review is overdue/stale, spell out the honest split:
  // `u` only re-arms the schedule, `U` runs a real update now. This is contextual
  // STATUS, not a shortcuts row — the FooterChips above are the single, canonical
  // key row (the old always-on prose duplicate was removed).
  const selectedDue = !onBench && !lensActive && selected ? dueText(selected, Math.floor(Date.now() / 60_000) * 60_000) : null
  const selectedStale = selectedDue?.status === 'now'
  const showStaleNote = !flash && !filtering && !modalOpen && !onBench && selectedStale

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {/* The FooterChips are the ONE shortcuts row (top row, per the operator).
          Gate chip mouse-runs while the settings modal owns the screen: the desk
          keyboard is already trapped (useInput early-returns on settingsOpen), so
          the still-visible footer must not leak clicks past that trap. The detail
          modal swaps to its own modal-only chip set, so it needs no gate here. */}
      <FooterChips chips={chips} disabled={settingsOpen || taskOpen || globalModal} t={t} />
      {/* An OPTIONAL status line — the in-flight mass-run progress (accent-swept,
          like the sweep indicator), else a transient flash / stale-review note. It
          only paints when there is something to say. */}
      {massProgress ? (
        <Text wrap="truncate-end">
          <Text color={sweepColor(sweepStops(t), now)}>
            {`↻ ${massProgress.verb} ${massProgress.current}/${massProgress.total} · ${massProgress.title}…`}
          </Text>
          {/* A re-trigger while the run is in flight parks its "already updating N…"
              guard note here (the run keeps going) rather than a duplicate fan-out. */}
          {flash ? <Text color={t.color.warn}>{`  ${flash}`}</Text> : null}
        </Text>
      ) : flash || showStaleNote ? (
        <Text wrap="truncate-end">
          {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
          {showStaleNote ? <Text color={t.color.warn}>stale · u re-arms next cycle · U updates now</Text> : null}
        </Text>
      ) : null}
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {/* The body stays mounted; the modal paints ABOVE it as an absolute overlay.
          Body clicks are gated while the modal is open (switchTab/onSelect early-
          return) so the still-visible tabs/rows can't leak interaction — the
          keyboard is already trapped by the `if (modalOpen) return` in useInput. */}
      <DeskTabsStrip active={tab} onSelect={i => { if (!modalOpen && !settingsOpen && !taskOpen && !globalModal) switchTab(i) }} t={t} tabs={tabs} width={width} />
      {onBench ? (
        // The Bench lens replaces the list+panel with its own read-only scoreboard
        // — bench questions never mix into the live organic-forecast list.
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          <BenchScoreboard bench={bench} loading={benchLoading} rows={visibleRows} t={t} width={width} />
        </Box>
      ) : wide ? (
        <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
          <Box flexDirection="column" flexShrink={0} width={listWidth}>
            {list}
          </Box>
          <Box flexDirection="column" flexShrink={0} marginLeft={1}>
            {panel}
          </Box>
        </Box>
      ) : (
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
          {list}
        </Box>
      )}
      {footer}
      {modalOpen ? modal : null}
      {settingsModal}
      {taskModal}
    </Box>
  )
}

// ── Sweep status line (skinny-panel header) ──────────────────────────────────
// One compact, honest line about the review due-sweep — and NOTHING when the desk
// is quiet (nothing due, no sweep running). WHILE a sweep runs: an animated
// spinner + "sweeping N due…". Otherwise, when reviews are due: a countdown to the
// gateway sweeper's next tick ("next sweep in Xm · N due"), or — when the sweeper
// is disabled — the nightly fallback ("N due · tonight") / a plain "N due".
export function SweepStatusLine({
  now,
  reviews,
  sweepRunning,
  t
}: {
  now: number
  reviews: ForecastReviewsNextResponse | null
  sweepRunning: null | ReviewSweepState
  t: Theme
}) {
  if (sweepRunning) {
    const dueCount = sweepRunning.dueCount ?? reviews?.due_count ?? 0
    // Reuse the Home chat's busy animation: the leading spinner glyph + the label
    // sweep the brand accent family via sweepColor(sweepStops(t), now) — the exact
    // mechanism appChrome's FaceTicker uses — and the ForecastPulse Δ pulses at the
    // tail (the same graphic the chat header floats). Both ride the desk's existing
    // `now` tick (500ms), so no new timer is introduced.
    const swept = sweepColor(sweepStops(t), now)
    return (
      <Text wrap="truncate-end">
        <Text color={swept}>{`${spinnerFrame(now)} sweeping ${dueCount} due… `}</Text>
        <ForecastPulse t={t} tick={now} />
      </Text>
    )
  }

  const due = reviews?.due_count ?? 0
  if (due <= 0) {
    return null
  }

  const sweeper = reviews?.sweeper
  if (sweeper?.enabled) {
    const tickAt = sweeper.next_tick_at ? Date.parse(sweeper.next_tick_at) : NaN
    const nowMs = Date.now()
    const imminent = !Number.isFinite(tickAt) || tickAt <= nowMs || tickAt - nowMs < 60000
    const label = imminent ? 'next sweep <1m' : `next sweep in ${Math.ceil((tickAt - nowMs) / 60000)}m`
    return (
      <Text color={t.color.muted} wrap="truncate-end">
        {`${label} · ${due} due`}
      </Text>
    )
  }

  // Sweeper disabled → the nightly cron is the only path. Show "tonight" only when
  // a nightly run is actually scheduled; otherwise just flag the count.
  return (
    <Text color={t.color.muted} wrap="truncate-end">
      {reviews?.nightly?.next_run_at ? `${due} due · tonight` : `${due} due`}
    </Text>
  )
}

// ── Detached agent-job progress line (skinny-panel header) ───────────────────
// A persistent, accent-swept one-liner while a detached A/T job runs — "🧠 agent
// 3/17 · <current title> · <stage>" — and NOTHING at rest. It sits directly under
// the sweep line in the summary panel, riding the desk's existing `now` tick so its
// colour sweeps the brand accent family in lock-step with the sweep spinner.
export function AgentProgressLine({
  agent,
  now,
  t,
  width
}: {
  agent: AgentJob | null
  now: number
  t: Theme
  width: number
}) {
  if (!agent) {
    return null
  }
  const inner = Math.max(16, width - 2)
  const label = agent.mode === 'task' ? 'task' : 'agent'
  const title = agent.current?.title ? ` · ${agent.current.title}` : ''
  const stage = agent.current?.stage ? ` · ${agent.current.stage}` : ''
  // Agent mode reads the per-question current title/stage; task mode (one session,
  // often no `current`) reads the latest progress[] note instead.
  const detail = agent.mode === 'task' && agent.note ? ` · ${agent.note}` : `${title}${stage}`
  const line = `🧠 ${label} ${agent.done}/${agent.total}${detail}`
  return (
    <Text color={sweepColor(sweepStops(t), now)} wrap="truncate-end">
      {truncate(line, inner)}
    </Text>
  )
}

// ── `T` task modal: free-text instruction over the selected batch ────────────
// A ModalOverlay form with a single free-text field (Enter submits, Esc cancels;
// a pasted multiline instruction survives intact). Owns its own keyboard — the desk
// useInput traps `taskOpen` — and goes inert while the palette / cheat-sheet stacks
// above. On submit the parent dispatches forecast.desk.task and rides the same
// detached-job progress/poll surface as A.
export function DeskTaskModal({
  cols,
  count,
  onCancel,
  onSubmit,
  rows,
  t
}: {
  cols: number
  count: number
  onCancel: () => void
  onSubmit: (instruction: string) => void
  rows: number
  t: Theme
}) {
  const globalModal = useStore($globalModal)
  // The modal OWNS the instruction (updater-form state, so a rapid/pasted multiline
  // chunk can't drop chars via a stale closure) and hands the trimmed text back on
  // submit — an empty instruction is rejected here (the server refuses one too).
  const [value, setValue] = useState('')
  useInput(
    (ch, key) => {
      if (key.escape) {
        return onCancel()
      }
      if (key.return) {
        // A bare Enter submits. (Multiline instructions arrive via paste — a pasted
        // chunk carries its own embedded newlines, with key.return unset.)
        const trimmed = value.trim()
        if (trimmed) {
          onSubmit(trimmed)
        }
        return
      }
      if (key.backspace || key.delete) {
        return setValue(v => v.slice(0, -1))
      }
      if (ch && !key.ctrl && !key.meta) {
        // Accept printable chars AND embedded newlines (bracketed paste) so a
        // multiline instruction survives intact.
        const printable = [...ch].filter(c => c >= ' ' || c === '\n').join('')
        if (printable) {
          setValue(v => v + printable)
        }
      }
    },
    { isActive: !globalModal }
  )

  const modalW = Math.max(48, Math.min(cols - 4, 84))
  const modalH = Math.max(10, Math.min(rows - 4, 16))
  const lines = value.length ? value.split('\n') : ['']

  return (
    <ModalOverlay cols={cols} footerHint="⏎ submit · Esc cancel" maxHeight={modalH} maxWidth={modalW} rows={rows} t={t} title="Agent task">
      <Box flexDirection="column" flexGrow={1} minHeight={0}>
        <Text color={t.color.muted} wrap="truncate-end">
          {`What should the agent do with these ${count} question${count === 1 ? '' : 's'}?`}
        </Text>
        <Box flexDirection="column" marginTop={1}>
          {value.length ? (
            lines.map((ln, i) => (
              <Text color={t.color.text} key={`tl:${i}`} wrap="truncate-end">
                {ln}
                {i === lines.length - 1 ? (
                  <Text color={t.color.text} inverse>
                    {' '}
                  </Text>
                ) : null}
              </Text>
            ))
          ) : (
            <Text wrap="truncate-end">
              <Text color={t.color.text} inverse>
                {' '}
              </Text>
              <Text color={t.color.muted}>{' e.g. add a watched source + a reference class, then reforecast'}</Text>
            </Text>
          )}
        </Box>
      </Box>
    </ModalOverlay>
  )
}

// ── Skinny right summary panel ───────────────────────────────────────────────
// Compact: a lens-aggregate header (thesis health / factor μ, when on a
// thesis/factor tab), then the forecast probability + delta + sparkline +
// status/impact + counts (panel/evidence/sources) + last-updated + a 1-line
// analyst teaser.

export function DeskSummary({
  latestNote,
  refFactor,
  refThesis,
  rows,
  selected,
  t,
  width
}: {
  latestNote: ForecastAnalystNote | null
  refFactor: ForecastFactor | undefined
  refThesis: ForecastThesis | undefined
  rows?: number
  selected: ForecastWorkspaceItem | null
  t: Theme
  width: number
}) {
  const inner = Math.max(16, width - 2)

  if (!selected) {
    // The lens row is selected → give the panel the same rich treatment as a
    // forecast: the lens's own aggregate + history graph + counts + teaser.
    if (refThesis || refFactor) {
      return <LensSummary refFactor={refFactor} refThesis={refThesis} rows={rows} t={t} width={width} />
    }

    return (
      <Box flexDirection="column" flexShrink={0} width={width}>
        <LensHeader refFactor={refFactor} refThesis={refThesis} t={t} width={inner} />
        <Text color={t.color.muted}>Select a forecast to see its summary.</Text>
      </Box>
    )
  }

  const delta = selected.delta
  const glyph = deltaGlyph(delta)
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error

  // Multi-row mini-graph of the headline series. bandChart is level-scaled (NOT
  // max-normalized like blockChart), so a flat 52% reads mid-height; the band
  // fills only for distributions (their snapshots carry a real 90% interval) —
  // binaries draw just the marker line, which is correct. Auto-zoom the y-axis to
  // the data + band range so small probability moves are actually visible.
  const bandPoints = historyToBandPoints(selected)
  const hasSeries = bandPoints.some(point => finite(point.y))
  const { yMax, yMin } = chartScale(bandPoints)
  // Adapt the graph height to the terminal so the rest of the skinny panel (counts,
  // freshness, close, teaser) never gets pushed past the bottom on a short screen.
  const chartHeight = Math.max(4, Math.min(7, (rows ?? 28) - 16))
  const chart = hasSeries
    ? bandChart(bandPoints, { height: chartHeight, width: inner, yMax, yMin })
    : null

  const teaser = latestNote?.headline || (latestNote?.body ?? '').slice(0, 120) || ''
  const sources = new Set((selected.evidence ?? []).map(e => e.source).filter(Boolean)).size
  const panelCount = selected.panel?.estimates?.length ?? 0

  return (
    <Box flexDirection="column" flexShrink={0} width={width}>
      <LensHeader refFactor={refFactor} refThesis={refThesis} t={t} width={inner} />

      <Text bold color={t.color.primary} wrap="truncate-end">
        {truncate(selected.title ?? selected.id ?? 'untitled', inner)}
      </Text>
      <Text wrap="truncate-end">
        {selected.domain ? <Text color={t.color.label}>{selected.domain}</Text> : null}
        {selected.impact ? (
          <Text color={t.color.muted}>
            {selected.domain ? ' · ' : ''}impact <Text color={t.color.warn}>{selected.impact}</Text>
          </Text>
        ) : null}
        {selected.status ? (
          <Text color={selected.status === 'active' ? t.color.ok : t.color.label}> · {selected.status}</Text>
        ) : null}
      </Text>

      <Box marginTop={1}>
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            {headlineCompact(selected)}
          </Text>
          <Text color={t.color.muted}>{'  '}</Text>
          <Text bold color={deltaColor}>
            {`${glyph} ${deltaLabel(selected).replace(/^· /, '')}`}
          </Text>
        </Text>
      </Box>
      {chart ? (
        <Box flexDirection="column" marginTop={1}>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={`band:${i}`} wrap="truncate-end">
              {row}
            </Text>
          ))}
          <Text color={t.color.muted} wrap="truncate-end">
            {selected.headline_kind === 'distribution' ? 'μ over time' : 'probability over time'}
          </Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="truncate-end">
          {`panel ${panelCount} · ev ${selected.evidence_count ?? 0} · src ${sources}`}
        </Text>
      </Box>
      {/* Under-saturated badge (Wave 3): only when the current snapshot scored
          below the alert bar — a compact "◌ saturation N/100 · below bar". Healthy
          forecasts show nothing, so the badge is a genuine attention signal. */}
      {selected.saturation_below_threshold ? (
        <Text color={t.color.warn} wrap="truncate-end">
          {`◌ saturation ${Math.round(selected.saturation_score ?? 0)}/100 · below bar`}
        </Text>
      ) : null}
      {/* In-flight auto-quorum chip: the payload only attaches quorum_run while a
          job for this question is queued/running (dashboard.py → active_quorum_by_q),
          so its mere presence means "a quorum is running right now". */}
      {selected.quorum_run?.run_id ? (
        <Text color={t.color.accent} wrap="truncate-end">
          {`⟳ quorum ${selected.quorum_run.status ?? 'running'}`}
        </Text>
      ) : null}
      {/* Machine-readiness: when the selected row has UNMET workability gaps, a
          compact score + up to 3 gap labels with their exact fix hints (muted, one
          truncated line each). A healthy row (no gaps) shows nothing — quiet desk. */}
      {selected.readiness && selected.readiness.gaps.length ? (
        <Box flexDirection="column" marginTop={1}>
          <Text wrap="truncate-end">
            <Text color={t.color.muted}>readiness </Text>
            <Text bold color={readinessColor(t, selected.readiness.score)}>
              {`${Math.round(selected.readiness.score)}/100`}
            </Text>
            <Text color={t.color.muted}>
              {` · ${selected.readiness.gaps.length} gap${selected.readiness.gaps.length === 1 ? '' : 's'}`}
            </Text>
          </Text>
          {selected.readiness.gaps.slice(0, 3).map(gap => (
            <Text color={t.color.muted} key={gap.key} wrap="truncate-end">
              {truncate(`· ${gap.label} — ${gap.fix_hint}`, inner)}
            </Text>
          ))}
        </Box>
      ) : null}
      <Text color={t.color.muted} wrap="truncate-end">
        {`updated ${shortDate(selected.as_of)}${selected.freshness ? ` (${selected.freshness})` : ''}`}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        {`${selected.snapshot_count ?? 0} update${(selected.snapshot_count ?? 0) === 1 ? '' : 's'} · close ${shortDate(selected.close_time)}`}
      </Text>

      {teaser ? (
        <Box marginTop={1}>
          <Text color={t.color.text} wrap="wrap">
            {truncate(teaser, inner * 2)}
          </Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.color.accent} wrap="truncate-end">
          ⏎ open full detail
        </Text>
      </Box>
    </Box>
  )
}

// The skinny-panel summary when the LENS ROW is selected — the lens's own
// aggregate + history graph + counts + analyst teaser, mirroring the forecast
// summary so the panel is never blank on a lens row.
function LensSummary({
  refFactor,
  refThesis,
  rows,
  t,
  width
}: {
  refFactor: ForecastFactor | undefined
  refThesis: ForecastThesis | undefined
  rows?: number
  t: Theme
  width: number
}) {
  const inner = Math.max(16, width - 2)
  const title = (refThesis?.title ?? refFactor?.title) ?? 'Lens'
  const delta = refThesis?.delta ?? refFactor?.delta ?? null
  const glyph = deltaGlyph(delta)
  const deltaColor = !finite(delta) || Math.abs(delta) < 0.005 ? t.color.muted : delta > 0 ? t.color.ok : t.color.error
  const unit = unitSuffix(refFactor?.units)

  // The health series (thesis) / return series (factor) over time. Factors carry
  // a real q05–q95 band; theses plot the health line (the score band is a
  // different 0–100 scale, so it isn't drawn here).
  const bandPoints = refFactor
    ? (refFactor.history ?? []).map(p => ({ hi: p.band_high ?? null, lo: p.band_low ?? null, y: p.headline_probability ?? null }))
    : (refThesis?.history ?? []).map(p => ({ y: p.headline_probability ?? null }))
  const hasSeries = bandPoints.some(p => finite(p.y))
  const { yMax, yMin } = chartScale(bandPoints)
  const chartHeight = Math.max(4, Math.min(7, (rows ?? 28) - 14))
  const chart = hasSeries ? bandChart(bandPoints, { height: chartHeight, width: inner, yMax, yMin }) : null

  const members = (refThesis?.member_count ?? refFactor?.member_count) ?? 0
  const coverage = refThesis?.coverage ?? refFactor?.coverage
  const nEff = refThesis?.n_eff ?? refFactor?.n_eff
  const asOf = refThesis?.as_of ?? refFactor?.as_of
  const freshness = refThesis?.freshness ?? refFactor?.freshness
  const note = refThesis?.analyst_note ?? refFactor?.analyst_note
  const teaser = note?.headline || (note?.body ?? '').slice(0, 120) || ''

  return (
    <Box flexDirection="column" flexShrink={0} width={width}>
      <Text bold color={t.color.accent} wrap="truncate-end">
        {`${refThesis ? '◆' : '▣'} ${truncate(title, inner - 2)}`}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">{refThesis ? 'thesis lens' : 'factor lens'}</Text>

      <Box marginTop={1}>
        {refThesis ? (
          <Text wrap="truncate-end">
            <Text color={t.color.muted}>health </Text>
            <Text bold color={healthColor(t, refThesis.health_probability)}>
              {refThesis.health_display ?? (finite(refThesis.health_probability) ? pct(refThesis.health_probability) : '—')}
            </Text>
            <Text color={t.color.label}> alive</Text>
            <Text color={t.color.muted}>{'  ·  score '}</Text>
            <Text bold color={t.color.primary}>{scoreText(refThesis.thesis_score)}</Text>
            <Text color={t.color.label}> strength</Text>
            <Text color={t.color.muted}>{'  '}</Text>
            <Text bold color={deltaColor}>{glyph}</Text>
          </Text>
        ) : refFactor ? (
          <Text wrap="truncate-end">
            <Text color={t.color.muted}>μ </Text>
            <Text bold color={signColor(t, refFactor.mean)}>{finite(refFactor.mean) ? `${trimNum(refFactor.mean)}${unit}` : '—'}</Text>
            <Text color={t.color.label}> return</Text>
            <Text color={t.color.muted}>{'  ·  vol σ '}</Text>
            <Text color={t.color.text}>{finite(refFactor.volatility) ? `${trimNum(refFactor.volatility)}${unit}` : '—'}</Text>
            <Text color={t.color.muted}>{'  '}</Text>
            <Text bold color={deltaColor}>{glyph}</Text>
          </Text>
        ) : null}
      </Box>

      {chart ? (
        <Box flexDirection="column" marginTop={1}>
          {chart.rows.map((row, i) => (
            <Text color={t.color.accent} key={`lband:${i}`} wrap="truncate-end">
              {row}
            </Text>
          ))}
          <Text color={t.color.muted} wrap="truncate-end">{refThesis ? 'health over time' : 'return over time'}</Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.color.muted} wrap="truncate-end">
          {`members ${members}${finite(coverage) ? ` · coverage ${pct(coverage)}` : ''}${finite(nEff) ? ` · nEff ${trimNum(nEff)}` : ''}`}
        </Text>
      </Box>
      <Text color={t.color.muted} wrap="truncate-end">
        {`updated ${shortDate(asOf)}${freshness ? ` (${freshness})` : ''}`}
      </Text>

      {teaser ? (
        <Box marginTop={1}>
          <Text color={t.color.text} wrap="wrap">
            {truncate(teaser, inner * 2)}
          </Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.color.accent} wrap="truncate-end">
          ⏎ open full lens read
        </Text>
      </Box>
    </Box>
  )
}

// The section-leading row on a thesis/factor lens tab: the lens itself, as a
// clickable row at the top of the list. Click or Enter opens the lens's full
// aggregate read (ThesisDeskRead/FactorDeskRead) in the modal.
function DeskLensRow({
  active,
  onOpen,
  refFactor,
  refThesis,
  t,
  width
}: {
  active: boolean
  onOpen: () => void
  refFactor: ForecastFactor | undefined
  refThesis: ForecastThesis | undefined
  t: Theme
  width: number
}) {
  const sem = semantics(t)
  const isThesis = !!refThesis
  const glyph = isThesis ? '◆' : '▣'
  const title = (isThesis ? refThesis?.title : refFactor?.title) ?? 'Lens'

  // Space-constrained list row: keep the pair unambiguous via UNITS, not words —
  // health carries "%", score carries "/100" so they can't be read as the same
  // kind of number even when their values are close ("health 54% · score 54/100").
  let agg = ''
  if (refThesis) {
    const health = refThesis.health_probability
    agg = `health ${refThesis.health_display ?? (finite(health) ? pct(health) : '—')} · score ${scoreText(refThesis.thesis_score)}`
  } else if (refFactor) {
    const unit = unitSuffix(refFactor.units)
    agg = `μ ${finite(refFactor.mean) ? `${trimNum(refFactor.mean)}${unit}` : '—'} · vol σ ${finite(refFactor.volatility) ? `${trimNum(refFactor.volatility)}${unit}` : '—'}`
  }

  const titleW = Math.max(8, width - agg.length - 18)
  return (
    <Box marginBottom={1} onClick={onOpen}>
      <Text backgroundColor={active ? t.color.selectionBg : undefined} bold wrap="truncate-end">
        <Text color={active ? sem.cursor : t.color.accent}>
          {active ? '▸ ' : '  '}
          {glyph}{' '}
        </Text>
        <Text color={active ? sem.selectionFg : t.color.label}>{truncate(title, titleW)}</Text>
        <Text color={sem.subtle}>{`  ${agg}`}</Text>
        <Text color={t.color.accent}>{'   ⏎ lens'}</Text>
      </Text>
    </Box>
  )
}

// On a thesis/factor lens tab, the aggregate read (health/score, or μ return)
// heads the skinny panel via tabRefThesis/tabRefFactor.
function LensHeader({
  refFactor,
  refThesis,
  t,
  width
}: {
  refFactor: ForecastFactor | undefined
  refThesis: ForecastThesis | undefined
  t: Theme
  width: number
}) {
  if (refThesis) {
    const health = refThesis.health_probability
    const score = refThesis.thesis_score

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          {truncate(refThesis.title ?? 'thesis', width)}
        </Text>
        {/* Two-line read: health is the headline ALIVE-probability (% + health ramp),
            score is the secondary STRENGTH index (/100, neutral) — the unit + word +
            colour together keep two close values from reading as the same thing. */}
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>health </Text>
          <Text bold color={healthColor(t, health)}>
            {refThesis.health_display ?? (finite(health) ? pct(health) : '—')}
          </Text>
          <Text color={t.color.label}> alive</Text>
        </Text>
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>score  </Text>
          <Text color={t.color.text}>{scoreText(score)}</Text>
          <Text color={t.color.label}> strength</Text>
        </Text>
      </Box>
    )
  }

  if (refFactor) {
    const mean = refFactor.mean
    const unit = unitSuffix(refFactor.units)

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          {truncate(refFactor.title ?? 'factor', width)}
        </Text>
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>μ </Text>
          <Text bold color={signColor(t, mean)}>
            {finite(mean) ? `${trimNum(mean)}${unit}` : '—'}
          </Text>
          <Text color={t.color.label}> return</Text>
        </Text>
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>vol σ </Text>
          <Text color={t.color.text}>{finite(refFactor.volatility) ? `${trimNum(refFactor.volatility)}${unit}` : '—'}</Text>
          <Text color={t.color.label}> volatility</Text>
        </Text>
      </Box>
    )
  }

  return null
}

// ── Dense column table (mirrors the Markets quote table) ─────────────────────
// QUESTION is the flexible left column (takes the slack); the rest are fixed,
// right-aligned numeric columns packed by PRIORITY when the pane is tight; a
// trailing 1-month trend sparkline fills whatever width is left over.

interface DeskCol {
  align: 'left' | 'right'
  key: string
  label: string
  // Fixed columns carry a width; QUESTION is flexible (w computed from slack).
  w: number
}

// Display order, left→right. QUESTION's `w` is a placeholder — it is recomputed
// from the leftover width after the kept fixed columns are reserved.
const DESK_COLS: DeskCol[] = [
  { align: 'left', key: 'q', label: 'QUESTION', w: 24 },
  { align: 'right', key: 'prob', label: 'PROB', w: 8 },
  { align: 'right', key: '1d', label: '1D', w: 7 },
  { align: 'right', key: '1w', label: '1W', w: 7 },
  { align: 'right', key: '1mo', label: '1MO', w: 8 },
  { align: 'right', key: 'ev', label: 'EV', w: 4 },
  // SRC = active watched-source count (0 = "no fuel", warning-coloured); RDY = the
  // 0-100 machine-readiness composite, banded by colour. Both reserve 5 (label 3 +
  // the " ▲/▼" sort indicator) so the sortable header renders without clipping —
  // the same "label + indicator fits" sizing every other numeric column uses.
  { align: 'right', key: 'src', label: 'SRC', w: 5 },
  { align: 'right', key: 'rdy', label: 'RDY', w: 5 },
  { align: 'right', key: 'age', label: 'AGE', w: 7 },
  // NEXT reserves 9 (vs the other numerics' 7-8): the honest due-state strings
  // ("◐ running", "due · Xm") are 8-9 chars, and unlike a min-width pad the column
  // must actually RESERVE the slot or the row's truncate-end clips into the string.
  { align: 'right', key: 'next', label: 'NEXT', w: 9 }
]

// Keep by priority when narrow (render still follows display order). QUESTION is
// always kept; PROB matters most; then SRC/RDY — the operator's machine-readiness
// signals (a 0-source row explains WHY nothing updates, which outranks momentum
// deltas: the operator asked for this column expressly) — then NEXT, the wider
// 1W window, EV, the noisier 1D/1MO, and AGE last.
const DESK_PRIORITY = ['prob', 'src', 'rdy', 'next', '1w', 'ev', '1d', '1mo', 'age']

// Every desk column is sortable except the trailing trend spark (which is not a
// column). `o` cycles through them in header (display) order.
const DESK_SORT_KEYS = DESK_COLS.map(c => c.key)

// The comparable value a desk row contributes for a given sort key. Text for
// QUESTION; the raw signed window Δ for 1D/1W/1MO; the probability/μ for PROB; a
// numeric age (older → larger, so ascending = freshest first) for AGE; the next
// event's epoch (soonest first ascending) for NEXT. Missing values sort last.
export const deskSortValue = (item: ForecastWorkspaceItem, key: string, nowMs: number): SortValue => {
  switch (key) {
    case '1d':
      return windowDelta(item.history, nowMs, 1)

    case '1mo':
      return windowDelta(item.history, nowMs, 30)

    case '1w':
      return windowDelta(item.history, nowMs, 7)

    case 'age': {
      const at = Date.parse(item.as_of ?? '')
      return Number.isFinite(at) ? nowMs - at : null
    }

    case 'ev':
      return item.evidence_count ?? 0

    case 'next': {
      const at = item.next_review_at
        ? Date.parse(item.next_review_at)
        : Date.parse(item.resolution_time ?? item.close_time ?? '')
      return Number.isFinite(at) ? at : null
    }

    case 'prob':
      return finite(item.headline_probability) ? item.headline_probability : null

    case 'q':
      return item.title ?? item.id ?? ''

    case 'rdy':
      return finite(item.readiness?.score) ? item.readiness!.score : null

    case 'src':
      return item.src_count ?? 0

    default:
      return null
  }
}

// Short freshness for the AGE column: "3d old" → "3d", "fresh today" → "now".
const shortAge = (freshness: string | undefined): string => {
  if (!freshness) {
    return '—'
  }
  if (/fresh|today|now/i.test(freshness)) {
    return 'now'
  }
  const m = /(\d+)\s*([a-z]+)/i.exec(freshness)
  // Keep the full unit (up to 2 chars) so months read "2mo", not "2m" (minutes).
  return m ? `${m[1]}${m[2].toLowerCase().slice(0, 2)}` : truncate(freshness, 6)
}

// Compact relative-time forward for the NEXT column: "5h", "3d", "2mo". Sub-day
// rounds to hours; up to ~7wk reads in days; further out collapses to months so a
// far-off resolution still fits the narrow column.
const relTime = (ms: number): string => {
  const days = ms / 86400000
  if (days < 1) return `${Math.max(1, Math.round(ms / 3600000))}h`
  if (days < 52) return `${Math.round(days)}d`
  return `${Math.max(2, Math.round(days / 30))}mo`
}

// Forward "time to NEXT auto-reforecast" for the NEXT column (the live schedule).
// "now" (due/overdue), "5h", "3d"; status drives colour. When there is NO live
// review (market_nightly markets deliberately have no re-forecast cadence; a
// primary-election cron the desk can't see), FALL BACK to the question's next
// real event — resolution_time ?? close_time — rendered with a leading "⤓" marker
// and a distinct 'res' status so it reads visibly as a resolution date, NOT a
// scheduled review. A real review (next_review_at present) renders EXACTLY as
// before — the fallback never alters it. Neither → "—".
const dueText = (
  item: ForecastWorkspaceItem,
  nowMs: number
): { status: 'none' | 'now' | 'ok' | 'res' | 'soon'; text: string } => {
  const at = item.next_review_at ? Date.parse(item.next_review_at) : NaN
  if (Number.isFinite(at)) {
    const ms = at - nowMs
    if (ms <= 0) return { status: 'now', text: 'now' }
    const days = ms / 86400000
    if (days < 1) return { status: 'soon', text: `${Math.max(1, Math.round(ms / 3600000))}h` }
    const d = Math.round(days)
    return { status: d <= 2 ? 'soon' : 'ok', text: `${d}d` }
  }

  // No scheduled review → show the next meaningful event (resolution), marked.
  const eventAt = Date.parse(item.resolution_time ?? item.close_time ?? '')
  if (!Number.isFinite(eventAt)) return { status: 'none', text: '—' }
  const ms = eventAt - nowMs
  // Already resolved/closed but still on the desk → just flag it as due.
  if (ms <= 0) return { status: 'res', text: '⤓now' }
  return { status: 'res', text: `⤓${relTime(ms)}` }
}

// The live review-sweep context threaded into the NEXT column so a DUE row can
// render honest state instead of a static "now": is a sweep running (spinner),
// when will the gateway sweeper next tick, and — when the sweeper is disabled —
// whether the nightly cron will pick it up "tonight". All epochs are ms (NaN when
// absent). `frame` is the 500ms spinner tick (only read while `running`). `nowMs`
// is the minute-bucketed clock so the "due · Xm" text is stable within a minute
// (which keeps the memoised row from re-rendering on every 500ms reflow when idle).
export interface DeskSweepCtx {
  frame: number
  nightlyNextAt: number
  nowMs: number
  running: boolean
  // The agent is working THIS question right now → the gutter animates with
  // the house accent sweep (same family as the Home chat / review sweep).
  runningNow?: boolean
  nextTickAt: number
  sweeperEnabled: boolean
}

// The NEXT cell for a row whose scheduled review is DUE (status 'now'). Honest,
// at-a-glance: while a sweep runs → an animated spinner + "running"; else, when
// the gateway sweeper is enabled → a countdown to its next tick ("due · Xm",
// "due · <1m" under a minute, imminent when the tick time is unknown/past); when
// the sweeper is disabled → "due · tonight" if the nightly cron will pick it up,
// else a plain "due". Strings stay narrow (≤ ~9 chars, bar the rare "tonight").
export const dueNowCell = (sweep: DeskSweepCtx | undefined, t: Theme): { color: string; text: string } => {
  if (!sweep) {
    return { color: t.color.error, text: 'now' }
  }
  if (sweep.running) {
    // Match the Home chat's busy spinner: colour the glyph (+ its "running" label)
    // by sweeping the brand accent family via sweepColor(sweepStops(t), frame) — the
    // exact helper appChrome's FaceTicker uses — instead of a static accent. `frame`
    // is the shared 500ms tick, so the cell cycles colour in lock-step with the
    // summary line while the memo keeps idle rows frozen.
    return { color: sweepColor(sweepStops(t), sweep.frame), text: `${spinnerFrame(sweep.frame)} running` }
  }
  if (sweep.sweeperEnabled) {
    const imminent = !Number.isFinite(sweep.nextTickAt) || sweep.nextTickAt <= sweep.nowMs
    if (imminent) {
      return { color: t.color.warn, text: 'due · <1m' }
    }
    const diff = sweep.nextTickAt - sweep.nowMs
    return { color: t.color.warn, text: diff < 60000 ? 'due · <1m' : `due · ${Math.ceil(diff / 60000)}m` }
  }
  if (Number.isFinite(sweep.nightlyNextAt)) {
    return { color: t.color.warn, text: 'due · tonight' }
  }
  return { color: t.color.warn, text: 'due' }
}

// Window change → display text only (colour is applied by the caller from the
// raw signed value so direction reads via colour AND glyph). For distributions
// the magnitude is outcome-unit Δμ; for probabilities it is percent-points.
const windowChgText = (item: ForecastWorkspaceItem, value: number | null): string => {
  if (value === null) {
    return '—'
  }
  const glyph = deltaGlyph(value)
  if (item.headline_kind === 'distribution') {
    if (!finite(value) || Math.abs(value) < 1e-6) {
      return '·'
    }
    return `${glyph}${value > 0 ? '+' : ''}${trimNum(value)}`
  }
  if (!finite(value) || Math.abs(value) < 0.005) {
    return '·'
  }
  const points = Math.round(value * 100)
  return `${glyph}${points > 0 ? '+' : ''}${points}`
}

// CHG cell colour + text together, so a flat ('·') or absent ('—') change is
// painted neutral rather than a misleading coloured up/down move.
const windowChgCell = (
  item: ForecastWorkspaceItem,
  value: number | null,
  sem: Semantics
): { color: string; text: string } => {
  const text = windowChgText(item, value)
  const color = text === '·' || text === '—' ? sem.subtle : dirColor(sem, value)
  return { color, text }
}

// One cell's colour + text. `windows` are the precomputed 1D/1W/1MO deltas so the
// switch stays a pure formatter. Exported so the SRC "no fuel" warning + the RDY
// band colours are unit-testable in isolation (the dueNowCell pattern).
export const deskCellText = (
  key: string,
  item: ForecastWorkspaceItem,
  sem: Semantics,
  t: Theme,
  windows: { '1d': number | null; '1mo': number | null; '1w': number | null },
  nowMs: number,
  sweep?: DeskSweepCtx
): { color: string; text: string } => {
  switch (key) {
    case '1d':
      return windowChgCell(item, windows['1d'], sem)

    case '1mo':
      return windowChgCell(item, windows['1mo'], sem)

    case '1w':
      return windowChgCell(item, windows['1w'], sem)

    case 'age':
      return { color: sem.subtle, text: shortAge(item.freshness) }

    case 'next': {
      const due = dueText(item, nowMs)
      // A DUE row ('now') no longer reads a static "now": spell out honest sweep
      // state (spinner while running, a countdown to the next tick, or the nightly
      // fallback). Every other status is unchanged.
      if (due.status === 'now') {
        return dueNowCell(sweep, t)
      }
      // A resolution-date fallback is informational (not an urgent review) → paint
      // it subtle so the "⤓" marker, not colour, signals the distinction.
      const color = due.status === 'soon' ? t.color.warn : sem.subtle
      return { color, text: due.text }
    }

    case 'ev':
      return { color: sem.subtle, text: String(item.evidence_count ?? 0) }

    case 'src': {
      // Active watched-source count. 0 is the "no fuel" signal — the autonomous
      // desk has nothing to refresh — so it paints in the warning colour; a
      // fuelled row stays subtle so only the empty ones draw the eye.
      const n = item.src_count ?? 0
      return { color: n > 0 ? sem.subtle : t.color.warn, text: String(n) }
    }

    case 'rdy': {
      // The 0-100 machine-readiness composite, banded by colour (≥80 ok, 50-79
      // warn, <50 danger). No composite (benchmark/market question) → subtle "—".
      const score = item.readiness?.score
      return finite(score)
        ? { color: readinessColor(t, score), text: String(Math.round(score)) }
        : { color: sem.subtle, text: '—' }
    }

    case 'prob':
      return { color: t.color.text, text: headlineCompact(item) }

    case 'q':
      return { color: t.color.label, text: item.title ?? item.id ?? 'untitled' }

    default:
      return { color: t.color.text, text: '' }
  }
}

export function DeskForecastList({
  cursor,
  empty,
  items,
  markedIds,
  nowMs,
  onSelect,
  onSort,
  runningId = null,
  runningIds,
  spinTick = 0,
  sortDir,
  sortKey,
  sweep,
  t,
  visibleRows,
  width
}: {
  cursor: number
  empty: string
  items: ForecastWorkspaceItem[]
  // The marked (mass-selected) question ids; a leading ▎ paints each marked row.
  markedIds: Set<string>
  nowMs: number
  onSelect: (i: number) => void
  // Clicking a column header sorts by it; undefined while a modal covers the body.
  onSort?: (key: string) => void
  // The question the agent is working RIGHT NOW → the animated accent-swept
  // spinner (the operator: "a nice ascii animation like we have in the home
  // view chats"). Null when no job runs.
  runningId?: null | string
  // The ids still in flight in the running detached agent job → a dim ⋯ gutter
  // marker. A stable empty set at rest keeps the memoised rows byte-identical.
  runningIds: ReadonlySet<string>
  // 500ms animation counter, non-zero ONLY while an agent job runs (the sweep
  // ctx pattern): drives the working row's spinner without waking idle rows.
  spinTick?: number
  sortDir: SortDir
  sortKey: null | string
  // Live review-sweep state for the NEXT column (referentially STABLE while idle so
  // the memoised rows still bail out on 500ms reflow ticks; changes each tick only
  // WHILE a sweep runs, to animate the spinner).
  sweep?: DeskSweepCtx
  t: Theme
  visibleRows: number
  width: number
}) {
  // Column packing + every other CURSOR-INDEPENDENT derived value, memoised on
  // [t, width]. A cursor move re-renders this list (its onSelect prop is a fresh
  // closure each parent render), but this memo keeps `sem`, `keptCols`, `colWidth`,
  // `trendW`, `showTrend` REFERENTIALLY STABLE — which is what lets the memoised
  // DeskListRow below bail out for every row whose `active` flag did not flip. So a
  // move re-renders 2 rows (the one that lost and the one that gained the cursor),
  // not all ~38 in the viewport, and never recomputes windowDelta×3 + the sparkline
  // for the untouched rows.
  // A 2-col saturation gutter is reserved ONLY when the book actually holds an
  // under-saturated forecast (Wave 3) — so a healthy book's table is byte-for-byte
  // unchanged, and the ◌ marker (always in the leading gutter) is never truncated.
  const hasUnderSaturated = useMemo(
    () => items.some(item => item.saturation_below_threshold === true),
    [items]
  )

  const layout = useMemo(() => {
    const sem = semantics(t)
    // Usable inner width (leave a column for the cursor marker + a trailing space).
    const avail = Math.max(20, width - 2)
    const satGutter = hasUnderSaturated ? 2 : 0

    // Pack the FIXED numeric columns by priority, but ALWAYS reserve QMIN for the
    // QUESTION column so a column is dropped (priority-drop) rather than QUESTION
    // overflowing + clipping the rightmost numerics on a tight terminal.
    const QMIN = 14
    const keep = new Set<string>(['q'])
    let usedW = 2 + satGutter // cursor marker + optional saturation gutter
    for (const key of DESK_PRIORITY) {
      const c = DESK_COLS.find(col => col.key === key)
      if (c && usedW + c.w + 1 <= avail - QMIN) {
        keep.add(key)
        usedW += c.w + 1
      }
    }

    // Split the leftover: a capped slice feeds the trailing 1MO trend sparkline
    // (so it actually renders — QUESTION no longer eats 100% of the slack), and
    // QUESTION takes the rest with at least QMIN.
    const leftover = Math.max(QMIN, avail - usedW)
    // The QUESTION column wins the slack — titles matter more than the trend — so the
    // trailing trend sparkline only claims width once QUESTION is comfortable; short
    // titles never truncate to make room for it.
    const QCOMFORT = 30
    const trendW = leftover >= QCOMFORT + 8 ? Math.min(14, leftover - QCOMFORT) : 0
    const questionW = leftover - trendW
    const showTrend = trendW >= 8
    const colWidth = (c: DeskCol): number => (c.key === 'q' ? questionW : c.w)
    const keptCols = DESK_COLS.filter(c => keep.has(c.key))

    return { avail, colWidth, keptCols, satGutter, sem, showTrend, trendW }
  }, [t, width, hasUnderSaturated])
  const { avail, colWidth, keptCols, satGutter, sem, showTrend, trendW } = layout

  if (!items.length) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted} wrap="wrap">
          {empty}
        </Text>
      </Box>
    )
  }

  // cursor may be -1 (the lead lens row is selected, no forecast highlighted);
  // clamp for windowing so the list still shows from the top.
  const { items: windowed, offset } = windowItems(items, Math.max(0, cursor), visibleRows)

  return (
    <Box flexDirection="column" flexGrow={0} flexShrink={0} minHeight={0} overflow="hidden">
      {/* The header row: each column label is a click target that sorts by it
          (gated while a modal covers the body). The active column shows a ▲/▼
          direction glyph and paints in accent; the rest stay the plain heading. */}
      <Box>
        <Text bold color={sem.heading}>{satGutter ? '    ' : '  '}</Text>
        {keptCols.map(c => {
          const active = sortKey === c.key
          const ind = active ? ` ${sortIndicator({ dir: sortDir, key: sortKey }, c.key)}` : ''

          return (
            <Box key={c.key} onClick={onSort ? () => onSort(c.key) : undefined}>
              <Text bold color={active ? t.color.accent : sem.heading}>
                {`${pad(`${c.label}${ind}`, colWidth(c), c.align)} `}
              </Text>
            </Box>
          )
        })}
        {showTrend ? <Text bold color={sem.heading}>{pad('1MO', trendW, 'left')}</Text> : null}
      </Box>
      <Text color={sem.rule}>{'─'.repeat(avail)}</Text>
      {windowed.map((item, i) => {
        const index = offset + i

        return (
          <Box key={item.id ?? `fc:${index}`} onClick={() => onSelect(index)} width={width}>
            <DeskListRow
              active={index === cursor}
              colWidth={colWidth}
              cols={keptCols}
              item={item}
              marked={markedIds.has(item.id ?? '')}
              nowMs={nowMs}
              running={runningIds.has(item.id ?? '')}
              runningNow={runningId !== null && runningId === item.id}
              spinFrame={runningId !== null && runningId === item.id ? spinTick : 0}
              satGutter={satGutter}
              sem={sem}
              showTrend={showTrend}
              sweep={sweep}
              t={t}
              trendW={trendW}
            />
          </Box>
        )
      })}
      {items.length > windowed.length ? (
        <Text color={t.color.muted}>
          {'  '}
          {offset + windowed.length}/{items.length}
        </Text>
      ) : null}
    </Box>
  )
}

// Memoised: with the layout props (colWidth/cols/sem/showTrend/trendW) held stable
// by DeskForecastList's [t, width] memo, a cursor move only flips `active` on 2
// rows — so only those 2 re-render (recomputing windowDelta×3 + the sparkline);
// the rest of the viewport bails out. Row work is O(1) per move, not O(viewport).
// The working-row spinner: braille frames swept through the brand accent family
// — the same animation language as the Home chat and the review sweep. Driven by
// the desk's 500ms reflow tick, so it costs nothing extra at rest.
const AGENT_SPIN_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

const DeskListRow = memo(function DeskListRow({
  active,
  colWidth,
  cols,
  item,
  marked,
  nowMs,
  running,
  runningNow = false,
  spinFrame = 0,
  satGutter,
  sem,
  showTrend,
  sweep,
  t,
  trendW
}: {
  active: boolean
  colWidth: (c: DeskCol) => number
  cols: DeskCol[]
  item: ForecastWorkspaceItem
  // Marked in the mass-selection set → a leading accent ▎. A cursor move flips
  // only `active`; a mark toggle flips only `marked` — either way just this row
  // re-renders (the memo bails on the rest).
  marked: boolean
  nowMs: number
  // In the running detached agent job's remaining set → a dim ⋯ gutter marker.
  // Flips only this row (the memo bails on the rest) when the job starts/advances.
  running: boolean
  // The agent is working THIS question right now → animated accent-swept
  // spinner. spinFrame advances every 500ms ONLY for the working row (0 at
  // rest), so the memo still bails everywhere else. nowMs is 60s-bucketed and
  // cannot drive an animation.
  runningNow?: boolean
  spinFrame?: number
  satGutter: number
  sem: Semantics
  showTrend: boolean
  sweep?: DeskSweepCtx
  t: Theme
  trendW: number
}) {
  // nowMs is a 60s-bucketed clock (deskView passes Math.floor(now/60_000)*60_000):
  // it keeps the live NEXT/age columns ticking ~once a minute WITHOUT defeating the
  // memo on every cursor move (the prior Date.now() here re-rendered nothing because
  // memo bailed on the parent's 500ms timer, freezing the column).
  const windows = {
    '1d': windowDelta(item.history, nowMs, 1),
    '1mo': windowDelta(item.history, nowMs, 30),
    '1w': windowDelta(item.history, nowMs, 7)
  }

  // 1-month level trend: the headline series on a fixed 0..1 scale for binaries,
  // auto-zoomed to the data range for distributions (μ is not a 0..1 quantity).
  const sparkValues = (item.history ?? []).slice(-trendW).map(point => point.headline_probability ?? null)
  const sparkOpts =
    item.headline_kind === 'distribution'
      ? (() => {
          const fv = sparkValues.filter((v): v is number => finite(v))
          return fv.length ? { yMax: Math.max(...fv), yMin: Math.min(...fv) } : {}
        })()
      : {}
  const trend = showTrend ? levelSparkline(sparkValues, sparkOpts) : ''
  const trendColor = dirColor(sem, item.delta ?? windows['1mo'])

  const alertBadge = (item.open_alert_count ?? 0) > 0 ? `!${item.open_alert_count}` : ''
  // A dim trailing marker for an under-saturated forecast (Wave 3). Appended like
  // the alert badge so the healthy case never widens the dense table.
  const underSaturated = item.saturation_below_threshold === true

  return (
    <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
      {/* Leading 2-char gutter, in precedence order: a marked row shows the accent
          ▎; else a row in the running agent job's remaining set shows a dim ⋯; else
          the cursor ▸ / blank. The row's background highlight always signals the
          cursor, so ▎/⋯ overriding the arrow never hides it. Idle + unmarked is
          byte-identical to before (`▸ `), so the dense table is untouched at rest. */}
      <Text
        bold={active || marked || runningNow}
        color={
          runningNow
            ? sweepColor(sweepStops(t), spinFrame)
            : marked
              ? t.color.accent
              : running
                ? t.color.accent
                : active
                  ? sem.cursor
                  : sem.faint
        }
      >
        {`${
          runningNow
            ? AGENT_SPIN_FRAMES[spinFrame % AGENT_SPIN_FRAMES.length]
            : marked
              ? '▎'
              : running
                ? '⋯'
                : active
                  ? '▸'
                  : ' '
        } `}
      </Text>
      {satGutter ? (
        // The reserved saturation gutter: a dim ◌ for an under-saturated forecast,
        // else blank. Always visible (leading, never truncated); only present when
        // the book holds at least one under-saturated row.
        <Text color={t.color.muted}>{underSaturated ? '◌ ' : '  '}</Text>
      ) : null}
      {cols.map(c => {
        const cell = deskCellText(c.key, item, sem, t, windows, nowMs, sweep)
        const highlight = active && c.key === 'q'

        return (
          <Text bold={active && c.key === 'q'} color={highlight ? sem.selectionFg : cell.color} key={c.key}>
            {`${pad(cell.text, colWidth(c), c.align)} `}
          </Text>
        )
      })}
      {showTrend ? <Text color={trendColor}>{trend}</Text> : null}
      {alertBadge ? <Text color={t.color.statusBad}> {alertBadge}</Text> : null}
    </Text>
  )
})

// ── Detail modal shell (InfoModal pattern + a scrollable body) ────────────────
// Reuses the InfoModal round-bordered centered-overlay shell, but renders the
// heavy ForecastDetail inside a ScrollBox with a scrollbar (Up/Down/PgUp/PgDn).

// The reviewable time series of prior write-ups inside the modal (newest-first).
function DeskAnalystLog({ notes, t }: { notes: ForecastAnalystNote[]; t: Theme }) {
  if (!notes.length) {
    return null
  }

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box marginTop={1}>
        <Text bold color={t.color.accent}>
          analyst log
        </Text>
      </Box>
      {notes.map((note, index) => (
        <Fragment key={`${note.created_at ?? note.as_of ?? ''}:${index}`}>
          <Box flexDirection="row">
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
        </Fragment>
      ))}
    </Box>
  )
}

// ── Bench lens: read-only ForecastBench scoreboard ───────────────────────────
// A visually-distinct (◇ diamond marker, dedicated aggregate banner) backtest
// scoreboard pairing the agent's closed-book forecast against the de-vigged
// market freeze price per resolved ForecastBench question. NOT the live desk —
// it renders the `forecast.bench` RPC payload, never the organic question list.

const benchBrierText = (value: null | number | undefined): string =>
  value === null || value === undefined || !finite(value) ? '—' : value.toFixed(3)

// EDGE = market Brier − agent Brier; positive (green) = the agent beat the
// honest market freeze on Brier. Neutral when either leg is missing.
const benchEdgeCell = (edge: null | number | undefined, t: Theme): { color: string; text: string } => {
  if (edge === null || edge === undefined || !finite(edge)) return { color: t.color.muted, text: '—' }
  const sign = edge > 0 ? '+' : ''
  return { color: Math.abs(edge) < 0.0005 ? t.color.muted : edge > 0 ? t.color.ok : t.color.error, text: `${sign}${edge.toFixed(3)}` }
}

function BenchScoreboard({
  bench,
  loading,
  rows: termRows,
  t,
  width
}: {
  bench: ForecastBenchResponse | null
  loading: boolean
  rows: number
  t: Theme
  width: number
}) {
  const rows = bench?.rows ?? []
  const agg = bench?.aggregate ?? {}
  const avail = Math.max(40, width - 2)

  if (loading && !rows.length) {
    return <Text color={t.color.muted}>Loading ForecastBench scoreboard…</Text>
  }

  if (!rows.length) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.accent} wrap="truncate-end">
          ◇ ForecastBench scoreboard
        </Text>
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="wrap">
            No ForecastBench backtests yet. Ingest a dataset (forecast ingest forecastbench …) to
            populate the agent-vs-market Brier board.
          </Text>
        </Box>
      </Box>
    )
  }

  // Fixed numeric columns; SOURCE + QUESTION take the slack. Widths mirror the
  // dense desk table style (right-aligned numerics, left title).
  const cAgent = 6
  const cMarket = 7
  const cOut = 4
  const cBrier = 8
  const cEdge = 7
  const cSrc = 9
  const numericW = cAgent + 1 + cMarket + 1 + cOut + 1 + cBrier + 1 + cBrier + 1 + cEdge + 1 + cSrc + 1
  const qW = Math.max(16, avail - numericW - 2)

  const edge = benchEdgeCell(agg.mean_brier_edge, t)
  const visibleRows = Math.max(4, termRows - 6)
  const shown = rows.slice(0, visibleRows)

  return (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflow="hidden">
      {/* Aggregate banner — the glanceable verdict for the whole board. */}
      <Box flexDirection="column" marginBottom={1}>
        <Text wrap="truncate-end">
          <Text bold color={t.color.accent}>
            ◇ ForecastBench
          </Text>
          <Text color={t.color.muted}>{`   ${bench?.count ?? rows.length} questions · ${bench?.resolved_count ?? 0} resolved · ${agg.n ?? 0} scored`}</Text>
        </Text>
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>agent Brier </Text>
          <Text bold color={t.color.primary}>{benchBrierText(agg.mean_agent_brier)}</Text>
          <Text color={t.color.muted}>{'  vs  market '}</Text>
          <Text bold color={t.color.text}>{benchBrierText(agg.mean_market_brier)}</Text>
          <Text color={t.color.muted}>{'   edge '}</Text>
          <Text bold color={edge.color}>{edge.text}</Text>
          <Text color={t.color.muted}>{edge.text === '—' ? '' : edge.color === t.color.ok ? ' (agent ahead)' : edge.color === t.color.error ? ' (market ahead)' : ''}</Text>
        </Text>
      </Box>

      {/* Column header + rule. */}
      <Text bold color={semantics(t).heading} wrap="truncate-end">
        {`${pad('QUESTION', qW, 'left')} ${pad('SRC', cSrc, 'left')} ${pad('AGENT', cAgent, 'right')} ${pad('MARKET', cMarket, 'right')} ${pad('OUT', cOut, 'right')} ${pad('A.BRIER', cBrier, 'right')} ${pad('M.BRIER', cBrier, 'right')} ${pad('EDGE', cEdge, 'right')}`}
      </Text>
      <Text color={semantics(t).rule}>{'─'.repeat(avail)}</Text>

      {shown.map((row: ForecastBenchRow) => {
        const e = benchEdgeCell(row.brier_edge, t)
        const outText = !row.resolved || row.outcome === null || row.outcome === undefined ? '—' : row.outcome >= 0.5 ? '1' : '0'
        const outColor = outText === '1' ? t.color.ok : outText === '0' ? t.color.error : t.color.muted
        return (
          <Text key={row.id} wrap="truncate-end">
            <Text color={t.color.label}>{pad(truncate(row.title ?? row.id, qW), qW, 'left')}</Text>
            <Text color={t.color.muted}>{` ${pad(truncate(row.source ?? '—', cSrc), cSrc, 'left')}`}</Text>
            <Text color={t.color.text}>{` ${pad(row.agent_probability_display ?? '—', cAgent, 'right')}`}</Text>
            <Text color={t.color.muted}>{` ${pad(row.market_probability_display ?? '—', cMarket, 'right')}`}</Text>
            <Text color={outColor}>{` ${pad(outText, cOut, 'right')}`}</Text>
            <Text color={t.color.text}>{` ${pad(benchBrierText(row.agent_brier), cBrier, 'right')}`}</Text>
            <Text color={t.color.muted}>{` ${pad(benchBrierText(row.market_brier), cBrier, 'right')}`}</Text>
            <Text bold color={e.color}>{` ${pad(e.text, cEdge, 'right')}`}</Text>
          </Text>
        )
      })}
      {rows.length > shown.length ? (
        <Text color={t.color.muted}>{`  ${shown.length}/${rows.length}`}</Text>
      ) : null}
    </Box>
  )
}
