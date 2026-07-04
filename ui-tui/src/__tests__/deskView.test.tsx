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
  // A short history whose NEWEST point is the thesis event probability (0.53) — this
  // drives the pinned row's PROB column at 2dp AND the window deltas, via the same
  // windowDelta path the member rows use. Dates are relative to now so the deltas
  // stay deterministic. (The workspace payload also carries this top-level as
  // headline_probability; the generated ForecastThesis type predates that field, so
  // the desk reads the newest history headline, which equals it.)
  history: [
    { as_of: inDays(-10), headline_probability: 0.5 },
    { as_of: inDays(0), headline_probability: 0.53 }
  ],
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
// (e.g. `U` → jobs.start refresh). Still resolves like fakeGw otherwise.
const recordingGw = (response: ForecastWorkspaceResponse, calls: { method: string; params: Record<string, unknown> }[]) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })

      if (method === 'forecast.question') {
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }

      // The detached-job runtime RPCs: jobs.start mints a job_id (so a U press
      // records the start), jobs.status/active answer benignly (no live job) so the
      // poll + mount re-attach are no-ops. Tests needing a completing/running job
      // script jobs.status themselves (see refreshGw).
      if (method === 'jobs.start') {
        return Promise.resolve({ job_id: 'job_rec', type: params.type })
      }

      if (method === 'jobs.active') {
        return Promise.resolve({ count: 0, jobs: [] })
      }

      if (method === 'jobs.status') {
        return Promise.resolve({ found: false, job: null })
      }

      return Promise.resolve(response)
    }
  }) as never

