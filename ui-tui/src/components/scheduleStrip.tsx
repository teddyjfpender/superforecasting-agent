import { Box, Text } from '@superforecasting/ink'
import { useEffect, useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { ForecastScheduleStatusResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

// ── Schedule-health strip ─────────────────────────────────────────────────────
// A compact, display-only read of the forecast cron jobs' liveness (from
// forecast.schedule.status): the next scheduled run, the last cron fire, and a
// green ok / red "last run errored" / amber "missed" verdict. It renders nothing
// until the payload actually carries a schedule (no installed cron jobs AND no
// scheduled reviews → the desk has nothing scheduled, so the strip stays hidden).
// There is no cron.manage pause/resume/run-now verb server-side, so this is
// purely informational — it wires no keys.

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// A short, human relative time ("in 3h" / "2d ago"); '' for a missing/unparseable
// stamp so the caller can drop the segment entirely.
export const relTime = (iso?: null | string, now: number = Date.now()): string => {
  if (!iso) {
    return ''
  }

  const at = Date.parse(iso)

  if (Number.isNaN(at)) {
    return ''
  }

  const diff = at - now
  const abs = Math.abs(diff)
  const mins = Math.round(abs / 60_000)
  const unit = mins < 60 ? `${Math.max(0, mins)}m` : mins < 60 * 48 ? `${Math.round(mins / 60)}h` : `${Math.round(mins / 1440)}d`

  return diff >= 0 ? `in ${unit}` : `${unit} ago`
}

export type ScheduleState = 'errored' | 'missed' | 'ok'

export interface ScheduleHealth {
  detail: string
  // Whether the payload carries any schedule at all (jobs OR scheduled reviews).
  hasContent: boolean
  lastRun: string
  nextRun: string
  state: ScheduleState
}

// Pure fold of the schedule payload into the strip's render model: the verdict
// (errored beats missed beats ok), the earliest upcoming run, and the latest fire.
export const deriveScheduleHealth = (
  status: ForecastScheduleStatusResponse | null,
  now: number = Date.now()
): ScheduleHealth => {
  const cron = status?.cron
  const jobs = cron?.jobs ?? []
  const reviews = status?.scheduled_reviews ?? []
  const hasContent = jobs.length > 0 || reviews.length > 0

  // Earliest FUTURE next-run across cron jobs + scheduled reviews.
  const nextStamps = [...jobs.map(j => j.next_run_at), ...reviews.map(r => r.next_run_at)]
    .map(s => (s ? Date.parse(s) : Number.NaN))
    .filter(n => !Number.isNaN(n) && n >= now)

  const nextRun = nextStamps.length ? relTime(new Date(Math.min(...nextStamps)).toISOString(), now) : ''

  // Latest last-run across the cron jobs (the most recent fire).
  const lastStamps = jobs
    .map(j => (j.last_run_at ? Date.parse(j.last_run_at) : Number.NaN))
    .filter(n => !Number.isNaN(n))

  const lastRun = lastStamps.length ? relTime(new Date(Math.max(...lastStamps)).toISOString(), now) : ''

  const erroredJob = jobs.find(j => j.errored)
  const missedJob = jobs.find(j => j.missed)

  if ((cron?.errored?.length ?? 0) > 0 || erroredJob) {
    const short = erroredJob?.last_error || cron?.errored?.[0] || 'run failed'

    return { detail: truncate(short, 48), hasContent, lastRun, nextRun, state: 'errored' }
  }

  if ((cron?.missed?.length ?? 0) > 0 || missedJob) {
    const which = missedJob?.name || cron?.missed?.[0] || ''

    return { detail: which ? truncate(which, 32) : '', hasContent, lastRun, nextRun, state: 'missed' }
  }

  return { detail: '', hasContent, lastRun, nextRun, state: 'ok' }
}

const STATE_LABEL: Record<ScheduleState, string> = {
  errored: 'last run errored',
  missed: 'missed',
  ok: 'ok'
}

interface ScheduleStripProps {
  gw: GatewayClient
  t: Theme
  width?: number
}

export function ScheduleStrip({ gw, t, width }: ScheduleStripProps) {
  const [status, setStatus] = useState<ForecastScheduleStatusResponse | null>(null)

  useEffect(() => {
    let live = true

    const load = () => {
      gw.request<unknown>('forecast.schedule.status', {})
        .then(raw => {
          if (live) {
            setStatus(asRpcResult<ForecastScheduleStatusResponse>(raw))
          }
        })
        .catch(() => undefined)
    }

    load()
    const id = setInterval(load, 30_000)

    return () => {
      live = false
      clearInterval(id)
    }
  }, [gw])

  const health = deriveScheduleHealth(status)

  // Nothing scheduled → nothing to say. Keep the landing clean.
  if (!health.hasContent) {
    return null
  }

  const stateColor = health.state === 'errored' ? t.color.error : health.state === 'missed' ? t.color.warn : t.color.ok
  const verdict = health.detail ? `${STATE_LABEL[health.state]}: ${health.detail}` : STATE_LABEL[health.state]

  return (
    <Box flexDirection="column" flexShrink={0} width={width}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>SCHEDULE</Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={stateColor}>{`● ${verdict}`}</Text>
        {health.nextRun ? <Text color={t.color.muted}>{`  · next ${health.nextRun}`}</Text> : null}
        {health.lastRun ? <Text color={t.color.muted}>{`  · last fired ${health.lastRun}`}</Text> : null}
      </Text>
    </Box>
  )
}
