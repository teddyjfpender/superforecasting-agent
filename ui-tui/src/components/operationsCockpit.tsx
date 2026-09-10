import { Box, Text } from '@superforecasting/ink'

import type { Theme } from '../theme.js'

type Lane = {
  backlog?: number
  claims_today?: number
  completed_today?: number
  daily_budget?: number
  oldest_age_minutes?: number
  slo_breaches?: number
  slo_minutes?: number
  dead_letter?: number
}

type HistoryPoint = {
  day?: string
  arrivals?: number
  services?: number
  cost_usd?: number
}

type Operations = {
  generated_at?: string
  queue?: Record<string, Lane>
  coverage?: Record<string, number>
  capacity?: Record<string, number>
  source_changes?: Record<string, unknown> & {
    flow?: {
      '6h'?: { arrivals?: number; terminal?: number; net?: number }
      '24h'?: { arrivals?: number; terminal?: number; net?: number }
      oldest_pending_hours?: number
      p90_pending_hours?: number
    }
    content_yield?: Array<{
      source_type?: string
      source?: string
      events?: number
      changed_items?: number
      insufficient_content_pct?: number | null
    }>
  }
  alert_flow?: Record<string, {
    arrivals?: number
    closures?: number
    net?: number
    open_age_p90_hours?: number | null
    closure_latency_p90_hours?: number | null
    executable_pct?: number
  }>
  human_inbox?: {
    count?: number
    groups?: number
    items?: Array<{
      task_id?: string
      title?: string
      severity?: string
      reason?: string
      escalation_owner?: string
      age_hours?: number
      actions?: Record<string, string>
    }>
  }
  cost?: {
    total_usd?: number
    today_usd?: number
    model_calls?: number
    source_calls?: number
    per_material_update_usd?: number | null
    per_resolution_usd?: number | null
    provenance?: Record<string, number>
  }
  history?: HistoryPoint[]
  rate_limits?: Array<{ bucket?: string; tokens?: number; capacity?: number; denied_count?: number }>
  utility?: {
    active_model?: string
    sample_size?: number
    pairwise_concordance?: number | null
    calibration_ready?: boolean
  }
  high_severity?: {
    open?: number
    unclaimed?: number
    slo_breaches?: number
    oldest_age_minutes?: number
    human_escalation?: number
    assigned_owner_count?: number
    awaiting_execution?: number
  }
}

const spark = (values: number[]): string => {
  const bars = '▁▂▃▄▅▆▇█'

  if (values.length === 0) {return '—'}
  const max = Math.max(...values, 1)

  return values.map(value => bars[Math.min(Math.round((Math.max(value, 0) / max) * 7), 7)]).join('')
}

const money = (value?: number | null): string => value == null ? '—' : `$${value.toFixed(value < 1 ? 4 : 2)}`

