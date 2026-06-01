import type {
  ForecastDashboardBacktest,
  ForecastDashboardCalibration,
  ForecastDashboardClaimStatus,
  ForecastDashboardDoctor,
  ForecastDashboardLiveBaseline,
  ForecastDashboardQuestion,
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastDashboardScheduleRun,
  ForecastQuestionPacket,
  ForecastQuestionPacketResponse
} from '../gatewayTypes.js'
import {
  FORECAST_TUI_FIND_SHORTCUT,
  FORECAST_TUI_VIEW_SHORTCUTS,
  forecastShortcutDisplayHotkey
} from '../lib/forecastShortcuts.js'
import type { PanelSection } from '../types.js'

type ForecastPanelRow = NonNullable<PanelSection['rows']>[number]

export interface ForecastDeskActionItem {
  command: string
  detail: string
  target?: string
}

export interface ForecastDeskCompactItem {
  label: string
  detail: string
}

export interface ForecastQuestionSearchMatch {
  index: number
  matched: string[]
  row: ForecastDashboardQuestion | ForecastDashboardReview
  score: number
}

const truncate = (value: string, max: number) => (value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value)

const draftTarget = (command: string) => `draft:${command}`

const unsafeCommandExample = (value: string) => /(?:<[^>]+>|\[[^\]]+\]|\.\.\.|;)/.test(value)

const forecastActionTarget = (value: null | string | undefined): string | undefined => {
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

const rowWithTarget = (key: string, value: string, target?: string): ForecastPanelRow =>
  target ? [key, value, target] : [key, value]

const numberValue = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const formatCount = (value: unknown) => {
  const number = numberValue(value)
  return number === null ? '0' : String(number)
}

// A distribution arrives as a label→number map (categorical outcomes like
// {yes:0.6,no:0.4}, or numeric stats/quantiles like {p50:2.0,mean:2.1}).
// Rendering the raw JSON in a desk row was unreadable, so surface the value of
// interest: the most-likely outcome for probabilities, or the leading stats.
const formatDistribution = (value: Record<string, unknown>): string => {
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

const formatProbability = (value: ForecastDashboardQuestion['probability']) => {
  const number = numberValue(value)
  if (number !== null) {
    return number.toFixed(3)
  }

  if (value && typeof value === 'object') {
    return formatDistribution(value as Record<string, unknown>)
  }

  return value ? String(value) : '-'
}

const formatDelta = (value: ForecastDashboardQuestion['delta']) => {
  const number = numberValue(value)
  if (number === null) {
    return '-'
  }

  return `${number >= 0 ? '+' : ''}${number.toFixed(3)}`
}

const formatConfidence = (value: ForecastDashboardQuestion['confidence']) => {
  const number = numberValue(value)
  return number === null ? '-' : number.toFixed(2)
}

const shortDate = (value: null | string | undefined) => (value ? value.slice(0, 10) : '-')

const shortId = (value: string | undefined) => (value ? value.replace(/^fq_/, '').slice(0, 8) : '-')

const DAY_MS = 24 * 60 * 60 * 1000

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

const formatMetric = (value: null | number | undefined) => {
  const number = numberValue(value)
  return number === null ? '-' : number.toFixed(6)
}

const formatBacktestWins = (row: { paired_agent_wins?: number; paired_baseline_wins?: number; paired_ties?: number }) =>
  `${row.paired_agent_wins ?? 0}/${row.paired_baseline_wins ?? 0}/${row.paired_ties ?? 0}`

const formatBacktestSources = (row: ForecastDashboardBacktest) =>
  truncate((row.probability_sources && row.probability_sources.length ? row.probability_sources : ['dataset']).join(','), 24)

const formatClaimVerdict = (claimStatus: ForecastDashboardClaimStatus | undefined) => {
  const verdict = claimStatus?.verdict
  if (verdict === 'benchmark_replay_only') {
    return 'replay only'
  }

  return verdict ? truncate(String(verdict).replace(/_/g, ' '), 24) : '-'
}

const formatClaimStatus = (row: ForecastDashboardBacktest) => {
  return formatClaimVerdict(row.claim_status)
}

const formatCi95 = (low: null | number | undefined, high: null | number | undefined) =>
  numberValue(low) === null || numberValue(high) === null
    ? '-'
    : `[${formatDelta(low)},${formatDelta(high)}]`

const formatLiveBaselineName = (row: ForecastDashboardLiveBaseline) =>
  truncate(`${row.baseline_type || '-'}:${row.source || '-'}`, 28)

const formatScheduleRunScope = (row: ForecastDashboardScheduleRun) => {
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

const formatVerdict = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 36) : '-'

const formatRequirement = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 28) : 'evidence'

const formatDoctorStatus = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 42) : '-'

const plural = (count: number, singular: string, pluralForm = `${singular}s`) =>
  `${count} ${count === 1 ? singular : pluralForm}`

const doctorRows = (doctor: ForecastDashboardDoctor): ForecastPanelRow[] => {
  const rows: ForecastPanelRow[] = [
    ['status', formatDoctorStatus(doctor.doctor_status)],
    [
      'pilot',
      `${formatCount(doctor.pilot_passed_checks)}/${formatCount(doctor.pilot_total_checks)} ${formatVerdict(
        doctor.pilot_status
      )}`
    ],
    [
      'readiness',
      `${formatVerdict(doctor.readiness_verdict)}  gaps ${formatCount(doctor.readiness_gap_count)}`
    ],
    ['scheduled runs', formatCount(doctor.scheduled_review_run_count)],
    ['claim live superiority', doctor.claim_live_superforecasting === true ? 'yes' : 'no']
  ]

  for (const item of (doctor.next_actions ?? []).slice(0, 3)) {
    const action = item.action || '/forecast doctor --json'
    rows.push(
      rowWithTarget(
        `next ${formatRequirement(item.requirement_id || item.source)}`,
        truncate(action, 88),
        forecastActionTarget(action)
      )
    )
  }

  return rows
}

const assumptionCounts = (summary: ForecastDashboardResponse['summary']) => {
  if (!summary) {
    return { open: 0, stale: 0 }
  }

  const summaryOpen = numberValue(summary.open_assumption_count)
  const summaryStale = numberValue(summary.stale_assumption_count)
  if (summaryOpen !== null || summaryStale !== null) {
    return { open: summaryOpen ?? 0, stale: summaryStale ?? 0 }
  }

  let open = 0
  let stale = 0

  for (const row of summary.questions ?? []) {
    open += numberValue(row.open_assumption_count) ?? 0
    stale += numberValue(row.stale_assumption_count) ?? 0
  }

  return { open, stale }
}

const referenceClassCounts = (summary: ForecastDashboardResponse['summary']) => {
  if (!summary) {
    return { open: 0, stale: 0 }
  }

  const summaryOpen = numberValue(summary.open_reference_class_count)
  const summaryStale = numberValue(summary.stale_reference_class_count)
  if (summaryOpen !== null || summaryStale !== null) {
    return { open: summaryOpen ?? 0, stale: summaryStale ?? 0 }
  }

  let open = 0
  let stale = 0

  for (const row of summary.questions ?? []) {
    open += numberValue(row.open_reference_class_count) ?? 0
    stale += numberValue(row.stale_reference_class_count) ?? 0
  }

  return { open, stale }
}

