import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastDashboardAlert,
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastWarningsAutomodeComplete,
  ForecastWarningsAutomodeError,
  ForecastWarningsAutomodeProgress,
  ForecastWarningsAutomodeRunResponse,
  ForecastWarningsResolveResponse
} from '../gatewayTypes.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { semantics } from '../lib/visualSemantics.js'
import { classifyWarning } from '../lib/warningKind.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { WarningResolveSheet } from './warningResolveSheet.js'

export const openAlertsView = () => patchOverlayState({ alerts: true })
export const closeAlertsView = () => patchOverlayState({ alerts: false })

// Map a severity / reason word to a semantic colour so the list is scannable.
const sevColor = (t: Theme, severity: string | undefined): string => {
  const s = (severity || '').toLowerCase()

  if (/crit|alert|fail|block|error|high/.test(s)) {
    return t.color.error
  }

  if (/warn|medium|review|stale|due|gap/.test(s)) {
    return t.color.warn
  }

  return t.color.muted
}

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// A row is directly resolvable from the TUI only when it is QUESTION-scoped (a
// concrete forecast the resolve sheet can act on). Source/domain/global alerts
// are skipped by the cursor — they are surfaced for review or swept by automode.
const isQuestionScoped = (a: ForecastDashboardAlert): boolean =>
  !!a.id && ((a.scope_type ?? '') === 'question' || /^fq_/.test(a.scope_ref ?? ''))

interface AutomodeState {
  done: number
  id: string
  phase: string
  reason?: string
  total: number
}

interface AlertsViewProps {
  gw: GatewayClient
  onClose: () => void
  sessionId?: string
  t: Theme
}

