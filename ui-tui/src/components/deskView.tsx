import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { Fragment, type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from 'react'

import { forecastQuestionDetailSections } from '../app/forecastPanel.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastAnalystNote,
  ForecastBenchResponse,
  ForecastBenchRow,
  ForecastFactor,
  ForecastQuestionPacketResponse,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspacePanel,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'
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
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { dirColor, pad, type Semantics, semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
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

  // On a thesis/factor tab, a "lens row" leads the section (row 0) — a click/Enter
  // into the lens's own aggregate read. The cursor space is [lens?, ...forecasts].
  const hasLens = !!(refThesis || refFactor)
  const lensOffset = hasLens ? 1 : 0
  const rowCount = lensOffset + visible.length
  const clampedSel = Math.min(sel, Math.max(0, rowCount - 1))
  const lensActive = hasLens && clampedSel === 0
  const selected = lensActive ? null : visible[clampedSel - lensOffset] ?? null
  const selectedId = selected?.id ?? null

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
  useEffect(() => {
    if (!selectedId) {
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
  }, [selectedId, gw])

  // Reset the modal scroll to the top whenever the selected entity changes.
  useEffect(() => {
    if (modalOpen) {
      modalScrollRef.current?.scrollTo?.(0)
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

  // Switch tabs reset the selection to row 0 (locked decision).
  const switchTab = (next: number) => {
    const n = Math.max(1, tabs.length)
    setTab(((next % n) + n) % n)
    setSel(0)
    setModalOpen(false)
  }

  // Run update: queue the selected forecast (or, on a lens row, the thesis/factor)
  // for the next reforecast cycle — re-arms its schedule to due-now, so NEXT flips
  // to "now" on the refresh and the autonomous cycle reforecasts it on its next tick.
  const runUpdate = () => {
    const targetId = lensActive ? (refThesis?.id ?? refFactor?.id) : selectedId
    const targetTitle = lensActive ? (refThesis?.title ?? refFactor?.title) : selected?.title
    if (!targetId) return
    setFlash(`↻ queued for update: ${truncate(targetTitle ?? targetId, 32)}`)
    gw.request('forecast.reforecast', { id: targetId })
      .then(() => load()) // silent refresh (no 'refreshed' flash) so NEXT flips to "now" but the queued message stays
      .catch(() => setFlash('update failed'))
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
    // The settings modal owns the keyboard while open (it has its own useInput);
    // trap everything here so the desk can't double-handle a key.
    if (settingsOpen) {
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
      // Esc clears an active filter first, else closes the view.
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

    if (key.tab || key.rightArrow) {
      return switchTab(tab + 1)
    }

    if (key.leftArrow) {
      return switchTab(tab - 1)
    }

    // The Bench lens is a read-only scoreboard: no per-row selection, modal, update,
    // settings, or filter — only tab-switching + refresh apply. Trap the rest here.
    if (onBench) {
      if (ch === 'h') {
        return setFlash('◇ Bench: read-only ForecastBench scoreboard · Tab/←→ lens · r refresh · q close')
      }

      return
    }

    if (ch === 'u') {
      return runUpdate()
    }

    if (ch === 's') {
      if (settingsTargetId) {
        return openSettings()
      }

      return
    }

    if (ch === 'h') {
      return setFlash('↑↓ select · Tab/←→ lens · Enter open · / filter · q close')
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
  })

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
          <Text color={t.color.muted}>No active forecasts. Create one with /forecast new …</Text>
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
            if (modalOpen || settingsOpen) return
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
        items={visible}
        onSelect={i => { if (!modalOpen && !settingsOpen) setSel(i + lensOffset) }}
        t={t}
        visibleRows={Math.max(3, visibleRows - (hasLens ? 2 : 0))}
        width={listW}
      />
    </Box>
  )

  const panel = (
    <DeskSummary
      latestNote={latestNote}
      refFactor={refFactor}
      refThesis={refThesis}
      rows={termRows}
      selected={selected}
      t={t}
      width={panelWidth}
    />
  )

  // ── Detail modal content (reused heavy components) ────────────────────────
  const modalBody = selected
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
  const refRead = !lensActive ? null : refThesis ? (
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

  const modal = modalOpen ? (
    <ModalOverlay
      cols={cols}
      footerHint="↑↓ scroll · PgUp/PgDn page · Esc/q close"
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
      : [
          { k: '↑↓', label: 'Select' },
          { k: '⇥', label: 'Lens', run: () => switchTab(tab + 1) },
          { k: '⏎', label: 'Open', run: () => (lensActive || selected) && setModalOpen(true) },
          { k: 'u', label: 'Update', run: () => runUpdate() },
          { k: 's', label: 'Settings', run: () => openSettings() },
          { k: '/', label: 'Filter', run: () => { setSel(0); setQuery(''); setFiltering(true) } },
          { k: 'h', label: 'Help', run: () => setFlash('↑↓ select · Tab/←→ lens · Enter open · u update · s settings · / filter · q close') },
          { k: 'q', label: 'Close', run: onClose }
        ]

  const footerHint = filtering
    ? `filter: ${truncate(query, Math.max(8, cols - 30))}▌  · ⏎ apply · Esc clear`
    : modalOpen
      ? '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · Esc/q close'
      : onBench
        ? '◇ Bench — read-only ForecastBench scoreboard · Tab/←→ lens · r refresh · q close'
        : '↑↓/jk select · Tab/←→ lens · ⏎ open · u update · s settings · / filter · r refresh · h help · q close'

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <FooterChips chips={chips} t={t} />
      <Text color={t.color.muted} wrap="truncate-end">
        {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
        {footerHint}
      </Text>
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {/* The body stays mounted; the modal paints ABOVE it as an absolute overlay.
          Body clicks are gated while the modal is open (switchTab/onSelect early-
          return) so the still-visible tabs/rows can't leak interaction — the
          keyboard is already trapped by the `if (modalOpen) return` in useInput. */}
      <DeskTabsStrip active={tab} onSelect={i => { if (!modalOpen && !settingsOpen) switchTab(i) }} t={t} tabs={tabs} width={width} />
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
    </Box>
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
  { align: 'right', key: 'age', label: 'AGE', w: 7 },
  { align: 'right', key: 'next', label: 'NEXT', w: 7 }
]

// Keep by priority when narrow (render still follows display order). QUESTION is
// always kept; PROB matters most, then the wider 1W/1MO windows, then NEXT (when
// the forecast next auto-updates), then EV, then the noisier 1D, then AGE.
const DESK_PRIORITY = ['prob', '1w', '1mo', 'next', 'ev', '1d', 'age']

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
// switch stays a pure formatter.
const deskCellText = (
  key: string,
  item: ForecastWorkspaceItem,
  sem: Semantics,
  t: Theme,
  windows: { '1d': number | null; '1mo': number | null; '1w': number | null },
  nowMs: number
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
      // A resolution-date fallback is informational (not an urgent review) → paint
      // it subtle so the "⤓" marker, not colour, signals the distinction.
      const color = due.status === 'now' ? t.color.error : due.status === 'soon' ? t.color.warn : sem.subtle
      return { color, text: due.text }
    }

    case 'ev':
      return { color: sem.subtle, text: String(item.evidence_count ?? 0) }

    case 'prob':
      return { color: t.color.text, text: headlineCompact(item) }

    case 'q':
      return { color: t.color.label, text: item.title ?? item.id ?? 'untitled' }

    default:
      return { color: t.color.text, text: '' }
  }
}

function DeskForecastList({
  cursor,
  empty,
  items,
  onSelect,
  t,
  visibleRows,
  width
}: {
  cursor: number
  empty: string
  items: ForecastWorkspaceItem[]
  onSelect: (i: number) => void
  t: Theme
  visibleRows: number
  width: number
}) {
  const sem = semantics(t)

  if (!items.length) {
    return (
      <Box flexDirection="column" flexGrow={1}>
        <Text color={t.color.muted} wrap="wrap">
          {empty}
        </Text>
      </Box>
    )
  }

  // Usable inner width (leave a column for the cursor marker + a trailing space).
  const avail = Math.max(20, width - 2)

  // Pack the FIXED numeric columns by priority, but ALWAYS reserve QMIN for the
  // QUESTION column so a column is dropped (priority-drop) rather than QUESTION
  // overflowing + clipping the rightmost numerics on a tight terminal.
  const QMIN = 14
  const keep = new Set<string>(['q'])
  let usedW = 2 // cursor marker
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

  // cursor may be -1 (the lead lens row is selected, no forecast highlighted);
  // clamp for windowing so the list still shows from the top.
  const { items: windowed, offset } = windowItems(items, Math.max(0, cursor), visibleRows)

  return (
    <Box flexDirection="column" flexGrow={0} flexShrink={0} minHeight={0} overflow="hidden">
      <Text bold color={sem.heading} wrap="truncate-end">
        {'  '}
        {keptCols.map(c => `${pad(c.label, colWidth(c), c.align)} `).join('')}
        {showTrend ? pad('1MO', trendW, 'left') : ''}
      </Text>
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
              sem={sem}
              showTrend={showTrend}
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

function DeskListRow({
  active,
  colWidth,
  cols,
  item,
  sem,
  showTrend,
  t,
  trendW
}: {
  active: boolean
  colWidth: (c: DeskCol) => number
  cols: DeskCol[]
  item: ForecastWorkspaceItem
  sem: Semantics
  showTrend: boolean
  t: Theme
  trendW: number
}) {
  const nowMs = Date.now()
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

  return (
    <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
      <Text bold={active} color={active ? sem.cursor : sem.faint}>
        {active ? '▸ ' : '  '}
      </Text>
      {cols.map(c => {
        const cell = deskCellText(c.key, item, sem, t, windows, nowMs)
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
}

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