// A gw that answers the detached REFRESH job RPCs (jobs.*): jobs.start mints a
// job_id, jobs.status returns a scripted JobRecord (done / running), and jobs.active
// returns a scripted live-job list (for the mount re-attach). Everything else
// resolves like fakeGw — the deterministic mass-U job flow end to end.
const refreshGw = (
  response: ForecastWorkspaceResponse,
  calls: { method: string; params: Record<string, unknown> }[],
  job: unknown,
  active: unknown[] = []
) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      if (method === 'forecast.question') {
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }
      if (method === 'jobs.start') {
        return Promise.resolve({ job_id: 'job_1', type: params.type })
      }
      if (method === 'jobs.status') {
        return Promise.resolve({ found: !!job, job })
      }
      if (method === 'jobs.active') {
        return Promise.resolve({ count: active.length, jobs: active })
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

  // Give Ink time to wire raw-mode input BEFORE any press — under heavy parallel
  // suite load a 60ms settle occasionally raced the subscription, dropping the
  // first keypress.
  await tick(100)

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
    expect(text).toContain('May 2026')
    // Footer chips — including the always-present Help chip (right before Close).
    expect(text).toContain('Lens')
    expect(text).toContain('Open')
    expect(text).toContain('Filter')
    expect(text).toContain('Help')
    desk.cleanup()
  })

  it('h (and ? alias) open the unified Help modal — and ← still switches lens', async () => {
    resetOverlayState()
    const desk = await mountDesk(120, fixture())
    expect(getOverlayState().cheatSheet).toBe(false)
    // ← is the remapped incumbent (previous lens). It must NOT open Help.
    await desk.press('[D')
    expect(getOverlayState().cheatSheet).toBe(false)
    // h opens the unified Help modal.
    await desk.press('h')
    expect(getOverlayState().cheatSheet).toBe(true)
    resetOverlayState()
    desk.cleanup()
  })

  it('? aliases to the same Help modal on the desk', async () => {
    resetOverlayState()
    const desk = await mountDesk(120, fixture())
    await desk.press('?')
    expect(getOverlayState().cheatSheet).toBe(true)
    resetOverlayState()
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
    // SRC/RDY (machine-readiness) now outrank the delta windows in the priority
    // order — the operator asked for these columns expressly, so they must render
    // at the common two-pane width even when 1MO/AGE drop.
    expect(text).toContain('SRC')
    expect(text).toContain('RDY')
    expect(text).toContain('1W')
    // The '─' rule under the header.
    expect(text).toContain('───')
    // A binary row carries its compact probability + an evidence count; a
    // distribution row shows its μ headline and never a fake percent in CHG.
    expect(text).toContain('52.00%')
    expect(text).toContain('μ4.23%')
    desk.cleanup()
  })

  it('pins the thesis as row 0 of the table (◆ + real 2dp PROB) — not a banner — and opens its read on Enter', async () => {
    const desk = await mountDesk(120, fixture())
    // The thesis tab is active by default → the thesis now IS the first table row:
    // an accent ◆ row carrying its EVENT probability at 2dp (same pct rendering as a
    // member forecast), read in the same visual language as the members below it.
    let text = desk.text()
    expect(text).toContain('◆')
    expect(text).toContain('53.00%') // the thesis headline_probability, 2dp — row-unique
    // The OLD banner is gone: its "⏎ lens" affordance + "health X% · score Y/100"
    // aggregate line no longer print on a thesis tab (that read lives in the modal).
    expect(text).not.toContain('⏎ lens')
    expect(text).not.toContain('score 54/100')
    // The cursor starts on the pinned thesis row → Enter opens the SAME thesis
    // aggregate read the banner used to open, painted ABOVE the still-visible body.
    await desk.press('\r')
    text = desk.text()
    expect(text).toContain('FORECASTS') // body still rendered behind the overlay
    expect(text).toContain('Inflation stays sticky through 2026')
    // ThesisDeskRead's domain·status·members header line is emitted ONLY by that read
    // (never the list/panel/tab-strip), so it proves the thesis read is present.
    expect(text).toContain('macro · active · 1 member · inflation, macro')
    desk.cleanup()
  })

  it('keeps the thesis pinned at row 0 under sorting and includes it in j/k navigation', async () => {
    const desk = await mountDesk(120, twoMemberFixture())
    // Sort by QUESTION — this reorders the MEMBER rows, never the pinned thesis.
    await desk.press('o')
    // The cursor is still on row 0 = the pinned thesis (sorting can't move it) →
    // Enter opens the thesis read (its domain·status·members header line is emitted
    // ONLY by ThesisDeskRead — the list/panel/tab-strip never print it).
    await desk.press('\r')
    expect(desk.text()).toContain('macro · active · 2 members · inflation, macro')
    await desk.press('\x1b') // close the modal
    // j moves the cursor OFF the pinned thesis onto the first MEMBER row (sorted
    // below it) → Enter opens that member's OWN detail (a CPI question), proving the
    // pinned row participates in j/k navigation and the members sort below it.
    await desk.press('j')
    await desk.press('\r')
    expect(desk.text()).toContain('CPI-U YoY')
    desk.cleanup()
  })

  it('Space on the pinned thesis row refuses to mark it and flashes why (jobs are per-question)', async () => {
    const desk = await mountDesk(120, fixture())
    // The cursor starts on the pinned thesis row → Space can't mark it (U/A fan out
    // over its members instead), so it flashes an explanatory refusal and marks
    // nothing.
    await desk.press(' ')
    const text = desk.text()
    expect(text).toContain('thesis row runs its members')
    expect(text).not.toContain('1 selected') // nothing entered the mark set
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
    expect(text).toContain('Will the Rep')
    expect(text).toContain('May 2026')
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

  it('U starts ONE detached REFRESH job (jobs.start) over the selected row — not a client-side loop', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // plainFixture has no thesis/factor lens → the first tab's row 0 is a concrete
    // forecast, so U targets a real question id.
    const desk = await mountDesk(120, plainFixture(), recordingGw(plainFixture(), calls))
    await desk.press('U')
    // The deterministic re-pool now runs as ONE detached runtime job (durable +
    // re-attachable), NOT the old per-row forecast.command loop that died on
    // navigate-away. `u`/re-arm stays request-based (forecast.reforecast).
    const start = calls.find(c => c.method === 'jobs.start')
    expect(start).toBeDefined()
    expect(start?.params.type).toBe('refresh')
    expect((start?.params.spec as { question_ids?: string[] })?.question_ids).toEqual(['fq_undersat'])
    // No client-side per-row forecast.command refresh is fired anymore.
    expect(calls.some(c => c.method === 'forecast.command')).toBe(false)
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
    expect(text).toContain('Will the Rep')
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
    expect(text).toContain('52.00%')
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
    expect(text).toContain('Will the Rep')
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
    const [{ dueNowCell }, { DARK_THEME }, { SPINNER }, { sweepColor, sweepStops }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/icons.js'),
      import('../lib/accentSweep.js')
    ])
    const now = 1_700_000_000_000
    const base = { frame: 0, nightlyNextAt: NaN, nextTickAt: NaN, nowMs: now, running: false, sweeperEnabled: false }

    // Running → the animated spinner glyph + "running", with its colour swept
    // through the brand accent family by the SAME helper the Home chat's busy
    // spinner uses (frame-driven). Assert the helper output — NOT a brittle ANSI
    // code — so the desk cell provably cycles colour in step with the chat.
    const runningCell = dueNowCell({ ...base, running: true, frame: 3 }, DARK_THEME)
    expect(runningCell.text).toContain('running')
    expect(runningCell.text.startsWith(SPINNER[3 % SPINNER.length]!)).toBe(true)
    expect(runningCell.color).toBe(sweepColor(sweepStops(DARK_THEME), 3))
    // A different frame → a different swept colour (the animation is live).
    expect(dueNowCell({ ...base, running: true, frame: 9 }, DARK_THEME).color).toBe(
      sweepColor(sweepStops(DARK_THEME), 9)
    )
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
    const [{ renderSync }, { SweepStatusLine }, { DARK_THEME }, { stripAnsi }, { SPINNER }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js'),
      import('../lib/icons.js')
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

    // Running → the Home-chat busy animation: the frame-driven spinner glyph +
    // the accent-swept "sweeping N due…" (the count comes from the running marker).
    // At now=0 the leading glyph is SPINNER frame 0; the ForecastPulse Δ stays dark
    // (its tick<=0 guard) so the line is deterministic to assert on.
    const sweeping = draw({ now: 0, reviews: null, sweepRunning: { dueCount: 4 }, t: DARK_THEME })
    expect(sweeping).toContain('sweeping 4 due')
    expect(sweeping).toContain(SPINNER[0])
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

// ── Mass forced re-run ("run en masse") ──────────────────────────────────────
// A plain (no thesis/factor) forecast under a shared #tag so the FIRST tab has
// concrete markable rows at cursor 0 (no lens row to offset).
const plainRow = (id: string, title: string): ForecastWorkspaceItem => ({
  as_of: '2026-06-29T00:00:00Z',
  close_time: '2026-12-31T00:00:00Z',
  delta: 0.01,
  domain: 'macro',
  evidence_count: 1,
  freshness: 'fresh today',
  headline_kind: 'probability',
  headline_probability: 0.44,
  history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.44 }],
  id,
  open_alert_count: 0,
  probability: 0.44,
  probability_display: '0.440',
  snapshot_count: 2,
  status: 'active',
  title,
  topics: ['macro']
})

const multiFixture = (): ForecastWorkspaceResponse => ({
  active_count: 3,
  closing_soon_count: 0,
  forecasts: [
    plainRow('fq_a', 'Alpha question'),
    plainRow('fq_b', 'Beta question'),
    plainRow('fq_c', 'Gamma question')
  ],
  generated_at: '2026-06-29T14:00:00Z',
  open_alert_count: 0,
  product: 'Superforecasting Agent'
})

// A thesis with TWO member questions, so a lens-row U provably fans out over BOTH.
const twoMemberFixture = (): ForecastWorkspaceResponse => ({
  active_count: 2,
  closing_soon_count: 0,
  factors: [],
  forecasts: [cpiItem(), { ...cpiItem(), id: 'fq_cpi2', title: 'Jun 2026 CPI-U YoY' }],
  generated_at: '2026-05-29T14:00:00Z',
  open_alert_count: 0,
  product: 'Superforecasting Agent',
  theses: [{ ...inflationThesis(), member_count: 2, question_ids: ['fq_cpi', 'fq_cpi2'] }]
})

describe('DeskView mass forced re-run (selection + U/u fan-out)', () => {
  it('refreshTally reads the job-computed server tally into the MassTally shape (None-safe)', async () => {
    const { refreshTally } = await import('../components/deskView.js')
    // The status classification now lives server-side (refresh.py); the desk just
    // reads the tally the REFRESH job produced.
    expect(refreshTally({ tally: { error: 1, no_sources: 2, refreshed: 3, unchanged: 4 } })).toEqual({
      error: 1,
      noSources: 2,
      refreshed: 3,
      unchanged: 4
    })
    // A missing / malformed tally reads as all zeros — a summary never invents counts.
    expect(refreshTally(undefined)).toEqual({ error: 0, noSources: 0, refreshed: 0, unchanged: 0 })
    expect(refreshTally({ tally: { refreshed: 'nope' } })).toEqual({ error: 0, noSources: 0, refreshed: 0, unchanged: 0 })
  })

  it('Space marks the cursor row and advances; marks stack + the header and chips show the count', async () => {
    const desk = await mountDesk(120, multiFixture())
    await desk.press(' ') // mark fq_a → cursor advances to fq_b
    await desk.press(' ') // mark fq_b → cursor advances to fq_c
    // The cumulative buffer holds both the 1-selected frame (after the first mark)
    // and the 2-selected frame (after the advance + second mark), proving marks
    // stack AND the cursor advanced onto a fresh row each time.
    const text = desk.text()
    expect(text).toContain('▎') // the leading accent mark glyph
    expect(text).toContain('1 selected') // header count after the first mark
    expect(text).toContain('2 selected') // header count after the second
    expect(text).toContain('Update (2)') // chips carry the live count
    expect(text).toContain('Re-arm (2)')
    desk.cleanup()
  })

  it('un-marking a row (Space toggles off) removes it from the fan-out', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, multiFixture(), recordingGw(multiFixture(), calls))
    await desk.press(' ') // mark fq_a → cursor fq_b
    await desk.press(' ') // mark fq_b → cursor fq_c
    await desk.press('k') // cursor back to fq_b
    await desk.press(' ') // UN-mark fq_b → cursor fq_c
    await desk.press('U') // only fq_a remains marked
    const starts = calls.filter(c => c.method === 'jobs.start')
    expect(starts).toHaveLength(1)
    expect((starts[0]?.params.spec as { question_ids?: string[] }).question_ids).toEqual(['fq_a'])
    desk.cleanup()
  })

  it('Shift+↓ extends the marked run over the rows it passes over', async () => {
    const desk = await mountDesk(120, multiFixture())
    // Shift+Down from fq_a marks the anchor (fq_a) AND the row it lands on (fq_b).
    await desk.press('\x1b[1;2B')
    expect(desk.text()).toContain('2 selected')
    // A second Shift+Down lands on fq_c and marks it too → a contiguous run of 3.
    await desk.press('\x1b[1;2B')
    expect(desk.text()).toContain('3 selected')
    desk.cleanup()
  })

  it('Esc clears the selection FIRST, before it would clear the filter', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, multiFixture(), recordingGw(multiFixture(), calls))
    // A filter that keeps all three rows, then mark two of them.
    await desk.press('/')
    await desk.press('question')
    await desk.press('\r')
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    // Esc must eat the MARKS, not the query: U then hits the single cursor row →
    // ONE job over just that row (its question_ids would be two if the marks had
    // survived the Esc).
    await desk.press('\x1b')
    await desk.press('U')
    const starts = calls.filter(c => c.method === 'jobs.start')
    expect(starts).toHaveLength(1)
    expect((starts[0]?.params.spec as { question_ids?: string[] }).question_ids).toHaveLength(1)
    desk.cleanup()
  })

  it('U starts ONE detached REFRESH job over EVERY marked id and toasts the job-computed honest tally', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // The job runs the whole batch server-side and reports back a done JobRecord
    // carrying the honest tally it computed (1 refreshed, 1 unchanged, 1 no-sources).
    const doneJob = {
      done_count: 3,
      result: { tally: { error: 0, no_sources: 1, refreshed: 1, unchanged: 1 } },
      status: 'done',
      total: 3
    }
    const desk = await mountDesk(120, multiFixture(), refreshGw(multiFixture(), calls, doneJob))
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    await desk.press(' ') // mark fq_c
    await desk.press('U')
    await tick(120)
    const starts = calls.filter(c => c.method === 'jobs.start')
    // ONE job over the whole batch — not a per-row client loop.
    expect(starts).toHaveLength(1)
    expect(starts[0]!.params.type).toBe('refresh')
    expect((starts[0]!.params.spec as { question_ids?: string[] }).question_ids).toEqual(['fq_a', 'fq_b', 'fq_c'])
    expect(calls.some(c => c.method === 'jobs.status')).toBe(true)
    // The tally the JOB computed — the toast must NOT claim three updates.
    expect(desk.text()).toContain('✓ 1 updated · 1 unchanged · 1 no sources')
    desk.cleanup()
  })

  it('U on a thesis LENS row starts ONE refresh job over ALL its member questions', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, twoMemberFixture(), recordingGw(twoMemberFixture(), calls))
    // Default thesis tab, cursor on the lens row (no marks) → U selects all members.
    await desk.press('U')
    const starts = calls.filter(c => c.method === 'jobs.start')
    expect(starts).toHaveLength(1)
    expect(((starts[0]!.params.spec as { question_ids?: string[] }).question_ids ?? []).slice().sort()).toEqual([
      'fq_cpi',
      'fq_cpi2'
    ])
    desk.cleanup()
  })

  it('the marked selection survives a payload reload → U starts one job over both (keyed by id, not index)', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, multiFixture(), recordingGw(multiFixture(), calls))
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    await desk.press('r') // force a workspace reload
    await desk.press('U') // marks persist → one job over both
    const starts = calls.filter(c => c.method === 'jobs.start')
    expect(starts).toHaveLength(1)
    expect((starts[0]!.params.spec as { question_ids?: string[] }).question_ids).toEqual(['fq_a', 'fq_b'])
    desk.cleanup()
  })

  it('u with a selection fans the cheap re-arm over every marked id', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, multiFixture(), recordingGw(multiFixture(), calls))
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    await desk.press('u')
    const rearms = calls.filter(c => c.method === 'forecast.reforecast')
    expect(rearms.map(c => c.params.id)).toEqual(['fq_a', 'fq_b'])
    expect(desk.text()).toContain('✓ 2 re-armed')
    desk.cleanup()
  })

  it('ignores a re-triggered U while a REFRESH job is in flight (no duplicate start)', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // A still-running JobRecord: the poll keeps refreshRunningRef latched so a second
    // U is guarded.
    const runningJob = { current: 'fq_a', done_count: 1, status: 'running', total: 2 }
    const desk = await mountDesk(120, multiFixture(), refreshGw(multiFixture(), calls, runningJob))
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    await desk.press('U') // starts job_1 (status stays 'running')
    await tick(120)
    await desk.press('U') // in-flight → guarded (parks "already updating", no 2nd start)
    expect(desk.text()).toContain('already updating')
    const starts = calls.filter(c => c.method === 'jobs.start')
    // Exactly ONE job — the guarded re-trigger started nothing.
    expect(starts).toHaveLength(1)
    desk.cleanup()
  })
})

