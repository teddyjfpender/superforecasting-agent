import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { getOverlayState, resetOverlayState } from '../app/overlayStore.js'
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

// Dates relative to "now" so the NEXT column (which reads real Date.now(), not
// the payload's generated_at) renders a stable forward duration regardless of the
// wall-clock date the suite runs on. Fixed calendar dates here silently rot: once
// real time passes them they collapse to "now" and the assertions break.
const inDays = (n: number): string => new Date(Date.now() + n * 86400000).toISOString()

// A question with a LIVE scheduled review → the NEXT column must read its
// relative due-time exactly as before (no resolution-fallback marker).
const reviewedItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  close_time: inDays(180),
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.4,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.4 }],
  id: 'fq_reviewed',
  next_review_at: inDays(5),
  probability: 0.4,
  probability_display: '0.400',
  review_cadence: 'every 2 days',
  snapshot_count: 1,
  status: 'active',
  title: 'A scheduled-review question',
  topics: ['misc']
})

// A market_nightly live-edge market: deliberately NO re-forecast cadence (no
// next_review_at), but it DOES have a near resolution_time → NEXT must fall back
// to that date with the distinguishing "⤓" marker.
const nightlyItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  close_time: inDays(6),
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.6,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.6 }],
  id: 'fq_nightly',
  probability: 0.6,
  probability_display: '0.600',
  resolution_time: inDays(6),
  snapshot_count: 1,
  status: 'active',
  title: 'A market_nightly live-edge market',
  topics: ['market_nightly']
})

// Neither a scheduled review nor a resolution/close date → NEXT stays "—".
const orphanItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.3,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.3 }],
  id: 'fq_orphan',
  probability: 0.3,
  probability_display: '0.300',
  snapshot_count: 1,
  status: 'active',
  title: 'A question with no review and no dates',
  topics: ['misc']
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

// A single under-saturated forecast (Wave-3 saturation flag) with NO thesis/factor
// lens and no alerts — the first tab's row 0 is this concrete question, so keyboard
// actions (U update, R resolve, n new) target it directly.
const underSatItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  close_time: '2026-12-31T00:00:00Z',
  confidence: 0.6,
  delta: 0.01,
  domain: 'macro',
  evidence_count: 2,
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.44,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.44 }],
  id: 'fq_undersat',
  open_alert_count: 0,
  probability: 0.44,
  probability_display: '0.440',
  saturation_below_threshold: true,
  saturation_score: 42,
  snapshot_count: 2,
  status: 'active',
  title: 'Under-saturated forecast',
  topics: ['macro']
})

const plainFixture = (): ForecastWorkspaceResponse => ({
  active_count: 1,
  closing_soon_count: 0,
  forecasts: [underSatItem()],
  generated_at: '2026-06-29T14:00:00Z',
  open_alert_count: 0,
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

// A gw that RECORDS every request so tests can assert the RPC the desk fired
// (e.g. `U` → forecast.command refresh). Still resolves like fakeGw otherwise.
const recordingGw = (response: ForecastWorkspaceResponse, calls: { method: string; params: Record<string, unknown> }[]) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })

      if (method === 'forecast.question') {
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }

      return Promise.resolve(response)
    }
  }) as never