export const forecastDeskStatusLabel = (response: ForecastDashboardResponse): string => {
  const summary = response.summary

  if (!summary) {
    return ''
  }

  const active = numberValue(summary.active_count) ?? (summary.questions ?? []).length
  const alerts = numberValue(summary.open_alert_count) ?? 0
  const reviews = numberValue(summary.review_queue_count) ?? (summary.review_queue ?? []).length
  const closing = numberValue(summary.closing_soon_count) ?? 0
  const calibrationCount = numberValue(summary.calibration?.count)
  const lessonCount = numberValue(summary.learning?.total_lessons)
  const assumptions = assumptionCounts(summary)
  const referenceClasses = referenceClassCounts(summary)
  // Lead with what needs a human (active, to-review, alerts, closing), then the
  // quieter health counters. Spell out the cryptic abbreviations and only show
  // stale counts when there actually are stale items, so the strip reads as a
  // glanceable summary rather than a slash-delimited code.
  const bits = [`${active} active`]

  if (reviews > 0) {
    bits.push(`${reviews} to review`)
  }

  if (alerts > 0) {
    bits.push(`${plural(alerts, 'alert')}`)
  }

  if (closing > 0) {
    bits.push(`${closing} closing`)
  }

  if (calibrationCount !== null) {
    bits.push(`cal ${calibrationCount}`)
  }

  if (lessonCount) {
    bits.push(plural(lessonCount, 'lesson'))
  }

  if (assumptions.open > 0 || assumptions.stale > 0) {
    bits.push(
      assumptions.stale > 0
        ? `${assumptions.open} assumptions (${assumptions.stale} stale)`
        : `${plural(assumptions.open, 'assumption')}`
    )
  }

  if (referenceClasses.open > 0 || referenceClasses.stale > 0) {
    bits.push(
      referenceClasses.stale > 0
        ? `${referenceClasses.open} ref-classes (${referenceClasses.stale} stale)`
        : `${referenceClasses.open} ref-classes`
    )
  }

  if (summary.doctor?.doctor_status) {
    bits.push(`doctor: ${formatDoctorStatus(summary.doctor.doctor_status)}`)
  }

  return bits.join('  ·  ')
}

const formatErrorScope = (row: { domain?: null | string; question_type?: null | string; topic?: null | string }) => {
  const base = row.domain || 'global'
  const topic = row.topic ? `/${row.topic}` : ''
  const questionType = row.question_type ? `:${row.question_type}` : ''
  return truncate(`${base}${topic}${questionType}`, 28)
}

const formatLessonScope = (row: { scope_ref?: null | string; scope_type?: null | string }) =>
  `${row.scope_type || 'global'}:${row.scope_ref || '*'}`

const componentContributionRows = (calibration: ForecastDashboardCalibration | undefined, limit: number): [string, string][] => {
  const rows = calibration?.ensemble_component_contributions
  if (!Array.isArray(rows)) {
    return []
  }

  return rows.slice(0, limit).map(row => [
    `component ${truncate(String(row?.name || '-'), 24)}`,
    `n ${formatCount(row?.count)}  contrib ${formatMetric(row?.mean_contribution)}  share ${formatMetric(
      row?.mean_weight_share
    )}  p ${formatMetric(row?.mean_probability)}`
  ])
}

const questionTypeCalibrationRows = (calibration: ForecastDashboardCalibration | undefined, limit: number): [string, string][] => {
  const rows = calibration?.question_type_breakdown
  if (!Array.isArray(rows)) {
    return []
  }

  return rows.slice(0, limit).map(row => [
    `type ${truncate(String(row?.question_type || '-'), 24)}`,
    `n ${formatCount(row?.count)}  brier_n ${formatCount(row?.brier_count)}  brier ${formatMetric(
      row?.mean_brier
    )}  proper ${formatMetric(row?.mean_proper_score)}`
  ])
}

const forecastStatus = (row: ForecastDashboardQuestion) => {
  const alerts = Number(row.open_alert_count || 0)
  const staleAssumptions = Number(row.stale_assumption_count || 0)
  const staleReferenceClasses = Number(row.stale_reference_class_count || 0)

  if (alerts > 0) {
    return `${alerts} alert${alerts === 1 ? '' : 's'}`
  }

  if (staleAssumptions > 0) {
    return `${staleAssumptions} stale asm`
  }

  if (staleReferenceClasses > 0) {
    return `${staleReferenceClasses} stale ref${staleReferenceClasses === 1 ? '' : 's'}`
  }

  if (row.probability === null || row.probability === undefined || row.probability === '') {
    return 'needs forecast'
  }

  return row.status || 'active'
}

const triageRows = (response: ForecastDashboardResponse): [string, string][] => {
  const summary = response.summary
  if (!summary) {
    return []
  }

  const active = numberValue(summary.active_count) ?? (summary.questions ?? []).length
  const alerts = numberValue(summary.open_alert_count) ?? 0
  const reviews = numberValue(summary.review_queue_count) ?? (summary.review_queue ?? []).length
  const learnedErrorReviews = learnedErrorReviewCount(summary.review_queue ?? [])
  const otherReviews = Math.max(reviews - learnedErrorReviews, 0)
  const closing = numberValue(summary.closing_soon_count) ?? 0
  const calibrationCount = numberValue(summary.calibration?.count) ?? 0
  const learning = summary.learning
  const backtests = summary.recent_backtests ?? []
  const assumptions = assumptionCounts(summary)
  const referenceClasses = referenceClassCounts(summary)
  const doctor = summary.doctor
  const rows: [string, string][] = []

  if (alerts > 0) {
    rows.push(['/alerts', `${plural(alerts, 'open alert')} need source or resolution review`])
  }

  if (closing > 0) {
    rows.push(['/review --stale', `${plural(closing, 'forecast')} approaching or past close time`])
  }

  if (learnedErrorReviews > 0) {
    rows.push([
      '/review --stale',
      `${plural(learnedErrorReviews, 'forecast')} queued by learned error-profile review`
    ])
  }

  if (otherReviews > 0) {
    rows.push(['/review --stale', `${plural(otherReviews, 'forecast')} queued for stale/close/evidence review`])
  }

  if (assumptions.stale > 0) {
    rows.push([
      '/forecast self-check',
      `${plural(assumptions.stale, 'stale assumption')} ${assumptions.stale === 1 ? 'needs' : 'need'} evidence or status review`
    ])
  }

  if (referenceClasses.stale > 0) {
    rows.push([
      '/forecast self-check',
      `${plural(referenceClasses.stale, 'stale reference class', 'stale reference classes')} ${
        referenceClasses.stale === 1 ? 'needs' : 'need'
      } base-rate or source review`
    ])
  }

  const evidenceGaps = summary.evidence_status?.gaps ?? []
  if (evidenceGaps.length > 0) {
    const nextAction = summary.evidence_status?.next_actions?.[0]?.action
    rows.push([
      '/forecast readiness',
      nextAction
        ? `${plural(evidenceGaps.length, 'evidence gap')}; ${truncate(nextAction, 88)}`
        : `${plural(evidenceGaps.length, 'evidence gap')} blocking stronger benchmark claims`
    ])
  }

  if (doctor?.doctor_status === 'needs_tester_pilot_artifacts') {
    const nextAction = doctor.next_actions?.[0]?.action || doctor.next_action
    rows.push([
      '/forecast doctor --json',
      nextAction
        ? `pilot ${formatCount(doctor.pilot_passed_checks)}/${formatCount(doctor.pilot_total_checks)}; ${truncate(
            nextAction,
            88
          )}`
        : `pilot ${formatCount(doctor.pilot_passed_checks)}/${formatCount(doctor.pilot_total_checks)} still missing tester artifacts`
    ])
  } else if (doctor?.tester_handoff_ready && doctor.claim_live_superforecasting === false) {
    rows.push([
      '/forecast doctor --json',
      `tester handoff ready; ${formatVerdict(doctor.readiness_verdict)}; live superiority claim remains blocked`
    ])
  }

  if (active === 0) {
    rows.push(['/forecast new', 'create the first scoreable question with resolution criteria'])
  }

  if (calibrationCount === 0) {
    rows.push(['/forecast calibration --by-origin', 'no eligible scores yet; resolve and score forecasts to build memory'])
  }

  if ((numberValue(learning?.total_lessons) ?? 0) === 0 && calibrationCount > 0) {
    rows.push(['/forecast lesson list', 'no reusable lessons yet; review resolved misses and promote useful rules'])
  }

  if ((numberValue(learning?.tentative_lessons) ?? 0) > 0) {
    rows.push(['/forecast lesson list', `${plural(numberValue(learning?.tentative_lessons) ?? 0, 'lesson')} awaiting review`])
  }

  if (!backtests.length) {
    rows.push(['/forecast backtest --benchmarks', 'run a benchmark replay before trusting probability changes'])
  }

  if (!rows.length) {
    rows.push(['/forecast self-check', 'desk is clean; run a standing evidence and resolution sweep'])
  }

  return rows.slice(0, 5)
}

