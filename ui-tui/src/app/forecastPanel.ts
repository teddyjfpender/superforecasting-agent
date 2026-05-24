import type {
  ForecastDashboardBacktest,
  ForecastDashboardCalibration,
  ForecastDashboardQuestion,
  ForecastDashboardResponse,
  ForecastDashboardReview
} from '../gatewayTypes.js'
import type { PanelSection } from '../types.js'

export interface ForecastDeskActionItem {
  command: string
  detail: string
}

export interface ForecastDeskCompactItem {
  label: string
  detail: string
}

const truncate = (value: string, max: number) => (value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value)

const numberValue = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const formatCount = (value: unknown) => {
  const number = numberValue(value)
  return number === null ? '0' : String(number)
}

const formatProbability = (value: ForecastDashboardQuestion['probability']) => {
  const number = numberValue(value)
  if (number !== null) {
    return number.toFixed(3)
  }

  if (value && typeof value === 'object') {
    return truncate(JSON.stringify(value), 24)
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

const formatMetric = (value: null | number | undefined) => {
  const number = numberValue(value)
  return number === null ? '-' : number.toFixed(6)
}

const formatBacktestWins = (row: { paired_agent_wins?: number; paired_baseline_wins?: number; paired_ties?: number }) =>
  `${row.paired_agent_wins ?? 0}/${row.paired_baseline_wins ?? 0}/${row.paired_ties ?? 0}`

const formatBacktestSources = (row: ForecastDashboardBacktest) =>
  truncate((row.probability_sources && row.probability_sources.length ? row.probability_sources : ['dataset']).join(','), 24)

const formatClaimStatus = (row: ForecastDashboardBacktest) => {
  const verdict = row.claim_status?.verdict
  if (verdict === 'benchmark_replay_only') {
    return 'replay only'
  }

  return verdict ? truncate(String(verdict).replace(/_/g, ' '), 24) : '-'
}

const formatVerdict = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 36) : '-'

const formatRequirement = (value: string | undefined) =>
  value ? truncate(String(value).replace(/_/g, ' '), 28) : 'evidence'

const plural = (count: number, singular: string, pluralForm = `${singular}s`) =>
  `${count} ${count === 1 ? singular : pluralForm}`

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

export const forecastDeskStatusLabel = (response: ForecastDashboardResponse): string => {
  const summary = response.summary

  if (!summary) {
    return ''
  }

  const active = numberValue(summary.active_count) ?? (summary.questions ?? []).length
  const alerts = numberValue(summary.open_alert_count) ?? 0
  const reviews = numberValue(summary.review_queue_count) ?? (summary.review_queue ?? []).length
  const calibrationCount = numberValue(summary.calibration?.count)
  const lessonCount = numberValue(summary.learning?.total_lessons)
  const assumptions = assumptionCounts(summary)
  const bits = [`desk ${active} active`]

  if (alerts > 0) {
    bits.push(`${plural(alerts, 'alert')}`)
  }

  if (reviews > 0) {
    bits.push(`${plural(reviews, 'review')}`)
  }

  if (calibrationCount !== null) {
    bits.push(`cal ${calibrationCount}`)
  }

  if (lessonCount !== null) {
    bits.push(plural(lessonCount, 'lesson'))
  }

  if (assumptions.open > 0 || assumptions.stale > 0) {
    bits.push(`asm ${assumptions.open}/${assumptions.stale}`)
  }

  return bits.join(' / ')
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

  if (alerts > 0) {
    return `${alerts} alert${alerts === 1 ? '' : 's'}`
  }

  if (staleAssumptions > 0) {
    return `${staleAssumptions} stale asm`
  }

  if (!row.probability) {
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
  const calibrationCount = numberValue(summary.calibration?.count) ?? 0
  const learning = summary.learning
  const backtests = summary.recent_backtests ?? []
  const assumptions = assumptionCounts(summary)
  const rows: [string, string][] = []

  if (alerts > 0) {
    rows.push(['/alerts', `${plural(alerts, 'open alert')} need source or resolution review`])
  }

  if (reviews > 0) {
    rows.push(['/review --stale', `${plural(reviews, 'forecast')} queued for stale/close/evidence review`])
  }

  if (assumptions.stale > 0) {
    rows.push([
      '/forecast self-check',
      `${plural(assumptions.stale, 'stale assumption')} ${assumptions.stale === 1 ? 'needs' : 'need'} evidence or status review`
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
  max: number
) => {
  if (actions.length >= max || seen.has(command)) {
    return
  }

  seen.add(command)
  actions.push({ command, detail })
}

type FocusedForecastRow = ForecastDashboardQuestion | ForecastDashboardReview

const focusedActionRows = (questions: ForecastDashboardQuestion[], reviewQueue: ForecastDashboardReview[]): [string, string][] => {
  const row: FocusedForecastRow | undefined = reviewQueue.find(candidate => candidate.id) ?? questions.find(candidate => candidate.id)
  if (!row?.id) {
    return []
  }

  const label = truncate(row.title || row.id, 64)
  return [
    [`/forecast show ${row.id}`, `load full ledger context for ${label}`],
    [`/forecast research ${row.id}`, 'collect source notes and evidence without moving probability'],
    [`/forecast update ${row.id} --probability <0-1>`, 'append an explicit probability update with rationale'],
    [`/forecast resolve ${row.id} --outcome <value> --source <url>`, 'record resolution when criteria are met']
  ]
}

export const forecastDeskActionStripItems = (sections: PanelSection[], max = 4): ForecastDeskActionItem[] => {
  const actions: ForecastDeskActionItem[] = []
  const seen = new Set<string>()
  const sectionByTitle = new Map(sections.map(section => [section.title, section]))
  const addRows = (section: PanelSection | undefined, skip = 0, limit = Number.POSITIVE_INFINITY) => {
    let added = 0
    for (const [command, detail] of (section?.rows ?? []).slice(skip)) {
      if (command.startsWith('/')) {
        const before = actions.length
        addUniqueAction(actions, seen, command, detail, max)
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
  const bookRows = new Map(book?.rows ?? [])
  const bookBits = [
    `${bookRows.get('active') ?? '0'} active`,
    `${bookRows.get('alerts') ?? '0'} alerts`,
    `${bookRows.get('reviews') ?? '0'} reviews`
  ]
  const assumptions = bookRows.get('assumptions')

  if (assumptions) {
    bookBits.push(`asm ${assumptions}`)
  }

  if (book?.rows?.length) {
    addCompactItem(items, 'book', bookBits.join(' / '), max)
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
  const calibration = summary?.calibration
  const evidenceStatus = summary?.evidence_status
  const learning = summary?.learning

  if (!summary) {
    return [{ text: response.output || '(no forecasts)' }]
  }

  const active = summary.active_count ?? questions.length
  const alerts = summary.open_alert_count ?? 0
  const reviews = summary.review_queue_count ?? reviewQueue.length
  const assumptions = assumptionCounts(summary)

  const sections: PanelSection[] = [
    {
      rows: [
        ['product', summary.product || 'Superforecasting Agent'],
        ['active forecasts', formatCount(active)],
        ['open alerts', formatCount(alerts)],
        ['review queue', formatCount(reviews)],
        ['assumptions', `${formatCount(assumptions.open)}/${formatCount(assumptions.stale)}`],
        ['calibration n', formatCount(calibration?.count)],
        ['lessons', formatCount(learning?.total_lessons)]
      ],
      title: 'Desk'
    }
  ]

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
          `asm ${formatCount(row.open_assumption_count)}/${formatCount(row.stale_assumption_count)}`,
          forecastStatus(row),
          truncate(row.title || '(untitled forecast)', 72)
        ].join('  ')

        return [key, details] as [string, string]
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
        const reasons = (row.reasons ?? []).slice(0, 3).join(', ') || 'review'
        const key = `${shortId(row.id)}  priority ${row.priority ?? 9}`
        const details = [
          `P=${formatProbability(row.probability)}`,
          `as-of ${shortDate(row.as_of)}`,
          `close ${shortDate(row.close_time)}`,
          truncate(reasons, 52),
          truncate(row.next_action || `/forecast show ${row.id || ''}`, 64)
        ].join('  ')

        return [key, details] as [string, string]
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

        return [key, details] as [string, string]
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

  if (evidenceStatus) {
    const scoreCounts = evidenceStatus.score_counts ?? {}
    const backtestCounts = evidenceStatus.backtests ?? {}
    const gaps = (evidenceStatus.gaps ?? []).slice(0, 4).map(gap => gap.replace(/_/g, ' ')).join(', ') || 'none'
    const evidenceRows: [string, string][] = [
      ['verdict', formatVerdict(evidenceStatus.verdict)],
      [
        'scores',
        `live ${formatCount(scoreCounts.live)}  backtest ${formatCount(scoreCounts.backtest)}  baseline ${formatCount(scoreCounts.imported_baseline)}`
      ],
      [
        'backtests',
        `agent-protocol ${formatCount(backtestCounts.agent_protocol_scored_count)}  leakage-free ${formatCount(backtestCounts.leakage_free_run_count)}  edge ${formatCount(backtestCounts.positive_best_baseline_edge_run_count)}  datasets ${formatCount(backtestCounts.distinct_dataset_count)}`
      ],
      ['gaps', truncate(gaps, 88)]
    ]

    for (const item of (evidenceStatus.next_actions ?? []).slice(0, 3)) {
      evidenceRows.push([`next ${formatRequirement(item.requirement_id)}`, truncate(item.action || '/forecast readiness', 88)])
    }

    sections.push({
      rows: evidenceRows,
      title: 'Evidence Status'
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
      '/forecast import gdelt "<query>" --question <id>',
      '/forecast import fivethirtyeight <dataset-or-url> --question <id>',
      '/forecast import owid <slug> --entity "<entity>" --question <id>',
      '/forecast import eia <series-id-or-api-url> --question <id>',
      '/forecast import treasury <dataset-path-or-api-url> --question <id>',
      '/forecast import census "<dataset-path?get=...&for=...>" --question <id>',
      '/forecast import socrata <domain>/<dataset-id> --question <id>',
      '/forecast import stooq <symbol-or-csv-url> --question <id>',
      '/forecast import yahoo <symbol> --question <id>',
      '/forecast import coingecko <coin-id> --question <id>',
      '/forecast import sec <cik> --question <id>',
      '/forecast import secfacts <cik>/<concept> --question <id>',
      '/forecast import crossref "<query-or-DOI>" --question <id>',
      '/forecast import wikipediapageviews <project>/<article> --question <id>',
      '/forecast import githubissues <owner/repo> --question <id>',
      '/forecast import githubcommits <owner/repo> --question <id>',
      '/forecast import githubactions <owner/repo> --question <id>',
      '/forecast import pypi <package> --question <id>',
      '/forecast import npm <package> --question <id>',
      '/forecast import hackernews "<query>" --question <id>',
      '/forecast import reddit "<query>" --question <id>',
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
      '/forecast calibration --by-origin',
      '/forecast performance --last 5',
      '/forecast readiness',
      '/forecast pilot-report',
      '/forecast pilot-cohort live-cohort.csv --dry-run --json',
      '/forecast backtest --benchmarks'
    ],
    title: 'Next Commands'
  })

  return sections
}

export const forecastDeskRailSections = (response: ForecastDashboardResponse): PanelSection[] => {
  const summary = response.summary

  if (!summary) {
    return response.output ? [{ text: truncate(response.output, 160), title: 'Desk' }] : []
  }

  const questions = summary.questions ?? []
  const reviewQueue = summary.review_queue ?? []
  const alertsList = summary.alerts ?? []
  const backtests = summary.recent_backtests ?? []
  const calibration = summary.calibration
  const evidenceStatus = summary.evidence_status
  const learning = summary.learning
  const active = summary.active_count ?? questions.length
  const alerts = summary.open_alert_count ?? 0
  const reviews = summary.review_queue_count ?? reviewQueue.length
  const assumptions = assumptionCounts(summary)
  const sections: PanelSection[] = [
    {
      rows: [
        ['active', formatCount(active)],
        ['alerts', formatCount(alerts)],
        ['reviews', formatCount(reviews)],
        ['assumptions', `${formatCount(assumptions.open)}/${formatCount(assumptions.stale)}`],
        ['scores', formatCount(calibration?.count)],
        ['lessons', formatCount(learning?.total_lessons)]
      ],
      title: 'Book'
    }
  ]

  const triage = triageRows(response)
  if (triage.length) {
    sections.push({
      rows: triage.slice(0, 3),
      title: 'Triage'
    })
  }

  const atRisk = questions
    .filter(row => Number(row.open_alert_count || 0) > 0 || Number(row.stale_assumption_count || 0) > 0 || !row.probability)
    .concat(questions)
    .filter((row, index, rows) => rows.findIndex(candidate => candidate.id === row.id) === index)
    .slice(0, 4)

  if (atRisk.length) {
    sections.push({
      rows: atRisk.map(row => [
        `${shortId(row.id)} P=${formatProbability(row.probability)} Δ=${formatDelta(row.delta)}`,
        truncate(`${forecastStatus(row)}  close ${shortDate(row.close_time)}  ${row.title || '(untitled forecast)'}`, 58)
      ]),
      title: 'Watchlist'
    })
  }

  if (alertsList.length) {
    sections.push({
      rows: alertsList.slice(0, 3).map(row => [
        `${shortId(row.id)} ${row.severity || 'info'}`,
        truncate(`${row.reason || 'alert'}  ${row.recommended_action || '/forecast alerts'}`, 64)
      ]),
      title: 'Alerts'
    })
  }

  if (evidenceStatus) {
    const scoreCounts = evidenceStatus.score_counts ?? {}
    const backtestCounts = evidenceStatus.backtests ?? {}
    const gaps = (evidenceStatus.gaps ?? []).slice(0, 3).map(gap => gap.replace(/_/g, ' ')).join(', ') || 'none'
    const evidenceRows: [string, string][] = [
      ['readiness', formatVerdict(evidenceStatus.verdict)],
      ['live/backtest', `${formatCount(scoreCounts.live)}/${formatCount(scoreCounts.backtest)}`],
      [
        'replay',
        `agent ${formatCount(backtestCounts.agent_protocol_scored_count)} edge ${formatCount(backtestCounts.positive_best_baseline_edge_run_count)} sets ${formatCount(backtestCounts.distinct_dataset_count)}`
      ],
      ['gaps', truncate(gaps, 58)]
    ]
    const nextAction = evidenceStatus.next_actions?.[0]
    if (nextAction) {
      evidenceRows.push([`next ${formatRequirement(nextAction.requirement_id)}`, truncate(nextAction.action || '/forecast readiness', 58)])
    }

    sections.push({
      rows: evidenceRows,
      title: 'Evidence'
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
