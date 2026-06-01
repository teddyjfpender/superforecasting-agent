import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ForecastWorkspaceItem, ForecastWorkspaceResponse } from '../gatewayTypes.js'

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

const fixture = (): ForecastWorkspaceResponse => ({
  active_count: 2,
  closing_soon_count: 0,
  forecasts: [texasItem(), cpiItem()],
  generated_at: '2026-05-29T14:00:00Z',
  open_alert_count: 13,
  product: 'Superforecasting Agent'
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

const renderWorkspace = async (columns: number, response: ForecastWorkspaceResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const [{ render }, { ForecastsWorkspace }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/forecastsWorkspace.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const fakeGw = {
    request: (_method: string, _params: Record<string, unknown>) => Promise.resolve(response)
  } as unknown as Parameters<typeof ForecastsWorkspace>[0]['gw']

  const instance = render(
    React.createElement(ForecastsWorkspace, { gw: fakeGw, onClose: () => undefined, t: DARK_THEME }),
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
    import('@hermes/ink'),
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
const TAIL_TITLES = new Set(['Forecast History', 'Assumptions And References', 'Model Runs', 'Actions'])
const renderTail = async (packet: Record<string, unknown>, width = 70) => {
  const [{ renderSync }, { ForecastPacketTail }, { forecastQuestionDetailSections }, { DARK_THEME }, { stripAnsi }] =
    await Promise.all([
      import('@hermes/ink'),
      import('../components/forecastsWorkspace.js'),
      import('../app/forecastPanel.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])
  const sections = forecastQuestionDetailSections({ packet } as never).filter(
    section => section.title && TAIL_TITLES.has(section.title)
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
  let mod: typeof import('../components/forecastsWorkspace.js')

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
  })

  it('historyToBandPoints derives a confidence band and uses panel spread for the latest', async () => {
    const { historyToBandPoints } = await import('../components/forecastsWorkspace.js')
    const points = historyToBandPoints(texasItem())
    expect(points).toHaveLength(3)
    // earlier points: confidence-derived band straddles y
    expect(points[0]!.lo).toBeLessThan(points[0]!.y as number)
    expect(points[0]!.hi).toBeGreaterThan(points[0]!.y as number)
    // latest point uses the panel spread (min 0.42 / max 0.58)
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
})

describe('ForecastsWorkspace render', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the master list with counts and forecast rows', async () => {
    const text = await renderWorkspace(120, fixture())
    expect(text).toContain('FORECASTS')
    expect(text).toContain('2 active')
    expect(text).toContain('13 open alert')
    // master list shows both forecasts
    expect(text).toContain('Texas Senate')
    expect(text).toContain('CPI-U YoY')
    // footer hints are present
    expect(text).toContain('focus detail')
  })

  it('renders the detail pane with charts, panel, reasoning, and decision card', async () => {
    const text = await renderDetail(texasItem())
    expect(text).toContain('Will the Republican win the Texas Senate seat?')
    expect(text).toContain('probability over time')
    expect(text).toContain('●') // chart marker
    expect(text).toContain('panel')
    expect(text).toContain('aggregate')
    expect(text).toContain('reasoning')
    expect(text).toContain('turnout model') // reasons_up
    expect(text).toContain('decision card')
    expect(text).toContain('Desk lead')
    expect(text).toContain('recent evidence')
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

  it('master list shows a compact μ label for distribution forecasts', async () => {
    const text = await renderWorkspace(120, fixture())
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