const mountDesk = async (columns: number, response: ForecastWorkspaceResponse, gwOverride?: unknown) => {
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
    React.createElement(DeskView, { gw: (gwOverride ?? fakeGw(response)) as never, onClose: () => undefined, t: DARK_THEME }),
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
    // The dense QUESTION column truncates the title, so assert the visible prefix.
    expect(text).toContain('CPI-U Y')
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
    // Health and score must read as DIFFERENT KINDS of number even though their
    // values are close: health carries "%", score carries "/100".
    expect(text).toContain('health 54%')
    expect(text).toContain('score 54/100')
    expect(text).toContain('⏎ lens')
    // The cursor starts on the lens row → Enter opens the thesis aggregate modal,
    // which paints ABOVE the body (overlay): the full thesis title appears in the
    // modal (the lens row truncates it) while the desk header stays visible behind.
    await desk.press('\r')
    text = desk.text()
    expect(text).toContain('FORECASTS') // body still rendered behind the overlay
    expect(text).toContain('Inflation stays sticky through 2026')
    // The INSPECTED item IS the thesis → the modal leads with the full thesis read.
    // Its domain·status·members header line is emitted ONLY by ThesisDeskRead (the
    // list/panel/tab-strip never print it), so it proves the thesis read is present
    // and ABOVE the modal fold.
    expect(text).toContain('macro · active · 1 member · inflation, macro')
    desk.cleanup()
  })

  it('a MEMBER question modal leads with the question detail — NOT the parent thesis read', async () => {
    const desk = await mountDesk(120, fixture())
    // Default thesis tab. Row 0 is the thesis lens; the cursor starts there. Move
    // DOWN onto row 1 — the member question (CPI-U) — then Enter to open it. A lens
    // is ACTIVE in the tab strip, but the INSPECTED item is a `forecast` member, so
    // the modal must NOT prepend the parent thesis read.
    await desk.press('j')
    await desk.press('\r')
    const text = desk.text()
    // The modal leads with the QUESTION's own detail (its full title heads the
    // overlay + the detail body).
    expect(text).toContain('May 2026 CPI-U YoY')
    // The thesis visual-summary block must be ABSENT. ThesisDeskRead's
    // domain·status·members header line is the read's first body row (above the
    // fold) and is emitted ONLY by that block — so its absence proves the parent
    // thesis read is NOT wrongly prepended above the member question's detail.
    expect(text).not.toContain('macro · active · 1 member · inflation, macro')
    expect(text).not.toContain('member contributions')
    desk.cleanup()
  })

  it('Tab switches the lens and resets the selection (All tab shows the whole book)', async () => {
    const desk = await mountDesk(120, fixture())
    // Tabs: [thesis, factor, #elections, All]. Three Tabs from the first → All.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    const text = desk.text()
    // The All lens shows every forecast. The dense QUESTION column truncates long
    // titles to fit, so assert the visible prefixes.
    expect(text).toContain('Will the Repub')
    expect(text).toContain('CPI-U Y')
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

  it('u re-arms the selected lens/forecast for the next cycle (honest flash + reforecast RPC)', async () => {
    const desk = await mountDesk(120, fixture())
    // Default thesis tab → the lens row is selected; u RE-ARMS the schedule (it does
    // NOT run a forecast) so the flash must say "re-armed", not "update".
    await desk.press('u')
    expect(desk.text()).toContain('re-armed for next cycle')
    desk.cleanup()
  })

  it('U runs a REAL update via forecast refresh (records the RPC + shows the updating flash)', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // plainFixture has no thesis/factor lens → the first tab's row 0 is a concrete
    // forecast, so U targets a real question id.
    const desk = await mountDesk(120, plainFixture(), recordingGw(plainFixture(), calls))
    await desk.press('U')
    // The in-process update runs `forecast refresh <id> --json` — the honest "real
    // update", distinct from `u`/re-arm which only marks the schedule due.
    const refresh = calls.find(c => c.method === 'forecast.command')
    expect(refresh).toBeDefined()
    expect(refresh?.params.argv).toEqual(['refresh', 'fq_undersat', '--json'])
    expect(desk.text()).toMatch(/updating|updated/)
    desk.cleanup()
  })

  it('n hands off to the new-question onboard modal (closes the desk overlay)', async () => {
    resetOverlayState()
    const desk = await mountDesk(120, plainFixture())
    await desk.press('n')
    expect(getOverlayState().onboard).toBe(true)
    expect(getOverlayState().forecasts).toBe(false)
    desk.cleanup()
    resetOverlayState()
  })

  it('R opens the detail modal for the selected forecast at the resolve/Actions tail', async () => {
    const desk = await mountDesk(120, plainFixture())
    await desk.press('R')
    const text = desk.text()
    // R opens the detail modal over the still-visible desk (its title = the
    // selected forecast); the resolve context now rides the modal's own footer
    // hint (visible in a real terminal, not this non-TTY harness) rather than the
    // old always-on prose shortcuts row, which was removed.
    expect(text).toContain('FORECASTS') // desk body still rendered behind the overlay
    expect(text).toContain('Under-saturated forecast')
    desk.cleanup()
  })

  it('marks an under-saturated forecast with the dim ◌ marker in the list', async () => {
    const desk = await mountDesk(120, plainFixture())
    // The Wave-3 saturation flag renders a trailing dim marker; a healthy forecast
    // (open_alert_count 0, above bar) would show nothing here.
    expect(desk.text()).toContain('◌')
    desk.cleanup()
  })

  it('skinny summary shows the under-saturated badge only when below the bar', async () => {
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
        refFactor: undefined,
        refThesis: undefined,
        selected: underSatItem(),
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('saturation 42/100')
    expect(text).toContain('below bar')

    // A healthy forecast (no saturation flag) shows NO badge.
    const healthy = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: null,
        refFactor: undefined,
        refThesis: undefined,
        selected: { ...underSatItem(), saturation_below_threshold: false, saturation_score: 88 },
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: healthy.stream } as never
    )
    expect(normalize(healthy.text(), stripAnsi)).not.toContain('below bar')
  })

  it('skinny summary shows the in-flight quorum chip only when a quorum_run is attached', async () => {
    const [{ renderSync }, { DeskSummary }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const running = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: null,
        refFactor: undefined,
        refThesis: undefined,
        selected: { ...underSatItem(), quorum_run: { run_id: 'qr_123', status: 'running' } },
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: running.stream } as never
    )
    expect(normalize(running.text(), stripAnsi)).toContain('quorum running')

    // No quorum_run attached → no chip.
    const idle = writeStream(120, 40)
    renderSync(
      React.createElement(DeskSummary, {
        latestNote: null,
        refFactor: undefined,
        refThesis: undefined,
        selected: underSatItem(),
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: idle.stream } as never
    )
    expect(normalize(idle.text(), stripAnsi)).not.toContain('quorum')
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
    expect(text).toContain('Will the Repub')
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
    // Lens-aggregate header (thesis health/score) heads the panel. Health is the
    // ALIVE probability ("54%") and score is the STRENGTH index ("54/100") — they
    // must read as visibly different kinds of number despite close values.
    expect(text).toContain('health')
    expect(text).toContain('54%')
    expect(text).toContain('54/100')
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
    expect(text).toContain('54%') // health aggregate (alive probability)
    expect(text).toContain('54/100') // score aggregate (strength index, distinct unit)
    expect(text).toContain('health over time') // the history graph
    expect(text).toContain('members 1')
    expect(text).toContain('Sticky services inflation') // analyst teaser
    expect(text).toContain('open full lens read')
  })

  it('o sorts the column (▲) and O toggles the direction (▼); the header carries the indicator', async () => {
    const desk = await mountDesk(120, fixture())
    // All tab holds the whole book so the dense column table + header render.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    // `o` sorts the first column (QUESTION) ascending → a ▲ indicator on the header.
    await desk.press('o')
    expect(desk.text()).toContain('QUESTION ▲')
    // `O` toggles to descending → the same column now shows ▼.
    await desk.press('O')
    expect(desk.text()).toContain('QUESTION ▼')
    desk.cleanup()
  })

  it('o cycles forward through the columns (QUESTION → PROB → …) in header order', async () => {
    const desk = await mountDesk(120, fixture())
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('o') // QUESTION
    await desk.press('o') // PROB (next in header order)
    expect(desk.text()).toContain('PROB ▲')
    desk.cleanup()
  })

  it('keeps the SELECTED forecast selected across a re-sort (tracks by id, not index)', async () => {
    const desk = await mountDesk(120, fixture())
    // All tab → rows are [texas ("Will…"), cpi ("May…")] in server order.
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t')
    // Put the cursor on row 1 — the CPI question.
    await desk.press('j')
    // Sort by QUESTION ascending → "May…"(cpi) sorts before "Will…"(texas), so the
    // CPI row moves to row 0. If selection tracked by INDEX the cursor would now sit
    // on texas; tracking by ID it follows CPI to row 0.
    await desk.press('o')
    // Open the selected row — the modal must lead with the CPI question (its full
    // title is modal-unique because the dense list truncates it).
    await desk.press('\r')
    expect(desk.text()).toContain('May 2026 CPI-U YoY')
    desk.cleanup()
  })

  it('sort composes with the / filter (sorts the filtered set, not the whole book)', async () => {
    const desk = await mountDesk(120, fixture())
    await desk.press('\t')
    await desk.press('\t')
    await desk.press('\t') // All tab
    await desk.press('/')
    await desk.press('senate') // narrows to the Texas Senate question only
    await desk.press('\r') // apply (drop filter focus)
    await desk.press('o') // sort the FILTERED set
    const text = desk.text()
    // The one match survives the sort and the indicator renders on the header.
    expect(text).toContain('Will the Repub')
    expect(text).toContain('1 matches')
    expect(text).toContain('QUESTION ▲')
    desk.cleanup()
  })

  it('NEXT column: scheduled review reads its due-time; no-review falls back to the marked resolution date; neither stays "—"', async () => {
    const desk = await mountDesk(120, {
      active_count: 3,
      closing_soon_count: 0,
      forecasts: [reviewedItem(), nightlyItem(), orphanItem()],
      generated_at: '2026-06-29T14:00:00Z',
      open_alert_count: 0,
      product: 'Superforecasting Agent'
    })
    // Tabs are [#misc, #market, All]. Switch to All so all three rows render in
    // one frame and every NEXT cell is visible.
    await desk.press('\t')
    await desk.press('\t')
    const text = desk.text()
    // The dense NEXT column is present.
    expect(text).toContain('NEXT')
    // 1) A scheduled review renders its relative due-time WITHOUT the "⤓" marker
    //    (unchanged behaviour). next_review_at is in the future → a plain "Nd"/"Nh".
    expect(text).toMatch(/(?<!⤓)\b\d+[dh]\b/)
    // 2) The market_nightly market has NO review but a resolution_time → the NEXT
    //    cell falls back to that date, marked with the distinguishing "⤓" glyph.
    expect(text).toContain('⤓')
    // 3) The orphan (no review, no dates) keeps the blank "—".
    expect(text).toContain('—')
    desk.cleanup()
  })
})

