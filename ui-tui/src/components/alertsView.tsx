import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastDashboardAlert,
  ForecastDashboardResponse,
  ForecastDashboardReview
} from '../gatewayTypes.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

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

interface AlertsViewProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

export function AlertsView({ gw, onClose, t }: AlertsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24

  const [data, setData] = useState<ForecastDashboardResponse | null>(
    () => getOverlayCache<ForecastDashboardResponse>('forecast.dashboard:alerts') ?? null
  )

  const [loading, setLoading] = useState(!data)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)

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

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'r') {
      return load(true)
    }

    if (key.upArrow || ch === 'k' || key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.downArrow || ch === 'j' || key.wheelDown) {
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
  const summary = data?.summary
  const alerts: ForecastDashboardAlert[] = summary?.alerts ?? []
  const reviews: ForecastDashboardReview[] = summary?.review_queue ?? []
  const gaps = summary?.evidence_status?.gaps ?? []
  const staleAssumptions = summary?.stale_assumption_count ?? 0
  const staleRefs = summary?.stale_reference_class_count ?? 0

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
                {alerts.map((a, i) => (
                  <Box flexDirection="column" key={a.id ?? i} marginBottom={1}>
                    <Text wrap="truncate-end">
                      <Text bold color={sevColor(t, a.severity)}>
                        {(a.severity || 'alert').toLowerCase()}
                      </Text>
                      <Text color={t.color.muted}>{a.scope_ref ? `  ${truncate(a.scope_ref, 24)}` : ''}</Text>
                    </Text>
                    {a.reason ? <Text color={t.color.text} wrap="wrap">{`  ${a.reason}`}</Text> : null}
                    {a.recommended_action ? (
                      <Text color={t.color.muted} wrap="wrap">{`  → ${a.recommended_action}`}</Text>
                    ) : null}
                  </Box>
                ))}
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
        <Text color={reviews.length ? t.color.warn : t.color.muted}>{reviews.length}</Text>
        <Text color={t.color.muted}> to review</Text>
      </Text>
    </Box>
  )

  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      <Text color={t.color.muted} wrap="truncate-end">
        ↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · r refresh · Esc/q close
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
