import { useStore } from '@nanostores/react'
import { Box, type ScrollBoxHandle, Text, useInput, useStdout } from '@superforecasting/ink'
import { Fragment, memo, useEffect, useMemo, useRef, useState } from 'react'

import { FORECAST_PACKET_TAIL_TITLES, forecastQuestionDetailSections } from '../app/forecastPanel.js'
import type { ReviewSweepState } from '../app/interfaces.js'
import { $globalModal, openHelpOverlay, patchOverlayState } from '../app/overlayStore.js'
import { $reviewSweep } from '../app/uiStore.js'
import { useJobAttach } from '../app/useJobAttach.js'
import type { GatewayClient } from '../gatewayClient.js'
import { sweepColor, sweepStops } from '../lib/accentSweep.js'
import {
  buildDeskTabs,
  type DeskTab,
  forecastsForTab,
  tabRefFactor,
  tabRefThesis
} from '../lib/deskGroups.js'
import { bandChart, deltaGlyph, downsampleSeries, levelSparkline, pct, shortDate, windowDelta, windowDeltaDetail, wrapLines } from '../lib/forecastCharts.js'
import { packetTailAudit } from '../lib/forecastTail.js'
import { type FieldSpec, filterRanked } from '../lib/fuzzyRank.js'
import { spinnerFrame } from '../lib/icons.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { nextCycleState, type SortDir, sortIndicator, sortRows, type TableSortState, useTableSort } from '../lib/tableSort.js'
import { dirColor, pad, readinessColor, type Semantics, semantics } from '../lib/visualSemantics.js'
import type {
  ForecastAnalystNote,
  ForecastBenchResponse,
  ForecastBenchRow,
  ForecastFactor,
  ForecastNextAction,
  ForecastQuestionPacketResponse,
  ForecastReforecastStartResponse,
  ForecastReviewsNextResponse,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspaceResponse
} from '../protocol/generated.js'
import type { Theme } from '../theme.js'

import { ForecastPulse } from './appChrome.js'
import {
  DESK_COLS,
  DESK_PRIORITY,
  DESK_SORT_KEYS,
  deskCellText,
  deskSortValue,
  dueNowCell,
  dueText,
  SORT_MODE_LABELS
} from './desk/cells.js'
import type { DeskCol, DeskSweepCtx } from './desk/cells.js'
import {
  AGENT_JOB_TYPES,
  agentJobFromRecord,
  reforecastStatusFromRecord,
  REFRESH_JOB_TYPES,
  refreshJobFromRecord,
  refreshTally,
  summarizeAgentJob,
  summarizeRearm,
  summarizeUpdate
} from './desk/jobs.js'
import type { AgentJob, MassTally, RefreshJob } from './desk/jobs.js'
import { DeskTabs as DeskTabsStrip } from './deskTabs.js'
import { type FooterChip, FooterChips } from './footerChips.js'
import { ForecastSettingsModal } from './forecastSettingsModal.js'
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
import { ModalOverlay } from './modalOverlay.js'
import { OperationsCockpit } from './operationsCockpit.js'
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
interface MassProgress {
  current: number
  title: string
  total: number
  verb: 're-arming' | 'updating'
}

