import type {
  ForecastDashboardCalibration,
  ForecastDashboardDoctor,
  ForecastDashboardQuestion,
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastQuestionPacket,
  ForecastQuestionPacketResponse,
  ForecastQuestionPacketSnapshot
} from '../gatewayTypes.js'
import {
  FORECAST_TUI_FIND_SHORTCUT,
  FORECAST_TUI_VIEW_SHORTCUTS,
  forecastShortcutDisplayHotkey
} from '../lib/forecastShortcuts.js'
import { snapshotTailAudit, tailAuditChip } from '../lib/forecastTail.js'
import type { PanelSection } from '../types.js'

import {
  countUnearnedTail,
  draftTarget,
  fieldString,
  forecastActionTarget,
  forecastFreshnessLabel,
  formatBacktestSources,
  formatBacktestWins,
  formatCi95,
  formatClaimStatus,
  formatClaimVerdict,
  formatConfidence,
  formatCount,
  formatDelta,
  formatDoctorStatus,
  formatErrorScope,
  formatLessonScope,
  formatLiveBaselineName,
  formatMetric,
  formatProbability,
  formatRequirement,
  formatReviewReason,
  formatScheduleRunScope,
  formatSigned,
  formatVerdict,
  learnedErrorReviewCount,
  numberValue,
  plural,
  probability_delta,
  rowWithTarget,
  shortDate,
  shortId,
  truncate,
  unearnedTailMarker
} from './forecast/format.js'
import type { ForecastPanelRow } from './forecast/format.js'

// forecastFreshnessLabel is the one publicly-imported formatter (the rest are
// internal to the section builders); re-exported so callers/tests keep it here.
export { forecastFreshnessLabel } from './forecast/format.js'
import { rankForecastQuestionMatches, searchNormalize } from './forecast/search.js'

// The question search/ranking helpers live in ./forecast/search.js;
// rankForecastQuestionMatches + the match shape are re-exported here for callers.
export { rankForecastQuestionMatches } from './forecast/search.js'
export type { ForecastQuestionSearchMatch } from './forecast/search.js'

export interface ForecastDeskActionItem {
  command: string
  detail: string
  target?: string
}