const addUniqueAction = (
  actions: ForecastDeskActionItem[],
  seen: Set<string>,
  command: string,
  detail: string,
  max: number,
  target?: string
) => {
  if (actions.length >= max || seen.has(command)) {
    return
  }

  seen.add(command)
  actions.push(target ? { command, detail, target } : { command, detail })
}

type FocusedForecastRow = ForecastDashboardQuestion | ForecastDashboardReview

const focusedForecastContext = (row: FocusedForecastRow) => {
  const bits = [
    `P=${formatProbability(row.probability)}`,
    `as-of ${shortDate(row.as_of)}`,
    `close ${shortDate(row.close_time)}`
  ]

  if ('reasons' in row && row.reasons?.length) {
    bits.push(`reasons ${truncate(row.reasons.slice(0, 2).map(formatReviewReason).join(','), 24)}`)
  }

  return bits.join('  ')
}

const focusedActionRows = (questions: ForecastDashboardQuestion[], reviewQueue: ForecastDashboardReview[]): ForecastPanelRow[] => {
  const row: FocusedForecastRow | undefined = reviewQueue.find(candidate => candidate.id) ?? questions.find(candidate => candidate.id)
  if (!row?.id) {
    return []
  }

  const label = truncate(row.title || row.id, 64)
  const context = focusedForecastContext(row)
  return [
    // Lead with the question title so the desk header/rail show the NAME, not a
    // raw fq_ id; the P=/as-of/reasons context follows.
    [`/questions ${row.id}`, `${label}  —  ${context}`],
    [
      `/note ${row.id} -- <evidence>`,
      'append timestamped evidence without moving probability',
      draftTarget(`/note ${row.id} -- `)
    ],
    [
      `/revise ${row.id} -- --probability <p> --rationale <why>`,
      'append a probability update after reviewing evidence',
      draftTarget(`/revise ${row.id} -- --probability `)
    ],
    [`/sources --question ${row.id}`, 'plan official data, RSS/news, markets, and watched searches'],
    [`/forecast research ${row.id}`, 'collect source notes and evidence without moving probability'],
    [
      `/forecast base-rate ${row.id} --name <reference-class> --inclusion-criteria <criteria> --base-rate <p>`,
      'add reference-class evidence before changing probability'
    ],
    [`/trend-model ${row.id} --series-json '[...]' --target-date <date>`, 'run a deterministic trend projection when time series matter'],
    [`/forecast resolve ${row.id} --outcome <value> --resolution-source <url>`, 'record resolution when criteria are met']
  ]
}

const searchNormalize = (value: unknown) =>
  String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9_ -]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const searchTokens = (query: string) =>
  searchNormalize(query)
    .split(/\s+/)
    .filter(token => token.length >= 2)

const uniqueForecastRows = (
  questions: ForecastDashboardQuestion[],
  reviewQueue: ForecastDashboardReview[]
): Array<{ index: number; row: ForecastDashboardQuestion | ForecastDashboardReview }> => {
  const rows: Array<{ index: number; row: ForecastDashboardQuestion | ForecastDashboardReview }> = []
  const seen = new Set<string>()

  questions.forEach((row, index) => {
    if (!row.id || seen.has(row.id)) {
      return
    }
    seen.add(row.id)
    rows.push({ index, row })
  })

  reviewQueue.forEach(row => {
    if (!row.id || seen.has(row.id)) {
      return
    }
    seen.add(row.id)
    rows.push({ index: rows.length, row })
  })

  return rows
}

const scoreForecastQuestionMatch = (
  row: ForecastDashboardQuestion | ForecastDashboardReview,
  query: string,
  tokens: string[]
): ForecastQuestionSearchMatch | null => {
  const id = row.id || ''
  const short = shortId(id)
  const title = row.title || ''
  const domain = row.domain || ''
  const topics = 'topics' in row && Array.isArray(row.topics) ? row.topics.join(' ') : ''
  const status = 'status' in row ? row.status || '' : ''
  const latestRationale = 'latest_rationale' in row ? row.latest_rationale || '' : ''
  const latestEvidence = [
    'latest_evidence_claim' in row ? row.latest_evidence_claim || '' : '',
    'latest_evidence_summary' in row ? row.latest_evidence_summary || '' : ''
  ].join(' ')
  const text = searchNormalize([id, short, title, domain, topics, status, latestRationale, latestEvidence].join(' '))
  const fullQuery = searchNormalize(query)
  const matched = new Set<string>()
  let score = 0

  if (!fullQuery) {
    return null
  }

  if (searchNormalize(id) === fullQuery || searchNormalize(short) === fullQuery) {
    score += 40
    matched.add('id')
  } else if (searchNormalize(id).includes(fullQuery) || searchNormalize(short).includes(fullQuery)) {
    score += 24
    matched.add('id')
  }

  if (searchNormalize(title).includes(fullQuery)) {
    score += 14
    matched.add('title')
  }

  if (domain && searchNormalize(domain).includes(fullQuery)) {
    score += 8
    matched.add('domain')
  }

  if (topics && searchNormalize(topics).includes(fullQuery)) {
    score += 8
    matched.add('topics')
  }

  if (latestRationale && searchNormalize(latestRationale).includes(fullQuery)) {
    score += 6
    matched.add('rationale')
  }

  if (latestEvidence && searchNormalize(latestEvidence).includes(fullQuery)) {
    score += 6
    matched.add('evidence')
  }

  for (const token of tokens) {
    if (!text.includes(token)) {
      continue
    }
    score += searchNormalize(title).includes(token) ? 4 : 2
    if (searchNormalize(title).includes(token)) {
      matched.add(token)
    }
  }

  if (tokens.length && tokens.every(token => text.includes(token))) {
    score += 6
  }

  return score > 0 ? { index: 0, matched: Array.from(matched), row, score } : null
}

export const rankForecastQuestionMatches = (
  response: ForecastDashboardResponse,
  query: string,
  limit = 12
): ForecastQuestionSearchMatch[] => {
  const summary = response.summary
  if (!summary) {
    return []
  }

  const tokens = searchTokens(query)
  return uniqueForecastRows(summary.questions ?? [], summary.review_queue ?? [])
    .map(({ index, row }) => {
      const match = scoreForecastQuestionMatch(row, query, tokens)
      return match ? { ...match, index } : null
    })
    .filter((match): match is ForecastQuestionSearchMatch => Boolean(match))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, Math.max(limit, 0))
}

const searchRowDelta = (row: ForecastDashboardQuestion | ForecastDashboardReview) =>
  'delta' in row ? formatDelta(row.delta) : '-'

const searchRowConfidence = (row: ForecastDashboardQuestion | ForecastDashboardReview) =>
  'confidence' in row ? formatConfidence(row.confidence) : '-'

const searchRowEvidenceCount = (row: ForecastDashboardQuestion | ForecastDashboardReview) =>
  'evidence_count' in row ? formatCount(row.evidence_count) : '-'

export const forecastQuestionSearchSections = (
  response: ForecastDashboardResponse,
  query: string,
  now = new Date()
): PanelSection[] => {
  const summary = response.summary
  const trimmed = query.trim()

  if (!summary) {
    return [{ text: response.output || '(no forecasts)' }]
  }

  if (!trimmed) {
    return forecastBookSections(response, now)
  }

  const matches = rankForecastQuestionMatches(response, trimmed, 12)
  const sections: PanelSection[] = [
    {
      rows: [
        ['query', trimmed],
        ['matches', formatCount(matches.length)],
        ['open', '/open <words> opens one unambiguous match; click a row to inspect the full ledger record']
      ],
      title: 'Forecast Search'
    }
  ]

  if (!matches.length) {
    sections.push({
      text: 'No matching active forecasts or review-queue items. Try fewer words, a topic, a domain, or /questions list 50.',
      title: 'Matches'
    })
    return sections
  }

  sections.push({
    rows: matches.map(match => {
      const row = match.row
      const key = `${match.index + 1}. ${shortId(row.id)}  P=${formatProbability(row.probability)}  Δ=${searchRowDelta(row)}`
      const details = [
        `score ${match.score}`,
        forecastFreshnessLabel(row.as_of, now),
        `close ${shortDate(row.close_time)}`,
        `conf ${searchRowConfidence(row)}`,
        `ev ${searchRowEvidenceCount(row)}`,
        forecastStatus(row as ForecastDashboardQuestion),
        truncate(row.title || '(untitled forecast)', 72)
      ].join('  ')

      return [key, details, row.id ? `/questions ${row.id}` : ''] as [string, string, string]
    }),
    title: 'Matches'
  })

  const top = matches[0]?.row
  if (top?.id) {
    const title = truncate(top.title || top.id, 68)
    sections.push({
      rows: [
        [`/questions ${top.id}`, `open full ledger context for ${title}`],
        [
          `/note ${top.id} -- <evidence>`,
          'append a timestamped evidence note without copying the id',
          draftTarget(`/note ${top.id} -- `)
        ],
        [
          `/revise ${top.id} -- --probability <p> --rationale <why>`,
          'append an explicit probability update',
          draftTarget(`/revise ${top.id} -- --probability `)
        ],
        [`/sources --question ${top.id}`, 'plan source coverage for this question']
      ],
      title: 'Top Match Shortcuts'
    })
  }

  return sections
}

