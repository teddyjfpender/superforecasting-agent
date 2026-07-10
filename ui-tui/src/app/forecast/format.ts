import type {
  ForecastDashboardBacktest,
  ForecastDashboardClaimStatus,
  ForecastDashboardLiveBaseline,
  ForecastDashboardQuestion,
  ForecastDashboardReview,
  ForecastDashboardScheduleRun
} from '../../gatewayTypes.js'
import { tailAuditFails, unearnedOutcomes } from '../../lib/forecastTail.js'
import type { PanelSection } from '../../types.js'

// ── Forecast desk panel: pure format lib ─────────────────────────────────────
// Number/probability/distribution/date formatters, the desk-action target parser,
// the unearned-tail markers, and the shared ForecastPanelRow row shape. Moved out
// of forecastPanel.ts verbatim (Wave-5 modularization); the panel re-exports the
// one public formatter (forecastFreshnessLabel) and imports the rest back.

// A categorical forecast with UNEARNED tail mass is a desk flag: the visual
// detail and the glanceable text must agree. These helpers read the optional
// `tail_audit` on a dashboard question; questions without one (binary,
// distribution, older snapshots, or a payload that doesn't carry the audit yet)
// are simply never flagged — no fake findings.
export const questionHasUnearnedTail = (row: { tail_audit?: ForecastDashboardQuestion['tail_audit'] }): boolean =>
  tailAuditFails(row.tail_audit)

export const countUnearnedTail = (questions: ForecastDashboardQuestion[]): number =>
  questions.reduce((count, row) => (questionHasUnearnedTail(row) ? count + 1 : count), 0)

// The compact "unearned tail" book/rail marker for one question, or '' when
// clean. e.g. "unearned tail 1.7% (Conway)".
export const unearnedTailMarker = (row: ForecastDashboardQuestion): string => {
  if (!questionHasUnearnedTail(row)) {
    return ''
  }

  const audit = row.tail_audit
  const offenders = unearnedOutcomes(audit)
  const lead = offenders[0]?.name

  const mass =
    typeof audit?.unearned_mass === 'number' && Number.isFinite(audit.unearned_mass)
      ? `${(audit.unearned_mass * 100).toFixed(audit.unearned_mass * 100 < 10 ? 1 : 0)}%`
      : ''

  return `unearned tail${mass ? ` ${mass}` : ''}${lead ? ` (${lead})` : ''}`
}

export type ForecastPanelRow = NonNullable<PanelSection['rows']>[number]

export const truncate = (value: string, max: number) => (value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value)

export const draftTarget = (command: string) => `draft:${command}`

export const unsafeCommandExample = (value: string) => /(?:<[^>]+>|\[[^\]]+\]|\.\.\.|;)/.test(value)

