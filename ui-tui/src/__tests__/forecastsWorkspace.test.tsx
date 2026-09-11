import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type * as ForecastWorkspaceModule from '../components/forecastsWorkspace.js'
import type {
  ForecastFactor,
  ForecastTailAudit,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const texasItem = (): ForecastWorkspaceItem => ({
  action_threshold: 'If P(R) < 0.45, flag competitive',
  as_of: '2026-05-29T00:00:00Z',
  change_my_mind: ['poll lead > 5pts'],
  close_time: '2026-11-03T00:00:00Z',
  confidence: 0.65,
  decision_owner: 'Desk lead',
  decision_readiness_issues: [],
  delta: 0.02,
  domain: 'us-politics',
  evidence: [
    {
      available_at: '2026-05-28T00:00:00Z',
      claim: 'FEC filing shows fundraising gap',
      id: 'ev_1',
      reliability_rating: 0.8,
      source: 'https://www.fec.gov/data',
      stance: 'increases'
    }
  ],
  distribution: {
    ci50: null,
    ci90: null,
    mean: null,
    median: null,
    pmf: [
      { label: 'Republican candidate', probability: 0.52 },
      { label: 'Democratic candidate', probability: 0.47 },
      { label: 'Other', probability: 0.01 }
    ],
    sd: null
  },
  evidence_count: 1,
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.52,
  history: [
    { as_of: '2026-05-01T00:00:00Z', band_low: null, confidence: 0.6, headline_probability: 0.55 },
    { as_of: '2026-05-15T00:00:00Z', band_low: null, confidence: 0.62, headline_probability: 0.5 },
    { as_of: '2026-05-29T00:00:00Z', band_low: null, confidence: 0.65, headline_probability: 0.52 }
  ],
  id: 'fq_texas',
  impact: 'high',
  method: 'log_odds_pool',
  open_alert_count: 13,
  outcome_type: 'binary',
  panel: {
    aggregate_probability: 0.52,
    aggregation_method: 'trimmed_geomean_odds',
    estimates: [
      { perspective: 'outside', probability: 0.5, trimmed: false },
      { perspective: 'inside', probability: 0.58, trimmed: true, crux: 'fundraising' },
      { perspective: 'market', probability: 0.54, trimmed: false }
    ],
    spread: { iqr: 0.04, max: 0.58, median: 0.52, min: 0.42, p25: 0.5, p75: 0.54 },
    trim: 1
  },
  probability: 0.52,
  probability_display: '0.520',
  reasons_down: ['incumbent edge'],
  reasons_up: ['turnout model'],
  resolution_criteria: 'Official certified 2026 Texas US Senate result names the Republican winner.',
  snapshot_count: 3,
  status: 'active',
  title: 'Will the Republican win the Texas Senate seat?',
  topics: ['elections', 'senate'],
  update_triggers: [{ mechanism: 'FEC filing update' }]
})

const cpiItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-05-28T00:00:00Z',
  decision_readiness_issues: ['missing decision_owner'],
  delta: 0.006,
  distribution: {
    ci50: [4.166, 4.297],
    ci90: [4.071, 4.398],
    mean: 4.232,
    median: 4.231,
    pmf: [
      { label: 'bucket_4_2', probability: 0.3789 },
      { label: 'bucket_4_3', probability: 0.2984 },
      { label: 'bucket_4_1', probability: 0.1735 },
      { label: 'bucket_ge_4_4', probability: 0.1197 },
      { label: 'bucket_le_4_0', probability: 0.0296 }
    ],
    sd: 0.098
  },
  headline_kind: 'distribution',
  headline_probability: 4.232,
  history: [
    { as_of: '2026-05-26T00:00:00Z', band_high: 4.6, band_low: 3.5, headline_probability: 4.05 },
    { as_of: '2026-05-27T00:00:00Z', band_high: 4.5, band_low: 3.9, headline_probability: 4.2 },
    { as_of: '2026-05-28T00:00:00Z', band_high: 4.398, band_low: 4.071, headline_probability: 4.232 }
  ],
  id: 'fq_cpi',
  outcome_type: 'distribution',
  probability: {
    bucket_4_1: 0.1735,
    bucket_4_2: 0.3789,
    bucket_4_3: 0.2984,
    bucket_ge_4_4: 0.1197,
    bucket_le_4_0: 0.0296,
    mean: 4.232,
    sd: 0.098
  },
  probability_display: '{"mean": 4.232, ...}',
  snapshot_count: 10,
  status: 'active',
  title: 'May 2026 CPI-U YoY',
  units: 'percent year-over-year'
})

// The operator's screenshot: a multi-candidate vote-share PMF. `probability` is a
// candidate DICT (not a scalar), each history snapshot carries its own share dict,
// and a probability-scale `panel` exists so we can assert it is NEVER rendered.
const clactonItem = (opts: { intervals?: boolean } = {}): ForecastWorkspaceItem => ({
  as_of: '2026-06-28T00:00:00Z',
  candidate_intervals:
    opts.intervals === false
      ? null
      : { 'Count Binface': { hi: 24, lo: 10 }, 'Nigel Farage': { hi: 78, lo: 55, mid: 67 } },
  close_time: '2026-07-04T00:00:00Z',
  confidence: 0.55,
  delta: 1.5,
  headline_kind: 'probability',
  // The single scalar the BROKEN chart plotted (max/first key, not even the leader).
  headline_probability: 16.5,
  history: [
    {
      as_of: '2026-06-20T00:00:00Z',
      headline_probability: 14,
      probability: { 'Count Binface': 14, 'Laurence Fox': 6, 'Nigel Farage': 62, 'Other official candidates': 18 }
    },
    {
      as_of: '2026-06-24T00:00:00Z',
      headline_probability: 15,
      probability: { 'Count Binface': 15, 'Laurence Fox': 5, 'Nigel Farage': 65, 'Other official candidates': 15 }
    },
    {
      as_of: '2026-06-28T00:00:00Z',
      headline_probability: 16.5,
      probability: { 'Count Binface': 16.5, 'Laurence Fox': 4, 'Nigel Farage': 67, 'Other official candidates': 12.5 }
    }
  ],
  id: 'fq_clacton',
  outcome_type: 'categorical',
  // A probability-scale panel spread — the binary machinery the modal must NOT mix
  // into a vote-share question.
  panel: {
    aggregate_probability: 0.5,
    aggregation_method: 'trimmed_geomean_odds',
    estimates: [
      { perspective: 'outside', probability: 0.42, trimmed: false },
      { perspective: 'market', probability: 0.58, trimmed: false }
    ],
    spread: { max: 0.6, median: 0.5, min: 0.4 },
    trim: 0
  },
  probability: { 'Count Binface': 16.5, 'Laurence Fox': 4, 'Nigel Farage': 67, 'Other official candidates': 12.5 },
  probability_display: 'Farage 67.0 · Binface 16.5 · Other 12.5 · +1 more',
  snapshot_count: 3,
  status: 'active',
  title: 'Clacton by-election: which candidate wins the seat?'
})

const fixture = (): ForecastWorkspaceResponse => ({
  active_count: 2,
  closing_soon_count: 0,
  forecasts: [texasItem(), cpiItem()],
  generated_at: '2026-05-29T14:00:00Z',
  open_alert_count: 13,
  product: 'Superforecasting Agent'
})

const inflationThesis = (): ForecastThesis => ({
  analyst_note: {
    as_of: '2026-05-29T00:00:00Z',
    headline: 'Disinflation is stalling near 4%',
    how_it_thinks: 'The members lean toward sticky prints rather than a clean glide path.',
    kind: 'brief'
  },
  as_of: '2026-05-29T00:00:00Z',
  coverage: 0.5,
  components: [
    {
      contribution_pts: 12.4,
      direction: 'support',
      id: 'fq_cpi',
      latest_belief_display: 'μ4.23%',
      s_i: 0.62,
      status: 'ok',
      title: 'May 2026 CPI-U YoY',
      weight: 1
    },
    {
      contribution_pts: -3.1,
      direction: 'inverted',
      id: 'fq_unmatched',
      latest_belief_display: '38%',
      s_i: 0.38,
      status: 'stale',
      title: 'Fed cuts before September',
      weight: 1
    }
  ],
  delta: -0.04,
  domain: 'macro',
  entities: [
    {
      action: 'better suited',
      delta: 0.25,
      kind: 'stock',
      name: 'BE',
      stance: 'well-suited',
      suitability: 0.71,
      suitability_display: '71%',
      top_driver: 'power-bottleneck rising'
    },
    {
      action: 'less suited',
      delta: -0.08,
      kind: 'stock',
      name: 'CORZ',
      stance: 'marginal',
      suitability: 0.41,
      suitability_display: '41%',
      top_driver: 'financing cost'
    },
    {
      kind: 'stock',
      name: 'IREN',
      suitability: null,
      top_driver: null
    }
  ],
  freshness: 'fresh today',
  health_display: '54%',
  health_probability: 0.54,
  history: [
    { as_of: '2026-05-15T00:00:00Z', headline_probability: 0.5 },
    { as_of: '2026-05-22T00:00:00Z', headline_probability: 0.58 },
    { as_of: '2026-05-29T00:00:00Z', headline_probability: 0.54 }
  ],
  id: 'th_inflation',
  member_count: 2,
  n_eff: 1.3,
  // The desk lens tab resolves its members from question_ids (server-side
  // membership); fq_cpi is the present member (fq_unmatched isn't in the book).
  question_ids: ['fq_cpi', 'fq_unmatched'],
  rho: 0.42,
  score_band: { q05: 41, q50: 54, q95: 67 },
  status: 'active',
  thesis_score: 54,
  title: 'Inflation stays sticky through 2026',
  topics: ['inflation', 'macro'],
  triggers: [
    {
      better: ['BE', 'IREN'],
      delta: 0.25,
      direction: 'up',
      member_id: 'fq_power',
      note: 'Power ▲ +25pp → BE, IREN better suited',
      signal: 'power'
    }
  ]
})