// The desk's job-record mappers + honest tally/completion summaries live in
// ./desk/jobs.js; re-exported here so callers and tests still import them from
// the deskView module.
export {
  agentJobFromRecord,
  reforecastStatusFromRecord,
  refreshJobFromRecord,
  refreshTally,
  summarizeAgentJob,
  summarizeRearm,
  summarizeUpdate
}
export type { DeskSweepCtx } from './desk/cells.js'

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

  // ── Detached Desk REFRESH job (U / mass-U "Update now") ─────────────────────
  // The deterministic mass re-pool as ONE runtime job. refreshRunningRef is the
  // SYNC guard that gates re-triggers; the job runs server-side and is polled by
  // job_id, so closing/leaving the Desk stops the poll but NOT the work — and the
  // mount re-attach below picks it back up on return (the operator's bug: the old
  // client-side loop's remaining queue vanished on navigate-away).
  const [refreshJob, setRefreshJob] = useState<RefreshJob | null>(null)
  const refreshRunningRef = useRef(false)

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
          if (cancelled) {return}
          const r = asRpcResult<ForecastReviewsNextResponse>(raw)

          if (r) {setReviewsNext(r)}
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

    if (was && !sweepRunning) {load()}
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

  // The ordered lens tabs: real theses (member count desc, "major" first) → All.
  const tabs = useMemo<DeskTab[]>(() => (payload ? buildDeskTabs(payload) : []), [payload])
  const activeTab = tabs[Math.min(tab, Math.max(0, tabs.length - 1))]
  const refThesis = tabRefThesis(activeTab, theses)
  const refFactor = tabRefFactor(activeTab, factors)

  // The Bench lens is a separate, read-only scoreboard surface — NOT the live
  // organic-forecast list. It loads its own `forecast.bench` payload (cached so
  // re-entry is instant) and renders a distinct agent-vs-market Brier table.
  const onBench = activeTab?.kind === 'bench'
  const onOperations = activeTab?.kind === 'operations'
  const cachedBench = getOverlayCache<ForecastBenchResponse>('forecast.bench')
  const [bench, setBench] = useState<ForecastBenchResponse | null>(() => cachedBench ?? null)
  const [benchLoading, setBenchLoading] = useState(false)

  useEffect(() => {
    if (!onBench) {return}

    if (!cachedBench) {setBenchLoading(true)}
    let cancelled = false
    gw.request<unknown>('forecast.bench', {})
      .then(raw => {
        if (cancelled) {return}
        const result = asRpcResult<ForecastBenchResponse>(raw)

        if (result) {
          setOverlayCache('forecast.bench', result)
          setBench(result)
        }

        setBenchLoading(false)
      })
      .catch(() => {
        if (!cancelled) {setBenchLoading(false)}
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

    if (id == null) {return}
    pendingReselectId.current = null
    const idx = sortedVisible.findIndex(it => it.id === id)

    if (idx >= 0) {setSel(idx + lensOffset)}
  }, [sortedVisible, lensOffset])

  const armReselect = () => {
    pendingReselectId.current = selectedId
  }

  // Flash the mode a sort action lands on — the ONLY on-screen signal for the
  // keyless 'voi' mode (it has no column header to carry the ▲/▼ indicator).
  const flashSort = (state: TableSortState) => {
    if (!state.key) {
      setFlash('sort: book order')

      return
    }

    const label = SORT_MODE_LABELS[state.key] ?? state.key
    setFlash(`sort: ${label}${state.key === 'voi' ? '' : ` ${state.dir === 'asc' ? '↑' : '↓'}`}`)
  }

  const onSortCycle = () => {
    armReselect()
    flashSort(nextCycleState(sort.state, DESK_SORT_KEYS))
    sort.cycle()
  }

  const onSortToggle = () => {
    armReselect()

    if (sort.state.key) {
      flashSort({ dir: sort.state.dir === 'asc' ? 'desc' : 'asc', key: sort.state.key })
    }

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
  }, [factors, tabs, theses])

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
      section => section.title && FORECAST_PACKET_TAIL_TITLES.has(section.title)
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
    if (!selected) {return null}

    if (!packet || packetId !== selectedId) {return selected}

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

  // The A/T detached agent run rides the ONE attach hook: it discovers a live
  // reforecast/task job on mount (agent jobs are DETACHED — they keep working when
  // the desk closes; the operator: "unclear if those 'A' agent runs persist when we
  // move to different tabs"), polls its record every ~5s, and refreshes on the
  // jobs.* events. onProgress maps the record into AgentJob; onComplete toasts the
  // HONEST tally, reloads, and clears. `runAgent`/`submitTask` call attach() with
  // the id the start alias returned.
  const { attach: attachAgentJob } = useJobAttach(gw, AGENT_JOB_TYPES, {
    onComplete: rec => {
      agentRunningRef.current = false
      setAgentJob(null)
      const mode = rec.type === 'task' ? 'task' : 'agent'
      setFlash(
        rec.status === 'error' && rec.error
          ? `agent failed: ${truncate(rec.error, 80)}`
          : summarizeAgentJob(reforecastStatusFromRecord(rec), mode)
      )
      load() // reload once so the freshly-committed rows land
    },
    onProgress: rec => {
      agentRunningRef.current = true
      setAgentJob(agentJobFromRecord(rec))
    }
  })

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

  // The U/mass-U detached REFRESH job rides the SAME attach hook — detached exactly
  // like the agent job (it keeps re-pooling when the Desk closes; the operator's
  // original U bug was the client-side loop's queue vanishing on navigate-away). It
  // discovers a live refresh job on mount, polls its record, and refreshes on the
  // jobs.* events. onProgress maps the record into RefreshJob; onComplete toasts the
  // job-computed tally, reloads, and clears. `runRefresh` calls attach() with the
  // job_id jobs.start returned.
  const { attach: attachRefreshJob } = useJobAttach(gw, REFRESH_JOB_TYPES, {
    onComplete: rec => {
      refreshRunningRef.current = false
      setRefreshJob(null)
      setFlash(
        rec.status === 'error'
          ? `update failed: ${truncate((rec.error as string) ?? 'error', 80)}`
          : summarizeUpdate(refreshTally(rec.result))
      )
      load() // reload once so the freshly-committed rows land
    },
    onProgress: rec => {
      refreshRunningRef.current = true
      setRefreshJob(refreshJobFromRecord(rec))
    }
  })

  // The refresh job's still-in-flight rows (targetIds − doneIds) → the SAME ⋯ /
  // spinner markers the agent job uses; merged with agentRemaining for the list.
  const refreshRemaining = useMemo<ReadonlySet<string>>(() => {
    if (!refreshJob) {
      return EMPTY_ID_SET
    }

    const rem = new Set<string>()

    for (const id of refreshJob.targetIds) {
      if (!refreshJob.doneIds.has(id)) {
        rem.add(id)
      }
    }

    return rem
  }, [refreshJob])

  // The union of the two detached jobs' in-flight rows (only one runs at a time in
  // practice, so a merge is cheap and usually returns one side unchanged).
  const runningRemaining = useMemo<ReadonlySet<string>>(() => {
    if (refreshRemaining.size === 0) {
      return agentRemaining
    }

    if (agentRemaining.size === 0) {
      return refreshRemaining
    }

    const merged = new Set<string>(agentRemaining)

    for (const id of refreshRemaining) {
      merged.add(id)
    }

    return merged
  }, [agentRemaining, refreshRemaining])

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

    if (!targetId) {return}
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
    } else if (lensActive && refThesis) {
      // The pinned thesis row is the AGGREGATE, not a per-question job target — U/A
      // fan out over its MEMBERS, so marking the thesis itself would be meaningless.
      // Refuse with a brief note (the mark set never picks it up), then advance like
      // a normal Space so the cursor lands on the first markable member below.
      setFlash('thesis row runs its members — mark member questions instead')
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

  // `u` with a selection — the cheap RE-ARM (`forecast.reforecast`) fanned
  // SEQUENTIALLY over every marked target with a live swept progress flash. This
  // stays request-based (instant, no job needed): re-arming only marks the schedule
  // due, so there is no durable work to survive a navigate-away. On completion it
  // reloads once and flashes the honest re-armed count, then clears the marks.
  // (`U` / mass-`U` — the REAL deterministic update — is `runRefresh` below: ONE
  // detached runtime job, so its progress + remaining queue survive the Desk.)
  const runMass = () => {
    if (massRunningRef.current) {
      const p = massProgress
      setFlash(p ? `already ${p.verb} ${p.total}…` : 're-arming…')

      return
    }

    const targets = massTargets('rearm')

    if (!targets.length) {
      setFlash('select a forecast to re-arm')

      return
    }

    massRunningRef.current = true
    setFlash('') // clear any stale flash so only the live progress shows during the run
    const total = targets.length
    const tally: MassTally = { error: 0, noSources: 0, refreshed: 0, unchanged: 0 }

    const step = (i: number) => {
      if (unmountedRef.current) {return}

      if (i >= total) {
        massRunningRef.current = false
        setMassProgress(null)
        clearSelection()
        load() // one reload after the whole fan-out
        setFlash(summarizeRearm(tally))

        return
      }

      const { id, title } = targets[i]!
      setMassProgress({ current: i + 1, title: truncate(title, 32), total, verb: 're-arming' })
      gw.request('forecast.reforecast', { id })
        .then(() => {
          tally.refreshed += 1
        })
        .catch(() => {
          tally.error += 1
        })
        .finally(() => step(i + 1))
    }

    step(0)
  }

  // `U` / mass-`U` — REAL UPDATE NOW: the deterministic re-pool over the selection
  // (marked set, or a lens row → all its members, reusing massTargets) as ONE
  // detached runtime job (`jobs.start {type:'refresh'}`), replacing the old
  // client-side per-row `forecast refresh` loop that lived in component state. The
  // job is durable + re-attachable, so leaving the Desk no longer kills the progress
  // heuristic or strands mass-U's un-run tail (the operator's bug). The poll effect
  // drives the ⋯ markers + spinner + the honest tally toast; one job at a time — a
  // re-press while it runs just parks a guard note.
  const runRefresh = () => {
    if (refreshRunningRef.current) {
      setFlash(refreshJob ? `already updating ${refreshJob.done}/${refreshJob.total}…` : 'already updating…')

      return
    }

    const targets = massTargets('update')

    if (!targets.length) {
      setFlash('select a forecast to update now')

      return
    }

    const ids = targets.map(target => target.id)
    refreshRunningRef.current = true
    setFlash('') // the re-attach-backed progress line below is the sole feedback
    gw.request<unknown>('jobs.start', { spec: { question_ids: ids }, type: 'refresh' })
      .then(raw => {
        const r = asRpcResult<{ job_id?: string }>(raw)

        if (!r?.job_id) {
          refreshRunningRef.current = false
          setFlash('update start failed')

          return
        }

        setRefreshJob({
          current: null,
          done: 0,
          doneIds: new Set(),
          jobId: r.job_id,
          status: 'queued',
          targetIds: new Set(ids),
          total: ids.length
        })
        attachRefreshJob(r.job_id) // the attach hook polls + event-refreshes this job
        clearSelection()
      })
      .catch(() => {
        refreshRunningRef.current = false
        setFlash('update start failed')
      })
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
        attachAgentJob(r.run_id) // the attach hook polls + event-refreshes this job
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
        attachAgentJob(r.run_id) // the attach hook polls + event-refreshes this job
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
    if (!settingsTargetId) {return}
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

    // `←` steps to the previous lens (Tab/→ go forward). `h` is now Help on every
    // view, so the old `h`-for-previous-lens alias is retired — ← still does it.
    if (key.leftArrow) {
      return switchTab(tab - 1)
    }

    // `h` (and the `?` alias) open the unified Help modal — consistent everywhere.
    if (ch === 'h' || ch === '?') {
      return openHelpOverlay()
    }

    // The Bench lens is a read-only scoreboard: no per-row selection, modal, update,
    // settings, or filter — only tab-switching + refresh apply. Trap the rest here.
    if (onBench) {
      return
    }

    if (ch === 'u') {
      return selectedIds.size > 0 ? runMass() : runRearm()
    }

    if (ch === 'U') {
      return runRefresh()
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
  // A THESIS lens now renders the thesis AS the first table row (pinned, columned,
  // accent-highlighted) so the operator reads it in the same visual language as the
  // member forecasts below it — the old banner is gone. A FACTOR lens keeps its
  // DeskLensRow banner (non-thesis lenses are unaffected). So the banner only leads
  // a factor tab, and refThesis is threaded into DeskForecastList as its pinned row.
  const showBanner = hasLens && !refThesis

  const list = (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
      {showBanner ? (
        <DeskLensRow
          active={lensActive}
          onOpen={() => {
            if (modalOpen || settingsOpen || taskOpen || globalModal) {return}
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
        // Clicking the pinned thesis row selects it (row 0 / lensActive), the same
        // as an arrow-key landing — Enter then opens the thesis read.
        onPinnedSelect={() => { if (!modalOpen && !settingsOpen && !taskOpen && !globalModal) {setSel(0)} }}
        onSelect={i => { if (!modalOpen && !settingsOpen && !taskOpen && !globalModal) {setSel(i + lensOffset)} }}
        // The header sorts on click, but only while nothing modal is covering the
        // body — matches the row/tab click gating.
        onSort={modalOpen || settingsOpen || taskOpen || globalModal ? undefined : onSortByKey}
        // On a thesis tab the thesis is pinned as row 0 (never sorted with the
        // members); pinnedActive tracks whether the cursor is on it. Undefined on
        // every non-thesis tab, so those tables are unchanged.
        pinnedActive={lensActive}
        pinnedThesis={refThesis}
        runningId={agentJob?.current?.question_id ?? refreshJob?.current ?? null}
        runningIds={runningRemaining}
        sortDir={sort.state.dir}
        sortKey={sort.state.key}
        spinTick={agentJob || refreshJob ? now : 0}
        sweep={sweepCtx}
        t={t}
        visibleRows={Math.max(3, visibleRows - (showBanner ? 2 : 0))}
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
        nextActions={payload?.next_actions ?? []}
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
      // The question-detail body (ForecastDetail) renders the ONE wrapping title
      // itself, so the modal chrome must NOT print a second truncated copy — only
      // the lens read (thesis/factor) needs the overlay's own title line.
      title={lensActive ? (refThesis?.title ?? refFactor?.title ?? 'Lens') : undefined}
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
          { k: 'r', label: 'Refresh', run: () => { setBenchLoading(true); gw.request<unknown>('forecast.bench', {}).then(raw => { const r = asRpcResult<ForecastBenchResponse>(raw);

 if (r) { setOverlayCache('forecast.bench', r); setBench(r) } setBenchLoading(false) }).catch(() => setBenchLoading(false)) } },
          { k: 'h', label: 'Help', run: openHelpOverlay },
          { k: 'q', label: 'Close', run: onClose }
        ]
      : selectedIds.size > 0
        ? // With a selection the footer focuses on the mass actions (live-keys-only):
          // Update/Re-arm carry the live count, plus Mark/extend and the Esc clear.
          [
            { k: 'U', label: `Update (${selectedIds.size})`, run: () => runRefresh() },
            { k: 'u', label: `Re-arm (${selectedIds.size})`, run: () => runMass() },
            { k: 'A', label: `Agent (${selectedIds.size})`, run: () => runAgent() },
            { k: 'T', label: `Task (${selectedIds.size})`, run: () => openTask() },
            { k: 'Spc', label: 'Mark', run: () => toggleMark() },
            { k: '⇧↑↓', label: 'Extend' },
            { k: 'Esc', label: 'Clear', run: () => clearSelection() },
            { k: 'h', label: 'Help', run: openHelpOverlay },
            { k: 'q', label: 'Close', run: onClose }
          ]
        : [
            { k: '↑↓', label: 'Select' },
            { k: '⇥', label: 'Lens', run: () => switchTab(tab + 1) },
            { k: '⏎', label: 'Open', run: () => (lensActive || selected) && setModalOpen(true) },
            { k: 'U', label: 'Update', run: () => runRefresh() },
            { k: 'u', label: 'Re-arm', run: () => runRearm() },
            { k: 'R', label: 'Resolve', run: () => openResolve() },
            { k: 'n', label: 'New', run: () => openNewQuestion() },
            { k: 's', label: 'Settings', run: () => openSettings() },
            { k: 'o', label: 'Sort', run: () => onSortCycle() },
            { k: '/', label: 'Filter', run: () => { setSel(0); setQuery(''); setFiltering(true) } },
            { k: 'h', label: 'Help', run: openHelpOverlay },
            { k: 'q', label: 'Close', run: onClose }
          ]

  // When the selected row's review is overdue/stale, spell out the honest split:
  // `u` only re-arms the schedule, `U` runs a real update now. This is contextual
  // STATUS, not a shortcuts row — the FooterChips above are the single, canonical
  // key row (the old always-on prose duplicate was removed).
  const selectedDue = !onBench && !lensActive && selected ? dueText(selected, Math.floor(Date.now() / 60_000) * 60_000) : null
  const selectedStale = selectedDue?.status === 'now'
  const showStaleNote = !flash && !filtering && !modalOpen && !onBench && selectedStale

  // The in-flight REFRESH job's current question title (looked up from the live
  // book by its id). Powers the footer progress line; null when the job is between
  // questions or the row already left the book.
  const refreshTitle = refreshJob?.current
    ? (items.find(it => it.id === refreshJob.current)?.title ?? refreshJob.current)
    : null

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
      ) : refreshJob ? (
        // The detached REFRESH job's live progress — re-attach-backed, so it PERSISTS
        // across leaving/returning to the Desk (the operator's original U bug). Same
        // accent sweep as the mass re-arm line; a re-press guard note ("already
        // updating N/N…") parks alongside it.
        <Text wrap="truncate-end">
          <Text color={sweepColor(sweepStops(t), now)}>
            {`↻ updating ${refreshJob.done}/${refreshJob.total}${refreshTitle ? ` · ${truncate(refreshTitle, 32)}` : ''}…`}
          </Text>
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
      <DeskTabsStrip active={tab} onSelect={i => { if (!modalOpen && !settingsOpen && !taskOpen && !globalModal) {switchTab(i)} }} t={t} tabs={tabs} width={width} />
      {onOperations ? (
        <OperationsCockpit operations={payload?.operations} t={t} />
      ) : onBench ? (
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

// The desk-level "what should I touch next?" block: the server's top VOI actions,
// each a keystroke-hinting badge (U update · +src add sources · R resolve) + the
// forecast title + its one-sentence reason, wrapped (never truncated mid-reason).
// Returns null on a quiet book so the panel stays clean when nothing is pressing.
const NEXT_ACTION_BADGE: Record<string, string> = {
  add_sources: '+src',
  review_due: 'R',
  update: 'U'
}

export function NextBestActions({ actions, t, width }: { actions: ForecastNextAction[]; t: Theme; width: number }) {
  const top = (actions ?? []).slice(0, 3)

  if (!top.length) {
    return null
  }

  const badgeColor = (action: string | undefined): string =>
    action === 'add_sources' ? t.color.warn : action === 'review_due' ? t.color.ok : t.color.accent

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text bold color={t.color.label} wrap="truncate-end">
        Next best actions
      </Text>
      {top.map((action, index) => {
        const badge = NEXT_ACTION_BADGE[action.action ?? ''] ?? '·'

        return (
          <Box flexDirection="column" key={action.question_id ?? `na:${index}`}>
            <Text wrap="truncate-end">
              <Text bold color={badgeColor(action.action)}>{`${index + 1}. ${badge} `}</Text>
              <Text color={t.color.text}>{truncate(action.title ?? action.question_id ?? '—', Math.max(8, width - 8))}</Text>
            </Text>
            {action.reason ? (
              <Text color={t.color.muted} wrap="wrap">
                {wrapLines(action.reason, width, 2).map(line => `   ${line}`).join('\n')}
              </Text>
            ) : null}
          </Box>
        )
      })}
    </Box>
  )
}

export function DeskSummary({
  latestNote,
  nextActions = [],
  refFactor,
  refThesis,
  rows,
  selected,
  t,
  width
}: {
  latestNote: ForecastAnalystNote | null
  // Desk-level VOI ranking (the server's top-5 "touch next" actions). Rendered as
  // a compact top-3 block so the panel answers "what should I touch next?" without
  // the operator hunting the book — the same list the CLI `forecast next` prints.
  nextActions?: ForecastNextAction[]
  refFactor: ForecastFactor | undefined
  refThesis: ForecastThesis | undefined
  rows?: number
  selected: ForecastWorkspaceItem | null
  t: Theme
  width: number
}) {
  const inner = Math.max(16, width - 2)
  const actionsBlock = <NextBestActions actions={nextActions} t={t} width={inner} />
  // When an item is INSPECTED (a forecast, or the lens row), the book-wide
  // Next-best-actions block moves BELOW that item's detail, separated by the
  // established hairline rule — so the panel reads "here is this item, THEN what to
  // touch next across the book" instead of leading with book-wide noise. Only shown
  // when there ARE actions (NextBestActions renders null otherwise, so no dangling
  // rule). When nothing is inspected the block still leads (it is all there is).
  const hasActions = (nextActions ?? []).length > 0

  const trailingActions = hasActions ? (
    <Box flexDirection="column" marginTop={1}>
      <Text color={semantics(t).rule}>{'─'.repeat(inner)}</Text>
      <Box marginTop={1}>{actionsBlock}</Box>
    </Box>
  ) : null

  if (!selected) {
    // The lens row is inspected → give the panel the same rich treatment as a
    // forecast: the lens's own aggregate + history graph + counts + teaser, THEN the
    // next-actions block below the hairline rule.
    if (refThesis || refFactor) {
      return (
        <Box flexDirection="column" flexShrink={0} width={width}>
          <LensSummary refFactor={refFactor} refThesis={refThesis} rows={rows} t={t} width={width} />
          {trailingActions}
        </Box>
      )
    }

    // Truly nothing inspected → the book-wide block leads (current placement stands).
    return (
      <Box flexDirection="column" flexShrink={0} width={width}>
        {actionsBlock}
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
  const fullBandPoints = historyToBandPoints(selected)
  const hasSeries = fullBandPoints.some(point => finite(point.y))
  // Thin a dense dot-strip to its material moves (≤15 dots); data untouched.
  const preview = downsampleSeries(fullBandPoints.map(point => point.y))
  const bandPoints = preview.keptIndices.map(i => fullBandPoints[i]!)
  const { yMax, yMin } = chartScale(bandPoints)
  // Adapt the graph height to the terminal so the rest of the skinny panel (counts,
  // freshness, close, teaser) never gets pushed past the bottom on a short screen.
  const chartHeight = Math.max(4, Math.min(7, (rows ?? 28) - 16))

  const chart = hasSeries
    ? bandChart(bandPoints, { height: chartHeight, width: inner, yMax, yMin })
    : null

  // The teaser must READ COMPLETE or end honestly: the old silent
  // body.slice(0,120) chopped mid-thought with no ellipsis (the operator:
  // "some text at the bottom trails off, it doesn't seem to finish").
  const teaser = latestNote?.headline || (latestNote?.body ?? '') || ''
  const sources = new Set((selected.evidence ?? []).map(e => e.source).filter(Boolean)).size
  const panelCount = selected.panel?.estimates?.length ?? 0

  return (
    <Box flexDirection="column" flexShrink={0} width={width}>
      <LensHeader refFactor={refFactor} refThesis={refThesis} t={t} width={inner} />

      <Text bold color={t.color.primary} wrap="wrap">
        {wrapLines(selected.title ?? selected.id ?? 'untitled', inner, 3).join('\n')}
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
            {headlineCompact(selected, 2)}
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
            {`${selected.headline_kind === 'distribution' ? 'μ over time' : 'probability over time'}${
              preview.downsampled ? ` · ${preview.note}` : ''
            }`}
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
            {wrapLines(teaser, inner, 4).join('\n')}
          </Text>
        </Box>
      ) : null}

      <Box marginTop={1}>
        <Text color={t.color.accent} wrap="truncate-end">
          ⏎ open full detail
        </Text>
      </Box>
      {trailingActions}
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
  const fullBandPoints = refFactor
    ? (refFactor.history ?? []).map(p => ({ hi: p.band_high ?? null, lo: p.band_low ?? null, y: p.headline_probability ?? null }))
    : (refThesis?.history ?? []).map(p => ({ y: p.headline_probability ?? null }))

  const hasSeries = fullBandPoints.some(p => finite(p.y))
  // Thin a dense dot-strip to its material moves (≤15 dots); data untouched.
  const preview = downsampleSeries(fullBandPoints.map(p => p.y))
  const bandPoints = preview.keptIndices.map(i => fullBandPoints[i]!)
  const { yMax, yMin } = chartScale(bandPoints)
  const chartHeight = Math.max(4, Math.min(7, (rows ?? 28) - 14))
  const chart = hasSeries ? bandChart(bandPoints, { height: chartHeight, width: inner, yMax, yMin }) : null

  const members = (refThesis?.member_count ?? refFactor?.member_count) ?? 0
  const coverage = refThesis?.coverage ?? refFactor?.coverage
  const nEff = refThesis?.n_eff ?? refFactor?.n_eff
  const asOf = refThesis?.as_of ?? refFactor?.as_of
  const freshness = refThesis?.freshness ?? refFactor?.freshness
  const note = refThesis?.analyst_note ?? refFactor?.analyst_note
  const teaser = note?.headline || (note?.body ?? '') || ''

  return (
    <Box flexDirection="column" flexShrink={0} width={width}>
      <Text bold color={t.color.accent} wrap="wrap">
        {`${refThesis ? '◆' : '▣'} ${wrapLines(title, inner - 2, 2).join('\n  ')}`}
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
          <Text color={t.color.muted} wrap="truncate-end">
            {`${refThesis ? 'health over time' : 'return over time'}${preview.downsampled ? ` · ${preview.note}` : ''}`}
          </Text>
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
            {wrapLines(teaser, inner, 4).join('\n')}
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

// Desk column specs, sort-key comparables, and per-cell colour+text formatters
// live in ./desk/cells.js; re-exported so callers/tests import them from deskView.
export { deskCellText, deskSortValue, dueNowCell, SORT_MODE_LABELS }
export type { AgentJob, MassOutcome, MassTally, RefreshJob } from './desk/jobs.js'

export function DeskForecastList({
  cursor,
  empty,
  items,
  markedIds,
  nowMs,
  onPinnedSelect,
  onSelect,
  onSort,
  pinnedActive = false,
  pinnedThesis,
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
  // Click handler for the pinned thesis row (thesis lens only) → select row 0.
  onPinnedSelect?: () => void
  onSelect: (i: number) => void
  // Clicking a column header sorts by it; undefined while a modal covers the body.
  onSort?: (key: string) => void
  // Whether the cursor is on the pinned thesis row (composes the selection highlight
  // with the accent thesis treatment). Only meaningful when pinnedThesis is set.
  pinnedActive?: boolean
  // On a THESIS lens, the thesis rendered as the pinned first table row (row 0),
  // never sorted with the members below it. Undefined on every other tab, so those
  // tables are byte-identical to before.
  pinnedThesis?: ForecastThesis
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
    // On a thesis lens each member row carries a dim ⇅±pp "which race moves the
    // event" marker in a RESERVED trailing slot (never the trend/QUESTION space),
    // so it fits the width budget exactly and never truncates. 0 off the thesis
    // lens → every other table is byte-identical to before.
    const sensSlot = pinnedThesis ? 8 : 0
    const keep = new Set<string>(['q'])
    let usedW = 2 + satGutter // cursor marker + optional saturation gutter

    for (const key of DESK_PRIORITY) {
      const c = DESK_COLS.find(col => col.key === key)

      if (c && usedW + c.w + 1 <= avail - QMIN) {
        keep.add(key)
        usedW += c.w + 1
      }
    }

    // Split the leftover: the reserved sensitivity slot comes off the top, then a
    // capped slice feeds the trailing 1MO trend sparkline (so it actually renders —
    // QUESTION no longer eats 100% of the slack), and QUESTION takes the rest.
    const leftover = Math.max(QMIN, avail - usedW - sensSlot)
    // The QUESTION column wins the slack — titles matter more than the trend — so the
    // trailing trend sparkline only claims width once QUESTION is comfortable; short
    // titles never truncate to make room for it.
    const QCOMFORT = 30
    const trendW = leftover >= QCOMFORT + 8 ? Math.min(14, leftover - QCOMFORT) : 0
    const questionW = leftover - trendW
    const showTrend = trendW >= 8
    const colWidth = (c: DeskCol): number => (c.key === 'q' ? questionW : c.w)
    const keptCols = DESK_COLS.filter(c => keep.has(c.key))

    return { avail, colWidth, keptCols, satGutter, sem, sensSlot, showTrend, trendW }
  }, [t, width, hasUnderSaturated, pinnedThesis])

  const { avail, colWidth, keptCols, satGutter, sem, sensSlot, showTrend, trendW } = layout

  // Thesis lens only: member_id → its ∂P(event)/∂p_i swing (as a signed pp), read
  // from the pinned thesis's stored event sensitivities. Drives the dim "which race
  // matters" marker each member row shows. Empty on every other lens (no marker).
  const sensByMember = useMemo(() => {
    const map = new Map<string, number>()

    for (const s of pinnedThesis?.top_sensitivities ?? []) {
      if (s.member_id != null && finite(s.delta_p_event)) {
        map.set(s.member_id, s.delta_p_event! * 100)
      }
    }

    return map
  }, [pinnedThesis])

  // With a pinned thesis row the table is never truly empty — the thesis leads it —
  // so only short-circuit to the empty state when there is ALSO no pinned row.
  if (!items.length && !pinnedThesis) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted} wrap="wrap">
          {empty}
        </Text>
      </Box>
    )
  }

  // cursor may be -1 (the pinned thesis / lens row is selected, no member
  // highlighted); clamp for windowing so the members still show from the top. The
  // pinned thesis row (when present) consumes one body line, so the member window
  // reserves it.
  const bodyRows = pinnedThesis ? Math.max(2, visibleRows - 1) : visibleRows
  const { items: windowed, offset } = windowItems(items, Math.max(0, cursor), bodyRows)

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
        {sensSlot ? <Text bold color={sem.heading}>{pad('ΔPP', sensSlot, 'left')}</Text> : null}
      </Box>
      <Text color={sem.rule}>{'─'.repeat(avail)}</Text>
      {pinnedThesis ? (
        // Row 0 on a thesis lens: the thesis itself, pinned above the sortable
        // members and accent-highlighted so it reads unmistakably as the thesis
        // level. Its click selects row 0 (the cursor CAN land on it).
        <Box onClick={onPinnedSelect} width={width}>
          <DeskThesisRow
            active={pinnedActive}
            cols={keptCols}
            colWidth={colWidth}
            nowMs={nowMs}
            satGutter={satGutter}
            sem={sem}
            sensSlot={sensSlot}
            showTrend={showTrend}
            t={t}
            thesis={pinnedThesis}
            trendW={trendW}
          />
        </Box>
      ) : null}
      {windowed.map((item, i) => {
        const index = offset + i

        return (
          <Box key={item.id ?? `fc:${index}`} onClick={() => onSelect(index)} width={width}>
            <DeskListRow
              active={index === cursor}
              cols={keptCols}
              colWidth={colWidth}
              item={item}
              marked={markedIds.has(item.id ?? '')}
              nowMs={nowMs}
              running={runningIds.has(item.id ?? '')}
              runningNow={runningId !== null && runningId === item.id}
              satGutter={satGutter}
              sem={sem}
              sensitivityPp={sensByMember.size ? sensByMember.get(item.id ?? '') ?? null : null}
              sensSlot={sensSlot}
              showTrend={showTrend}
              spinFrame={runningId !== null && runningId === item.id ? spinTick : 0}
              sweep={sweep}
              t={t}
              trendW={trendW}
            />
          </Box>
        )
      })}
      {!items.length && pinnedThesis ? (
        // A thesis with no member questions yet still leads with its pinned row; the
        // empty note sits below it (never the whole-table empty short-circuit).
        <Text color={t.color.muted} wrap="wrap">{`  ${empty}`}</Text>
      ) : null}
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
  sensSlot = 0,
  sensitivityPp = null,
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
  // The reserved trailing width for the thesis-lens sensitivity marker (0 off a
  // thesis lens → nothing rendered, row byte-identical to before).
  sensSlot?: number
  // Thesis lens only: this member's signed ∂P(event) swing in pp (how much its
  // ±2pp move shifts the thesis event). Rendered in the reserved sensSlot as a dim
  // "⇅±X.XX"; null / negligible → the slot stays blank (alignment preserved).
  sensitivityPp?: number | null
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

  // Thesis lens: the member's signed ∂P(event) swing (in pp), shown IN the trend
  // slot (its reserved width, so it never truncates) IN PLACE of the 1MO spark —
  // on a thesis lens "which race moves the event" outranks the member's own spark.
  // Kept compact (no "pp" suffix; ⇅ + the h-help entry carry the unit) so even a
  // double-digit swing fits the 8-wide minimum trend budget. Non-movers keep their
  // spark; null off the thesis lens → the row is byte-identical to before.
  const sensMarker =
    finite(sensitivityPp) && Math.abs(sensitivityPp!) >= 0.005
      ? `⇅${sensitivityPp! >= 0 ? '+' : ''}${sensitivityPp!.toFixed(2)}`
      : ''

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
      {sensSlot ? <Text color={sem.subtle}>{pad(sensMarker, sensSlot, 'left')}</Text> : null}
      {alertBadge ? <Text color={t.color.statusBad}> {alertBadge}</Text> : null}
    </Text>
  )
})

// ── Pinned thesis row (thesis-lens leader) ───────────────────────────────────
// On a THESIS lens the thesis IS the first table row — pinned (never sorted with the
// members below it), columned like a forecast, and accent-stamped so it reads
// unmistakably as the thesis level. It reuses the member row's exact formatters via
// a thin ForecastWorkspaceItem projection, so PROB/1D/1W/1MO/AGE render byte-
// identically to a real forecast; the columns the thesis has no analogue for
// (EV/SRC/RDY/NEXT) render an honest '—' (absence as absence, never a fabricated 0).

// The thesis EVENT probability the desk pins into the PROB column. The workspace
// payload carries it top-level as `headline_probability` (dashboard.py: the current
// event probability, health as the fallback) — now declared on the generated
// ForecastThesis model. Fall back to the newest finite history headline (the same
// value the series ends on). Absent both → null → '—'.
const thesisHeadline = (thesis: ForecastThesis): null | number => {
  const direct = thesis.headline_probability

  if (finite(direct)) {
    return direct
  }

  const hist = thesis.history ?? []

  for (let i = hist.length - 1; i >= 0; i -= 1) {
    const y = hist[i]?.headline_probability

    if (finite(y)) {
      return y
    }
  }

  return null
}

// Project the thesis onto the ForecastWorkspaceItem shape the cell formatters read:
// its EVENT probability drives PROB, its history drives the window deltas + spark,
// its as_of drives AGE. Nothing else is invented (headline_kind pinned to
// 'probability' so PROB renders the same pct as a binary forecast, never a fake μ).
const thesisAsItem = (thesis: ForecastThesis): ForecastWorkspaceItem => ({
  as_of: thesis.as_of ?? undefined,
  freshness: thesis.freshness,
  headline_kind: 'probability',
  headline_probability: thesisHeadline(thesis),
  history: (thesis.history ?? []).map(point => ({
    as_of: point.as_of,
    headline_probability: point.headline_probability
  })),
  id: thesis.id,
  title: thesis.title
})

// The thesis's REGIME-AWARE window deltas. Computed off `thesis.history` (not the
// projected item.history) because the history points carry `headline_regime`, and
// a window must only compare WITHIN the current regime — a baseline that predates
// the event-config switch (health → event series) is an honest '—' (new series),
// never a cross-regime lie. Members carry no regime so this never fires for them.
const thesisWindows = (
  thesis: ForecastThesis,
  nowMs: number
): { '1d': number | null; '1mo': number | null; '1w': number | null } => ({
  '1d': windowDelta(thesis.history, nowMs, 1),
  '1mo': windowDelta(thesis.history, nowMs, 30),
  '1w': windowDelta(thesis.history, nowMs, 7)
})

// One pinned-thesis cell's colour + text. PROB/1D/1W/1MO/AGE reuse deskCellText via
// the projection (identical rendering to a member row); QUESTION + PROB wear the
// thesis accent; EV/SRC/RDY/NEXT — which the aggregate has no per-question analogue
// for — render an honest '—'. Exported so the honest-absence + 2dp-prob contract is
// unit-testable in isolation (the deskCellText / dueNowCell pattern).
export const thesisCellText = (
  key: string,
  thesis: ForecastThesis,
  sem: Semantics,
  t: Theme,
  windows: { '1d': number | null; '1mo': number | null; '1w': number | null },
  nowMs: number
): { color: string; text: string } => {
  const item = thesisAsItem(thesis)

  switch (key) {
    case 'q':
      return { color: t.color.accent, text: item.title ?? item.id ?? 'thesis' }

    case 'prob':
      return { color: t.color.accent, text: headlineCompact(item, 2) }

    case '1d':

    case '1mo':
    case '1w': {
      // The number/colour comes from the precomputed regime-aware window. When it
      // is null we distinguish two honest absences: a bare '—' (no in-window
      // anchor) vs '—ⁿ' — a "new series" hint painted the SAME subtle colour —
      // when the only in-window baseline predates the event-config regime switch,
      // so there is no same-regime comparison yet (never a cross-regime lie).
      const value = windows[key]

      if (value === null) {
        const days = key === '1d' ? 1 : key === '1w' ? 7 : 30

        if (windowDeltaDetail(thesis.history, nowMs, days).newSeries) {
          return { color: sem.subtle, text: '—ⁿ' }
        }
      }

      return deskCellText(key, item, sem, t, windows, nowMs, undefined)
    }

    case 'age':
      return deskCellText(key, item, sem, t, windows, nowMs, undefined)

    default:
      // EV / SRC / RDY / NEXT: the thesis aggregate has no per-question analogue —
      // render an honest '—' rather than a fabricated 0 / warning colour.
      return { color: sem.subtle, text: '—' }
  }
}

const DeskThesisRow = memo(function DeskThesisRow({
  active,
  colWidth,
  cols,
  nowMs,
  satGutter,
  sem,
  sensSlot = 0,
  showTrend,
  t,
  thesis,
  trendW
}: {
  active: boolean
  colWidth: (c: DeskCol) => number
  cols: DeskCol[]
  nowMs: number
  satGutter: number
  sem: Semantics
  // Reserved trailing sensitivity-marker width (the members carry the markers; the
  // pinned thesis row keeps the slot BLANK so the columns line up beneath it).
  sensSlot?: number
  showTrend: boolean
  t: Theme
  thesis: ForecastThesis
  trendW: number
}) {
  const item = thesisAsItem(thesis)
  // Regime-aware window deltas (off thesis.history, which carries headline_regime):
  // a delta never straddles the health→event series switch.
  const windows = thesisWindows(thesis, nowMs)
  // The 1-month level trend spark, on the same fixed 0..1 scale a binary member row
  // uses (the thesis event probability is a 0..1 quantity).
  const sparkValues = (item.history ?? []).slice(-trendW).map(point => point.headline_probability ?? null)
  const trend = showTrend ? levelSparkline(sparkValues) : ''
  // Colour the "1MO" trend by the SAME regime-honest 1MO window the 1MO cell reads
  // — so when that cell is an honest '—' (no same-regime move / new series) the
  // spark is subtle too, never a coloured cross-regime `thesis.delta` that
  // contradicts the '—' cells beside it.
  const trendColor = windows['1mo'] !== null ? dirColor(sem, windows['1mo']) : sem.subtle

  return (
    <Text backgroundColor={active ? t.color.selectionBg : undefined} bold wrap="truncate-end">
      {/* The ◆ thesis marker ALWAYS leads the gutter (not the member ▸): the pinned
          row's identity is the diamond, and the selection background — not an arrow —
          signals the cursor, so the two compose without hiding each other. */}
      <Text color={active ? sem.cursor : t.color.accent}>{'◆ '}</Text>
      {satGutter ? <Text color={t.color.muted}>{'  '}</Text> : null}
      {cols.map(c => {
        const cell = thesisCellText(c.key, thesis, sem, t, windows, nowMs)
        // QUESTION + PROB carry the thesis accent (or the high-contrast selection fg
        // when the cursor is on the row); the rest keep their column semantics. The
        // whole row is bold, so it reads as the aggregate even where colour is muted.
        const stamp = c.key === 'q' || c.key === 'prob'
        const color = active && stamp ? sem.selectionFg : cell.color

        return (
          <Text color={color} key={c.key}>
            {`${pad(cell.text, colWidth(c), c.align)} `}
          </Text>
        )
      })}
      {showTrend ? <Text color={active ? sem.selectionFg : trendColor}>{trend}</Text> : null}
      {sensSlot ? <Text>{pad('', sensSlot, 'left')}</Text> : null}
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
  if (edge === null || edge === undefined || !finite(edge)) {return { color: t.color.muted, text: '—' }}
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