export function AlertsView({ gw, onClose, sessionId = '', t }: AlertsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const sem = semantics(t)

  const [data, setData] = useState<ForecastDashboardResponse | null>(
    () => getOverlayCache<ForecastDashboardResponse>('forecast.dashboard:alerts') ?? null
  )

  const [loading, setLoading] = useState(!data)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const [sel, setSel] = useState(0)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [automode, setAutomode] = useState<AutomodeState | null>(null)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)
  // Mirror the live automode job id into a ref so the (stable) gateway-event
  // handlers can filter their own job's events without re-subscribing.
  const automodeIdRef = useRef<null | string>(null)

  const load = (announce = false) => {
    setLoading(!data)
    gw.request<unknown>('forecast.dashboard', { limit: 50 })
      .then(raw => {
        const result = asRpcResult<ForecastDashboardResponse>(raw)

        if (!result) {
          setError('forecast.dashboard returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('forecast.dashboard:alerts', result)
        setData(result)
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
    scrollRef.current?.scrollTo(0)
  }, [data])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const summary = data?.summary
  const alerts: ForecastDashboardAlert[] = useMemo(() => summary?.alerts ?? [], [summary])
  const reviews: ForecastDashboardReview[] = summary?.review_queue ?? []
  const gaps = summary?.evidence_status?.gaps ?? []
  const staleAssumptions = summary?.stale_assumption_count ?? 0
  const staleRefs = summary?.stale_reference_class_count ?? 0

  // The cursor lives over the question-scoped subset (skips non-question rows).
  const selectable = useMemo(() => alerts.filter(isQuestionScoped), [alerts])
  const clampedSel = Math.min(sel, Math.max(0, selectable.length - 1))
  const selectedAlert = selectable[clampedSel] ?? null
  const selectedId = selectedAlert?.id ?? null

  // Best-effort follow: keep the selected row roughly centred as the cursor moves
  // (each alert occupies ~4 rendered rows; the leading section header ~2).
  useEffect(() => {
    if (!selectedId) {
      return
    }

    const allIndex = alerts.findIndex(a => a.id === selectedId)

    if (allIndex < 0) {
      return
    }

    const pageSize = Math.max(4, termRows - 10)
    const rowsBefore = 2 + allIndex * 4
    scrollRef.current?.scrollTo(Math.max(0, rowsBefore - Math.floor(pageSize / 2)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // ── Automode lifecycle (streamed gateway events) ──────────────────────────
  useEffect(() => {
    const onProgress = (p: ForecastWarningsAutomodeProgress) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      setAutomode(prev =>
        prev
          ? { ...prev, done: p.done ?? prev.done, total: p.total ?? prev.total, phase: p.phase ?? prev.phase, reason: p.reason ?? prev.reason }
          : prev
      )
    }

    const onComplete = (p: ForecastWarningsAutomodeComplete) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      automodeIdRef.current = null
      setAutomode(null)
      setFlash(
        `automode ${p.cancelled ? 'cancelled' : 'done'} — ${p.processed ?? 0}/${p.total ?? 0} processed`
      )
      load()
    }

    const onError = (p: ForecastWarningsAutomodeError) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      automodeIdRef.current = null
      setAutomode(null)
      setFlash(`automode error: ${p.message ?? 'failed'}`)
    }

    gw.on('forecast.warnings.automode.progress', onProgress)
    gw.on('forecast.warnings.automode.complete', onComplete)
    gw.on('forecast.warnings.automode.error', onError)

    return () => {
      gw.off?.('forecast.warnings.automode.progress', onProgress)
      gw.off?.('forecast.warnings.automode.complete', onComplete)
      gw.off?.('forecast.warnings.automode.error', onError)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  const startAutomode = () => {
    if (automode) {
      return
    }

    setFlash('automode starting…')
    gw.request<unknown>('forecast.warnings.automode.run', { session_id: sessionId })
      .then(raw => {
        const res = asRpcResult<ForecastWarningsAutomodeRunResponse>(raw)

        if (!res?.job_id) {
          setFlash('automode failed to start')

          return
        }

        automodeIdRef.current = res.job_id
        setAutomode({ done: 0, id: res.job_id, phase: 'start', total: 0 })
      })
      .catch((err: unknown) => {
        setFlash(`automode error: ${err instanceof Error ? err.message : String(err)}`)
      })
  }

  const cancelAutomode = () => {
    if (!automode) {
      return
    }

    setFlash('cancelling automode…')
    gw.request('forecast.warnings.automode.cancel', { job_id: automode.id }).catch(() => undefined)
  }

  const toggleAutomode = () => (automode ? cancelAutomode() : startAutomode())

  // Resolve the selected alert directly (the `a` shortcut) — drives the same
  // gated dispatcher the sheet does, then reports the real per-alert status.
  const resolveSelected = () => {
    if (resolving || !selectedAlert?.id) {
      return
    }

    const target = selectedAlert.id
    const kindLabel = classifyWarning(selectedAlert.reason)
    setResolving(true)
    setFlash(`resolving ${truncate(selectedAlert.scope_ref ?? target, 28)}…`)
    gw.request<unknown>('forecast.warnings.resolve', { alert_id: target })
      .then(raw => {
        const res = asRpcResult<ForecastWarningsResolveResponse>(raw)
        const first = res?.results?.[0]
        const status = first?.status ?? 'failed'
        setResolving(false)
        setFlash(`${status} · ${kindLabel} · ${truncate(first?.detail ?? '', 48)}`)
        load()
      })
      .catch((err: unknown) => {
        setResolving(false)
        setFlash(`resolve failed: ${err instanceof Error ? err.message : String(err)}`)
      })
  }

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    // The resolve sheet owns the keyboard while open (it has its own useInput).
    if (sheetOpen) {
      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'A') {
      return toggleAutomode()
    }

    if (ch === 'r') {
      return load(true)
    }

    // Selection over the question-scoped subset.
    if (key.upArrow || ch === 'k') {
      return setSel(i => Math.max(0, i - 1))
    }

    if (key.downArrow || ch === 'j') {
      return setSel(i => Math.min(Math.max(0, selectable.length - 1), i + 1))
    }

    if (key.return) {
      if (selectedAlert) {
        return setSheetOpen(true)
      }

      return
    }

    if (ch === 'a') {
      return resolveSelected()
    }

    // Scrolling (the page is taller than the cursor's alert section).
    if (key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.wheelDown) {
      return scrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollRef.current?.scrollBy(pageSize)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  })

  const width = Math.max(40, cols - 4)

  const nothing =
    !loading &&
    !error &&
    alerts.length === 0 &&
    reviews.length === 0 &&
    gaps.length === 0 &&
    staleAssumptions === 0 &&
    staleRefs === 0

  let body

  if (loading && !data) {
    body = <Text color={t.color.muted}>Loading warnings…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load warnings: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (nothing) {
    body = (
      <Text color={t.color.ok} wrap="wrap">
        All clear — no open alerts, nothing queued for review, no stale assumptions or evidence gaps.
      </Text>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            {alerts.length > 0 ? (
              <Section t={t} title={`Open alerts (${alerts.length})`}>
                {alerts.map((a, i) => {
                  const active = !!selectedId && a.id === selectedId
                  const resolvable = isQuestionScoped(a)

                  return (
                    <Box flexDirection="column" key={a.id ?? i} marginBottom={1}>
                      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                        <Text color={active ? sem.cursor : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                        <Text bold color={sevColor(t, a.severity)}>
                          {(a.severity || 'alert').toLowerCase()}
                        </Text>
                        <Text color={resolvable ? t.color.muted : t.color.border}>
                          {a.scope_ref ? `  ${truncate(a.scope_ref, 24)}` : ''}
                          {resolvable ? '' : '  (review)'}
                        </Text>
                      </Text>
                      {a.reason ? <Text color={t.color.text} wrap="wrap">{`  ${a.reason}`}</Text> : null}
                      {a.recommended_action ? (
                        <Text color={t.color.muted} wrap="wrap">{`  → ${a.recommended_action}`}</Text>
                      ) : null}
                    </Box>
                  )
                })}
              </Section>
            ) : null}

            {reviews.length > 0 ? (
              <Section t={t} title={`Review queue (${reviews.length})`}>
                {reviews.map((r, i) => (
                  <Box flexDirection="column" key={r.id ?? i} marginBottom={1}>
                    <Text wrap="truncate-end">
                      <Text bold color={t.color.warn}>{`P${r.priority ?? '-'}`}</Text>
                      <Text color={t.color.text}>{`  ${truncate(r.title || r.id || '—', width - 8)}`}</Text>
                    </Text>
                    {r.reasons?.length ? (
                      <Text color={t.color.muted} wrap="wrap">{`  ${r.reasons.join(', ')}`}</Text>
                    ) : null}
                    {r.next_action ? (
                      <Text color={t.color.label} wrap="truncate-end">{`  → ${truncate(r.next_action, width - 6)}`}</Text>
                    ) : null}
                  </Box>
                ))}
              </Section>
            ) : null}

            {staleAssumptions > 0 || staleRefs > 0 ? (
              <Section t={t} title="Stale">
                {staleAssumptions > 0 ? (
                  <Text color={t.color.warn}>{`  ${staleAssumptions} stale assumption${staleAssumptions === 1 ? '' : 's'}`}</Text>
                ) : null}
                {staleRefs > 0 ? (
                  <Text color={t.color.warn}>{`  ${staleRefs} stale reference class${staleRefs === 1 ? '' : 'es'}`}</Text>
                ) : null}
              </Section>
            ) : null}

            {gaps.length > 0 ? (
              <Section t={t} title="Readiness gaps">
                {gaps.map((g, i) => (
                  <Text color={t.color.warn} key={i} wrap="wrap">{`  ${g.replace(/_/g, ' ')}`}</Text>
                ))}
              </Section>
            ) : null}
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    )
  }

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          WARNINGS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={alerts.length ? t.color.error : t.color.muted}>{alerts.length}</Text>
        <Text color={t.color.muted}> open · </Text>
        <Text color={selectable.length ? t.color.accent : t.color.muted}>{selectable.length}</Text>
        <Text color={t.color.muted}> resolvable · </Text>
        <Text color={reviews.length ? t.color.warn : t.color.muted}>{reviews.length}</Text>
        <Text color={t.color.muted}> to review</Text>
      </Text>
    </Box>
  )

  // Live automode heartbeat line (done/total + current alert reason + cancel hint).
  const automodeLine = automode ? (
    <Text color={t.color.accent} wrap="truncate-end">
      {`◇ automode ${automode.phase} ${automode.done}/${automode.total || '…'}${automode.reason ? ` · ${truncate(automode.reason, 28)}` : ''} · Shift-A cancel`}
    </Text>
  ) : null

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {automodeLine}
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        ↑↓/jk select · ⏎ resolve sheet · a resolve · Shift-A automode · PgUp/PgDn scroll · r refresh · Esc/q close
      </Text>
    </Box>
  )

  const sheet =
    sheetOpen && selectedAlert ? (
      <WarningResolveSheet
        alert={selectedAlert}
        cols={cols}
        gw={gw}
        onClose={() => setSheetOpen(false)}
        onResolved={(status, detail) => {
          setFlash(`${status} · ${truncate(detail, 56)}`)
          load()
        }}
        rows={termRows}
        t={t}
      />
    ) : null

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
      {sheet}
    </Box>
  )
}

function Section({ children, t, title }: { children: ReactNode; t: Theme; title: string }) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color={t.color.accent}>
        {title}
      </Text>
      {children}
    </Box>
  )
}