const thesisFixture = (): ForecastWorkspaceResponse => ({
  ...fixture(),
  theses: [inflationThesis()],
  thesis_count: 1
})

const powerFactor = (): ForecastFactor => ({
  analyst_note: {
    as_of: '2026-05-29T00:00:00Z',
    headline: 'The power-bottleneck basket carries positive expected return',
    how_it_thinks: 'The long names dominate the basket; the short hedge trims downside.',
    kind: 'brief'
  },
  as_of: '2026-05-29T00:00:00Z',
  constituents: [
    {
      contribution: 6.2,
      direction: 'long',
      id: 'fq_be',
      mean: 8.4,
      sd: 2.1,
      status: 'ok',
      title: 'Bloom Energy upside',
      w_norm: 0.6,
      weight: 0.6
    },
    {
      contribution: -1.4,
      direction: 'short',
      id: 'fq_corz',
      mean: -3.1,
      sd: 1.8,
      status: 'stale',
      title: 'Core Scientific hedge',
      w_norm: 0.4,
      weight: 0.4
    }
  ],
  coverage: 0.5,
  cvar: -7.2,
  delta: 0.9,
  domain: 'energy',
  downside: -4.5,
  freshness: 'fresh today',
  history: [
    { as_of: '2026-05-15T00:00:00Z', band_high: 7.5, band_low: -2.0, headline_probability: 3.1, volatility: 2.9 },
    { as_of: '2026-05-22T00:00:00Z', band_high: 8.0, band_low: -1.5, headline_probability: 3.8, volatility: 2.8 },
    { as_of: '2026-05-29T00:00:00Z', band_high: 8.6, band_low: -1.2, headline_probability: 4.7, volatility: 2.7 }
  ],
  id: 'fx_power',
  member_count: 2,
  mean: 4.7,
  n_eff: 1.4,
  q05: -1.2,
  q50: 4.7,
  // The desk lens tab resolves its members from question_ids; fq_texas is the
  // present member in the book (the constituent ids aren't standalone forecasts).
  question_ids: ['fq_texas'],
  q95: 8.6,
  sd: 2.7,
  title: 'Power-bottleneck basket',
  topics: ['energy', 'power'],
  units: 'percent return',
  volatility: 2.7
})

const factorFixture = (): ForecastWorkspaceResponse => ({
  ...fixture(),
  factor_count: 1,
  factors: [powerFactor()]
})

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isRaw?: boolean
    isTTY: boolean
    ref?: () => PassThrough
    rows: number
    setRawMode?: (mode: boolean) => void
    unref?: () => PassThrough
  }

  let output = ''
  Object.assign(stream, {
    columns,
    isRaw: false,
    isTTY,
    rows,
    ref: () => stream,
    setRawMode: (mode: boolean) => {
      stream.isRaw = mode
    },
    unref: () => stream
  })
  stream.on('data', chunk => {
    output += chunk.toString()
  })

  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, ''))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// The live Desk is now DeskView (the redesigned, Markets-style lens-tab surface).
