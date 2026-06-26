import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type {
  ForecastFactor,
  ForecastThesis,
  ForecastWorkspaceItem,
  ForecastWorkspaceResponse
} from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const texasItem = (): ForecastWorkspaceItem => ({
  analyst_notes: [
    {
      as_of: '2026-05-29T00:00:00Z',
      headline: 'Texas still leans Republican',
      how_it_thinks: 'Fundamentals and the outside view both favor the Republican here.',
      kind: 'brief'
    }
  ],
  as_of: '2026-05-29T00:00:00Z',
  close_time: '2026-11-03T00:00:00Z',
  confidence: 0.65,
  delta: 0.02,
  domain: 'us-politics',
  evidence: [
    { available_at: '2026-05-28T00:00:00Z', claim: 'FEC filing', id: 'ev_1', source: 'https://www.fec.gov/data', stance: 'increases' }
  ],
  evidence_count: 1,
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.52,
  history: [
    { as_of: '2026-05-01T00:00:00Z', headline_probability: 0.55 },
    { as_of: '2026-05-29T00:00:00Z', headline_probability: 0.52 }
  ],
  id: 'fq_texas',
  impact: 'high',
  open_alert_count: 13,
  probability: 0.52,
  probability_display: '0.520',
  reasons_up: ['turnout model'],
  resolution_criteria: 'Official certified 2026 Texas US Senate result names the Republican winner.',
  snapshot_count: 3,
  status: 'active',
  title: 'Will the Republican win the Texas Senate seat?',
  topics: ['elections', 'senate']
})

const cpiItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-05-28T00:00:00Z',
  delta: 0.006,
  distribution: { mean: 4.232, sd: 0.098 },
  headline_kind: 'distribution',
  headline_probability: 4.232,
  history: [{ as_of: '2026-05-28T00:00:00Z', headline_probability: 4.232 }],
  id: 'fq_cpi',
  snapshot_count: 10,
  status: 'active',
  title: 'May 2026 CPI-U YoY',
  topics: ['inflation'],
  units: 'percent year-over-year'
})

const inflationThesis = (): ForecastThesis => ({
  as_of: '2026-05-29T00:00:00Z',
  domain: 'macro',
  health_display: '54%',
  health_probability: 0.54,
  id: 'th_inflation',
  member_count: 1,
  question_ids: ['fq_cpi'],
  status: 'active',
  thesis_score: 54,
  title: 'Inflation stays sticky through 2026',
  topics: ['inflation', 'macro']
})

const powerFactor = (): ForecastFactor => ({
  as_of: '2026-05-29T00:00:00Z',
  domain: 'energy',
  id: 'fx_power',
  mean: 4.7,
  member_count: 0,
  question_ids: [],
  title: 'Power-bottleneck basket',
  units: 'percent return',
  volatility: 2.7
})

const fixture = (): ForecastWorkspaceResponse => ({
  active_count: 2,
  closing_soon_count: 0,
  factors: [powerFactor()],
  forecasts: [texasItem(), cpiItem()],
  generated_at: '2026-05-29T14:00:00Z',
  open_alert_count: 13,
  product: 'Superforecasting Agent',
  theses: [inflationThesis()]
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

const fakeGw = (response: ForecastWorkspaceResponse) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      if (method === 'forecast.question') {
        // A minimal packet so the modal's async tail resolves without throwing.
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }

      return Promise.resolve(response)
    }
  }) as never