export const forecastActionTarget = (value: null | string | undefined): string | undefined => {
  const raw = (value ?? '').trim()

  if (!raw) {
    return undefined
  }

  const direct = raw.startsWith('/') ? raw.split(/\s+(?:and|then)\s+/i)[0]?.trim() ?? raw : ''

  if (direct && !unsafeCommandExample(direct)) {
    return direct
  }

  const quoted = raw.match(/`(\/?(?:forecast|superforecasting-agent\s+forecast)\s+[^`]+)`/i)?.[1]?.trim()
  const command = quoted || raw.match(/\b(forecast\s+[A-Za-z0-9][^.;\n]*)/i)?.[1]?.trim()

  if (!command || unsafeCommandExample(command)) {
    return undefined
  }

  if (command.toLowerCase().startsWith('superforecasting-agent forecast ')) {
    return `/forecast ${command.slice('superforecasting-agent forecast '.length).trim()}`
  }

  if (command.toLowerCase().startsWith('forecast ')) {
    return `/forecast ${command.slice('forecast '.length).trim()}`
  }

  return command.startsWith('/') ? command : undefined
}

export const rowWithTarget = (key: string, value: string, target?: string): ForecastPanelRow =>
  target ? [key, value, target] : [key, value]

export const numberValue = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

export const formatCount = (value: unknown) => {
  const number = numberValue(value)

  return number === null ? '0' : String(number)
}

// A distribution arrives as a label→number map (categorical outcomes like
// {yes:0.6,no:0.4}, or numeric stats/quantiles like {p50:2.0,mean:2.1}).
// Rendering the raw JSON in a desk row was unreadable, so surface the value of
// interest: the most-likely outcome for probabilities, or the leading stats.
export const formatDistribution = (value: Record<string, unknown>): string => {
  const entries = Object.entries(value)
    .map(([key, raw]) => [key, numberValue(raw)] as [string, number | null])
    .filter((entry): entry is [string, number] => entry[1] !== null)

  if (!entries.length) {
    return '-'
  }

  const looksProbabilistic = entries.every(([, n]) => n >= 0 && n <= 1)

  if (looksProbabilistic) {
    const [topKey, topValue] = [...entries].sort((a, b) => b[1] - a[1])[0]!
    const more = entries.length > 1 ? ` (+${entries.length - 1})` : ''

    return truncate(`${topKey} ${topValue.toFixed(2)}${more}`, 24)
  }

  return truncate(entries.slice(0, 2).map(([key, n]) => `${key} ${n}`).join('  '), 24)
}

// Human-first number grammar: probabilities read as percentages ("61%",
// "8.5%"), deltas as direction + points ("↑8pt", "↓0.4pt"). The raw-decimal
// "P=0.610 Δ=+0.080" notation read like ledger internals, not a dashboard.
export const formatPercent = (number: number) => {
  const pct = number * 100
  const text = Math.abs(pct - Math.round(pct)) < 0.05 ? pct.toFixed(0) : pct.toFixed(1)

  return `${text}%`
}

export const formatProbability = (value: ForecastDashboardQuestion['probability']) => {
  const number = numberValue(value)

  if (number !== null) {
    return formatPercent(number)
  }

  if (value && typeof value === 'object') {
    return formatDistribution(value as Record<string, unknown>)
  }

  return value ? String(value) : '-'
}

export const formatDelta = (value: ForecastDashboardQuestion['delta']) => {
  const number = numberValue(value)

  if (number === null) {
    return '-'
  }

  if (number === 0) {
    return 'unchanged'
  }

  const pts = Math.abs(number) * 100
  const text = Math.abs(pts - Math.round(pts)) < 0.05 ? pts.toFixed(0) : pts.toFixed(1)

  return `${number > 0 ? '↑' : '↓'}${text}pt`
}

export const formatConfidence = (value: ForecastDashboardQuestion['confidence']) => {
  const number = numberValue(value)

  return number === null ? '-' : formatPercent(number)
}

// Signed decimal for SCORE quantities (Brier edges, CI bounds) — these are
// score differences, not probability points, so the ↑pt grammar would lie.
export const formatSigned = (value: ForecastDashboardQuestion['delta']) => {
  const number = numberValue(value)

  if (number === null) {
    return '-'
  }

  return `${number >= 0 ? '+' : ''}${number.toFixed(3)}`
}

export const shortDate = (value: null | string | undefined) => (value ? value.slice(0, 10) : '-')

export const shortId = (value: string | undefined) => (value ? value.replace(/^fq_/, '').slice(0, 8) : '-')

export const DAY_MS = 24 * 60 * 60 * 1000

export const forecastFreshnessLabel = (value: null | string | undefined, now = new Date()) => {
  if (!value) {
    return 'no as-of'
  }

  const timestamp = Date.parse(value)

  if (!Number.isFinite(timestamp)) {
    return 'as-of set'
  }

  const ageDays = Math.max(0, Math.floor((now.getTime() - timestamp) / DAY_MS))

  if (ageDays === 0) {
    return 'fresh today'
  }

  if (ageDays === 1) {
    return '1d old'
  }

  if (ageDays < 31) {
    return `${ageDays}d old`
  }

  const ageMonths = Math.floor(ageDays / 30)

  return `${ageMonths}mo old`
}

export const formatMetric = (value: null | number | undefined) => {
  const number = numberValue(value)

  return number === null ? '-' : number.toFixed(6)
}

export const formatBacktestWins = (row: { paired_agent_wins?: number; paired_baseline_wins?: number; paired_ties?: number }) =>
  `${row.paired_agent_wins ?? 0}/${row.paired_baseline_wins ?? 0}/${row.paired_ties ?? 0}`

export const formatBacktestSources = (row: ForecastDashboardBacktest) =>
  truncate((row.probability_sources && row.probability_sources.length ? row.probability_sources : ['dataset']).join(','), 24)

export const formatClaimVerdict = (claimStatus: ForecastDashboardClaimStatus | undefined) => {
  const verdict = claimStatus?.verdict

  if (verdict === 'benchmark_replay_only') {
    return 'replay only'
  }

  return verdict ? truncate(String(verdict).replace(/_/g, ' '), 24) : '-'
}

export const formatClaimStatus = (row: ForecastDashboardBacktest) => {
  return formatClaimVerdict(row.claim_status)
}

export const formatCi95 = (low: null | number | undefined, high: null | number | undefined) =>
  numberValue(low) === null || numberValue(high) === null
    ? '-'
    : `[${formatSigned(low)},${formatSigned(high)}]`

export const formatLiveBaselineName = (row: ForecastDashboardLiveBaseline) =>
  truncate(`${row.baseline_type || '-'}:${row.source || '-'}`, 28)

export const formatScheduleRunScope = (row: ForecastDashboardScheduleRun) => {
  if (row.scope_type === 'domain_topic' && row.scope_ref) {
    try {
      const parsed = JSON.parse(row.scope_ref) as { domain?: string; topic?: string }

      return `domain:${parsed.domain || '*'}/${parsed.topic || '*'}`
    } catch {
      return `domain:${row.scope_ref}`
    }
  }

  return `${row.scope_type || 'schedule'}:${row.scope_ref || '*'}`
}

export const formatVerdict = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 36) : '-'

export const formatRequirement = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 28) : 'evidence'

export const formatDoctorStatus = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 42) : '-'

export const plural = (count: number, singular: string, pluralForm = `${singular}s`) =>
  `${count} ${count === 1 ? singular : pluralForm}`

export const formatErrorScope = (row: { domain?: null | string; question_type?: null | string; topic?: null | string }) => {
  const base = row.domain || 'global'
  const topic = row.topic ? `/${row.topic}` : ''
  const questionType = row.question_type ? `:${row.question_type}` : ''

  return truncate(`${base}${topic}${questionType}`, 28)
}

export const formatLessonScope = (row: { scope_ref?: null | string; scope_type?: null | string }) =>
  `${row.scope_type || 'global'}:${row.scope_ref || '*'}`

export const fieldString = (row: Record<string, unknown> | null | undefined, key: string) => {
  const value = row?.[key]

  if (value === null || value === undefined || value === '') {
    return '-'
  }

  return String(value)
}

export const probability_delta = (previous: unknown, current: unknown) => {
  const previousNumber = numberValue(previous)
  const currentNumber = numberValue(current)

  return previousNumber === null || currentNumber === null ? null : currentNumber - previousNumber
}

export const isLearnedErrorReviewReason = (reason?: string) => (reason ?? '').startsWith('domain_error_profile_applies:')

export const formatReviewReason = (reason?: string) =>
  isLearnedErrorReviewReason(reason) ? 'learned error profile' : reason || 'review'

export const learnedErrorReviewCount = (rows: ForecastDashboardReview[]) =>
  rows.filter(row => (row.reasons ?? []).some(isLearnedErrorReviewReason)).length