export interface ForecastDeskCompactItem {
  label: string
  detail: string
}

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
  const thesisCount = numberValue(summary.thesis_count) ?? (summary.theses ?? []).length
  const factorCount = numberValue(summary.factor_count) ?? (summary.factors ?? []).length
  const entityCount = numberValue(summary.entity_count) ?? 0
  const alerts = numberValue(summary.open_alert_count) ?? 0
  const reviews = numberValue(summary.review_queue_count) ?? (summary.review_queue ?? []).length
  const closing = numberValue(summary.closing_soon_count) ?? 0
  const assumptions = assumptionCounts(summary)
  const referenceClasses = referenceClassCounts(summary)
  // Lead with what needs a human (active, to-review, alerts, closing), then the
  // quieter health counters. Spell out the cryptic abbreviations and only show
  // stale counts when there actually are stale items, so the strip reads as a
  // glanceable summary rather than a slash-delimited code.
  const bits = [`${active} forecasts`]

  if (thesisCount > 0) {
    bits.push(`${thesisCount} ${thesisCount === 1 ? 'thesis' : 'theses'}`)
  }

  if (factorCount > 0) {
    bits.push(`${factorCount} ${factorCount === 1 ? 'factor' : 'factors'}`)
  }

  if (entityCount > 0) {
    bits.push(`${entityCount} entities`)
  }

  if (reviews > 0) {
    bits.push(`${reviews} to review`)
  }

  if (alerts > 0) {
    bits.push(`${plural(alerts, 'alert')}`)
  }

  if (closing > 0) {
    bits.push(`${closing} closing`)
  }

  // A categorical forecast with unearned tail mass is a finding the desk must
  // surface, not bury — it belongs with the act-on-me counters, not the quiet
  // inventory. Only shown when at least one exists.
  const unearnedTail = countUnearnedTail(summary.questions ?? [])

  if (unearnedTail > 0) {
    bits.push(`${unearnedTail} with unearned tail`)
  }

  // Steady-state inventory (calibration totals, lesson counts, healthy
  // assumptions/reference classes) stays OFF the strip — it's findable in
  // /calibration and the question detail. The strip only carries counts a
  // human should act on, so an amber/red segment is meaningful at a glance.
  if (assumptions.stale > 0) {
    bits.push(`${assumptions.stale} stale ${assumptions.stale === 1 ? 'assumption' : 'assumptions'}`)
  }

  if (referenceClasses.stale > 0) {
    bits.push(
      `${referenceClasses.stale} stale reference ${referenceClasses.stale === 1 ? 'class' : 'classes'}`
    )
  }

  if (summary.doctor?.doctor_status) {
    bits.push(`doctor: ${formatDoctorStatus(summary.doctor.doctor_status)}`)
  }

  return bits.join('  ·  ')
}

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

  // An unearned tail is a finding, not steady-state: it outranks the stale
  // bookkeeping counters in the one-line status.
  const tailMarker = unearnedTailMarker(row)

  if (tailMarker) {
    return tailMarker
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
  const unearnedTail = countUnearnedTail(summary.questions ?? [])
  const rows: [string, string][] = []

  if (alerts > 0) {
    rows.push(['/alerts', `${plural(alerts, 'open alert')} need source or resolution review`])
  }

  if (unearnedTail > 0) {
    rows.push([
      '/forecast self-check',
      `${plural(unearnedTail, 'categorical forecast')} ${
        unearnedTail === 1 ? 'has' : 'have'
      } unearned tail mass — price each outcome by its path or compress the tail`
    ])
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
    formatProbability(row.probability),
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
      // Title-first: identity reads as the question, not the ledger id. The
      // numeric cluster trails as a compact suffix.
      const key = `${match.index + 1}. ${formatProbability(row.probability)}  ${searchRowDelta(row)}`

      const details = [
        truncate(row.title || '(untitled forecast)', 72),
        forecastFreshnessLabel(row.as_of, now),
        `close ${shortDate(row.close_time)}`,
        `conf ${searchRowConfidence(row)}`,
        `${searchRowEvidenceCount(row)} evidence`,
        forecastStatus(row as ForecastDashboardQuestion)
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

const packetCurrentSnapshot = (packet: ForecastQuestionPacket) => packet.forecast_history?.at(-1)

const packetProbability = (value: unknown) =>
  formatProbability(value as ForecastDashboardQuestion['probability'])

const compactPacketSource = (item: { source_name?: null | string; source_type?: string; source_url?: null | string }) => {
  // No inner truncation: this label is embedded in the Recent Evidence value,
  // which now wraps in full. The 42-char cap clipped real source names mid-word.
  return item.source_name || item.source_url || item.source_type || 'manual note'
}

const packetQuestionTitle = (packet: ForecastQuestionPacket) =>
  packet.question?.title || packet.question?.id || '(untitled forecast)'

// The tail-audit row(s) for the current snapshot, or [] when it carries no
// audit (non-categorical / older snapshot). Renders the same FAIL/PASS chip the
// workspace shows so the textual detail never contradicts the visual one.
const currentTailAuditRows = (current: ForecastQuestionPacketSnapshot | undefined): [string, string][] => {
  const audit = snapshotTailAudit(current)
  const chip = tailAuditChip(audit)

  return chip ? [['tail audit', chip]] : []
}

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
        ['probability', packetProbability(current?.probability_or_distribution)],
        ['delta', history.length >= 2 ? formatDelta(probability_delta(history.at(-2)?.probability_or_distribution, current?.probability_or_distribution)) : '-'],
        ['as-of', shortDate(current?.as_of)],
        ['confidence', formatConfidence(current?.confidence)],
        ['method', current?.method || '-'],
        ['origin', current?.forecast_origin || '-'],
        // The categorical tail audit, when the current snapshot carries one, so
        // the textual detail agrees with the workspace's Tail Audit section.
        ...currentTailAuditRows(current),
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
        // Full claim/summary — the primary evidence content; the renderer wraps it.
        `${item.stance || '-'}  ${item.claim_type || '-'}  ${compactPacketSource(item)}  ${item.claim || item.summary || '-'}`
      ]),
      title: 'Recent Evidence'
    })
  }

  if (history.length) {
    sections.push({
      rows: history.slice(-6).reverse().map(item => [
        shortDate(item.as_of),
        truncate(
          `${packetProbability(item.probability_or_distribution)}  conf ${formatConfidence(item.confidence)}  ${
            item.method || '-'
          }  ${item.rationale || '-'}`,
          240
        )
      ]),
      title: 'Forecast History'
    })
  }

  if (assumptions.length || references.length) {
    const rows: [string, string][] = []

    for (const item of assumptions.slice(0, 3)) {
      rows.push([`assumption · ${item.status || '-'}`, truncate(item.text || '-', 180)])
    }

    for (const item of references.slice(0, 3)) {
      rows.push([
        `reference · ${item.status || '-'}`,
        truncate(`${item.name || '-'}  base ${packetProbability(item.base_rate)}`, 150)
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
            200
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

  const facts = Object.entries(packet.applicability_facts ?? {})

  if (facts.length) {
    sections.push({title: 'Source Conditions', rows: facts.slice(0, 4).map(([key, value]) => {
      const fact = value as Record<string, unknown>

      return [key, fact.status === 'verified'
        ? `${String(fact.value)} · source observed ${shortDate(String(fact.observed_at))}`
        : `Unknown: ${String(fact.reason)}; inspect or refresh the source`, `/forecast facts show ${question.id}`]
    })})
  }

  if (packet.settlement_review) {
    const review = packet.settlement_review
    sections.push({title: 'Settlement Review', rows: [
      ['state', String(review.state)], ['next action', String(review.next_action)],
      ['owner', String(review.owner)], ['revisit', shortDate(review.revisit_at ? String(review.revisit_at) : undefined)]
    ]})
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
      [`/forecast facts show ${question.id}`, 'inspect source-backed conditions and missing evidence'],
      [`/forecast lessons explain ${question.id}`, 'inspect lesson conditions, sources and decisions'],
      [`/forecast resolve ${question.id} --outcome <value> --resolution-source <url>`, 'record the outcome when criteria are met']
    ],
    title: 'Actions'
  })

  return sections
}

const sectionTitlesByLedgerView: Record<string, string[]> = {
  alerts: ['Desk', 'Open Alerts', 'Triage', 'Focused Actions'],
  backtests: ['Evidence Status', 'Recent Backtests', 'Live Performance', 'Triage', 'Next Commands'],
  book: ['Desk', 'Lifecycle', 'Active Forecasts', 'Review Queue', 'Triage', 'Focused Actions'],
  calibration: ['Calibration', 'Live Performance', 'Evidence Status', 'Learning Memory', 'Next Commands'],
  evidence: ['Evidence Status', 'Focused Actions', 'Evidence Imports', 'Triage'],
  learning: ['Learning Memory', 'Calibration', 'Triage', 'Next Commands'],
  review: ['Lifecycle', 'Review Queue', 'Triage', 'Focused Actions', 'Active Forecasts'],
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

  // These are decision views, not a second dump of the whole book. A tall
  // inline transcript panel hides its beginning behind the virtualizer. Keep
  // findings and executable actions in view; full reports remain one command away.
  if (alias === 'review' && response.summary.lifecycle) {
    const lifecycle = dashboardSections.find(section => section.title === 'Lifecycle')

    return lifecycle ? [{ ...lifecycle, rows: [
      ...(lifecycle.rows ?? []),
      rowWithTarget('review forecasts', 'Inspect forecasts needing an explicit update', '/review --stale')
    ] }] : []
  }

  if (alias === 'learning' && response.summary.learning?.effectiveness) {
    const learning = dashboardSections.find(section => section.title === 'Learning Memory')

    return learning ? [{ ...learning, rows: (learning.rows ?? []).slice(0, 5) }] : []
  }

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

  // Thesis layer: the macro aggregates over the book — theses (health) + factors
  // (basket return) + the entity-suitability count.
  const theses = summary.theses ?? []
  const factors = summary.factors ?? []
  const thesisCount = summary.thesis_count ?? theses.length
  const factorCount = summary.factor_count ?? factors.length
  const entityCount = summary.entity_count ?? 0

  if (thesisCount > 0 || factorCount > 0) {
    const layerRows: ForecastPanelRow[] = [
      ['theses', formatCount(thesisCount)],
      ['factors', formatCount(factorCount)],
      ['entities', formatCount(entityCount)]
    ]

    for (const t of theses.slice(0, 6)) {
      const health =
        typeof t.health_probability === 'number'
          ? `${Math.round(t.health_probability * 100)}%`
          : t.health_display ?? '—'

      layerRows.push([truncate(t.title || t.id || 'thesis', 32), `${health} · ${formatCount(t.member_count)} members`])
    }

    for (const f of factors.slice(0, 6)) {
      const mean = typeof f.mean === 'number' ? `${f.mean >= 0 ? '+' : ''}${f.mean.toFixed(1)}` : '—'
      const vol = typeof f.sd === 'number' ? f.sd.toFixed(1) : '—'
      layerRows.push([truncate(f.title || f.id || 'factor', 32), `ret ${mean} · vol ${vol}`])
    }

    sections.push({ rows: layerRows, title: 'Thesis Layer' })
  }

  if (doctor) {
    sections.push({
      rows: doctorRows(doctor),
      title: 'Doctor Gate'
    })
  }

  if (questions.length) {
    sections.push({
      rows: questions.slice(0, 12).map(row => {
        const key = `${formatProbability(row.probability)}  ${formatDelta(row.delta)}`
        const staleRefs = numberValue(row.stale_reference_class_count) ?? 0
        const staleAssumptions = numberValue(row.stale_assumption_count) ?? 0

        const details = [
          // Title-first identity; bookkeeping counts only when actionable
          // (stale) — steady-state inventory lives in the detail pane.
          truncate(row.title || '(untitled forecast)', 72),
          `as-of ${shortDate(row.as_of)}`,
          `close ${shortDate(row.close_time)}`,
          `conf ${formatConfidence(row.confidence)}`,
          `${formatCount(row.evidence_count)} evidence`,
          ...(staleRefs > 0 ? [`${staleRefs} stale reference ${staleRefs === 1 ? 'class' : 'classes'}`] : []),
          ...(staleAssumptions > 0 ? [`${staleAssumptions} stale ${staleAssumptions === 1 ? 'assumption' : 'assumptions'}`] : []),
          forecastStatus(row)
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
        const key = `priority ${row.priority ?? 9}`

        const details = [
          truncate(row.title || '(untitled forecast)', 56),
          formatProbability(row.probability),
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

  if (summary.lifecycle?.counts) {
    const counts = summary.lifecycle.counts

    const rows: ForecastPanelRow[] = [
      rowWithTarget('review outcomes', `${formatCount(counts.settlement_review)} due; verify the source before resolving`, '/forecast lifecycle status'),
      ['forecast updates', `${formatCount(counts.review_overdue)} overdue; update probabilities explicitly`],
      rowWithTarget('deferred reviews', `${formatCount(counts.deferred_settlements)} waiting · ${formatCount(counts.review_reminders_due)} reminders due`, '/forecast lifecycle status'),
      rowWithTarget('documented limits', `${formatCount(counts.documented_unscoreable)} outcomes without historical forecasts`, '/forecast lifecycle status')
    ]

    const recoverable = (counts.ready_tasks ?? 0) + (counts.missing_tasks ?? 0)

    if (recoverable > 0) {
      rows.push(rowWithTarget('finish handoffs', `${recoverable} score/postmortem handoffs ready`, '/forecast lifecycle run'))
    }

    if ((counts.unfinished ?? 0) > 0) {
      rows.push(rowWithTarget('unfinished', `${counts.unfinished} need completion or missing-forecast review`, '/forecast lifecycle status'))
    }

    if ((counts.failed_tasks ?? 0) > 0) {
      rows.push(rowWithTarget('recovery errors', `${counts.failed_tasks} failed tasks; inspect the recorded error`, '/forecast lifecycle status'))
    }

    sections.push({title: 'Lifecycle', rows})
  }

  if (learning) {
    const learningRows: ForecastPanelRow[] = [
      [
        'lessons',
        `active ${formatCount(learning.active_lessons)}  tentative ${formatCount(learning.tentative_lessons)}  invalidated ${formatCount(learning.invalidated_lessons)}`
      ]
    ]

    if (learning.effectiveness) {
      const counts = learning.effectiveness.counts ?? {}
      learningRows.push(
        rowWithTarget('learning benefit', 'Not established · inspect scored evidence', '/forecast lessons effectiveness'),
        ['decisions', `${formatCount(counts.verified_decision_snapshots)} verified · ${formatCount(counts.historical_unverified_snapshots)} historical unverified`],
        ['scored questions', `${formatCount(counts.scored_distinct_questions)} questions · earliest pre-close forecast`],
        rowWithTarget('controlled trials', `${formatCount(learning.trials?.total)} trials · ${formatCount(learning.trials?.completed)} completed arms; inspect paired outcomes`, '/forecast trial list')
      )
    }

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
        `brier ${formatMetric(row.mean_brier)}  paired ${formatCount(row.paired_count)}  edge ${formatSigned(
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
          `edge ${formatSigned(row.agent_edge)}`,
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
      const key = `${index + 1}. ${formatProbability(row.probability)} ${formatDelta(row.delta)}`

      const details = [
        truncate(row.title || '(untitled forecast)', 76),
        forecastFreshnessLabel(row.as_of, now),
        `as-of ${shortDate(row.as_of)}`,
        `close ${shortDate(row.close_time)}`,
        `conf ${formatConfidence(row.confidence)}`,
        `${formatCount(row.evidence_count)} evidence`,
        forecastStatus(row)
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
        const key = `${formatProbability(row.probability)} ${formatDelta(row.delta)}`

        const details = truncate(
          `${row.title || '(untitled forecast)'}  ${forecastStatus(row)}  as-of ${shortDate(row.as_of)}  close ${shortDate(
            row.close_time
          )}  conf ${formatConfidence(row.confidence)}`,
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
          )} edge ${formatSigned(topBaseline.mean_brier_improvement_vs_baseline)} wins ${formatBacktestWins(
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
          `src ${formatBacktestSources(row)}  agent ${formatMetric(row.agent_mean_brier)}  edge ${formatSigned(row.agent_edge)}  ${formatClaimStatus(row)}`,
          64
        )
      ]),
      title: 'Backtests'
    })
  }

  return sections
}