describe('live payload re-pull', () => {
  it('quietly re-fetches forecast.workspace on the 90s interval while open, stops on unmount', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, plainFixture(), recordingGw(plainFixture(), calls))
    const count = () => calls.filter(c => c.method === 'forecast.workspace').length
    const initial = count()
    expect(initial).toBeGreaterThanOrEqual(1)

    // The interval is real (not fake timers — the harness paints on real ticks),
    // so assert the LIFECYCLE contract instead of wall-clock: the interval id is
    // cleared on unmount, meaning no further pulls arrive afterwards.
    desk.cleanup()
    const settled = count()
    await tick(200)
    expect(count()).toBe(settled)
  })
})

// ── SRC / RDY machine-readiness columns ───────────────────────────────────────
// The desk's two-pane list|panel flex is not measured reliably in the inline
// harness (the existing DeskSummary tests render that component DIRECTLY for the
// same reason). So the width-dependent column packing — SRC/RDY render + colours +
// priority-drop — is asserted on the exported DeskForecastList in isolation with an
// EXPLICIT width, and the readiness summary block on DeskSummary directly.
type Gap = { fix_hint: string; key: string; label: string }

const readyRow = (id: string, title: string, src: number, score: number, gaps: Gap[] = []): ForecastWorkspaceItem => ({
  ...plainRow(id, title),
  readiness: { gaps, score },
  src_count: src
})