const mountDesk = async (columns: number, response: ForecastWorkspaceResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { DeskView }, { DARK_THEME }, { stripAnsi }, { clearOverlayCache }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/deskView.js'),
    import('../theme.js'),
    import('../lib/text.js'),
    import('../lib/overlayCache.js')
  ])

  clearOverlayCache()
  const stdout = writeStream(columns, 40)
  const stdin = writeStream(columns, 40, true)

  const instance = render(
    React.createElement(DeskView, { gw: fakeGw(response), onClose: () => undefined, t: DARK_THEME }),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(60)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(60)
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('DeskView (redesigned forecast desk)', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the header counts and the horizontal lens tabs (theses → factors → tags → All)', async () => {
    const desk = await mountDesk(120, fixture())
    const text = desk.text()
    expect(text).toContain('FORECASTS')
    expect(text).toContain('2 active')
    expect(text).toContain('13 open alert')
    // Lens tab strip: short labels (kind-noise stripped, stopwords dropped) so the
    // strip stays on one line — "Inflation stays sticky through 2026" -> "Inflation
    // stays", "Power-bottleneck basket" -> "Power-bottleneck".
    expect(text).toContain('Inflation stays')
    expect(text).toContain('Power-bottleneck')
    expect(text).toContain('All')
    desk.cleanup()
  })

  it('shows the per-tab forecast list and a footer shortcuts bar', async () => {
    const desk = await mountDesk(120, fixture())
    const text = desk.text()
    // The first (thesis) tab is active → its member forecast renders in the list.
    expect(text).toContain('CPI-U YoY')
    // Footer chips.
    expect(text).toContain('Lens')
    expect(text).toContain('Open')
    expect(text).toContain('Filter')
    desk.cleanup()
  })

  it('renders the dense column-table header and per-row numeric columns', async () => {
    const desk = await mountDesk(120, fixture())
    // Move to the All tab so both forecasts are listed.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    const text = desk.text()
    // The bold header row names the dense columns (mirrors the Markets table).
    expect(text).toContain('QUESTION')
    expect(text).toContain('PROB')
    expect(text).toContain('1W')
    expect(text).toContain('1MO')
    expect(text).toContain('EV')
    expect(text).toContain('AGE')
    // The '─' rule under the header.
    expect(text).toContain('───')
    // A binary row carries its compact probability + an evidence count; a
    // distribution row shows its μ headline and never a fake percent in CHG.
    expect(text).toContain('52%')
    expect(text).toContain('μ4.23%')
    desk.cleanup()
  })

  it('leads a thesis tab with a clickable lens row that opens the aggregate read', async () => {
    const desk = await mountDesk(120, fixture())
    // The thesis tab is active by default → a lens row leads the section with the
    // thesis glyph + its aggregate (health/score) + the open affordance.
    let text = desk.text()
    expect(text).toContain('◆')
    expect(text).toContain('health 54%')
    expect(text).toContain('⏎ lens')
    // The cursor starts on the lens row → Enter opens the thesis aggregate modal,
    // which paints ABOVE the body (overlay): the full thesis title appears in the
    // modal (the lens row truncates it) while the desk header stays visible behind.
    await desk.press('\r')
    text = desk.text()
    expect(text).toContain('FORECASTS') // body still rendered behind the overlay
    expect(text).toContain('Inflation stays sticky through 2026')
    desk.cleanup()
  })

  it('Tab switches the lens and resets the selection (All tab shows the whole book)', async () => {
    const desk = await mountDesk(120, fixture())
    // Tabs: [thesis, factor, #elections, All]. Three Tabs from the first → All.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    const text = desk.text()
    // The All lens shows every forecast. The dense QUESTION column truncates a
    // long title to fit, so assert the visible prefix (the CPI title fits whole).
    expect(text).toContain('Will the Republican win')
    expect(text).toContain('CPI-U YoY')
    desk.cleanup()
  })

  it('Enter opens the full-detail modal for the selected forecast', async () => {
    const desk = await mountDesk(120, fixture())
    // Move to the All tab so a concrete forecast is selected, then open it.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\r')
    const text = desk.text()
    // The modal paints ABOVE the body (overlay, not a replacement): the desk header
    // stays present AND the modal shows the FULL forecast title (the list row
    // truncates it, so the full string is modal-unique) + its detail.
    expect(text).toContain('FORECASTS') // body still rendered behind the overlay
    expect(text).toContain('Will the Republican win the Texas Senate seat?')
    expect(text).toContain('P 52%')
    desk.cleanup()
  })

  it('/ opens the inline filter and narrows the visible list', async () => {
    const desk = await mountDesk(120, fixture())
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t') // All tab — holds both forecasts
    await desk.press('/')
    await desk.press('texas')
    const text = desk.text()
    // Filter bar reflects the query; the matching forecast survives (the dense
    // QUESTION column truncates the long title, so assert the visible prefix).
    expect(text).toContain('⌕')
    expect(text).toContain('Will the Republican win')
    // The header match count proves the list narrowed to just the one match
    // (the cumulative stdout buffer keeps earlier frames, so we assert the
    // live match indicator rather than the absence of the filtered-out row).
    expect(text).toContain('1 matches')
    desk.cleanup()
  })

  it('shows an empty state when there are no active forecasts', async () => {
    const desk = await mountDesk(120, {
      active_count: 0,
      closing_soon_count: 0,
      forecasts: [],
      open_alert_count: 0
    })

    expect(desk.text()).toContain('No active forecasts')
    desk.cleanup()
  })

  // The skinny summary panel is rendered directly (explicit width) so the
  // assertion does not depend on a headless terminal's side-by-side flex
  // measurement (unreliable outside a real TTY).
  it('skinny summary leads with the thesis aggregate, then prob/delta/counts and the analyst teaser', async () => {
    const [{ renderSync }, { DeskSummary }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const item = texasItem()
    const stdout = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: item.analyst_notes?.[0] ?? null,
        refFactor: undefined,
        refThesis: inflationThesis(),
        selected: item,
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    // Lens-aggregate header (thesis health/score) heads the panel.
    expect(text).toContain('health')
    expect(text).toContain('54%')
    // The selected forecast's compact headline + counts.
    expect(text).toContain('52%')
    expect(text).toContain('panel')
    expect(text).toContain('ev 1')
    // The 1-line analyst teaser.
    expect(text).toContain('Texas still leans Republican')
    // The open-detail affordance.
    expect(text).toContain('open full detail')
  })

  it('skinny summary leads with the factor μ aggregate on a factor lens tab', async () => {
    const [{ renderSync }, { DeskSummary }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: null,
        refFactor: powerFactor(),
        refThesis: undefined,
        selected: cpiItem(),
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('Power-bottleneck basket')
    expect(text).toContain('μ')
    expect(text).toContain('4.7')
    expect(text).toContain('vol σ')
  })

  it('skinny summary gives the LENS ROW its own aggregate + graph, not a blank panel', async () => {
    const [{ renderSync }, { DeskSummary }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const thesis = {
      ...inflationThesis(),
      analyst_note: { headline: 'Sticky services inflation keeps it elevated', kind: 'brief' },
      coverage: 0.8,
      delta: 0.03,
      history: [
        { as_of: '2026-05-01T00:00:00Z', headline_probability: 0.48 },
        { as_of: '2026-05-15T00:00:00Z', headline_probability: 0.51 },
        { as_of: '2026-05-29T00:00:00Z', headline_probability: 0.54 }
      ],
      n_eff: 3
    } as ForecastThesis

    const stdout = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: null,
        refFactor: undefined,
        refThesis: thesis,
        selected: null, // the lens row is what's selected
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).not.toContain('Select a forecast')
    expect(text).toContain('54%') // health aggregate
    expect(text).toContain('health over time') // the history graph
    expect(text).toContain('members 1')
    expect(text).toContain('Sticky services inflation') // analyst teaser
    expect(text).toContain('open full lens read')
  })
})
