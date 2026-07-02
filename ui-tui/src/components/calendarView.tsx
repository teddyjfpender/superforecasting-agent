import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef, useState } from 'react'

import { $globalModal, patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

export const openCalendarView = () => patchOverlayState({ calendar: true })
export const closeCalendarView = () => patchOverlayState({ calendar: false })

const DAY_MS = 86_400_000

type Bucket = 'Overdue' | 'Today' | 'This week' | 'This month' | 'Later'
const BUCKET_ORDER: Bucket[] = ['Overdue', 'Today', 'This week', 'This month', 'Later']

interface CalEvent {
  bucket: Bucket
  id?: string
  kind: 'closes' | 'resolves'
  rel: string
  stamp: number
  title: string
  when: string
}

const startOfToday = (now: number): number => {
  const d = new Date(now)
  d.setHours(0, 0, 0, 0)

  return d.getTime()
}

const bucketFor = (stamp: number, now: number): Bucket => {
  const today = startOfToday(now)

  if (stamp < today) {
    return 'Overdue'
  }

  if (stamp < today + DAY_MS) {
    return 'Today'
  }

  if (stamp < today + 7 * DAY_MS) {
    return 'This week'
  }

  if (stamp < today + 31 * DAY_MS) {
    return 'This month'
  }

  return 'Later'
}

const monthDay = (stamp: number): string =>
  new Date(stamp).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })

const relDays = (stamp: number, now: number): string => {
  const days = Math.round((startOfToday(stamp) - startOfToday(now)) / DAY_MS)

  if (days === 0) {
    return 'today'
  }

  if (days === 1) {
    return 'tomorrow'
  }

  if (days === -1) {
    return 'yesterday'
  }

  return days > 0 ? `in ${days}d` : `${Math.abs(days)}d ago`
}

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

interface CalendarViewProps {
  gw: GatewayClient
  onClose: () => void
  t: Theme
}

export function CalendarView({ gw, onClose, t }: CalendarViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  // Render the last dashboard immediately on reopen, refresh in the background.
  const [data, setData] = useState<ForecastDashboardResponse | null>(
    () => getOverlayCache<ForecastDashboardResponse>('forecast.dashboard') ?? null
  )

  const [loading, setLoading] = useState(!data)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const scrollRef = useRef<null | ScrollBoxHandle>(null)

  const load = (announce = false) => {
    setLoading(!data)
    // fast: the calendar reads only questions[].{title,id,close_time,resolution_time},
    // all carried in fast mode — so skip the full-build cost (backtests, live/pilot
    // reports, evidence status, stale-review walk) the calendar never renders.
    gw.request<unknown>('forecast.dashboard', { fast: true, limit: 200 })
      .then(raw => {
        const result = asRpcResult<ForecastDashboardResponse>(raw)

        if (!result) {
          setError('forecast.dashboard returned no data')
          setLoading(false)

          return
        }

        setOverlayCache('forecast.dashboard', result)
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
  }, { isActive: !globalModal })

  const width = Math.max(40, cols - 4)
  const wallNow = Date.now()

  const events: CalEvent[] = []

  for (const q of data?.summary?.questions ?? []) {
    const title = q.title || q.id || '—'

    const add = (raw: null | string | undefined, kind: CalEvent['kind']) => {
      if (!raw) {
        return
      }

      const stamp = Date.parse(raw)

      if (!Number.isFinite(stamp)) {
        return
      }

      events.push({
        bucket: bucketFor(stamp, wallNow),
        id: q.id,
        kind,
        rel: relDays(stamp, wallNow),
        stamp,
        title,
        when: monthDay(stamp)
      })
    }

    add(q.close_time, 'closes')
    add(q.resolution_time, 'resolves')
  }

  events.sort((a, b) => a.stamp - b.stamp)

  const grouped = new Map<Bucket, CalEvent[]>()

  for (const ev of events) {
    const list = grouped.get(ev.bucket) ?? []
    list.push(ev)
    grouped.set(ev.bucket, list)
  }

  let body

  if (loading && !data) {
    body = <Text color={t.color.muted}>Loading calendar…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load calendar: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (events.length === 0) {
    body = (
      <Text color={t.color.muted} wrap="wrap">
        No dated forecasts yet — set a close or resolution time on a question and it will show up here.
      </Text>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            {BUCKET_ORDER.filter(b => grouped.has(b)).map(bucket => {
              const list = grouped.get(bucket) ?? []
              const overdue = bucket === 'Overdue'

              return (
                <Box flexDirection="column" key={bucket} marginTop={1}>
                  <Text bold color={overdue ? t.color.error : t.color.accent}>
                    {`${bucket} (${list.length})`}
                  </Text>
                  {list.map((ev, i) => (
                    <Text key={`${ev.id ?? ''}-${ev.kind}-${i}`} wrap="truncate-end">
                      <Text color={t.color.label}>{`  ${ev.when.padEnd(7)}`}</Text>
                      <Text color={ev.kind === 'resolves' ? t.color.primary : t.color.warn}>
                        {ev.kind.padEnd(9)}
                      </Text>
                      <Text color={t.color.text}>{truncate(ev.title, width - 30)}</Text>
                      <Text color={t.color.muted}>{`  ${ev.rel}`}</Text>
                    </Text>
                  ))}
                </Box>
              )
            })}
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
          CALENDAR
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={t.color.text}>{events.length}</Text>
        <Text color={t.color.muted}> dated events · closes + resolutions</Text>
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