const lowGaps = (): Gap[] => [
  { fix_hint: 'no watched sources — add one, or a T task', key: 'watches', label: 'watched sources' },
  { fix_hint: 'reforecast to decompose into drivers, or a T task', key: 'components', label: 'structured components' },
  { fix_hint: 'no enabled scheduled review — add one, or a T task', key: 'scheduled', label: 'enabled review schedule' },
  { fix_hint: 'add a base rate, or a T task', key: 'ref_classes', label: 'reference classes' }
]

const readinessItems = (): ForecastWorkspaceItem[] => [
  readyRow('fq_hi', 'Alpha question', 5, 90),
  readyRow('fq_mid', 'Beta question', 2, 60, [{ fix_hint: 'add a base rate, or a T task', key: 'ref_classes', label: 'reference classes' }]),
  readyRow('fq_low', 'Gamma question', 0, 30, lowGaps())
]

const renderList = async (width: number, items: ForecastWorkspaceItem[], props: Record<string, unknown> = {}) => {
  const [{ renderSync }, { DeskForecastList }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/deskView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])
  const stdout = writeStream(Math.max(width + 6, 80), 40)
  renderSync(
    React.createElement(DeskForecastList as never, {
      cursor: 0,
      empty: 'none',
      items,
      markedIds: new Set<string>(),
      nowMs: Math.floor(Date.now() / 60_000) * 60_000,
      onSelect: () => undefined,
      runningIds: new Set<string>(),
      sortDir: 'asc',
      sortKey: null,
      t: DARK_THEME,
      visibleRows: 12,
      width,
      ...props
    } as never),
    { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
  )
  return normalize(stdout.text(), stripAnsi)
}