// These render-contract assertions target it; the heavy detail building blocks
// (ForecastDetail, ThesisDeskRead, FactorDeskRead, AnalystNote, ForecastPacketTail)
// are still exported from forecastsWorkspace.js and covered directly below.
const renderWorkspace = async (columns: number, response: ForecastWorkspaceResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { DeskView }, { DARK_THEME }, { stripAnsi }, { clearOverlayCache }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/deskView.js'),
    import('../theme.js'),
    import('../lib/text.js'),
    import('../lib/overlayCache.js')
  ])

  clearOverlayCache()
  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const fakeGw = {
    request: (method: string, params: Record<string, unknown>) =>
      method === 'forecast.question'
        ? Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
        : Promise.resolve(response)
  } as unknown as Parameters<typeof DeskView>[0]['gw']

  const instance = render(
    React.createElement(DeskView, { gw: fakeGw, onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  // Allow the async forecast.workspace fetch promise + an Ink frame to flush.
  await tick(60)
  const text = normalize(stdout.text(), stripAnsi)
  instance.unmount?.()
  instance.cleanup?.()

  return text
}

// The detail pane is rendered directly (it takes an explicit `width` prop) so
// the assertion does not depend on a headless terminal's width or ScrollBox
// height measurement — both unreliable outside a real TTY.
const renderDetail = async (item: ForecastWorkspaceItem, width = 70) => {
  const [{ renderSync }, { ForecastDetail }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/forecastsWorkspace.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 60)
  renderSync(React.createElement(ForecastDetail, { item, t: DARK_THEME, width }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdout: stdout.stream
  } as never)

  return normalize(stdout.text(), stripAnsi)
}

// Renders just the tail (forecast history / assumptions / model runs / actions)
// the same way the workspace does: feed a packet through the real section
// builder, keep only the tail titles, and render ForecastPacketTail directly so
// the assertion doesn't depend on headless ScrollBox height measurement.

const renderTail = async (packet: Record<string, unknown>, width = 70) => {
  const [{ renderSync }, { ForecastPacketTail }, { FORECAST_PACKET_TAIL_TITLES, forecastQuestionDetailSections }, { DARK_THEME }, { stripAnsi }] =
    await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../app/forecastPanel.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

  const sections = forecastQuestionDetailSections({ packet } as never).filter(
    section => section.title && FORECAST_PACKET_TAIL_TITLES.has(section.title)
  )

  const stdout = writeStream(120, 80)
  renderSync(React.createElement(ForecastPacketTail, { sections, t: DARK_THEME, width }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdout: stdout.stream
  } as never)

  return { sections, text: normalize(stdout.text(), stripAnsi) }
}

describe('ForecastsWorkspace pure transforms', () => {
  let mod: typeof ForecastWorkspaceModule

  it('imports helpers', async () => {
    mod = await import('../components/forecastsWorkspace.js')
    expect(typeof mod.matchesFilter).toBe('function')
  })

  it('matchesFilter matches title/domain/topics case-insensitively', async () => {
    const { matchesFilter } = await import('../components/forecastsWorkspace.js')
    const item = texasItem()
    expect(matchesFilter(item, '')).toBe(true)
    expect(matchesFilter(item, 'texas')).toBe(true)
    expect(matchesFilter(item, 'SENATE')).toBe(true)
    expect(matchesFilter(item, 'us-politics')).toBe(true)
    expect(matchesFilter(item, 'cpi')).toBe(false)
  })

  it('distributionBars sorts categorical outcomes and skips scalars/mean-sd', async () => {
    const { distributionBars } = await import('../components/forecastsWorkspace.js')
    const bars = distributionBars({ '3_0_3_2': 0.45, gt_3_2: 0.3, lt_3_0: 0.25 })
    expect(bars).not.toBeNull()
    expect(bars![0]!.label).toBe('3_0_3_2')
    expect(bars![0]!.value).toBe(0.45)
    expect(distributionBars(0.52)).toBeNull()
    expect(distributionBars({ mean: 3.1, sd: 0.4 })).toBeNull()
    expect(distributionBars(null)).toBeNull()

    // hybrid payload (candidate shares + bolted-on leader distribution): show ONLY
    // the candidate bars, never the quantile/interval fields as spurious candidates.
    const hybrid = distributionBars({
      'Andy Biggs': 64, 'David Schweikert': 27, Other: 9,
      mean: 64, median: 63.36, q05: 43.29, q25: 55.35, q50: 63.36, q75: 70.6, q95: 79.32,
      interval_90_low: 43.29, interval_90_high: 79.32, interval_50_low: 55.35, interval_50_high: 70.6,
    })

    expect(hybrid).not.toBeNull()
    expect(hybrid!.map(b => b.label).sort()).toEqual(['Andy Biggs', 'David Schweikert', 'Other'])
  })

  it('distributionBars attaches per-candidate intervals by label', async () => {
    const { distributionBars } = await import('../components/forecastsWorkspace.js')

    const bars = distributionBars(
      { Pappas: 72, Jarvis: 6, Other: 22 },
      { Pappas: { lo: 50, hi: 85 }, Jarvis: { lo: 2, hi: 14 } }
    )

    const byLabel = Object.fromEntries((bars ?? []).map(b => [b.label, b.interval]))
    expect(byLabel.Pappas).toEqual({ lo: 50, hi: 85 })
    expect(byLabel.Jarvis).toEqual({ lo: 2, hi: 14 })
    expect(byLabel.Other).toBeNull() // no interval supplied for this candidate
  })

  it('distributionHeadline shows the LEADER 90% interval where published, tail point-only', async () => {
    const { distributionHeadline } = await import('../components/forecastsWorkspace.js')

    const head = distributionHeadline(
      { 'Nigel Farage': 67, 'Count Binface': 16.5, 'Laurence Fox': 4 },
      { intervals: { 'Nigel Farage': { lo: 61, hi: 73 }, 'Count Binface': { lo: 12, hi: 22 } } }
    )

    // leader carries "67.0 [61-73]"; the tail (Binface) stays a bare point.
    expect(head).toContain('Farage 67.0 [61-73]')
    expect(head).toContain('Binface 16.5')
    expect(head).not.toContain('Binface 16.5 [')
  })

  it('distributionHeadline omits the interval when the leader has none', async () => {
    const { distributionHeadline } = await import('../components/forecastsWorkspace.js')
    const head = distributionHeadline({ 'Nigel Farage': 67, 'Count Binface': 16.5 })
    expect(head).toBe('Farage 67.0 · Binface 16.5')
  })

  it('intervalForLabel tolerates case/whitespace divergence between share + interval keys', async () => {
    const { intervalForLabel } = await import('../components/forecastsWorkspace.js')
    const intervals = { 'Chris Pappas': { lo: 50, hi: 85 } }
    expect(intervalForLabel(intervals, 'Chris Pappas')).toEqual({ lo: 50, hi: 85 }) // exact
    expect(intervalForLabel(intervals, 'chris pappas ')).toEqual({ lo: 50, hi: 85 }) // normalized
    expect(intervalForLabel(intervals, 'Other')).toBeNull()
    expect(intervalForLabel(undefined, 'x')).toBeNull()
  })

  it('historyToBandPoints shows only REAL bands — no confidence-synthesized band', async () => {
    const { historyToBandPoints } = await import('../components/forecastsWorkspace.js')
    const points = historyToBandPoints(texasItem())
    expect(points).toHaveLength(3)
    // earlier points: no real interval + no panel -> NO band (was a confidence-derived
    // band on a 0-1 scale, which detached from non-probability points — the bug).
    expect(points[0]!.lo).toBeNull()
    expect(points[0]!.hi).toBeNull()
    // latest point still uses the REAL panel spread (min 0.42 / max 0.58)
    expect(points[2]!.lo).toBeCloseTo(0.42, 5)
    expect(points[2]!.hi).toBeCloseTo(0.58, 5)
  })

  it('chartScale auto-zooms to data range (clamped to [0,1] for probabilities)', async () => {
    const { chartScale } = await import('../components/forecastsWorkspace.js')
    // probabilities: zoom in around the data, stay within [0,1]
    const prob = chartScale([{ y: 0.49 }, { y: 0.52 }, { y: 0.58 }])
    expect(prob.yMin).toBeGreaterThanOrEqual(0)
    expect(prob.yMax).toBeLessThanOrEqual(1)
    expect(prob.yMin).toBeLessThan(0.49)
    expect(prob.yMax).toBeGreaterThan(0.58)
    // a tighter window than the full axis so movement is visible
    expect(prob.yMax - prob.yMin).toBeLessThan(0.6)
    // numeric (e.g. CPI mean) pads beyond the data and is not clamped to 1
    const numeric = chartScale([{ y: 3 }, { y: 3.4 }])
    expect(numeric.yMin).toBeLessThan(3)
    expect(numeric.yMax).toBeGreaterThan(3.4)
  })

  it('chartScale enforces a minimum span for a flat series', async () => {
    const { chartScale } = await import('../components/forecastsWorkspace.js')
    const flat = chartScale([{ y: 0.5 }, { y: 0.5 }])
    expect(flat.yMax - flat.yMin).toBeGreaterThan(0.1)
  })

  it('chartScale handles empty input', async () => {
    const { chartScale } = await import('../components/forecastsWorkspace.js')
    expect(chartScale([])).toEqual({ yMax: 1, yMin: 0 })
  })

  it('chartScale domain includes EVERY drawn artifact — band edges, not just markers', async () => {
    const { chartScale } = await import('../components/forecastsWorkspace.js')

    // A tight marker series with a much wider band (e.g. the event interval): the
    // domain must contain the band edges too, or the band would be clipped/pinned.
    const scale = chartScale([
      { y: 0.5, lo: 0.2, hi: 0.85 },
      { y: 0.52, lo: 0.22, hi: 0.9 }
    ])

    expect(scale.yMin).toBeLessThanOrEqual(0.2)
    expect(scale.yMax).toBeGreaterThanOrEqual(0.9)
  })

  it('a rendered chart never clamps a drawn value onto the axis boundary (FIX 1)', async () => {
    const [{ bandChart }, { chartScale, thesisHealthBandPoints }] = await Promise.all([
      import('../lib/forecastCharts.js'),
      import('../components/forecastsWorkspace.js')
    ])

    // The real event-band shape: headline + p10/p90 lows/highs per snapshot.
    const points = thesisHealthBandPoints({
      history: [
        { as_of: '2026-05-15T00:00:00Z', event_high: 0.42, event_low: 0.3, headline_probability: 0.34 },
        { as_of: '2026-05-22T00:00:00Z', event_high: 0.41, event_low: 0.31, headline_probability: 0.36 },
        { as_of: '2026-05-29T00:00:00Z', event_high: 0.4, event_low: 0.31, headline_probability: 0.352 }
      ]
    } as never)

    const chart = bandChart(points, { height: 7, width: 48, ...chartScale(points) })

    // Every drawn value sits strictly inside the domain the chart reports — the
    // clamp in rowFor is a proven no-op, so no dot escapes the axis.
    for (const p of points) {
      for (const v of [p.y, p.lo, p.hi]) {
        if (typeof v === 'number' && Number.isFinite(v)) {
          expect(v).toBeGreaterThanOrEqual(chart.yMin)
          expect(v).toBeLessThanOrEqual(chart.yMax)
        }
      }
    }
  })

  it('multiSeriesChart floors the axis at 0 (never a negative vote share) and expands the ceiling to the data', async () => {
    const { multiSeriesChart } = await import('../lib/forecastCharts.js')

    // The old single-series bug: 15% padding pushed the axis below 0. multiSeriesChart
    // keeps the caller's floor (0) and only ever raises yMax to contain the markers.
    const chart = multiSeriesChart(
      [
        { label: 'Farage', values: [62, 65, 67] },
        { label: 'Binface', values: [14, null, 16.5] }
      ],
      { height: 7, width: 40, yMax: 10, yMin: 0 } // yMax deliberately below the data
    )

    expect(chart.yMin).toBe(0) // never negative
    expect(chart.yMax).toBeGreaterThanOrEqual(67) // expanded to contain the leader
    expect(chart.glyphs[0]).toBe('●') // leader gets the distinct filled marker
    expect(chart.glyphs[1]).toBe('◆')
  })

  it('multiSeriesChart draws the leader LAST so it wins a shared cell (leader visually distinct)', async () => {
    const { multiSeriesChart } = await import('../lib/forecastCharts.js')

    // Two series at the same value + only column → they collide on one cell; the
    // leader (index 0) is drawn last and overwrites, so ● shows, never ◆.
    const chart = multiSeriesChart(
      [
        { label: 'lead', values: [10] },
        { label: 'other', values: [10] }
      ],
      { height: 5, width: 20, yMax: 12, yMin: 0 }
    )

    const flat = chart.rows.map(row => row.cells.map(cell => cell.ch).join('')).join('')
    expect(flat).toContain('●')
    expect(flat).not.toContain('◆') // leader overwrote the collision
  })

  it('multiSeriesChart draws a per-candidate whisker on the latest column, point marker on top', async () => {
    const { multiSeriesChart } = await import('../lib/forecastCharts.js')

    // A wide interval [20, 85] around a latest point of 50, so the ┬/┴ caps sit clear
    // of the ● marker's own row (the marker legitimately wins any shared cell).
    const chart = multiSeriesChart(
      [{ label: 'lead', values: [30, 50], latestInterval: { lo: 20, hi: 85 } }],
      { height: 11, width: 24, yMax: 90, yMin: 0 }
    )

    const flat = chart.rows.map(row => row.cells.map(cell => cell.ch).join('')).join('')
    expect(flat).toContain('┬') // p95 cap
    expect(flat).toContain('┴') // p05 cap
    expect(flat).toContain('╎') // whisker stem
    expect(flat).toContain('●') // the latest point marker still shows
    expect(chart.yMax).toBeGreaterThanOrEqual(85) // domain contains the whisker top
  })

  it('seriesRuns collapses tagged cells into contiguous same-series runs', async () => {
    const { seriesRuns } = await import('../components/forecastsWorkspace.js')
    expect(
      seriesRuns([
        { ch: ' ', series: -1 },
        { ch: '●', series: 0 },
        { ch: '●', series: 0 },
        { ch: '◆', series: 1 }
      ])
    ).toEqual([
      { series: -1, text: ' ' },
      { series: 0, text: '●●' },
      { series: 1, text: '◆' }
    ])
  })

  it('buildVoteShareSeries pivots history into top-K candidate series + an aggregated Other (leader first)', async () => {
    const { buildVoteShareSeries, distributionBars } = await import('../components/forecastsWorkspace.js')

    const item = {
      headline_kind: 'probability',
      history: [
        { as_of: 'd1', probability: { A: 38, B: 24, C: 16, D: 11, E: 6, F: 5 } },
        { as_of: 'd2', probability: { A: 40, B: 25, C: 15, D: 10, E: 6, F: 4 } }
      ],
      probability: { A: 40, B: 25, C: 15, D: 10, E: 6, F: 4 }
    } as unknown as ForecastWorkspaceItem

    const bars = distributionBars(item.probability)!
    const result = buildVoteShareSeries(item, bars)
    // Top-4 candidates (value DESC, leader first) then a single Other for the tail.
    expect(result.series.map(s => s.label)).toEqual(['A', 'B', 'C', 'D', 'Other'])
    expect(result.scale).toBe(1) // percentage-scale payload, unscaled
    // Other aggregates E+F per point: d1 → 11, d2 → 10.
    const other = result.series[4]!
    expect(other.values).toEqual([11, 10])
    // The leader series carries A's shares across the (undownsampled) history.
    expect(result.series[0]!.values).toEqual([38, 40])
  })

  it('buildVoteShareSeries scales a fraction-scale payload ×100 and gaps a missing candidate', async () => {
    const { buildVoteShareSeries, distributionBars } = await import('../components/forecastsWorkspace.js')

    const item = {
      headline_kind: 'probability',
      history: [
        { as_of: 'd1', probability: { No: 0.45, Yes: 0.55 } },
        { as_of: 'd2', probability: { Maybe: 0.4, Yes: 0.6 } }, // No absent → a gap, not a fake 0
        { as_of: 'd3', probability: { No: 0.4, Yes: 0.6 } }
      ],
      probability: { No: 0.4, Yes: 0.6 }
    } as unknown as ForecastWorkspaceItem

    const bars = distributionBars(item.probability)!
    const result = buildVoteShareSeries(item, bars)
    const round = (values: (null | number)[]) => values.map(v => (v == null ? null : Math.round(v)))
    expect(result.scale).toBe(100)
    expect(result.series[0]!.label).toBe('Yes') // leader
    expect(round(result.series[0]!.values)).toEqual([55, 60, 60]) // ×100
    // 'No' is absent from d2 (a ≥2-candidate dict that just omits it) → a null gap.
    expect(result.series[1]!.label).toBe('No')
    expect(round(result.series[1]!.values)).toEqual([45, null, 40])
  })

  it('headlineLabel renders percent for probabilities and μ/σ for distributions', async () => {
    const { headlineLabel } = await import('../components/forecastsWorkspace.js')
    expect(headlineLabel({ headline_kind: 'probability', headline_probability: 0.52 } as ForecastWorkspaceItem)).toBe('52%')
    // distribution outcome (e.g. CPI mean) must NOT render as "423%" or raw JSON
    expect(
      headlineLabel({
        headline_kind: 'distribution',
        distribution: { mean: 4.232, sd: 0.098 },
        units: 'percent year-over-year'
      } as ForecastWorkspaceItem)
    ).toBe('μ 4.23% · σ 0.1')
    expect(headlineLabel({ probability_display: '0.520' } as ForecastWorkspaceItem)).toBe('0.520')
    expect(headlineLabel({} as ForecastWorkspaceItem)).toBe('—')
  })

  it('headlineLabel renders a categorical vote-share as a value-sorted, leader-first list — never JSON', async () => {
    const { headlineLabel } = await import('../components/forecastsWorkspace.js')

    // The Clacton bug: insertion-ordered JSON that truncated the leader (Farage 67).
    const clacton = headlineLabel({
      headline_kind: 'probability',
      probability: { 'Count Binface': 16.5, 'Laurence Fox': 4.0, 'Nigel Farage': 67.0, 'Other official candidates': 12.5 },
      probability_display: '{"Count Binface": 16.5, ...}'
    } as ForecastWorkspaceItem)

    expect(clacton).not.toContain('{')
    expect(clacton).not.toContain('"')
    // Leader FIRST (Farage 67 — the value that got truncated before), strict value
    // DESC, 1dp, "+N more" for the tail (compact row). "Other official candidates"
    // (12.5) outranks Fox (4.0), so it is the third shown, not Fox.
    expect(clacton.startsWith('Farage 67.0')).toBe(true)
    expect(clacton).toBe('Farage 67.0 · Binface 16.5 · Other offi… 12.5 · +1 more')
  })

  it('shortCandidateLabel collapses long two-word names to the surname', async () => {
    const { shortCandidateLabel } = await import('../components/forecastsWorkspace.js')
    expect(shortCandidateLabel('Nigel Farage')).toBe('Farage')
    expect(shortCandidateLabel('Count Binface')).toBe('Binface')
    expect(shortCandidateLabel('Laurence Fox')).toBe('Fox')
    expect(shortCandidateLabel('Fox')).toBe('Fox') // already short — unchanged
    expect(shortCandidateLabel('Other official candidates')).toBe('Other offi…') // 3 words → truncate
    expect(shortCandidateLabel('Supercalifragilistic')).toBe('Supercalif…') // single long token → truncate
  })

  it('distributionHeadline: sorted DESC, 1dp, compact "+N more" for rows vs full list for detail', async () => {
    const { distributionHeadline } = await import('../components/forecastsWorkspace.js')
    const pmf = { 'Count Binface': 16.5, 'Laurence Fox': 4.0, 'Nigel Farage': 67.0, 'Other official candidates': 12.5 }
    // Row context: leader first, top-3 + "+N more" (the row then tail-ellipsizes).
    expect(distributionHeadline(pmf, { compact: true, max: 3 })).toBe('Farage 67.0 · Binface 16.5 · Other offi… 12.5 · +1 more')
    // Detail context: every candidate, no truncation of a value.
    expect(distributionHeadline(pmf)).toBe('Farage 67.0 · Binface 16.5 · Other offi… 12.5 · Fox 4.0')
    // Fraction-scale PMFs render as percentages (×100).
    expect(distributionHeadline({ Yes: 0.62, No: 0.38 })).toBe('Yes 62.0 · No 38.0')
    // Not a ≥2-candidate PMF → null (scalar / mean-sd shapes fall back elsewhere).
    expect(distributionHeadline(0.52)).toBeNull()
    expect(distributionHeadline({ mean: 3.1, sd: 0.4 })).toBeNull()
    expect(distributionHeadline(null)).toBeNull()
  })

  it('historyToBandPoints uses the distribution band, not the panel spread', async () => {
    const { historyToBandPoints } = await import('../components/forecastsWorkspace.js')
    const points = historyToBandPoints(cpiItem())
    // last point band is the snapshot's own 90% interval (CPI percent units)
    expect(points[2]!.y).toBeCloseTo(4.232, 3)
    expect(points[2]!.lo).toBeCloseTo(4.071, 3)
    expect(points[2]!.hi).toBeCloseTo(4.398, 3)
  })

  it('historyToBandPoints marks non-numeric points as null y', async () => {
    const { historyToBandPoints } = await import('../components/forecastsWorkspace.js')

    const points = historyToBandPoints({
      headline_kind: 'probability',
      history: [{ headline_probability: null }, { headline_probability: 0.5, confidence: 0.5 }]
    } as ForecastWorkspaceItem)

    expect(points[0]!.y).toBeNull()
    expect(points[1]!.y).toBe(0.5)
  })

  it('panelFromPacket prefers the recorded panel run', async () => {
    const { panelFromPacket } = await import('../components/forecastsWorkspace.js')

    const panel = panelFromPacket({
      forecast_history: [
        {
          ensemble_components: { components: [{ name: 'base_rate', probability: 0.4 }, { name: 'model', probability: 0.6 }] },
          probability_or_distribution: 0.5
        }
      ],
      panel_runs: [
        {
          aggregate_probability: 0.52,
          aggregation_method: 'trimmed_geomean_odds',
          estimates: [
            { perspective: 'outside', probability: 0.5, trimmed: false },
            { perspective: 'inside', probability: 0.58, trimmed: true }
          ],
          id: 'pr_1',
          spread_summary: { max: 0.58, min: 0.5 },
          trim: 1
        }
      ]
    })

    expect(panel).not.toBeNull()
    expect(panel!.kind).toBe('panel')
    expect(panel!.aggregate_probability).toBe(0.52)
    expect(panel!.estimates).toHaveLength(2)
    expect(panel!.spread).toEqual({ max: 0.58, min: 0.5 })
  })

  it('panelFromPacket reconstructs an ensemble spread from snapshot components', async () => {
    const { panelFromPacket } = await import('../components/forecastsWorkspace.js')

    const panel = panelFromPacket({
      forecast_history: [
        { ensemble_components: {}, probability_or_distribution: 0.2 },
        {
          as_of: '2026-06-01T00:00:00Z',
          ensemble_components: {
            components: [
              { name: 'base_rate', probability: 0.4, weight: 2 },
              { name: 'model', probability: 0.62, weight: 1 },
              { name: 'broken', probability: 'nope' }
            ]
          },
          method: 'log_odds_pool',
          probability_or_distribution: 0.48
        }
      ]
    })

    expect(panel).not.toBeNull()
    expect(panel!.kind).toBe('ensemble')
    expect(panel!.aggregate_probability).toBe(0.48)
    expect(panel!.aggregation_method).toBe('log_odds_pool')
    // the malformed component is dropped, never rendered as a fake number
    expect(panel!.estimates!.map(estimate => estimate.perspective)).toEqual(['base_rate', 'model'])
    expect(panel!.estimates![0]!.weight).toBe(2)
  })

  it('panelFromPacket reads plain name→probability ensemble maps', async () => {
    const { panelFromPacket } = await import('../components/forecastsWorkspace.js')

    const panel = panelFromPacket({
      forecast_history: [
        { ensemble_components: { base_rate: 0.4, market: { probability: 0.55, weight: 1.5 } }, probability_or_distribution: 0.5 }
      ]
    })

    expect(panel).not.toBeNull()
    expect(panel!.estimates!.map(estimate => [estimate.perspective, estimate.probability])).toEqual([
      ['base_rate', 0.4],
      ['market', 0.55]
    ])
  })

  it('panelFromPacket returns null without a run or 2+ usable components', async () => {
    const { panelFromPacket } = await import('../components/forecastsWorkspace.js')

    expect(panelFromPacket(null)).toBeNull()
    expect(panelFromPacket({})).toBeNull()
    expect(panelFromPacket({ forecast_history: [] })).toBeNull()
    expect(
      panelFromPacket({
        forecast_history: [
          { ensemble_components: { components: [{ name: 'only_one', probability: 0.5 }] }, probability_or_distribution: 0.5 }
        ]
      })
    ).toBeNull()
  })
})

describe('ForecastsWorkspace render', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the desk header counts, lens tabs, an active-tab forecast row, and footer chips', async () => {
    const text = await renderWorkspace(120, fixture())
    expect(text).toContain('FORECASTS')
    expect(text).toContain('2 active')
    expect(text).toContain('13 open alert')
    // With no thesis, every forecast lands in the single All catch-all — the tag
    // pseudo-lenses were removed, so "#elections" no longer appears in the strip.
    expect(text).toContain('All')
    expect(text).not.toContain('#elections')
    // The active tab's forecast renders as a dense table row (cursor + QUESTION
    // column); the long title truncates, so assert the visible prefix.
    expect(text).toContain('Will the Rep')
    // Footer chip shortcuts bar (Markets-style).
    expect(text).toContain('Lens')
    expect(text).toContain('Open')
    expect(text).toContain('Filter')
  })

  it('renders the detail pane with charts, panel, causal paths, and decision card', async () => {
    const text = await renderDetail(texasItem())
    expect(text).toContain('Will the Republican win the Texas Senate seat?')
    expect(text).toContain('probability over time')
    expect(text).toContain('●') // chart marker
    expect(text).toContain('panel')
    expect(text).toContain('aggregate')
    // Reasons render as labelled causal PATHS, not a generic "reasons" blob.
    expect(text).toContain('causal paths')
    expect(text).toContain('Path up')
    expect(text).toContain('turnout model') // reasons_up
    expect(text).toContain('decision card')
    expect(text).toContain('Desk lead')
    expect(text).toContain('recent evidence')
  })

  it('wraps long causal-path text in a narrow pane instead of cutting it with a trailing ellipsis', async () => {
    const [{ Box, renderSync }, { ForecastDetail }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const item = texasItem()
    // A causal-path link (reasons_up) long enough that a narrow detail pane MUST
    // wrap it. The tail token survives in the output only if the line wrapped,
    // not if it was cut with a trailing ellipsis (the old truncate-end bug).
    item.reasons_up = [
      'early-vote composition shifted decisively toward suburban precincts that historically resist the incumbent WRAPTAILUP'
    ]
    // Bound the detail to a narrow column so the wrap boundary actually bites
    // (ForecastDetail renders text into its container width).
    const stdout = writeStream(120, 60)
    renderSync(
      React.createElement(Box, { width: 44 }, React.createElement(ForecastDetail, { item, t: DARK_THEME, width: 44 })),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('Path up')
    expect(text).toContain('WRAPTAILUP')
  })

  it('panel section shows each perspective vs the aggregate with rail, delta, and trim note', async () => {
    const text = await renderDetail(texasItem())
    expect(text).toContain('panel (3 perspectives)')
    // every perspective gets a value + delta-from-aggregate column
    expect(text).toContain('outside')
    expect(text).toContain('-2pt') // outside 50% vs aggregate 52%
    expect(text).toContain('inside')
    expect(text).toContain('+6pt') // inside 58% vs aggregate 52%
    expect(text).toContain('market')
    expect(text).toContain('+2pt')
    // the trimmed estimate is marked and the trimmed-mean rule is spelled out
    expect(text).toContain('×')
    expect(text).toContain('trimmed mean: 1 outlier estimate (×) excluded before pooling')
    // each row has the position rail with the aggregate tick
    expect(text).toContain('┊')
    expect(text).toContain('fundraising') // crux still shown
  })

  it('detail falls back to the packet panel when the workspace item has none', async () => {
    const [{ renderSync }, { ForecastDetail, panelFromPacket }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const item = { ...texasItem(), panel: null }

    const packetPanel = panelFromPacket({
      forecast_history: [
        {
          ensemble_components: {
            components: [
              { name: 'base_rate', probability: 0.45, weight: 2 },
              { name: 'model', probability: 0.6, weight: 1 }
            ]
          },
          method: 'log_odds_pool',
          probability_or_distribution: 0.52
        }
      ]
    })

    const stdout = writeStream(120, 60)
    renderSync(React.createElement(ForecastDetail, { item, packetPanel, t: DARK_THEME, width: 70 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)

    expect(text).toContain('ensemble (2 components)')
    expect(text).toContain('base_rate')
    expect(text).toContain('-7pt') // 45% vs aggregate 52%
    expect(text).toContain('model')
    expect(text).toContain('+8pt')
    // differing weights are surfaced for ensemble components
    expect(text).toContain('w 2.0')
    // no trim on ensembles → no trimmed-mean note
    expect(text).not.toContain('trimmed mean')
  })

  it('renders a distribution forecast as μ/σ, mean-over-time, PMF buckets, and CI — not raw JSON', async () => {
    const text = await renderDetail(cpiItem())
    // headline is the distribution summary, NOT a "423%" or a JSON dump
    expect(text).toContain('μ 4.23%')
    expect(text).toContain('σ 0.1')
    expect(text).not.toContain('{"mean"')
    expect(text).not.toContain('423%')
    // continuous summary line with intervals
    expect(text).toContain('90% [4.07, 4.4]')
    // time-series is labelled as the mean, with a 90% interval band
    expect(text).toContain('mean over time')
    expect(text).toContain('90% interval')
    // PMF section shows only the buckets (no mean/interval rows mixed in)
    expect(text).toContain('outcome buckets (PMF)')
    expect(text).toContain('bucket_4_2')
    expect(text).not.toContain('interval_90_high')
    expect(text).toContain('█')
    expect(text).toContain('missing decision_owner')
  })

  it('the per-tab list shows a compact μ label for distribution forecasts', async () => {
    // The CPI distribution forecast is the inflation thesis's member, so the
    // default (first) lens tab lists it and its μ label renders in the row.
    const text = await renderWorkspace(120, thesisFixture())
    expect(text).toContain('μ4.23%')
  })

  it('shows an empty state when there are no active forecasts', async () => {
    const text = await renderWorkspace(120, {
      active_count: 0,
      closing_soon_count: 0,
      forecasts: [],
      open_alert_count: 0
    })

    expect(text).toContain('No active forecasts')
  })

  it('renders the analyst quick read with headline, labeled angles, and wrapped body', async () => {
    const [{ renderSync }, { AnalystNote }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const note = {
      as_of: '2026-06-01T00:00:00Z',
      be_aware: 'The poll lead is early and not fully independent of prior evidence.',
      body: '',
      headline: 'Texas still leans Republican',
      how_it_feels: 'Comfortable around 59 percent, with room for the number to drift.',
      how_it_thinks: 'Fundamentals and the outside view both favor the Republican here.',
      kind: 'brief' as const,
      looking_for: 'A clean independent poll that confirms or breaks the Talarico signal.',
      stance: 'lean_yes' as const
    }

    const stdout = writeStream(120, 60)
    renderSync(React.createElement(AnalystNote, { note, t: DARK_THEME, variant: 'quickread' }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('QUICK READ')
    expect(text).toContain('Texas still leans Republican')
    expect(text).toContain('how it feels')
    expect(text).toContain('watching for')
    expect(text).toContain('be aware')
    expect(text).toContain('lean yes')
    expect(text).toContain('Comfortable around 59 percent')
  })

  it('suppresses the ambiguous stance chip when showStance is false (distribution forecasts)', async () => {
    const [{ renderSync }, { AnalystNote }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const note = {
      as_of: '2026-06-01T00:00:00Z',
      headline: 'May CPI still looks like a 4.2 or 4.3 print',
      how_it_feels: 'A fairly comfortable number, not a heroic one.',
      kind: 'brief' as const,
      stance: 'lean_no' as const
    }

    const stdout = writeStream(120, 60)
    renderSync(
      React.createElement(AnalystNote, { note, showStance: false, t: DARK_THEME, variant: 'quickread' }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('QUICK READ')
    expect(text).toContain('May CPI still looks like')
    // The yes/no stance is meaningless for a distribution question, so it is hidden.
    expect(text).not.toContain('lean no')
  })

  it('renders a resolved retrospective with its verdict', async () => {
    const [{ renderSync }, { AnalystNote }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const note = {
      as_of: '2026-11-04T00:00:00Z',
      body: 'It landed close.\n\nThe fundamentals held but the margin was tighter than the model implied.',
      headline: 'Right call, thin margin',
      kind: 'retrospective' as const,
      verdict: 'close' as const
    }

    const stdout = writeStream(120, 60)
    renderSync(React.createElement(AnalystNote, { note, t: DARK_THEME, variant: 'retrospective' }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('RETROSPECTIVE')
    expect(text).toContain('close')
    expect(text).toContain('Right call, thin margin')
    // No discrete angle fields: falls back to the body paragraphs.
    expect(text).toContain('It landed close')
    expect(text).toContain('tighter than the model implied')
  })

  it('renders related forecasts with relationship tags and the shared-source flag', async () => {
    const [{ renderSync }, { RelatedForecasts }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const related = {
      forecasts: [
        {
          as_of: '2026-06-01T00:00:00Z',
          headline_kind: 'probability' as const,
          id: 'fq_cpi_yoy',
          link_type: 'auto' as const,
          note_headline: 'CPI tracking around 4.2',
          probability_display: '61%',
          relationship: 'correlated_sibling' as const,
          title: 'CPI YoY May 2026?'
        }
      ],
      informed_by: ['fq_cpi_yoy'],
      shared_sources: [{ kind: 'watched_source', shared_with: [], source: 'fred:GASREGW' }]
    }

    const stdout = writeStream(120, 60)
    renderSync(React.createElement(RelatedForecasts, { related, t: DARK_THEME, width: 70 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('related forecasts')
    expect(text).toContain('sibling')
    expect(text).toContain('CPI YoY May 2026?')
    expect(text).toContain('61%')
    expect(text).toContain('CPI tracking around 4.2')
    // independence heads-up, never merged
    expect(text).toContain('shares fred:GASREGW')
    expect(text).toContain('possibly non-independent')
  })

  it('renders the thesis as the leading lens tab with its member forecasts listed', async () => {
    const text = await renderWorkspace(120, thesisFixture())
    // The thesis is the first (active) lens tab (label truncated by the strip) AND
    // now the pinned ◆ leading table row — both truncate the title, so assert the
    // shared visible prefix — ahead of the tag tabs and the catch-all All tab.
    expect(text).toContain('Inflation stays')
    expect(text).toContain('◆')
    expect(text).toContain('All')
    // Its member forecast (CPI) renders in the active-tab list with its μ label.
    // The dense QUESTION column truncates the title, so assert the visible prefix.
    expect(text).toContain('May 2026')
    expect(text).toContain('μ4.23%')
  })

  it('renders the thesis read with health trend, aggregate stats, members, and caveats', async () => {
    const [{ renderSync }, { ThesisDeskRead }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 80)
    renderSync(React.createElement(ThesisDeskRead, { t: DARK_THEME, thesis: inflationThesis(), width: 80 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('Inflation stays sticky through 2026')
    // health trend + delta in pp
    expect(text).toContain('health over time')
    expect(text).toContain('▼ 4pp')
    // aggregate stats — health is the alive PROBABILITY, score is the 0–100
    // STRENGTH index; the "/100" unit + the legend keep the two close 54-ish
    // numbers from reading as the same kind of value.
    expect(text).toContain('aggregate')
    expect(text).toContain('54%') // health (probability)
    expect(text).toContain('54/100') // score (strength index, distinct unit)
    expect(text).toContain('strength index') // the disambiguating legend
    expect(text).toContain('41 – 67') // score band
    expect(text).toContain('coverage')
    expect(text).toContain('n_eff')
    // analyst note
    expect(text).toContain('Disinflation is stalling near 4%')
    // member contribution table: direction, belief, signal, contribution
    expect(text).toContain('member contributions')
    expect(text).toContain('↑supp')
    expect(text).toContain('↓risk')
    expect(text).toContain('μ4.23%')
    expect(text).toContain('+12.4')
    // uncertainty caveat with rho / n_eff
    expect(text).toContain('caveats')
    expect(text).toContain('co-move')
    expect(text).toContain('0.42')
  })

  it('renders the entity suitability table and trade triggers under the member contributions', async () => {
    const [{ renderSync }, { ThesisDeskRead }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 90)
    renderSync(React.createElement(ThesisDeskRead, { t: DARK_THEME, thesis: inflationThesis(), width: 90 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    // §22 per-name suitability table, sorted by suitability desc.
    expect(text).toContain('ENTITY SUITABILITY')
    expect(text).toContain('BE')
    expect(text).toContain('71%')
    expect(text).toContain('CORZ')
    expect(text).toContain('41%')
    // The best-suited name (BE, 71%) sorts above the marginal one (CORZ, 41%).
    expect(text.indexOf('BE')).toBeLessThan(text.indexOf('CORZ'))
    // signed delta in pp + the top driver.
    expect(text).toContain('▲25pp')
    expect(text).toContain('power-bottleneck rising')
    // A withheld entity (IREN) shows "withheld", never a fabricated number.
    expect(text).toContain('IREN')
    expect(text).toContain('withheld')
    // §10 trade triggers render their note verbatim.
    expect(text).toContain('TRADE TRIGGERS')
    expect(text).toContain('Power ▲ +25pp → BE, IREN better suited')
  })

  it('shows withheld (not a fake number) for a thesis with no health snapshot', async () => {
    const [{ renderSync }, { ThesisDeskRead }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const thesis = { ...inflationThesis(), health_display: undefined, health_probability: null }
    const stdout = writeStream(120, 80)
    renderSync(React.createElement(ThesisDeskRead, { t: DARK_THEME, thesis, width: 80 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('withheld')
  })

  it('renders the P(event) headline band for a joint-event thesis (the interval an all-binary thesis CAN publish)', async () => {
    const [{ renderSync }, mod, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const { ThesisDeskRead, thesisHealthBandPoints } = mod

    // A joint-threshold thesis (all-binary members): the mean-index score band is
    // withheld (no calibrated 0..1 dispersion), but the second-order MC publishes a
    // real interval ON the event headline. history points carry event_low/high.
    const thesis = {
      ...inflationThesis(),
      event_band: { p10: 0.31, p50: 0.35, p90: 0.4 },
      event_probability: 0.352,
      history: [
        { as_of: '2026-05-15T00:00:00Z', event_high: 0.42, event_low: 0.3, headline_probability: 0.34, headline_regime: 'event' },
        { as_of: '2026-05-22T00:00:00Z', event_high: 0.41, event_low: 0.31, headline_probability: 0.36, headline_regime: 'event' },
        { as_of: '2026-05-29T00:00:00Z', event_high: 0.4, event_low: 0.31, headline_probability: 0.352, headline_regime: 'event' }
      ],
      score_band: null // mean-index band honestly withheld for an all-binary thesis
    }

    // The trend band points come from the event interval, not a fabricated band.
    const points = thesisHealthBandPoints(thesis as never)
    expect(points[points.length - 1]).toEqual({ hi: 0.4, lo: 0.31, y: 0.352 })

    const stdout = writeStream(120, 80)
    renderSync(React.createElement(ThesisDeskRead, { t: DARK_THEME, thesis: thesis as never, width: 80 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    // The event headline + its 90% interval both surface (35% point, 31–40% band).
    expect(text).toContain('event %')
    expect(text).toContain('35%')
    expect(text).toContain('event band')
    expect(text).toContain('31% – 40%')
    // The mean-index score band is still honestly withheld (shows the em dash).
    expect(text).toContain('score band')
    // The caveat now explains the band propagates parameter uncertainty.
    expect(text).toContain('second-order MC')
  })

  it('caps the thesis dot-plot preview at ~15 dots and captions the thinning honestly (FIX 2)', async () => {
    const [{ renderSync }, mod, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const { ThesisDeskRead } = mod

    // 84 snapshots — the exact "dozens of dots in clumps" case the operator hit.
    const history = Array.from({ length: 84 }, (_, i) => ({
      as_of: new Date(Date.parse('2026-01-01T00:00:00Z') + i * 86_400_000).toISOString(),
      headline_probability: 0.3 + 0.2 * Math.sin(i / 4),
      headline_regime: 'event'
    }))

    const thesis = { ...inflationThesis(), event_band: null, history, score_band: null }

    const stdout = writeStream(120, 90)
    renderSync(React.createElement(ThesisDeskRead, { t: DARK_THEME, thesis: thesis as never, width: 90 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    // Honest caption: N of 84 shown, largest moves.
    expect(text).toContain('of 84 snapshots shown · largest moves')
    expect(text).toContain('15 of 84')
    // The drawn marker count never exceeds the cap (one ● per kept snapshot; the
    // chart squeezes columns but never draws more than 15 distinct dots).
    const markerCount = (text.match(/●/g) ?? []).length
    // headline legend also carries one ● — allow it, but the plot must be capped.
    expect(markerCount).toBeLessThanOrEqual(15 + 1)
  })

  it('does NOT surface a factor as a lens tab — its members fall into All', async () => {
    const text = await renderWorkspace(120, factorFixture())
    // Factors are no longer a lens (the desk navigates by real theses + All only),
    // so the factor label never appears in the tab strip…
    expect(text).not.toContain('Power-bottleneck bask')
    expect(text).toContain('All')
    // …and its former member forecast (Texas) simply renders under the All tab; the
    // dense QUESTION column truncates the long title, so assert the visible prefix.
    expect(text).toContain('Will the Rep')
  })

  it('renders the factor read with return trend, factor-return stats, constituents, and caveats', async () => {
    const [{ renderSync }, { FactorDeskRead }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 90)
    renderSync(React.createElement(FactorDeskRead, { factor: powerFactor(), t: DARK_THEME, width: 90 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('The power-bottleneck basket carries positive expected return')
    // return band trend over the factor history (mean + 90% band)
    expect(text).toContain('return over time')
    expect(text).toContain('●') // chart mean marker
    expect(text).toContain('90% band')
    // Factor Return aggregate stats
    expect(text).toContain('Factor Return')
    expect(text).toContain('vol σ')
    expect(text).toContain('downside')
    expect(text).toContain('CVaR')
    expect(text).toContain('coverage')
    expect(text).toContain('n_eff')
    // analyst note
    expect(text).toContain('long names dominate the basket')
    // CONSTITUENTS table: direction long/short, title, w_norm %, μ, σ, contribution
    expect(text).toContain('CONSTITUENTS')
    expect(text).toContain('long')
    expect(text).toContain('short')
    expect(text).toContain('Bloom Energy upside')
    expect(text).toContain('60%') // w_norm of the long leg
    expect(text).toContain('+6.2') // signed contribution
    // sorted by |contribution| desc: the long leg (|6.2|) leads the short hedge (|1.4|)
    expect(text.indexOf('Bloom Energy upside')).toBeLessThan(text.indexOf('Core Scientific hedge'))
    // uncertainty caveat names co-movement + n_eff
    expect(text).toContain('caveats')
    expect(text).toContain('co-move')
  })

  it('shows withheld (not a fake number) for a factor with no return snapshot', async () => {
    const [{ renderSync }, { FactorDeskRead }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const factor = { ...powerFactor(), mean: null }
    const stdout = writeStream(120, 90)
    renderSync(React.createElement(FactorDeskRead, { factor, t: DARK_THEME, width: 90 }), {
      exitOnCtrlC: false,
      patchConsole: false,
      stdout: stdout.stream
    } as never)
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('withheld')
  })

  it('renders the packet tail (history, model runs, action playbook) under the summary', async () => {
    const { sections, text } = await renderTail({
      assumptions: [{ id: 'asm_1', status: 'active', text: 'Polling response rates hold near 2024 levels.' }],
      forecast_history: [
        {
          as_of: '2026-05-20T00:00:00Z',
          confidence: 0.6,
          forecast_id: 'fc_a',
          method: 'panel',
          probability_or_distribution: 0.55,
          rationale: 'Initial estimate after first evidence sweep.'
        },
        {
          as_of: '2026-05-27T00:00:00Z',
          confidence: 0.62,
          forecast_id: 'fc_b',
          method: 'panel',
          probability_or_distribution: 0.58,
          rationale: 'Nudged up after the FEC filing widened the fundraising gap.'
        }
      ],
      model_runs: [{ created_at: '2026-05-26T00:00:00Z', id: 'mr_1', model_type: 'gpt', summary: 'Ensemble agreed with the panel.' }],
      question: { close_time: '2026-11-03T00:00:00Z', id: 'fq_tail', status: 'active', title: 'Tail test forecast' }
    })

    // The tail builder must surface exactly the long-form sections the desk omits.
    expect(sections.map(s => s.title)).toEqual(['Forecast History', 'Assumptions And References', 'Model Runs', 'Actions'])
    // Section labels render…
    expect(text).toContain('Forecast History')
    expect(text).toContain('Model Runs')
    expect(text).toContain('Actions')
    // …with their long-form content…
    expect(text).toContain('fundraising gap')
    expect(text).toContain('Ensemble agreed')
    expect(text).toContain('Polling response rates')
    // …and the action playbook is keyed to the question id, read-only.
    expect(text).toContain('/revise fq_tail')
    expect(text).toContain('/forecast research fq_tail')
  })
})

// ── Tail audit + ensemble components + causal paths (the new desk surfaces) ──

const failingAudit = (): ForecastTailAudit => ({
  issues: ['1.7% of probability is unearned tail mass'],
  null_model: {
    agent_tail: 0.04,
    null_tail: 0.006,
    ratio: 6.7,
    within_tolerance: false
  },
  outcomes: [
    { classification: 'live', evidence_strength: 'strong', has_path: true, name: 'Abbott', path: 'leads polls', probability: 0.62, unearned: false },
    { classification: 'live_ish', evidence_strength: 'mixed', has_path: true, name: 'Allred', path: 'ad spend', probability: 0.34, unearned: false },
    { classification: 'unpriced', evidence_strength: 'none', has_path: false, name: 'Conway', path: '', probability: 0.017, unearned: true },
    { classification: 'residual', has_path: false, name: 'Other', path: '', probability: 0.023, unearned: false }
  ],
  passes: false,
  residual_cap: 0.05,
  threshold: 0.005,
  total_mass: 1,
  unearned_mass: 0.017
})

const renderDetailProps = async (
  props: Record<string, unknown>,
  width = 90
) => {
  const [{ renderSync }, { ForecastDetail }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@superforecasting/ink'),
    import('../components/forecastsWorkspace.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(140, 70)
  renderSync(React.createElement(ForecastDetail, { t: DARK_THEME, width, ...props } as never), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdout: stdout.stream
  } as never)

  return normalize(stdout.text(), stripAnsi)
}

describe('forecasts workspace tail audit + ensemble', () => {
  it('renders the Tail Audit section with the probability-mass table, headline, and null model', async () => {
    const text = await renderDetailProps({ item: texasItem(), tailAudit: failingAudit() })
    expect(text).toContain('Tail Audit')
    expect(text).toContain('FAIL')
    // The probability-mass table: outcome name, classification, and the unearned offender.
    expect(text).toContain('Abbott')
    expect(text).toContain('Conway')
    expect(text).toContain('unpriced')
    // The unearned-mass headline (1.7% over the 0.5% threshold).
    expect(text).toContain('unearned tail mass 1.7%')
    // The null-model comparison line.
    expect(text).toContain('no-path tail 4%')
    expect(text).toContain('simple-null')
    expect(text).toContain('6.7x')
  })

  it('omits the Tail Audit section entirely when no audit is present (honest empty state)', async () => {
    const text = await renderDetailProps({ item: texasItem(), tailAudit: null })
    expect(text).not.toContain('Tail Audit')
  })

  it('renders pooled ensemble components with weights and flags a discounted thin market', async () => {
    const rows = [
      { name: 'outside view', probability: 0.5, source: 'reference_class', weight: 1.0 },
      { name: 'kalshi market', probability: 0.58, source: 'kalshi:tx-senate', weight: 0.2 },
      { name: 'liquid market', probability: 0.54, source: 'polymarket:tx-senate', weight: 1.0 }
    ]

    const text = await renderDetailProps({ ensembleRows: rows, item: texasItem() })
    expect(text).toContain('ensemble components (3)')
    expect(text).toContain('kalshi market')
    expect(text).toContain('w 0.20')
    // The thin kalshi market (weight 0.2 vs a liquid 1.0) is hinted as discounted.
    expect(text).toContain('discounted')
  })

  it('colours the unearned outcome row and the headline as a finding (not buried)', async () => {
    // The unearned Conway row and the unearned-mass headline both render; the
    // ! glyph marks the offender so it reads as a flag, not steady state.
    const text = await renderDetailProps({ item: texasItem(), tailAudit: failingAudit() })
    expect(text).toContain('! Conway')
    expect(text).toContain('owes an explanation') // null-model out-of-tolerance note
  })
})

// The operator's Clacton critique — the detail chart was plotting a SINGLE generic
// scalar with the binary panel band mixed in and a negative axis. These assert the
// distribution-aware rebuild: multi-series, [0,…] axis, honest leader header, no band.
describe('distribution-aware vote-share detail', () => {
  it('draws a MULTI-SERIES vote-share chart (leader distinct) with a non-negative axis', async () => {
    const text = await renderDetail(clactonItem(), 80)
    // The chart is now a dedicated multi-candidate series, not "probability over time".
    expect(text).toContain('vote share over time')
    expect(text).not.toContain('probability over time')
    // The leader (Farage, ●) is legended distinctly ahead of the other candidates.
    expect(text).toContain('● Farage')
    expect(text).toContain('◆') // a second, distinct series marker
    expect(text).toContain('Binface')

    // Every y-axis gutter label is >= 0 — a vote share is never negative (the bug).
    const axisNums = text
      .split('\n')
      .filter(line => line.includes('│'))
      .map(line => Number.parseFloat(line.split('│')[0]!.trim()))
      .filter(n => Number.isFinite(n))

    expect(axisNums.length).toBeGreaterThan(0)

    for (const n of axisNums) {
      expect(n).toBeGreaterThanOrEqual(0)
    }
  })

  it('NEVER renders the binary panel-spread band or panel section on a vote-share question', async () => {
    // clactonItem carries a probability-scale `panel`; it must be gated off entirely.
    const text = await renderDetail(clactonItem(), 80)
    expect(text).not.toContain('panel spread')
    expect(text).not.toContain('confidence band')
    expect(text).not.toContain('panel (') // the PanelSection header
    // No band glyph WITHIN the chart (the histogram below legitimately uses ░ for
    // unfilled bar track, so scope the check to the chart block).
    const lines = text.split('\n')
    const start = lines.findIndex(line => line.includes('vote share over time'))
    const end = lines.findIndex((line, i) => i > start && line.includes('outcome distribution'))
    expect(lines.slice(start, end).join('\n')).not.toContain('░')
  })

  it('headers the LEADER + its real interval, or an honest "no interval published"', async () => {
    // With per-candidate intervals present: the leader value + its 90% band render.
    const withIv = await renderDetail(clactonItem({ intervals: true }), 80)
    expect(withIv).toContain('leader Nigel Farage 67.0')
    expect(withIv).toContain('90% [55.0–78.0]')
    expect(withIv).not.toContain('no interval published')
    // Without them: the leader value stands, and the missing band is stated honestly
    // — never a fabricated one.
    const noIv = await renderDetail(clactonItem({ intervals: false }), 80)
    expect(noIv).toContain('leader Nigel Farage 67.0')
    expect(noIv).toContain('no interval published')
  })

  it('keeps the per-candidate bars section below the chart', async () => {
    const text = await renderDetail(clactonItem(), 80)
    expect(text).toContain('outcome distribution')
    expect(text).toContain('Nigel Farage')
    expect(text).toContain('█') // the histogram bar fill
  })

  it('leaves a binary question (scalar probability + PMF breakdown) unchanged', async () => {
    // texasItem is binary: its `probability` is a SCALAR 0.52 even though it also
    // ships a 3-way candidate PMF — it must NOT be mistaken for a vote share.
    const text = await renderDetail(texasItem(), 80)
    expect(text).toContain('probability over time')
    expect(text).not.toContain('vote share over time')
    expect(text).not.toContain('leader ')
    expect(text).toContain('panel (3 perspectives)') // the binary panel still renders
  })

  it('leaves a continuous distribution (CPI mean/sd) unchanged', async () => {
    const text = await renderDetail(cpiItem(), 80)
    expect(text).toContain('mean over time')
    expect(text).not.toContain('vote share over time')
    expect(text).not.toContain('leader ')
  })
})

// The operator's screenshot critique — the modal has room, so informational text
// WRAPS; truncation is for dense tables only. These assert the four exhibits.
describe('question-detail modal formatting law', () => {
  const countOf = (haystack: string, needle: string): number => haystack.split(needle).length - 1

  it('renders the question title ONCE, wrapping instead of truncating the tail', async () => {
    const item = texasItem()
    item.title = 'Will the Republican candidate win the United States Senate election in Mississippi in 2026 ULTRAWRAPTAIL'
    const text = await renderDetail(item, 60)
    // The full title survives (tail token present → it wrapped, was not cut with '…')...
    expect(text).toContain('ULTRAWRAPTAIL')
    expect(text).toContain('Mississippi')
    // ...and the body renders the title exactly once (no duplicate header line).
    expect(countOf(text, 'ULTRAWRAPTAIL')).toBe(1)
  })

  it('draws a real x-axis with deduped tick labels across the snapshot range', async () => {
    const text = await renderDetail(texasItem(), 70)
    expect(text).toContain('probability over time')
    // Both ends of the real time range are labelled (the axis label line carries
    // the first snapshot; the deduping itself is covered by the timeAxis unit test).
    const axisLine = text.split('\n').find(line => line.includes('2026-05-01'))!
    expect(axisLine).toContain('2026-05-01')
    expect(axisLine).toContain('2026-05-29')
    expect(countOf(axisLine, '2026-05-29')).toBe(1)
    // ...with real tick structure, and NOT the old degenerate "date → date" line.
    expect(text).toContain('┬')
    expect(text).not.toContain('2026-05-01 → 2026-05-29')
  })

  it('labels a single-snapshot chart ONCE (degenerate x-axis)', async () => {
    const item = texasItem()
    item.history = [{ as_of: '2026-06-22T00:00:00Z', band_low: null, confidence: 0.6, headline_probability: 0.52 }]
    const text = await renderDetail(item, 70)
    expect(countOf(text, '2026-06-22')).toBe(1)
  })

  it('renders ensemble components on two lines with the FULL source slug (never truncated)', async () => {
    const rows = [
      { name: 'partisan_baseline_outside_view_reference', probability: 0.5, source: 'reference_class:2024-baseline', weight: 1.0 },
      { name: 'kalshi market', probability: 0.58, source: 'kalshi:tx-senate-2026-general-election', weight: 0.2 },
      { name: 'liquid market', probability: 0.54, source: 'polymarket:tx-senate', weight: 1.0 }
    ]

    const text = await renderDetailProps({ ensembleRows: rows, item: texasItem() })
    expect(text).toContain('ensemble components (3)')
    // Full slugs, in full — the old truncate(…, 20) would have cut all three.
    expect(text).toContain('reference_class:2024-baseline')
    expect(text).toContain('kalshi:tx-senate-2026-general-election')
    expect(text).toContain('polymarket:tx-senate')
    // A long component name survives in full (wrapped, not '…').
    expect(text).toContain('partisan_baseline_outside_view_reference')
    expect(text).toContain('w 0.20')
    // No truncation WITHIN the ensemble section (the dense histogram above it may
    // still abbreviate its own bucket labels — that's the table exception).
    const lines = text.split('\n')
    const start = lines.findIndex(line => line.includes('ensemble components (3)'))
    const end = lines.findIndex((line, i) => i > start && line.includes('panel ('))
    expect(lines.slice(start, end).join('\n')).not.toContain('…')
  })

  it('aligns the panel grid — value column and ±pt end column share one column across all rows', async () => {
    const text = await renderDetail(texasItem(), 70)
    const lines = text.split('\n')
    const start = lines.findIndex(line => line.includes('panel (3 perspectives)'))
    const end = lines.findIndex((line, i) => i > start && line.includes('trimmed mean'))
    expect(start).toBeGreaterThanOrEqual(0)
    expect(end).toBeGreaterThan(start)
    const panelLines = lines.slice(start + 1, end)

    // Every row carrying a percent value (aggregate / range / each perspective)
    // right-aligns it in the SAME value column.
    const pctCols = panelLines.filter(line => /\d%/.test(line)).map(line => line.indexOf('%'))
    expect(pctCols.length).toBeGreaterThanOrEqual(4)
    expect(new Set(pctCols).size).toBe(1)

    // The ±pt delta markers land in the same fixed end column across perspectives.
    const deltaCols = panelLines.filter(line => /[+-]\d+pt/.test(line)).map(line => line.indexOf('pt'))
    expect(deltaCols.length).toBe(3)
    expect(new Set(deltaCols).size).toBe(1)

    // No perspective name is cut with an ellipsis.
    expect(panelLines.join('\n')).not.toContain('…')
  })
})

it('renders typed censored resolutions in the actual narrow detail pane', async () => {
  const item = { ...cpiItem(), resolution: {
    outcome: { kind: 'right_censored', lower_bound: 6, inclusive: true, units: 'days', observed_through: '2026-09-10T12:00:00Z' },
    resolution_status: 'confirmed'
  }} as unknown as ForecastWorkspaceItem

  const text = await renderDetail(item, 50)
  expect(text).toContain('At least 6 days')
  expect(text).toContain('right-censored')
  expect(text.replace(/\s+/g, ' ')).toContain('exact outcome remains unknown')
  expect(text).not.toContain('[object Object]')
})


it('renders verified measurement limits in the shared packet tail', async () => {
  const { text } = await renderTail({ question: { id: 'fq_source', title: 'Measurement' },
    applicability_facts: { temperature: { status: 'verified', value: 24, units: 'wmoUnit:degC',
      entity: 'KJFK', observation_period: 'instant', observed_at: '2026-09-11T07:05:00Z' } } }, 50)

  expect(text).toContain('Source Conditions')
  expect(text).toContain('24 °C')
  expect(text).toContain('KJFK')
  expect(text.replace(/\s+/g, ' ')).toContain('daily maximum unconfirmed')
})