// An overdue-review question (next_review_at in the PAST) → dueText status 'now',
// so the NEXT cell renders the honest sweep state instead of a static "now".
const dueItem = (): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  close_time: inDays(180),
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.5,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.5 }],
  id: 'fq_due',
  next_review_at: inDays(-1),
  probability: 0.5,
  probability_display: '0.500',
  snapshot_count: 1,
  status: 'active',
  title: 'An overdue-review question',
  topics: ['misc']
})

const dueWorkspace = (): ForecastWorkspaceResponse => ({
  active_count: 1,
  closing_soon_count: 0,
  forecasts: [dueItem()],
  generated_at: '2026-06-29T14:00:00Z',
  open_alert_count: 0,
  product: 'Superforecasting Agent'
})

// A gw that answers the review-sweep countdown read (forecast.reviews.next) with a
// fixed payload while still serving the workspace/question like fakeGw.
const reviewsGw = (workspace: ForecastWorkspaceResponse, reviews: unknown) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      if (method === 'forecast.reviews.next') return Promise.resolve(reviews)
      if (method === 'forecast.question') {
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }

      return Promise.resolve(workspace)
    }
  }) as never

describe('DeskView review-sweep NEXT column + summary status', () => {
  afterEach(async () => {
    delete process.env.FORECAST_TUI_INLINE
    const { patchUiState } = await import('../app/uiStore.js')
    patchUiState({ reviewSweep: null })
  })

  it('dueNowCell: running spinner, countdown boundaries (<1m / minutes), tonight fallback, disabled, and the no-context "now"', async () => {
    const [{ dueNowCell }, { DARK_THEME }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js')
    ])
    const now = 1_700_000_000_000
    const base = { frame: 0, nightlyNextAt: NaN, nextTickAt: NaN, nowMs: now, running: false, sweeperEnabled: false }

    // Running → an animated spinner glyph + "running".
    expect(dueNowCell({ ...base, running: true }, DARK_THEME).text).toContain('running')
    // Sweeper enabled, next tick 4 minutes out → a minute countdown.
    expect(dueNowCell({ ...base, nextTickAt: now + 4 * 60000, sweeperEnabled: true }, DARK_THEME).text).toBe('due · 4m')
    // Sweeper enabled, next tick 30s out → the sub-minute "<1m".
    expect(dueNowCell({ ...base, nextTickAt: now + 30_000, sweeperEnabled: true }, DARK_THEME).text).toBe('due · <1m')
    // Sweeper enabled, tick time unknown (NaN) → imminent "<1m".
    expect(dueNowCell({ ...base, sweeperEnabled: true }, DARK_THEME).text).toBe('due · <1m')
    // Sweeper DISABLED but a nightly run is scheduled → the nightly fallback.
    expect(dueNowCell({ ...base, nightlyNextAt: now + 8 * 3600000 }, DARK_THEME).text).toBe('due · tonight')
    // Sweeper disabled and no nightly → a plain "due".
    expect(dueNowCell(base, DARK_THEME).text).toBe('due')
    // No sweep context at all → the legacy static "now".
    expect(dueNowCell(undefined, DARK_THEME).text).toBe('now')
  })

  it('SweepStatusLine: running spinner line, countdown line, tonight fallback, and NOTHING when the desk is quiet', async () => {
    const [{ renderSync }, { SweepStatusLine }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const draw = (props: Record<string, unknown>): string => {
      const out = writeStream(48, 6)
      renderSync(React.createElement(SweepStatusLine as never, props as never), {
        exitOnCtrlC: false,
        patchConsole: false,
        stdout: out.stream
      } as never)
      return normalize(out.text(), stripAnsi)
    }

    const future = new Date(Date.now() + 8 * 60000).toISOString()

    // Running → "⟳ sweeping N due…" (the count comes from the running marker).
    expect(draw({ now: 0, reviews: null, sweepRunning: { dueCount: 4 }, t: DARK_THEME })).toContain('sweeping 4 due')
    // Due + enabled sweeper w/ a future tick → "next sweep in Xm · N due".
    const countdown = draw({
      now: 0,
      reviews: { due_count: 3, sweeper: { enabled: true, next_tick_at: future } },
      sweepRunning: null,
      t: DARK_THEME
    })
    expect(countdown).toContain('next sweep in')
    expect(countdown).toContain('3 due')
    // Due + DISABLED sweeper + a scheduled nightly → "N due · tonight".
    expect(
      draw({
        now: 0,
        reviews: { due_count: 2, nightly: { next_run_at: future }, sweeper: { enabled: false } },
        sweepRunning: null,
        t: DARK_THEME
      })
    ).toContain('2 due · tonight')
    // Nothing due and nothing running → the quiet desk stays quiet (renders NOTHING).
    expect(draw({ now: 0, reviews: { due_count: 0 }, sweepRunning: null, t: DARK_THEME })).toBe('')
  })

  it('NEXT cell: an overdue review with an enabled sweeper reads "due · Xm" (not a static "now")', async () => {
    const future = new Date(Date.now() + 8 * 60000).toISOString()
    const ws = dueWorkspace()
    const reviews = {
      due_count: 1,
      nightly: { installed: true, next_run_at: future },
      sweeper: { enabled: true, interval_minutes: 10, next_tick_at: future, running: false }
    }
    const desk = await mountDesk(120, ws, reviewsGw(ws, reviews))
    const text = desk.text()
    // The honest countdown replaced the static "now".
    expect(text).toMatch(/due · \d+m/)
    desk.cleanup()
  })

  it('NEXT cell: while a sweep is running an overdue row shows the spinner "running" text', async () => {
    const { patchUiState } = await import('../app/uiStore.js')
    // Arm the in-flight marker BEFORE mount so the desk paints the running state.
    patchUiState({ reviewSweep: { dueCount: 1 } })

    const ws = dueWorkspace()
    const reviews = { due_count: 1, sweeper: { enabled: true, next_tick_at: null, running: true } }
    const desk = await mountDesk(120, ws, reviewsGw(ws, reviews))
    const text = desk.text()
    expect(text).toContain('running')
    desk.cleanup()
  })

  it('NEXT cell: a NOT-due row keeps its plain countdown even while a sweep runs', async () => {
    const { patchUiState } = await import('../app/uiStore.js')
    patchUiState({ reviewSweep: { dueCount: 1 } })

    // reviewedItem has next_review_at 5 days out → status is 'soon'/'ok', never 'now'.
    const ws: ForecastWorkspaceResponse = {
      active_count: 1,
      closing_soon_count: 0,
      forecasts: [reviewedItem()],
      generated_at: '2026-06-29T14:00:00Z',
      open_alert_count: 0,
      product: 'Superforecasting Agent'
    }
    const reviews = { due_count: 1, sweeper: { enabled: true, next_tick_at: null, running: true } }
    const desk = await mountDesk(120, ws, reviewsGw(ws, reviews))
    const text = desk.text()
    // Its NEXT cell reads a plain forward duration, NOT the running/spinner text.
    expect(text).toMatch(/\b\d+[dh]\b/)
    expect(text).not.toMatch(/due · \d+m/)
    desk.cleanup()
  })
})