describe('DeskView SRC / RDY readiness columns', () => {
  it('renders the SRC + RDY headers and per-row values on a wide list', async () => {
    const text = await renderList(112, readinessItems())
    expect(text).toContain('SRC')
    expect(text).toContain('RDY')
    // The readiness scores land in the RDY column (90 / 60 / 30).
    expect(text).toContain('90')
    expect(text).toContain('60')
    expect(text).toContain('30')
  })

  it('deskCellText colours SRC=0 as the warning "no fuel" signal and bands RDY by score', async () => {
    const [{ deskCellText }, { DARK_THEME }, { semantics }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/visualSemantics.js')
    ])
    const sem = semantics(DARK_THEME)
    const win = { '1d': null, '1mo': null, '1w': null }
    const cell = (key: string, item: ForecastWorkspaceItem) => deskCellText(key, item, sem, DARK_THEME, win, 0)
    // SRC: 0 → warning ("no fuel"); >0 → subtle.
    expect(cell('src', { src_count: 0 })).toEqual({ color: DARK_THEME.color.warn, text: '0' })
    expect(cell('src', { src_count: 4 })).toEqual({ color: sem.subtle, text: '4' })
    // RDY bands: ≥80 ok, 50-79 warn, <50 danger; no composite → subtle "—".
    expect(cell('rdy', { readiness: { gaps: [], score: 88 } }).color).toBe(DARK_THEME.color.ok)
    expect(cell('rdy', { readiness: { gaps: [], score: 60 } }).color).toBe(DARK_THEME.color.warn)
    expect(cell('rdy', { readiness: { gaps: [], score: 40 } }).color).toBe(DARK_THEME.color.error)
    expect(cell('rdy', {})).toEqual({ color: sem.subtle, text: '—' })
  })

  it('deskSortValue exposes SRC/RDY so the shared tableSort can order by them', async () => {
    const { deskSortValue } = await import('../components/deskView.js')
    expect(deskSortValue(readyRow('a', 'A', 3, 70), 'src', 0)).toBe(3)
    expect(deskSortValue(readyRow('a', 'A', 3, 70), 'rdy', 0)).toBe(70)
    // A missing source count is 0 (no fuel), a missing composite is null (sorts last).
    expect(deskSortValue({}, 'src', 0)).toBe(0)
    expect(deskSortValue({}, 'rdy', 0)).toBeNull()
  })

  it('a header click sorts by SRC/RDY (the ▲/▼ indicator renders without clipping)', async () => {
    const sorts: string[] = []
    const text = await renderList(112, readinessItems(), { onSort: (k: string) => sorts.push(k), sortDir: 'asc', sortKey: 'rdy' })
    // The RDY column is the active sort → its header carries the ascending indicator,
    // and the 5-wide column hosts "RDY ▲" without clipping to "RD…".
    expect(text).toContain('RDY ▲')
  })

  it('keeps SRC/RDY at narrow widths — the delta windows drop first', async () => {
    // The operator's machine-readiness columns outrank momentum deltas in the
    // priority order: at a width too tight for the full set, SRC/RDY survive and
    // 1MO/AGE are the ones that drop.
    const text = await renderList(76, readinessItems())
    expect(text).toContain('SRC')
    expect(text).toContain('RDY')
    expect(text).not.toContain('1MO')
  })

  it('marks the running agent job\'s remaining rows with a dim ⋯ gutter marker', async () => {
    // fq_hi + fq_low are still in flight; fq_mid has landed → only the remaining
    // rows carry the ⋯ marker.
    const running = await renderList(112, readinessItems(), { runningIds: new Set(['fq_hi', 'fq_low']) })
    expect(running).toContain('⋯')
    // No job running → no ⋯ (byte-identical-at-rest gutter).
    const idle = await renderList(112, readinessItems())
    expect(idle).not.toContain('⋯')
  })
})

describe('DeskView pinned thesis row (thesis-lens leader)', () => {
  // inflationThesis' newest history point (0.53) IS the thesis event probability the
  // desk reads into PROB (the workspace payload also carries it top-level as
  // headline_probability; the generated type predates that field, so the newest
  // history headline — which equals it — is the typed source).
  it('thesisCellText: PROB is the event probability at 2dp; EV/SRC/RDY/NEXT are an honest —', async () => {
    const [{ thesisCellText }, { DARK_THEME }, { semantics }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/visualSemantics.js')
    ])
    const sem = semantics(DARK_THEME)
    const win = { '1d': null, '1mo': null, '1w': null }
    const cell = (key: string) => thesisCellText(key, inflationThesis(), sem, DARK_THEME, win, 0)
    // PROB reuses the member headline formatter at 2dp (0.53 → "53.00%"), accent-stamped.
    expect(cell('prob').text).toBe('53.00%')
    expect(cell('prob').color).toBe(DARK_THEME.color.accent)
    // QUESTION is the thesis title.
    expect(cell('q').text).toBe('Inflation stays sticky through 2026')
    // The columns a thesis has no per-question analogue for render an honest '—'
    // (absence as absence — never a fabricated 0, unlike a member SRC 0 warning).
    for (const key of ['ev', 'src', 'rdy', 'next']) {
      expect(cell(key)).toEqual({ color: sem.subtle, text: '—' })
    }
    // A thesis with no history/event probability stays an honest '—', never a fake number.
    expect(
      thesisCellText('prob', { ...inflationThesis(), history: [] }, sem, DARK_THEME, win, 0).text
    ).toBe('—')
  })

  it('thesisCellText: 1D/1W/1MO run through the same window-delta formatter (2dp point deltas)', async () => {
    const [{ thesisCellText }, { DARK_THEME }, { semantics }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/visualSemantics.js')
    ])
    const sem = semantics(DARK_THEME)
    // A +3pt 1W move formats exactly like a member row's window column.
    expect(
      thesisCellText('1w', inflationThesis(), sem, DARK_THEME, { '1d': null, '1mo': null, '1w': 0.03 }, 0).text
    ).toContain('3.00')
    // A missing window (too little history) is an honest '—'.
    expect(
      thesisCellText('1d', inflationThesis(), sem, DARK_THEME, { '1d': null, '1mo': null, '1w': null }, 0).text
    ).toBe('—')
  })

  it('renders the ◆ pinned thesis row above the members with its real 2dp PROB (component width)', async () => {
    const text = await renderList(112, [cpiItem()], {
      cursor: -1,
      pinnedActive: true,
      pinnedThesis: inflationThesis()
    })
    // The pinned thesis leads the table: the ◆ marker + its 2dp event probability,
    // with the member forecast (CPI) rendering below it.
    expect(text).toContain('◆')
    expect(text).toContain('53.00%')
    expect(text).toContain('CPI-U YoY')
  })
})