export function OperationsCockpit({ operations, t }: { operations?: Record<string, unknown>; t: Theme }) {
  const data = (operations || {}) as Operations
  const lanes = Object.entries(data.queue || {})
  const history = data.history || []
  const cost = data.cost || {}
  const coverage = data.coverage || {}
  const capacity = data.capacity || {}
  const rateLimited = (data.rate_limits || []).filter(bucket => (bucket.denied_count || 0) > 0)
  const utility = data.utility || {}
  const high = data.high_severity || {}
  const sources = data.source_changes || {}
  const sourceFlow = sources.flow?.['24h'] || {}
  const sourceAges = sources.flow || {}
  const contentYield = sources.content_yield || []
  const alertFlow = data.alert_flow?.['24h'] || {}
  const humanInbox = data.human_inbox || {}

  return (
    <Box flexDirection="column" flexGrow={1} minHeight={0}>
      <Text bold color={t.color.accent}>Operational cockpit</Text>
      <Text color={t.color.muted}>queue health · throughput · spend · coverage</Text>
      <Text color={(high.slo_breaches || 0) > 0 ? t.color.warn : t.color.text}>
        {`high severity · open ${high.open || 0} · awaiting ${high.awaiting_execution || 0} · unowned ${high.unclaimed || 0} · SLA breaches ${high.slo_breaches || 0} · oldest ${Math.round(high.oldest_age_minutes || 0)}m · human escalation ${high.human_escalation || 0} · assigned ${high.assigned_owner_count || 0}`}
      </Text>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>Source-event lifecycle</Text>
        <Text color={Number(sources.stranded || 0) > 0 || Number(sources.open_failed || 0) > 0 ? t.color.warn : t.color.text}>{`pending ${sources.pending || 0} · estimating ${sources.estimator_required || 0} · stranded ${sources.stranded || 0} · open failures ${sources.open_failed || 0} · processed ${sources.processed || 0}`}</Text>
        <Text color={(sourceFlow.net || 0) > 0 ? t.color.warn : t.color.muted}>{`24h arrivals ${sourceFlow.arrivals || 0} · terminal ${sourceFlow.terminal || 0} · net ${sourceFlow.net || 0} · oldest ${sourceAges.oldest_pending_hours || 0}h · P90 ${sourceAges.p90_pending_hours || 0}h`}</Text>
        <Text color={t.color.muted}>{`oldest pending ${String(sources.oldest_pending_at || '—')}`}</Text>
        {contentYield.filter(row => (row.events || 0) >= 3 && (row.insufficient_content_pct || 0) >= 90).slice(0, 3).map(row => (
          <Text color={t.color.warn} key={`${row.source_type}:${row.source}`}>{`low content · ${row.source_type} · ${row.insufficient_content_pct}% insufficient · ${row.changed_items || 0} changed items`}</Text>
        ))}
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>Alert flow and human inbox</Text>
        <Text color={(alertFlow.net || 0) > 0 ? t.color.warn : t.color.text}>{`24h arrivals ${alertFlow.arrivals || 0} · closures ${alertFlow.closures || 0} · net ${alertFlow.net || 0} · executable ${alertFlow.executable_pct ?? 0}% · closure P90 ${alertFlow.closure_latency_p90_hours ?? '—'}h`}</Text>
        <Text color={(humanInbox.count || 0) > 0 ? t.color.warn : t.color.muted}>{`awaiting human ${humanInbox.count || 0} across ${humanInbox.groups || 0} questions`}</Text>
        {(humanInbox.items || []).slice(0, 5).map(item => (
          <Box flexDirection="column" key={item.task_id}>
            <Text color={item.severity === 'critical' || item.severity === 'high' ? t.color.warn : t.color.muted}>
              {`${Math.round(item.age_hours || 0)}h · ${item.escalation_owner || 'unowned'} · ${item.title || item.reason || item.task_id}`}
            </Text>
            <Text color={t.color.muted}>{`actions · ${(Object.keys(item.actions || {})).join(' / ')}`}</Text>
          </Box>
        ))}
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>LANE                    BACKLOG   OLDEST / SLO   BREACH   TODAY / BUDGET</Text>
        {lanes.map(([name, lane]) => (
          <Text color={(lane.slo_breaches || 0) > 0 ? t.color.warn : t.color.text} key={name}>
            {`${name.padEnd(23)} ${String(lane.backlog || 0).padStart(7)}   ${String(Math.round(lane.oldest_age_minutes || 0)).padStart(5)}m / ${String(lane.slo_minutes || 0).padStart(4)}m   ${String(lane.slo_breaches || 0).padStart(6)}   ${String(lane.claims_today || 0).padStart(5)} / ${lane.daily_budget || 0}`}
          </Text>
        ))}
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>30-day flow</Text>
        <Text color={t.color.accent}>{`arrivals ${spark(history.map(point => point.arrivals || 0))}`}</Text>
        <Text color={t.color.ok}>{`services ${spark(history.map(point => point.services || 0))}`}</Text>
        <Text color={t.color.muted}>{history.length ? `${history[0]?.day || ''} → ${history.at(-1)?.day || ''}` : 'No task history yet'}</Text>
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>Measured cost</Text>
        <Text>{`today ${money(cost.today_usd)} · total ${money(cost.total_usd)} · model calls ${cost.model_calls || 0} · source calls ${cost.source_calls || 0}`}</Text>
        <Text color={t.color.muted}>{`per material update ${money(cost.per_material_update_usd)} · per resolution ${money(cost.per_resolution_usd)}`}</Text>
        <Text color={t.color.muted}>{`cost basis ${Object.entries(cost.provenance || {}).map(([status, count]) => `${status} ${count}`).join(' · ') || 'no measured attempts'}`}</Text>
      </Box>

      <Box flexDirection="column" marginTop={1}>
        <Text bold color={t.color.text}>Coverage and capacity</Text>
        <Text>{`active ${coverage.active_questions || 0} · invariant gaps ${coverage.service_mode_coverage_gaps || 0} · unclassified ${coverage.unclassified_active || 0}`}</Text>
        <Text color={t.color.muted}>{`serviced/no schedule ${coverage.actively_serviced_without_schedule || 0} · monitor/no watch ${coverage.monitor_only_without_watch || 0} · resolution/no settlement schedule ${coverage.resolution_only_without_schedule || 0}`}</Text>
        <Text color={t.color.muted}>{`serviced ${capacity.actively_serviced || 0} · monitor ${capacity.monitor_only || 0} · resolution-only ${capacity.resolution_only || 0} · resolved ${capacity.resolved || 0} · archived ${capacity.archived || 0}`}</Text>
        <Text color={t.color.muted}>{`utility ${utility.active_model || 'utility-v1'} · n=${utility.sample_size || 0} · concordance ${utility.pairwise_concordance == null ? '—' : utility.pairwise_concordance.toFixed(2)}${utility.calibration_ready ? ' · calibration ready' : ''}`}</Text>
      </Box>

      {rateLimited.length ? (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={t.color.warn}>Rate-limit pressure</Text>
          {rateLimited.slice(0, 5).map(bucket => (
            <Text color={t.color.warn} key={bucket.bucket}>{`${bucket.bucket} · denied ${bucket.denied_count} · tokens ${(bucket.tokens || 0).toFixed(1)}/${bucket.capacity || 0}`}</Text>
          ))}
        </Box>
      ) : null}
    </Box>
  )
}
