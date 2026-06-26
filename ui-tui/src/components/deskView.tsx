import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { Fragment, type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from 'react'

import { forecastQuestionDetailSections } from '../app/forecastPanel.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastAnalystNote,
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

  // The ordered lens tabs (theses → factors → #tag-groups → All).
  const tabs = useMemo<DeskTab[]>(() => (payload ? buildDeskTabs(payload) : []), [payload])
  const activeTab = tabs[Math.min(tab, Math.max(0, tabs.length - 1))]
  const refThesis = tabRefThesis(activeTab, theses)
  const refFactor = tabRefFactor(activeTab, factors)

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

  const modalPageSize = Math.max(4, termRows - 12)

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

    if (ch === '/') {
      setQuery('')

      return setFiltering(true)
    }

    if (ch === 'r') {
      return load(true)
    }

    if (ch === 'h') {
      return setFlash('↑↓ select · Tab/←→ lens · Enter open · / filter · q close')
    }

    if (key.tab || key.rightArrow) {
      return switchTab(tab + 1)
    }

    if (key.leftArrow) {
      return switchTab(tab - 1)
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
            if (modalOpen) return
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
        onSelect={i => { if (!modalOpen) setSel(i + lensOffset) }}
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

  // The lens tab can lead with the thesis/factor aggregate read — shown ABOVE
  // the forecast detail in the modal so the lens context heads it.
  const refRead = refThesis ? (
    <ThesisDeskRead t={t} thesis={refThesis} width={Math.max(20, (wide ? Math.min(cols - 10, 92) : cols - 6) - 4)} />
  ) : refFactor ? (
    <FactorDeskRead factor={refFactor} t={t} width={Math.max(20, (wide ? Math.min(cols - 10, 92) : cols - 6) - 4)} />
  ) : null

  const modal = modalOpen ? (
    <DeskModal
      narrow={!wide}
      onClose={() => setModalOpen(false)}
      rows={termRows}
      scrollRef={modalScrollRef}
      t={t}
      tick={now}
      title={lensActive ? (refThesis?.title ?? refFactor?.title ?? 'Lens') : (selected?.title ?? selected?.id ?? 'Forecast')}
      width={cols}
    >
      {refRead ? (
        <Box flexDirection="column" marginBottom={1}>
          {refRead}
        </Box>
      ) : null}
      {modalBody}
    </DeskModal>
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
    : [
        { k: '↑↓', label: 'Select' },
        { k: '⇥', label: 'Lens', run: () => switchTab(tab + 1) },
        { k: '⏎', label: 'Open', run: () => (lensActive || selected) && setModalOpen(true) },
        { k: '/', label: 'Filter', run: () => { setSel(0); setQuery(''); setFiltering(true) } },
        { k: 'h', label: 'Help', run: () => setFlash('↑↓ select · Tab/←→ lens · Enter open · / filter · q close') },
        { k: 'q', label: 'Close', run: onClose }
      ]

  const footerHint = filtering
    ? `filter: ${truncate(query, Math.max(8, cols - 30))}▌  · ⏎ apply · Esc clear`
    : modalOpen
      ? '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · Esc/q close'
      : '↑↓/jk select · Tab/←→ lens · ⏎ open · / filter · r refresh · h help · q close'

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
      <DeskTabsStrip active={tab} onSelect={i => { if (!modalOpen) switchTab(i) }} t={t} tabs={tabs} width={width} />
      {wide ? (
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
            <Text color={t.color.muted}>{'  score '}</Text>
            <Text bold color={t.color.primary}>{finite(refThesis.thesis_score) ? refThesis.thesis_score.toFixed(0) : '—'}</Text>
            <Text color={t.color.muted}>{'  '}</Text>
            <Text bold color={deltaColor}>{glyph}</Text>
          </Text>
        ) : refFactor ? (
          <Text wrap="truncate-end">
            <Text color={t.color.muted}>μ </Text>
            <Text bold color={signColor(t, refFactor.mean)}>{finite(refFactor.mean) ? `${trimNum(refFactor.mean)}${unit}` : '—'}</Text>
            <Text color={t.color.muted}>{'  vol '}</Text>
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

  let agg = ''
  if (refThesis) {
    const health = refThesis.health_probability
    const score = refThesis.thesis_score
    agg = `health ${refThesis.health_display ?? (finite(health) ? pct(health) : '—')} · score ${finite(score) ? score.toFixed(0) : '—'}`
  } else if (refFactor) {
    const unit = unitSuffix(refFactor.units)
    agg = `μ ${finite(refFactor.mean) ? `${trimNum(refFactor.mean)}${unit}` : '—'} · vol ${finite(refFactor.volatility) ? `${trimNum(refFactor.volatility)}${unit}` : '—'}`
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
        <Text wrap="truncate-end">
          <Text color={t.color.muted}>health </Text>
          <Text bold color={healthColor(t, health)}>
            {refThesis.health_display ?? (finite(health) ? pct(health) : '—')}
          </Text>
          <Text color={t.color.muted}>{'  score '}</Text>
          <Text color={t.color.text}>{finite(score) ? score.toFixed(0) : '—'}</Text>
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
          <Text color={t.color.muted}>{'  vol σ '}</Text>
          <Text color={t.color.text}>{finite(refFactor.volatility) ? `${trimNum(refFactor.volatility)}${unit}` : '—'}</Text>
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
  { align: 'right', key: 'age', label: 'AGE', w: 7 }
]

// Keep by priority when narrow (render still follows display order). QUESTION is
// always kept; PROB matters most, then the wider 1W/1MO windows, then EV, then
// the noisier 1D, then AGE.
const DESK_PRIORITY = ['prob', '1w', '1mo', 'ev', '1d', 'age']

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
  windows: { '1d': number | null; '1mo': number | null; '1w': number | null }
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
        const cell = deskCellText(c.key, item, sem, t, windows)
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
// Esc/q close — handled by the parent keymap while the modal is open.

function DeskModal({
  children,
  narrow,
  onClose: _onClose,
  rows,
  scrollRef,
  t,
  tick,
  title,
  width
}: {
  children: ReactNode
  narrow: boolean
  onClose: () => void
  rows: number
  scrollRef: RefObject<null | ScrollBoxHandle>
  t: Theme
  tick: number
  title: string
  width: number
}) {
  const modalW = narrow ? Math.max(40, width - 2) : Math.max(48, Math.min(width - 6, 100))
  const modalH = Math.max(10, Math.min(rows - 6, 36))

  // Painted as an ABSOLUTE overlay over the desk body (not replacing it): the
  // background list stays visible AROUND the box, while the box's solid black
  // backgroundColor makes its interior opaque so nothing leaks through it.
  // The wrapper is CONTENT-sized (height = the box) + positioned with a computed
  // top — a full-height (height={rows}) wrapper overflows the desk pane and the
  // body reflows away on the next re-render.
  const modalTop = Math.max(0, Math.floor((rows - modalH) / 2) - 1)
  return (
    <Box alignItems="center" left={0} position="absolute" top={modalTop} width={width}>
      <Box
        backgroundColor="black"
        borderColor={t.color.accent}
        borderStyle="round"
        flexDirection="column"
        height={modalH}
        paddingX={2}
        paddingY={1}
        width={modalW}
      >
        <Text bold color={t.color.primary} wrap="truncate-end">
          {truncate(title, Math.max(10, modalW - 6))}
        </Text>
        <Box flexDirection="row" flexShrink={0} height={Math.max(3, modalH - 5)} marginTop={1} minHeight={0}>
          <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
            {children}
          </ScrollBox>
          <NoSelect flexShrink={0} marginLeft={1}>
            <OverlayScrollbar scrollRef={scrollRef} t={t} tick={tick} />
          </NoSelect>
        </Box>
        <Text color={t.color.muted}>↑↓ scroll · PgUp/PgDn page · Esc/q close</Text>
      </Box>
    </Box>
  )
}

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