describe('DeskView readiness summary block', () => {
  const renderSummary = async (selected: ForecastWorkspaceItem) => {
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
        selected,
        t: DARK_THEME,
        width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    return normalize(stdout.text(), stripAnsi)
  }

  it('shows score + up to 3 gap labels with fix hints when the selected row has gaps', async () => {
    const text = await renderSummary(readyRow('fq_low', 'Gamma question', 0, 30, lowGaps()))
    expect(text).toContain('readiness')
    expect(text).toContain('30/100')
    expect(text).toContain('4 gaps')
    // The first gap label + the leading fragment of its fix hint (one truncated line).
    expect(text).toContain('watched sources')
    // Only the first THREE gaps are shown (the fourth label is omitted).
    expect(text).not.toContain('reference classes')
  })

  it('shows NOTHING for a healthy row (no gaps) — the quiet desk', async () => {
    const text = await renderSummary(readyRow('fq_hi', 'Alpha question', 5, 90))
    expect(text).not.toContain('readiness')
  })
})

describe('AgentProgressLine', () => {
  const agentJob = (over: Record<string, unknown> = {}) => ({
    current: { stage: 'research', title: 'Some macro question' },
    done: 3,
    doneIds: new Set<string>(),
    mode: 'agent' as const,
    runId: 'run_1',
    status: 'running',
    targetIds: new Set<string>(),
    total: 17,
    ...over
  })

  it('renders the accent-swept "🧠 agent done/total · title · stage" line while a job runs', async () => {
    const [{ renderSync }, { AgentProgressLine }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@hermes/ink'),
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])
    const stdout = writeStream(60, 6)
    renderSync(
      React.createElement(AgentProgressLine as never, { agent: agentJob(), now: 0, t: DARK_THEME, width: 56 } as never),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream } as never
    )
    const text = normalize(stdout.text(), stripAnsi)
    expect(text).toContain('🧠 agent 3/17')
    expect(text).toContain('research')

    // Task mode reads the latest progress[] note instead of a per-question title.
    const task = writeStream(60, 6)
    renderSync(
      React.createElement(AgentProgressLine as never, {
        agent: agentJob({ current: null, done: 0, mode: 'task', note: 'watching sources', total: 2 }),
        now: 0,
        t: DARK_THEME,
        width: 56
      } as never),
      { exitOnCtrlC: false, patchConsole: false, stdout: task.stream } as never
    )
    const taskText = normalize(task.text(), stripAnsi)
    expect(taskText).toContain('🧠 task 0/2')
    expect(taskText).toContain('watching sources')

    // No job → the line renders nothing (quiet at rest).
    const idle = writeStream(60, 6)
    renderSync(
      React.createElement(AgentProgressLine as never, { agent: null, now: 0, t: DARK_THEME, width: 56 } as never),
      { exitOnCtrlC: false, patchConsole: false, stdout: idle.stream } as never
    )
    expect(normalize(idle.text(), stripAnsi)).toBe('')
  })
})

// ── Detached A/T agent jobs (start → poll → tally) ────────────────────────────
// A gw that answers the detached-job RPCs: the start/task ALIASES return a run_id
// (byte-compatible with the old surface), and the GENERIC jobs.status returns a
// scripted JobRecord — the desk's A/T job now rides the one useJobAttach hook over
// jobs.status/jobs.active, so the poll reads the runtime record directly.
const jobGw = (
  response: ForecastWorkspaceResponse,
  calls: { method: string; params: Record<string, unknown> }[],
  record: unknown
) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      if (method === 'forecast.question') {
        return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
      }
      if (method === 'forecast.reforecast.start' || method === 'forecast.desk.task') {
        return Promise.resolve({
          note: 'ok',
          run_id: 'run_1',
          total: Array.isArray(params.question_ids) ? (params.question_ids as unknown[]).length : 0
        })
      }
      if (method === 'jobs.status') {
        return Promise.resolve({ found: !!record, job: record })
      }
      if (method === 'jobs.active') {
        return Promise.resolve({ count: 0, jobs: [] }) // no pre-existing job; start+attach drives it
      }
      return Promise.resolve(response)
    }
  }) as never