const fieldString = (row: Record<string, unknown> | null | undefined, key: string) => {
  const value = row?.[key]
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

const packetCurrentSnapshot = (packet: ForecastQuestionPacket) => packet.forecast_history?.at(-1)

const packetProbability = (value: unknown) =>
  formatProbability(value as ForecastDashboardQuestion['probability'])

const compactPacketSource = (item: { source_name?: null | string; source_type?: string; source_url?: null | string }) => {
  const label = item.source_name || item.source_url || item.source_type || 'manual note'
  return truncate(label, 42)
}

const packetQuestionTitle = (packet: ForecastQuestionPacket) =>
  packet.question?.title || packet.question?.id || '(untitled forecast)'

export const forecastQuestionDetailSections = (response: ForecastQuestionPacketResponse): PanelSection[] => {
  const packet = response.packet
  const question = packet?.question
  if (!packet || !question?.id) {
    return [{ text: '(forecast question not found)', title: 'Forecast Detail' }]
  }

  const current = packetCurrentSnapshot(packet)
  const evidence = packet.evidence ?? []
  const history = packet.forecast_history ?? []
  const assumptions = packet.assumptions ?? []
  const references = packet.reference_classes ?? []
  const modelRuns = packet.model_runs ?? []
  const watchedSources = packet.watched_sources ?? []
  const title = packetQuestionTitle(packet)
  const topicText = question.topics?.length ? question.topics.join(', ') : '-'
  const sections: PanelSection[] = [
    {
      rows: [
        ['id', question.id],
        ['status', question.status || '-'],
        ['domain', question.domain || '-'],
        ['topics', truncate(topicText, 74)],
        ['close', shortDate(question.close_time)],
        ['resolution', shortDate(question.resolution_time)],
        ['cadence', question.review_cadence || '-'],
        ['next review', shortDate(question.next_review_at)]
      ],
      title: truncate(title, 78)
    },
    {
      rows: [
        ['P(now)', packetProbability(current?.probability_or_distribution)],
        ['delta', history.length >= 2 ? formatDelta(probability_delta(history.at(-2)?.probability_or_distribution, current?.probability_or_distribution)) : '-'],
        ['as-of', shortDate(current?.as_of)],
        ['confidence', formatConfidence(current?.confidence)],
        ['method', current?.method || '-'],
        ['origin', current?.forecast_origin || '-'],
        ['rationale', truncate(current?.rationale || 'No forecast snapshot recorded.', 118)]
      ],
      title: 'Current Forecast'
    },
    {
      rows: [
        ['evidence', formatCount(evidence.length)],
        ['history', formatCount(history.length)],
        ['assumptions', `${formatCount(assumptions.filter(item => item.status === 'active').length)}/${formatCount(assumptions.filter(item => item.status && item.status !== 'active').length)}`],
        ['references', `${formatCount(references.filter(item => item.status === 'active').length)}/${formatCount(references.filter(item => item.status && item.status !== 'active').length)}`],
        ['models', formatCount(modelRuns.length)],
        ['watches', formatCount(watchedSources.length)]
      ],
      title: 'Ledger State'
    }
  ]

  if (evidence.length) {
    sections.push({
      rows: evidence.slice(-6).reverse().map(item => [
        `${shortId(item.id)} ${shortDate(item.available_at)}`,
        truncate(
          `${item.stance || '-'}  ${item.claim_type || '-'}  ${compactPacketSource(item)}  ${item.claim || item.summary || '-'}`,
          116
        )
      ]),
      title: 'Recent Evidence'
    })
  }

  if (history.length) {
    sections.push({
      rows: history.slice(-6).reverse().map(item => [
        `${shortId(item.forecast_id)} ${shortDate(item.as_of)}`,
        truncate(
          `P=${packetProbability(item.probability_or_distribution)}  conf ${formatConfidence(item.confidence)}  ${
            item.method || '-'
          }  ${item.rationale || '-'}`,
          116
        )
      ]),
      title: 'Forecast History'
    })
  }

  if (assumptions.length || references.length) {
    const rows: [string, string][] = []
    for (const item of assumptions.slice(0, 3)) {
      rows.push([`asm ${shortId(item.id)} ${item.status || '-'}`, truncate(item.text || '-', 96)])
    }
    for (const item of references.slice(0, 3)) {
      rows.push([
        `ref ${shortId(item.id)} ${item.status || '-'}`,
        truncate(`${item.name || '-'}  base ${packetProbability(item.base_rate)}`, 96)
      ])
    }
    sections.push({ rows, title: 'Assumptions And References' })
  }

  if (modelRuns.length) {
    sections.push({
      rows: modelRuns.slice(-4).reverse().map(row => {
        const modelRun = row as Record<string, unknown>
        return [
          `${shortId(fieldString(modelRun, 'id'))} ${shortDate(fieldString(modelRun, 'created_at'))}`,
          truncate(
            `${fieldString(modelRun, 'model_type')}  p ${packetProbability(modelRun.probability_or_distribution)}  ${fieldString(
              modelRun,
              'summary'
            )}`,
            104
          )
        ] as [string, string]
      }),
      title: 'Model Runs'
    })
  }

  if (packet.resolution) {
    const resolution = packet.resolution as Record<string, unknown>
    sections.push({
      rows: [
        ['outcome', fieldString(resolution, 'outcome')],
        ['status', fieldString(resolution, 'resolution_status')],
        ['resolved', shortDate(fieldString(resolution, 'resolved_at'))],
        ['source', truncate(fieldString(resolution, 'resolution_source'), 96)]
      ],
      title: 'Resolution'
    })
  }

  sections.push({
    rows: [
      [
        `/note ${question.id} -- <evidence>`,
        'append timestamped evidence; probability remains unchanged',
        draftTarget(`/note ${question.id} -- `)
      ],
      [
        `/revise ${question.id} -- --probability <p> --rationale <why>`,
        'append an explicit probability update',
        draftTarget(`/revise ${question.id} -- --probability `)
      ],
      [`/sources --question ${question.id}`, 'plan source coverage and watched streams'],
      [`/forecast research ${question.id}`, 'review evidence freshness and new items since current forecast'],
      [`/forecast resolve ${question.id} --outcome <value> --resolution-source <url>`, 'record the outcome when criteria are met']
    ],
    title: 'Actions'
  })

  return sections
}

const probability_delta = (previous: unknown, current: unknown) => {
  const previousNumber = numberValue(previous)
  const currentNumber = numberValue(current)
  return previousNumber === null || currentNumber === null ? null : currentNumber - previousNumber
}

const sectionTitlesByLedgerView: Record<string, string[]> = {
  alerts: ['Desk', 'Open Alerts', 'Triage', 'Focused Actions'],
  backtests: ['Evidence Status', 'Recent Backtests', 'Live Performance', 'Triage', 'Next Commands'],
  book: ['Desk', 'Active Forecasts', 'Review Queue', 'Triage', 'Focused Actions'],
  calibration: ['Calibration', 'Live Performance', 'Evidence Status', 'Learning Memory', 'Next Commands'],
  evidence: ['Evidence Status', 'Focused Actions', 'Evidence Imports', 'Triage'],
  learning: ['Learning Memory', 'Calibration', 'Triage', 'Next Commands'],
  review: ['Review Queue', 'Triage', 'Focused Actions', 'Active Forecasts'],
  schedules: ['Scheduled Self-Checks', 'Triage', 'Focused Actions', 'Next Commands'],
  sources: ['Evidence Status', 'Focused Actions', 'Evidence Imports', 'Triage']
}

const ledgerViewShortcuts = (activeView: string): PanelSection => ({
  rows: [
    ...FORECAST_TUI_VIEW_SHORTCUTS.map(shortcut => [
      forecastShortcutDisplayHotkey(shortcut),
      `${shortcut.label}${shortcut.id === activeView ? ' (active)' : ''}: ${shortcut.description}`,
      shortcut.command
    ] as [string, string, string]),
    [
      FORECAST_TUI_FIND_SHORTCUT.hotkey,
      `${FORECAST_TUI_FIND_SHORTCUT.label}: ${FORECAST_TUI_FIND_SHORTCUT.description}`,
      '/find <words>'
    ],
    [
      '/1 … /9',
      'portable view shortcuts for terminals that reserve Alt/Option',
      '/1'
    ]
  ],
  title: 'View Shortcuts'
})

export const forecastLedgerViewSections = (
  response: ForecastDashboardResponse,
  view = 'book',
  now = new Date()
): PanelSection[] => {
  const normalized = searchNormalize(view) || 'book'
  const searchPrefix = 'search '
  if (normalized.startsWith(searchPrefix)) {
    return forecastQuestionSearchSections(response, view.trim().replace(/^search\s+/i, ''), now)
  }

  if (!response.summary) {
    return [{ text: response.output || '(no forecasts)', title: 'Ledger' }]
  }

  if (normalized === 'questions' || normalized === 'book') {
    return [ledgerViewShortcuts('book'), ...forecastBookSections(response, now)]
  }

  if (normalized === 'all' || normalized === 'overview' || normalized === 'dashboard') {
    return [ledgerViewShortcuts(normalized === 'all' ? 'all' : 'overview'), ...forecastDashboardSections(response)]
  }

  const alias = normalized === 'state' || normalized === 'store' || normalized === 'desk' ? 'book' : normalized
  const titles = sectionTitlesByLedgerView[alias]
  if (!titles) {
    return forecastQuestionSearchSections(response, view, now)
  }

  const dashboardSections = forecastDashboardSections(response)
  const selected = dashboardSections.filter(section => section.title && titles.includes(section.title))
  return [ledgerViewShortcuts(alias), ...(selected.length ? selected : forecastDashboardSections(response))]
}

export const forecastDeskActionStripItems = (sections: PanelSection[], max = 4): ForecastDeskActionItem[] => {
  const actions: ForecastDeskActionItem[] = []
  const seen = new Set<string>()
  const sectionByTitle = new Map(sections.map(section => [section.title, section]))
  const addRows = (section: PanelSection | undefined, skip = 0, limit = Number.POSITIVE_INFINITY) => {
    let added = 0
    for (const [command, detail, target] of (section?.rows ?? []).slice(skip)) {
      if (command.startsWith('/')) {
        const before = actions.length
        addUniqueAction(actions, seen, command, detail, max, target)
        if (actions.length > before) {
          added += 1
          if (added >= limit) {
            return
          }
        }
      }
    }
  }
  const addItems = (section: PanelSection | undefined) => {
    for (const command of section?.items ?? []) {
      if (command.startsWith('/')) {
        addUniqueAction(actions, seen, command, '', max)
      }
    }
  }

  const triage = sectionByTitle.get('Triage')
  addRows(triage, 0, 1)
  addRows(sectionByTitle.get('Focused Actions'))
  addRows(triage, 1)
  addItems(sectionByTitle.get('Next Commands'))

  return actions
}

export const forecastDeskPrimaryActionItem = (sections: PanelSection[]): ForecastDeskActionItem | undefined => {
  const focused = sections.find(section => section.title === 'Focused Actions')?.rows?.find(row => row[0].startsWith('/'))
  if (focused) {
    return { command: focused[0], detail: focused[1] }
  }

  return forecastDeskActionStripItems(sections, 1)[0]
}

const findSection = (sections: PanelSection[], title: string) => sections.find(section => section.title === title)

const addCompactItem = (
  items: ForecastDeskCompactItem[],
  label: string,
  detail: string | undefined,
  max: number
) => {
  if (items.length >= max || !detail) {
    return
  }

  items.push({ label, detail })
}

export const forecastDeskCompactItems = (sections: PanelSection[], max = 3): ForecastDeskCompactItem[] => {
  const items: ForecastDeskCompactItem[] = []
  const book = findSection(sections, 'Book')
  const bookRows = new Map((book?.rows ?? []).map(([key, value]) => [key, value] as [string, string]))
  const bookBits = [
    `${bookRows.get('active') ?? '0'} active`,
    `${bookRows.get('alerts') ?? '0'} alerts`,
    `${bookRows.get('reviews') ?? '0'} reviews`
  ]
  const assumptions = bookRows.get('assumptions')
  const referenceClasses = bookRows.get('refs')

  if (assumptions) {
    bookBits.push(`asm ${assumptions}`)
  }

  if (referenceClasses && referenceClasses !== '0/0') {
    bookBits.push(`refs ${referenceClasses}`)
  }

  if (book?.rows?.length) {
    addCompactItem(items, 'book', bookBits.join(' / '), max)
  }

  const doctor = findSection(sections, 'Doctor') ?? findSection(sections, 'Doctor Gate')
  const doctorStatus = doctor?.rows?.find(row => row[0] === 'status')
  if (doctorStatus) {
    addCompactItem(items, 'doctor', doctorStatus[1], max)
  }

  const triage = findSection(sections, 'Triage')?.rows?.[0]
  if (triage) {
    addCompactItem(items, 'triage', `${triage[0]} ${triage[1]}`, max)
  }

  const watch = findSection(sections, 'Watchlist')?.rows?.[0]
  if (watch) {
    addCompactItem(items, 'watch', `${watch[0]} ${watch[1]}`, max)
  }

  const alert = findSection(sections, 'Alerts')?.rows?.[0]
  if (alert) {
    addCompactItem(items, 'alert', `${alert[0]} ${alert[1]}`, max)
  }

  const evidence = findSection(sections, 'Evidence')?.rows?.find(row => row[0].startsWith('next ')) ?? findSection(
    sections,
    'Evidence'
  )?.rows?.find(row => row[0] === 'gaps')
  if (evidence) {
    addCompactItem(items, 'evidence', `${evidence[0]} ${evidence[1]}`, max)
  }

  return items
}

export const forecastDashboardSections = (response: ForecastDashboardResponse): PanelSection[] => {
  const summary = response.summary
  const questions = summary?.questions ?? []
  const reviewQueue = summary?.review_queue ?? []
  const alertsList = summary?.alerts ?? []
  const backtests = summary?.recent_backtests ?? []
  const livePerformance = summary?.live_performance
  const liveBaselines = livePerformance?.baselines ?? []
  const calibration = summary?.calibration
  const evidenceStatus = summary?.evidence_status
  const learning = summary?.learning
  const doctor = summary?.doctor
  const scheduledRuns = summary?.scheduled_review_runs ?? []

  if (!summary) {
    return [{ text: response.output || '(no forecasts)' }]
  }

  const active = summary.active_count ?? questions.length
  const alerts = summary.open_alert_count ?? 0
  const reviews = summary.review_queue_count ?? reviewQueue.length
  const closing = summary.closing_soon_count ?? 0
  const assumptions = assumptionCounts(summary)
  const referenceClasses = referenceClassCounts(summary)

  const sections: PanelSection[] = [
    {
      rows: [
        ['product', summary.product || 'Superforecasting Agent'],
        ['active forecasts', formatCount(active)],
        ['open alerts', formatCount(alerts)],
        ['review queue', formatCount(reviews)],
        ['closing soon', formatCount(closing)],
        ['assumptions', `${formatCount(assumptions.open)}/${formatCount(assumptions.stale)}`],
        ['reference classes', `${formatCount(referenceClasses.open)}/${formatCount(referenceClasses.stale)}`],
        ['calibration n', formatCount(calibration?.count)],
        ['lessons', formatCount(learning?.total_lessons)]
      ],
      title: 'Desk'
    }
  ]

  if (doctor) {
    sections.push({
      rows: doctorRows(doctor),
      title: 'Doctor Gate'
    })
  }

  if (questions.length) {
    sections.push({
      rows: questions.slice(0, 12).map(row => {
        const key = `${shortId(row.id)}  P=${formatProbability(row.probability)}  Δ=${formatDelta(row.delta)}`
        const details = [
          `as-of ${shortDate(row.as_of)}`,
          `close ${shortDate(row.close_time)}`,
          `conf ${formatConfidence(row.confidence)}`,
          `ev ${formatCount(row.evidence_count)}`,
          `base ${formatCount(row.baseline_count)}`,
          `refs ${formatCount(row.open_reference_class_count)}/${formatCount(row.stale_reference_class_count)}`,
          `asm ${formatCount(row.open_assumption_count)}/${formatCount(row.stale_assumption_count)}`,
          forecastStatus(row),
          truncate(row.title || '(untitled forecast)', 72)
        ].join('  ')

        return [key, details, row.id ? `/questions ${row.id}` : ''] as [string, string, string]
      }),
      title: 'Active Forecasts'
    })
  } else {
    sections.push({
      text: 'No active forecasts. Create one with /forecast new "Will X happen?" --resolution-criteria "...".',
      title: 'Active Forecasts'
    })
  }

  if (reviewQueue.length) {
    sections.push({
      rows: reviewQueue.slice(0, 6).map(row => {
        const reasons = (row.reasons ?? []).slice(0, 3).map(formatReviewReason).join(', ') || 'review'
        const key = `${shortId(row.id)}  priority ${row.priority ?? 9}`
        const details = [
          `P=${formatProbability(row.probability)}`,
          `as-of ${shortDate(row.as_of)}`,
          `close ${shortDate(row.close_time)}`,
          truncate(reasons, 52),
          truncate(row.next_action || `/questions ${row.id || ''}`, 64)
        ].join('  ')

        return [key, details, row.id ? `/questions ${row.id}` : ''] as [string, string, string]
      }),
      title: 'Review Queue'
    })
  }

  if (alertsList.length) {
    sections.push({
      rows: alertsList.slice(0, 6).map(row => {
        const scope = `${row.scope_type || '-'}:${row.scope_ref || '-'}`
        const key = `${shortId(row.id)}  ${row.severity || 'info'}  ${truncate(scope, 28)}`
        const details = [
          shortDate(row.created_at),
          truncate(row.reason || 'alert', 52),
          truncate(row.recommended_action || '/forecast alerts', 64)
        ].join('  ')

        return rowWithTarget(key, details, forecastActionTarget(row.recommended_action))
      }),
      title: 'Open Alerts'
    })
  }

  if (calibration) {
    const calibrationRows: [string, string][] = [
      ['eligible scores', formatCount(calibration.count)],
      ['mean brier', formatMetric(calibration.mean_brier)],
      ['mean log score', formatMetric(calibration.mean_log_score)],
      ['mean sharpness', formatMetric(calibration.mean_sharpness)],
      ['movement n', formatCount(calibration.probability_movement_count)],
      ['mean abs movement', formatMetric(calibration.mean_abs_probability_movement_before_close)]
    ]
    calibrationRows.push(...componentContributionRows(calibration, 3))
    calibrationRows.push(...questionTypeCalibrationRows(calibration, 4))

    sections.push({
      rows: calibrationRows,
      title: 'Calibration'
    })
  }

  if (learning) {
    const learningRows: [string, string][] = [
      [
        'lessons',
        `active ${formatCount(learning.active_lessons)}  tentative ${formatCount(learning.tentative_lessons)}  invalidated ${formatCount(learning.invalidated_lessons)}`
      ]
    ]

    for (const row of (learning.top_error_profiles ?? []).slice(0, 4)) {
      const errors = (row.recurring_errors ?? []).slice(0, 2).join(', ') || 'no recurring label'
      learningRows.push([
        formatErrorScope(row),
        `n ${formatCount(row.sample_count)}  brier ${formatMetric(row.mean_brier)}  ${truncate(errors, 48)}`
      ])
    }

    for (const row of (learning.recent_lessons ?? []).slice(0, 2)) {
      learningRows.push([
        `${row.status || '-'} ${formatLessonScope(row)}`,
        truncate(row.lesson || '(lesson without text)', 76)
      ])
    }

    sections.push({
      rows: learningRows,
      title: 'Learning Memory'
    })
  }

  if (scheduledRuns.length) {
    sections.push({
      rows: scheduledRuns.slice(0, 5).map(row => [
        `${shortId(row.id)}  alerts ${formatCount(row.alert_count)}`,
        [
          formatScheduleRunScope(row),
          `scores ${formatCount(row.score_count)}`,
          `postmortems ${formatCount(row.postmortem_count)}`,
          `learning ${formatCount(row.learning_review_count)}`,
          `next ${shortDate(row.next_run_at)}`
        ].join('  ')
      ]),
      title: 'Scheduled Self-Checks'
    })
  }

  if (evidenceStatus) {
    const scoreCounts = evidenceStatus.score_counts ?? {}
    const backtestCounts = evidenceStatus.backtests ?? {}
    const gaps = (evidenceStatus.gaps ?? []).slice(0, 4).map(gap => gap.replace(/_/g, ' ')).join(', ') || 'none'
    const evidenceRows: ForecastPanelRow[] = [
      ['verdict', formatVerdict(evidenceStatus.verdict)],
      [
        'scores',
        `live ${formatCount(scoreCounts.live)}  backtest ${formatCount(scoreCounts.backtest)}  baseline ${formatCount(scoreCounts.imported_baseline)}`
      ],
      [
        'backtests',
        `agent-protocol ${formatCount(backtestCounts.agent_protocol_scored_count)}  leakage-free ${formatCount(backtestCounts.leakage_free_run_count)}  edge ${formatCount(backtestCounts.positive_best_baseline_edge_run_count)}  datasets ${formatCount(backtestCounts.distinct_dataset_count)}  external ${formatCount(backtestCounts.external_dataset_count)}  families ${formatCount(backtestCounts.external_source_family_count)}`
      ],
      ['gaps', truncate(gaps, 88)]
    ]

    for (const item of (evidenceStatus.next_actions ?? []).slice(0, 3)) {
      const action = item.action || '/forecast readiness'
      evidenceRows.push(
        rowWithTarget(`next ${formatRequirement(item.requirement_id)}`, truncate(action, 88), forecastActionTarget(action))
      )
    }

    sections.push({
      rows: evidenceRows,
      title: 'Evidence Status'
    })
  }

  if (livePerformance && ((numberValue(livePerformance.score_count) ?? 0) > 0 || liveBaselines.length > 0)) {
    const liveRows: [string, string][] = [
      [
        'scores',
        `live ${formatCount(livePerformance.score_count)}  agent brier ${formatMetric(
          livePerformance.agent?.mean_brier
        )}  baselines ${formatCount(liveBaselines.length)}`
      ],
      ['claim', formatClaimVerdict(livePerformance.claim_status)]
    ]

    for (const row of liveBaselines.slice(0, 4)) {
      liveRows.push([
        formatLiveBaselineName(row),
        `brier ${formatMetric(row.mean_brier)}  paired ${formatCount(row.paired_count)}  edge ${formatDelta(
          row.mean_brier_improvement_vs_baseline
        )}  ci95 ${formatCi95(row.paired_agent_edge_ci95_low, row.paired_agent_edge_ci95_high)}  wins ${formatBacktestWins(
          row
        )}`
      ])
    }

    sections.push({
      rows: liveRows,
      title: 'Live Performance'
    })
  }

  if (backtests.length) {
    sections.push({
      rows: backtests.slice(0, 3).map(row => {
        const baseline = row.best_baseline
          ? `${row.best_baseline}=${formatMetric(row.best_baseline_brier)}`
          : 'baseline -'
        const details = [
          `cases ${formatCount(row.case_count)}`,
          `src ${formatBacktestSources(row)}`,
          `agent ${formatMetric(row.agent_mean_brier)}`,
          baseline,
          `edge ${formatDelta(row.agent_edge)}`,
          `wins ${formatBacktestWins(row)}`,
          `claim ${formatClaimStatus(row)}`,
          row.leakage_checks_passed === false ? 'leakage review' : 'leakage ok',
          truncate(row.dataset || '-', 48)
        ].join('  ')

        return [row.id || '-', details] as [string, string]
      }),
      title: 'Recent Backtests'
    })
  }

  const triage = triageRows(response)
  if (triage.length) {
    sections.push({
      rows: triage,
      title: 'Triage'
    })
  }

  const focusedActions = focusedActionRows(questions, reviewQueue)
  if (focusedActions.length) {
    sections.push({
      rows: focusedActions,
      title: 'Focused Actions'
    })
  }

  sections.push({
    items: [
      '/sources',
      '/sources --question <id>',
      '/forecast new "<question>" --resolution-criteria "<criteria>" --source-plan',
      '/forecast import news <rss-or-atom-url> --question <id> --keyword <term>',
      '/forecast watch add --question <id> --source-type rss rss:<feed-url> --keyword <term>',
      '/forecast import gdelt "<query>" --question <id>',
      '/forecast import fivethirtyeight <dataset-or-url> --question <id>',
      '/forecast import owid <slug> --entity "<entity>" --question <id>',
      '/forecast import whogho <indicator-code> --country <ISO3> --question <id>',
      '/forecast import fema <state|disaster-number|query> --question <id>',
      '/forecast import eia <series-id-or-api-url> --question <id>',
      '/forecast import treasury <dataset-path-or-api-url> --question <id>',
      '/forecast import imf <indicator>/<country> --question <id>',
      '/forecast import census "<dataset-path?get=...&for=...>" --question <id>',
      '/forecast import socrata <domain>/<dataset-id> --question <id>',
      '/forecast import ckan <domain>/<query> --question <id>',
      '/forecast import stooq <symbol-or-csv-url> --question <id>',
      '/forecast import yahoo <symbol> --question <id>',
      '/forecast import coingecko <coin-id> --question <id>',
      '/forecast import sec <cik> --question <id>',
      '/forecast import secfacts <cik>/<concept> --question <id>',
      '/forecast import crossref "<query-or-DOI>" --question <id>',
      '/forecast import wikipediapageviews <project>/<article> --question <id>',
      '/forecast import githubrepo <owner/repo> --question <id>',
      '/forecast import githubissues <owner/repo> --question <id>',
      '/forecast import githubcommits <owner/repo> --question <id>',
      '/forecast import githubactions <owner/repo> --question <id>',
      '/forecast import pypi <package> --question <id>',
      '/forecast import npm <package> --question <id>',
      '/forecast import hackernews "<query>" --question <id>',
      '/forecast import reddit "<query>" --question <id>',
      '/forecast import bluesky "<query>" --question <id>',
      '/forecast import mastodon <tag-or-instance/tag> --question <id>',
      '/forecast import reliefweb "<query>" --question <id>',
      '/forecast import clinicaltrials <query-or-NCT-id> --question <id>',
      '/forecast import openfda <query-or-application-number> --question <id>',
      '/forecast import pubmed "<query-or-PMID>" --question <id>',
      '/forecast import openmeteo <lat,lon> --question <id>',
      '/forecast import airquality <lat,lon> --question <id>',
      '/forecast import weatherhistory <lat,lon> --start-date <date> --end-date <date> --question <id>',
      '/forecast import usgs "<query>" --question <id>',
      '/forecast import eonet "<query-or-category>" --question <id>',
      '/forecast import nws "<area-or-point-or-query>" --question <id>',
      '/forecast import nvd "<keyword-or-CVE>" --question <id>',
      '/forecast import cisakev "<keyword-or-CVE-or-all>" --question <id>',
      '/forecast import federalregister "<query>" --question <id>',
      '/forecast import courtlistener "<query>" --question <id>',
      '/forecast watch add --question <id> <adapter>:<source>'
    ],
    title: 'Evidence Imports'
  })

  sections.push({
    items: [
      '/forecast review --stale',
      '/forecast self-check',
      '/sources',
      '/trend-model <id> --series-json \'[...]\' --target-date <date>',
      '/forecast calibration --by-origin',
      '/forecast lesson list',
      '/forecast errors',
      '/forecast autopilot status <id>',
      '/forecast autopilot enable <id> --source <adapter>:<source> --required-source <critical-adapter>:<source> --cadence 1d --mode propose',
      '/forecast autopilot history <id>',
      '/forecast schedule run --due --auto-score --auto-postmortem',
      '/forecast schedule history --json',
      '/forecast performance --last 5',
      '/forecast readiness',
      '/forecast doctor',
      '/forecast pilot-report',
      '/forecast pilot-cohort examples/forecasting/live-cohort.example.csv --dry-run --json',
      '/forecast pilot-bundle --include-export --output .pilot/tester-bundle.json',
      '/forecast export all --format json --output .pilot/tester-export.json',
      '/forecast import packet .pilot/tester-export.json --conflict skip --json',
      '/forecast pilot-aggregate .pilot/*-export.json --json',
      '/forecast backtest --benchmarks'
    ],
    title: 'Next Commands'
  })

  return sections
}

export const forecastBookSections = (
  response: ForecastDashboardResponse,
  now = new Date()
): PanelSection[] => {
  const summary = response.summary
  const questions = summary?.questions ?? []

  if (!summary) {
    return [{ text: response.output || '(no forecasts)' }]
  }

  const sections: PanelSection[] = [
    {
      rows: [
        ['active', formatCount(summary.active_count ?? questions.length)],
        ['alerts', formatCount(summary.open_alert_count)],
        ['reviews', formatCount(summary.review_queue_count)],
        ['freshness', 'Use /questions <number> to drill into a row without copying its id'],
        ['search', 'Use /find <words> or /questions <words> to locate forecasts by title, topic, or domain'],
        ['edit', 'Click Quick Edits or use /note <row|words> -- <evidence> and /revise <row|words> -- <args>']
      ],
      title: 'Book'
    }
  ]

  if (!questions.length) {
    sections.push({
      text: 'No active forecasts. Create one with /forecast new "Will X happen?" --resolution-criteria "...".',
      title: 'Forecast Questions'
    })
    return sections
  }

  sections.push({
    rows: questions.slice(0, 20).map((row, index) => {
      const key = `${index + 1}. P=${formatProbability(row.probability)} Δ=${formatDelta(row.delta)}`
      const details = [
        forecastFreshnessLabel(row.as_of, now),
        `as-of ${shortDate(row.as_of)}`,
        `close ${shortDate(row.close_time)}`,
        `conf ${formatConfidence(row.confidence)}`,
        `ev ${formatCount(row.evidence_count)}`,
        forecastStatus(row),
        truncate(row.title || '(untitled forecast)', 76)
      ].join('  ')

      return [key, details, `/questions ${index + 1}`]
    }),
    title: 'Forecast Questions'
  })

  sections.push({
    rows: questions.slice(0, 8).flatMap((row, index) => {
      const rowNumber = index + 1
      const title = truncate(row.title || row.id || `forecast ${rowNumber}`, 58)

      return [
        [
          `/note ${rowNumber}`,
          `draft evidence note for ${title}`,
          draftTarget(`/note ${rowNumber} -- `)
        ],
        [
          `/revise ${rowNumber}`,
          `draft probability update for ${title}`,
          draftTarget(`/revise ${rowNumber} -- --probability `)
        ]
      ] as ForecastPanelRow[]
    }),
    title: 'Quick Edits'
  })

  sections.push({
    rows: questions.slice(0, 8).map((row, index) => [
      `/questions ${index + 1}`,
      `open full details for ${truncate(row.title || row.id || `forecast ${index + 1}`, 76)}`
    ]),
    title: 'Drill Down'
  })

  return sections
}

const isLearnedErrorReviewReason = (reason?: string) => (reason ?? '').startsWith('domain_error_profile_applies:')

const formatReviewReason = (reason?: string) =>
  isLearnedErrorReviewReason(reason) ? 'learned error profile' : reason || 'review'

const learnedErrorReviewCount = (rows: ForecastDashboardReview[]) =>
  rows.filter(row => (row.reasons ?? []).some(isLearnedErrorReviewReason)).length

export const forecastDeskRailSections = (response: ForecastDashboardResponse): PanelSection[] => {
  const summary = response.summary

  if (!summary) {
    return response.output ? [{ text: truncate(response.output, 160), title: 'Desk' }] : []
  }

  const questions = summary.questions ?? []
  const reviewQueue = summary.review_queue ?? []
  const alertsList = summary.alerts ?? []
  const backtests = summary.recent_backtests ?? []
  const livePerformance = summary.live_performance
  const liveBaselines = livePerformance?.baselines ?? []
  const scheduledRuns = summary.scheduled_review_runs ?? []
  const calibration = summary.calibration
  const evidenceStatus = summary.evidence_status
  const learning = summary.learning
  const doctor = summary.doctor
  const active = summary.active_count ?? questions.length
  const alerts = summary.open_alert_count ?? 0
  const reviews = summary.review_queue_count ?? reviewQueue.length
  const closing = summary.closing_soon_count ?? 0
  const assumptions = assumptionCounts(summary)
  const referenceClasses = referenceClassCounts(summary)
  const sections: PanelSection[] = [
    {
      rows: [
        ['active', formatCount(active)],
        ['alerts', formatCount(alerts)],
        ['reviews', formatCount(reviews)],
        ['closing', formatCount(closing)],
        ['assumptions', `${formatCount(assumptions.open)}/${formatCount(assumptions.stale)}`],
        ['refs', `${formatCount(referenceClasses.open)}/${formatCount(referenceClasses.stale)}`],
        ['scores', formatCount(calibration?.count)],
        ['lessons', formatCount(learning?.total_lessons)]
      ],
      title: 'Book'
    }
  ]

  if (doctor) {
    const rows = doctorRows(doctor)
    const next = rows.find(row => row[0].startsWith('next '))
    sections.push({
      rows: [
        ['status', rows.find(row => row[0] === 'status')?.[1] ?? '-'],
        ['pilot', rows.find(row => row[0] === 'pilot')?.[1] ?? '-'],
        ['readiness', rows.find(row => row[0] === 'readiness')?.[1] ?? '-'],
        ['claim live', doctor.claim_live_superforecasting === true ? 'yes' : 'no'],
        ...(next ? ([[next[0], truncate(next[1], 58)]] as [string, string][]) : [])
      ],
      title: 'Doctor'
    })
  }

  const triage = triageRows(response)
  if (triage.length) {
    sections.push({
      rows: triage.slice(0, 3),
      title: 'Triage'
    })
  }

  const focusedRows = focusedActionRows(questions, reviewQueue)
  if (focusedRows.length) {
    sections.push({
      rows: focusedRows.slice(0, 3),
      title: 'Focused Actions'
    })
  }

  const atRisk = questions
    .filter(
      row =>
        Number(row.open_alert_count || 0) > 0 ||
        Number(row.stale_assumption_count || 0) > 0 ||
        Number(row.stale_reference_class_count || 0) > 0 ||
        !row.probability
    )
    .concat(questions)
    .filter((row, index, rows) => rows.findIndex(candidate => candidate.id === row.id) === index)
    .slice(0, 4)

  if (atRisk.length) {
    sections.push({
      rows: atRisk.map(row => {
        const key = `${shortId(row.id)} P=${formatProbability(row.probability)} Δ=${formatDelta(row.delta)}`
        const details = truncate(
          `${forecastStatus(row)}  as-of ${shortDate(row.as_of)}  close ${shortDate(row.close_time)}  conf ${formatConfidence(
            row.confidence
          )}  ${row.title || '(untitled forecast)'}`,
          88
        )

        return [key, details, row.id ? `/questions ${row.id}` : ''] as [string, string, string]
      }),
      title: 'Watchlist'
    })
  }

  if (alertsList.length) {
    sections.push({
      rows: alertsList.slice(0, 3).map(row =>
        rowWithTarget(
          `${shortId(row.id)} ${row.severity || 'info'}`,
          truncate(`${row.reason || 'alert'}  ${row.recommended_action || '/forecast alerts'}`, 64),
          forecastActionTarget(row.recommended_action)
        )
      ),
      title: 'Alerts'
    })
  }

  if (scheduledRuns.length) {
    sections.push({
      rows: scheduledRuns.slice(0, 2).map(row => [
        `${shortId(row.id)} alerts ${formatCount(row.alert_count)}`,
        truncate(
          `${formatScheduleRunScope(row)}  scores ${formatCount(row.score_count)}  pm ${formatCount(
            row.postmortem_count
          )}  learn ${formatCount(row.learning_review_count)}  next ${shortDate(row.next_run_at)}`,
          64
        )
      ]),
      title: 'Schedules'
    })
  }

  if (evidenceStatus) {
    const scoreCounts = evidenceStatus.score_counts ?? {}
    const backtestCounts = evidenceStatus.backtests ?? {}
    const gaps = (evidenceStatus.gaps ?? []).slice(0, 3).map(gap => gap.replace(/_/g, ' ')).join(', ') || 'none'
    const evidenceRows: ForecastPanelRow[] = [
      ['readiness', formatVerdict(evidenceStatus.verdict)],
      ['live/backtest', `${formatCount(scoreCounts.live)}/${formatCount(scoreCounts.backtest)}`],
      [
        'replay',
        `agent ${formatCount(backtestCounts.agent_protocol_scored_count)} edge ${formatCount(backtestCounts.positive_best_baseline_edge_run_count)} sets ${formatCount(backtestCounts.distinct_dataset_count)} ext ${formatCount(backtestCounts.external_dataset_count)} fam ${formatCount(backtestCounts.external_source_family_count)}`
      ],
      ['gaps', truncate(gaps, 58)]
    ]
    const nextAction = evidenceStatus.next_actions?.[0]
    if (nextAction) {
      const action = nextAction.action || '/forecast readiness'
      evidenceRows.push(
        rowWithTarget(
          `next ${formatRequirement(nextAction.requirement_id)}`,
          truncate(action, 58),
          forecastActionTarget(action)
        )
      )
    }

    sections.push({
      rows: evidenceRows,
      title: 'Evidence'
    })
  }

  if (livePerformance && ((numberValue(livePerformance.score_count) ?? 0) > 0 || liveBaselines.length > 0)) {
    const liveRows: [string, string][] = [
      [
        'scores',
        `live ${formatCount(livePerformance.score_count)} brier ${formatMetric(
          livePerformance.agent?.mean_brier
        )} bases ${formatCount(liveBaselines.length)}`
      ],
      ['claim', formatClaimVerdict(livePerformance.claim_status)]
    ]
    const topBaseline = liveBaselines[0]
    if (topBaseline) {
      liveRows.push([
        formatLiveBaselineName(topBaseline),
        truncate(
          `brier ${formatMetric(topBaseline.mean_brier)} paired ${formatCount(
            topBaseline.paired_count
          )} edge ${formatDelta(topBaseline.mean_brier_improvement_vs_baseline)} wins ${formatBacktestWins(
            topBaseline
          )}`,
          64
        )
      ])
    }

    sections.push({
      rows: liveRows,
      title: 'Live'
    })
  }

  const topComponents = componentContributionRows(calibration, 2)
  if (topComponents.length) {
    sections.push({
      rows: topComponents,
      title: 'Ensemble'
    })
  }

  if (backtests.length) {
    sections.push({
      rows: backtests.slice(0, 2).map(row => [
        row.id || '-',
        truncate(
          `src ${formatBacktestSources(row)}  agent ${formatMetric(row.agent_mean_brier)}  edge ${formatDelta(row.agent_edge)}  ${formatClaimStatus(row)}`,
          64
        )
      ]),
      title: 'Backtests'
    })
  }

  return sections
}