describe('DeskView detached agent jobs (A / T)', () => {
  it('A starts a detached agent run over the marked batch, polls status, and toasts the HONEST tally', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // A terminal reforecast JobRecord (jobs.status shape): per-question results ride
    // the record's `result`; quorums_started is derived from the quorum_autorun rows.
    const record = {
      done_count: 3,
      job_id: 'run_1',
      result: {
        results: [
          { committed: true, question_id: 'fq_a', quorum_autorun: true },
          { committed: false, question_id: 'fq_b' },
          { committed: false, error: 'boom', question_id: 'fq_c' }
        ]
      },
      spec: { question_ids: ['fq_a', 'fq_b', 'fq_c'] },
      status: 'done',
      total: 3,
      type: 'reforecast'
    }
    const desk = await mountDesk(120, multiFixture(), jobGw(multiFixture(), calls, record))
    await desk.press(' ') // mark fq_a
    await desk.press(' ') // mark fq_b
    await desk.press(' ') // mark fq_c
    await desk.press('A')
    await tick(220)
    const start = calls.find(c => c.method === 'forecast.reforecast.start')
    expect(start).toBeDefined()
    expect(start?.params.question_ids).toEqual(['fq_a', 'fq_b', 'fq_c'])
    expect(calls.some(c => c.method === 'jobs.status')).toBe(true)
    // 1 committed, 1 blocked (ran, no commit, no error), 1 error, 1 quorum started —
    // the tally never claims a commit it didn't earn.
    const text = desk.text()
    expect(text).toContain('1 committed')
    expect(text).toContain('1 blocked')
    expect(text).toContain('1 quorum')
    desk.cleanup()
  })

  it('guards ONE job at a time — a second A while running flashes the run_id, no duplicate start', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const running = {
      current: { stage: 'research', title: 'Beta question' },
      done_count: 1,
      results: [{ committed: true, question_id: 'fq_a' }],
      run_id: 'run_1',
      status: 'running',
      total: 3
    }
    const desk = await mountDesk(120, multiFixture(), jobGw(multiFixture(), calls, running))
    await desk.press(' ')
    await desk.press(' ')
    await desk.press(' ')
    await desk.press('A') // starts run_1 (status stays 'running')
    await tick(140)
    await desk.press('A') // guarded — no second start
    const starts = calls.filter(c => c.method === 'forecast.reforecast.start')
    expect(starts).toHaveLength(1)
    expect(desk.text()).toContain('agent running')
    desk.cleanup()
  })

  it('the selection footer gains the "Agent (N)" and "Task (N)" chips', async () => {
    const desk = await mountDesk(120, multiFixture())
    await desk.press(' ') // mark fq_a → 1 selected
    const text = desk.text()
    expect(text).toContain('Agent (1)')
    expect(text).toContain('Task (1)')
    desk.cleanup()
  })

  it('T opens the task modal, captures typed text, and submits forecast.desk.task with the batch + toast', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // A terminal TASK JobRecord: the agent's own task_summary rides `result` and
    // leads the completion toast (mode resolved from the record's `type`).
    const record = {
      done_count: 1,
      job_id: 'run_1',
      result: { results: [{ committed: true, question_id: 'fq_a' }], task_summary: 'added a watched source and reforecast' },
      spec: { question_ids: ['fq_a'] },
      status: 'done',
      total: 1,
      type: 'task'
    }
    const desk = await mountDesk(120, multiFixture(), jobGw(multiFixture(), calls, record))
    await desk.press(' ') // mark fq_a → the task batch is {fq_a}
    await desk.press('T')
    let text = desk.text()
    expect(text).toContain('Agent task')
    expect(text).toContain('What should the agent do with these 1 question')
    await desk.press('add a watched source')
    expect(desk.text()).toContain('add a watched source')
    await desk.press('\r') // submit
    await tick(220)
    const task = calls.find(c => c.method === 'forecast.desk.task')
    expect(task).toBeDefined()
    expect(task?.params.instruction).toBe('add a watched source')
    expect(task?.params.question_ids).toEqual(['fq_a'])
    // Task mode leads the toast with the agent's own task_summary.
    text = desk.text()
    expect(text).toContain('added a watched source and reforecast')
    desk.cleanup()
  })

  it('Esc cancels the task modal without dispatching a task', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const desk = await mountDesk(120, multiFixture(), recordingGw(multiFixture(), calls))
    await desk.press(' ')
    await desk.press('T')
    await desk.press('never mind')
    await desk.press('\x1b') // Esc → cancel
    await tick(60)
    expect(calls.some(c => c.method === 'forecast.desk.task')).toBe(false)
    desk.cleanup()
  })

  it('summarizeAgentJob leads task mode with the task_summary, agent mode with the committed/blocked split', async () => {
    const { summarizeAgentJob } = await import('../components/deskView.js')
    const agent = summarizeAgentJob(
      {
        quorums_started: 4,
        results: [
          { committed: true, question_id: 'a' },
          ...Array.from({ length: 11 }, (_, i) => ({ committed: true, question_id: `c${i}` })),
          { committed: false, question_id: 'b1' },
          { committed: false, question_id: 'b2' },
          { committed: false, error: 'x', question_id: 'e1' },
          { committed: false, error: 'y', question_id: 'e2' },
          { committed: false, error: 'z', question_id: 'e3' }
        ],
        status: 'done'
      },
      'agent'
    )
    expect(agent).toContain('12 committed')
    expect(agent).toContain('2 blocked')
    expect(agent).toContain('3 errors')
    expect(agent).toContain('4 quorum')
    // Task mode with a summary leads with it.
    expect(summarizeAgentJob({ results: [], status: 'done', task_summary: 'did the thing' }, 'task')).toBe('✓ did the thing')
    // Task mode WITHOUT a summary falls back to the same split.
    expect(summarizeAgentJob({ results: [{ committed: true, question_id: 'a' }], status: 'done' }, 'task')).toContain('1 committed')
  })
})

describe('DeskView agent-run visibility', () => {
  const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

  it('re-attaches to a live detached job on mount and animates the working row', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // A live reforecast JobRecord (jobs.status/jobs.active shape): the per-question
    // pointer rides annotations.current; the target batch rides spec.question_ids.
    const record = {
      annotations: { current: { question_id: 'fq_a', stage: 'research', title: 'A' }, results: [] },
      done_count: 0,
      job_id: 'run_9',
      progress: [],
      spec: { question_ids: ['fq_a', 'fq_b'] },
      status: 'running',
      total: 2,
      type: 'reforecast'
    }
    const resp = (): ForecastWorkspaceResponse => ({
      active_count: 3,
      closing_soon_count: 0,
      forecasts: [plainRow('fq_a', 'Alpha question'), plainRow('fq_b', 'Beta question'), plainRow('fq_c', 'Gamma question')],
      generated_at: '2026-06-29T14:00:00Z',
      open_alert_count: 0,
      product: 'Superforecasting Agent'
    })
    const gw = {
      request: (method: string, params: Record<string, unknown>) => {
        calls.push({ method, params })
        if (method === 'jobs.active') {
          return Promise.resolve({ count: 1, jobs: [record] })
        }
        if (method === 'jobs.status') {
          return Promise.resolve({ found: true, job: record })
        }
        if (method === 'forecast.question') {
          return Promise.resolve({ packet: { question: { id: params.id, title: 'pkt' } } })
        }
        return Promise.resolve(resp())
      }
    } as never

    const desk = await mountDesk(120, resp(), gw)
    // The mount discovery found the live job and the poller attached to it.
    await tick(300)
    expect(calls.some(c => c.method === 'jobs.active')).toBe(true)
    expect(calls.some(c => c.method === 'jobs.status' && c.params.job_id === 'run_9')).toBe(true)
    // The working row (fq_a, per status.current) shows an animated braille
    // spinner frame; the queued row shows the in-flight ⋯ marker.
    await tick(700)
    const text = desk.text()
    expect(SPIN.some(f => text.includes(f))).toBe(true)
    expect(text).toContain('⋯')
    // The animation actually MOVES: the cumulative buffer accumulates more
    // than one distinct frame across further 500ms ticks.
    await tick(1300)
    const later = desk.text()
    const seen = SPIN.filter(f => later.includes(f))
    expect(seen.length).toBeGreaterThanOrEqual(2)
    desk.cleanup()
  })
})

describe('DeskView detached REFRESH jobs (U / mass-U)', () => {
  const SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

  it('re-attaches to a live REFRESH job on mount (jobs.active) and resumes the spinner + ⋯ markers', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    // A live job the operator started before leaving the Desk: fq_a is in flight
    // (current), fq_b is still queued. jobs.active discovers it on mount; the poller
    // then resumes the visuals — the whole point of moving the loop onto the runtime.
    const liveJob = {
      annotations: { results: [] },
      current: 'fq_a',
      done_count: 0,
      job_id: 'job_9',
      spec: { question_ids: ['fq_a', 'fq_b'] },
      status: 'running',
      total: 2
    }
    const runningStatus = {
      annotations: { results: [] },
      current: 'fq_a',
      done_count: 0,
      job_id: 'job_9',
      spec: { question_ids: ['fq_a', 'fq_b'] },
      status: 'running',
      total: 2
    }
    const resp = (): ForecastWorkspaceResponse => ({
      active_count: 3,
      closing_soon_count: 0,
      forecasts: [plainRow('fq_a', 'Alpha question'), plainRow('fq_b', 'Beta question'), plainRow('fq_c', 'Gamma question')],
      generated_at: '2026-06-29T14:00:00Z',
      open_alert_count: 0,
      product: 'Superforecasting Agent'
    })
    const desk = await mountDesk(120, resp(), refreshGw(resp(), calls, runningStatus, [liveJob]))
    await tick(300)
    // The mount discovery found the live job and the poller attached to it by id.
    expect(calls.some(c => c.method === 'jobs.active')).toBe(true)
    expect(calls.some(c => c.method === 'jobs.status' && c.params.job_id === 'job_9')).toBe(true)
    // fq_a (current) animates a braille spinner; the queued fq_b shows the ⋯ marker.
    await tick(700)
    const text = desk.text()
    expect(SPIN.some(f => text.includes(f))).toBe(true)
    expect(text).toContain('⋯')
    desk.cleanup()
  })

  it('the completion toast matches the old client-side wording exactly (summarizeUpdate parity)', async () => {
    const { summarizeUpdate } = await import('../components/deskView.js')
    // The wording the desk used to build client-side, now fed by the job's tally.
    expect(summarizeUpdate({ error: 0, noSources: 0, refreshed: 7, unchanged: 0 })).toBe('✓ 7 updated')
    expect(summarizeUpdate({ error: 2, noSources: 7, refreshed: 7, unchanged: 3 })).toBe(
      '✓ 7 updated · 3 unchanged · 7 no sources · 2 failed'
    )
    // A run that refreshed nothing still says so honestly (updated always shown).
    expect(summarizeUpdate({ error: 0, noSources: 4, refreshed: 0, unchanged: 0 })).toBe('✓ 0 updated · 4 no sources')
  })
})

describe('sidebar wrap law', () => {
  it('the focused title WRAPS in the summary panel (no … chop) and long teasers end honestly', async () => {
    // useStdout reports nothing in the inline harness (the desk falls back to
    // 80 cols and never mounts the two-pane panel), so pin the contract at the
    // COMPONENT level with a deterministic width — the pmSection pattern.
    const { render } = await import('@hermes/ink')
    const { DeskSummary } = await import('../components/deskView.js')
    const { DARK_THEME } = await import('../theme.js')
    const item = plainRow('fq_long', 'Will the market begin pricing AI-infrastructure scarcity as a persistent macro constraint through 2027?')
    const stdout = writeStream(60, 40)
    const inst = render(
      React.createElement(DeskSummary as never, {
        latestNote: {
          body: 'Still a lean no at 37 percent, with overbuild risk reading as more of a 2027 tail scenario than the base case for the year ahead.',
          headline: null
        },
        refFactor: undefined, refThesis: undefined,
        selected: item, t: DARK_THEME, width: 44
      }),
      { exitOnCtrlC: false, patchConsole: false, stdout: stdout.stream }
    )
    await tick(80)
    inst.unmount?.()
    const text = stripAnsiLocal(stdout.text())
    expect(text).toContain('through')
    expect(text).toContain('2027?')
    expect(text).not.toContain('AI-infrastr…')
    // The teaser reads to its END (the old silent slice(0,120) chopped it).
    expect(text).toContain('year ahead')
  })
})

const stripAnsiLocal = (s: string): string => s.replace(new RegExp(String.fromCharCode(27) + '\\[[0-9;]*m', 'g'), '')
