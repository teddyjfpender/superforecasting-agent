import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { ForecastWorkspaceResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

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

// A "chips row" = a normalized line carrying at least three `[k Label]` bracket
// chips (the FooterChips row). The removed prose duplicate carried NO brackets.
const hasChipsRow = (text: string): boolean =>
  text.split('\n').some(line => (line.match(/\]/g) ?? []).length >= 3)

// The DISTINCT shortcut-row styles present in the buffer. Frame-independent (a
// style is present or not, regardless of how many cumulative frames the non-TTY
// harness kept): the operator's bug was TWO styles per view (chips + prose); the
// fix leaves exactly one.
const shortcutStyles = (text: string, prose: string): string[] =>
  [hasChipsRow(text) ? 'chips' : '', text.includes(prose) ? 'prose' : ''].filter(Boolean)

describe('MarketsView column sort', () => {
  let home: string

  beforeEach(() => {
    home = mkdtempSync(join(tmpdir(), 'mkt-sort-'))
    process.env.FORECAST_HOME = home
    process.env.FORECAST_TUI_INLINE = '1'

    // A watchlist so the quote table renders without any network, plus a fresh
    // quote cache (recent asOf → the mount refresh skips fetching).
    const watchlist = [
      { category: 'Stocks', name: 'Apple', provider: 'yahoo', symbol: 'AAPL' },
      { category: 'Stocks', name: 'Microsoft', provider: 'yahoo', symbol: 'MSFT' },
      { category: 'Stocks', name: 'Nvidia', provider: 'yahoo', symbol: 'NVDA' }
    ]

    writeFileSync(join(home, 'markets.json'), JSON.stringify({ categories: [], custom: [], providers: [], watchlist }))
    const now = Date.now()

    const q = (symbol: string, name: string, value: number, changePct: number) => ({
      asOf: now,
      change: changePct,
      changePct,
      name,
      provider: 'yahoo',
      symbol,
      value,
      volume: value * 1000
    })

    writeFileSync(
      join(home, 'markets_cache.json'),
      JSON.stringify({
        'yahoo:AAPL': q('AAPL', 'Apple', 190, 1.2),
        'yahoo:MSFT': q('MSFT', 'Microsoft', 420, -0.4),
        'yahoo:NVDA': q('NVDA', 'Nvidia', 900, 3.1)
      })
    )
  })

  afterEach(() => {
    delete process.env.FORECAST_HOME
    delete process.env.FORECAST_TUI_INLINE
  })

  const mount = async (columns: number) => {
    const [{ render }, { MarketsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
      import('@superforecasting/ink'),
      import('../components/marketsView.js'),
      import('../theme.js'),
      import('../lib/text.js')
    ])

    const stdout = writeStream(columns, 40)
    const stdin = writeStream(columns, 40, true)
    const gw = { off: () => undefined, on: () => undefined, request: () => Promise.resolve({}) } as never

    const instance = render(
      React.createElement(MarketsView, { gw, onAsk: () => undefined, onClose: () => undefined, t: DARK_THEME }),
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

  it('o sorts a column (▲) and O toggles the direction (▼) on the quote table header', async () => {
    const view = await mount(150)
    // The seeded watchlist renders the dense quote table with its NAME column
    // (NAME is the top-priority column, always kept even when the headless flex
    // layout gives the table a narrow measured width).
    expect(view.text()).toContain('NAME')
    // `o` cycles SYMBOL → NAME; the second lands on NAME ascending → ▲ indicator.
    await view.press('o') // SYMBOL (priority-dropped in this headless layout)
    await view.press('o') // NAME
    expect(view.text()).toContain('NAME ▲')
    // `O` toggles the current column (NAME) to descending → ▼.
    await view.press('O')
    expect(view.text()).toContain('NAME ▼')
    view.cleanup()
  })

  it('o cycles forward through the columns in header order (a second o lands on NAME)', async () => {
    const view = await mount(150)
    await view.press('o') // SYMBOL
    await view.press('o') // NAME (next in header order)
    expect(view.text()).toContain('NAME ▲')
    view.cleanup()
  })
})

// ── The single-shortcuts-row regression ──────────────────────────────────────
// The operator saw a SECOND duplicate row of shortcuts under most views: the
// FooterChips row PLUS a prose restatement of the same keys. The prose row was
// removed (keep the top / chips row). This locks that in for all four views.
describe('single shortcuts row (no duplicate prose hint row)', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
    delete process.env.FORECAST_HOME
  })

  const deskFixture = (): ForecastWorkspaceResponse => ({
    active_count: 1,
    closing_soon_count: 0,
    forecasts: [
      {
        as_of: '2026-06-29T00:00:00Z',
        headline_kind: 'probability',
        headline_probability: 0.5,
        history: [{ as_of: '2026-06-29T00:00:00Z', headline_probability: 0.5 }],
        id: 'fq_x',
        snapshot_count: 1,
        status: 'active',
        title: 'A plain question',
        topics: ['x']
      }
    ],
    generated_at: '2026-06-29T14:00:00Z',
    open_alert_count: 0,
    product: 'X'
  })

  // Wide enough that the desk's full 11-chip FooterChips row fits on ONE line (a
  // narrower width wraps it, splitting chip labels across rows).
  const mountView = async (element: React.ReactElement, columns = 150) => {
    const [{ render }, { stripAnsi }] = await Promise.all([import('@superforecasting/ink'), import('../lib/text.js')])
    const stdout = writeStream(columns, 40)
    const stdin = writeStream(columns, 40, true)
    const instance = render(element, { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream })
    await tick(70)

    return {
      cleanup: () => {
        instance.unmount?.()
        instance.cleanup?.()
      },
      text: () => normalize(stdout.text(), stripAnsi)
    }
  }

  it('Desk shows exactly one (chips) shortcuts row — the prose duplicate is gone', async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ DeskView }, { DARK_THEME }, { clearOverlayCache }] = await Promise.all([
      import('../components/deskView.js'),
      import('../theme.js'),
      import('../lib/overlayCache.js')
    ])

    clearOverlayCache()
    const gw = { request: () => Promise.resolve(deskFixture()) } as never
    const view = await mountView(React.createElement(DeskView, { gw, onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    // The canonical chips row survives (its own `o Sort` chip proves it's the chips
    // row, not the removed prose) and it is the ONLY shortcut-row style — the prose
    // duplicate (`↑↓/jk select · Tab/←→ lens · …`) is gone.
    expect(text).toContain('o Sort')
    expect(shortcutStyles(text, '↑↓/jk select · Tab/←→ lens')).toEqual(['chips'])
    view.cleanup()
  })

  it('Markets shows exactly one (chips) shortcuts row — the prose duplicate is gone', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    process.env.FORECAST_HOME = mkdtempSync(join(tmpdir(), 'mkt-row-'))
    // A watchlist so the data-mode footer (dataChips) renders.
    writeFileSync(
      join(process.env.FORECAST_HOME, 'markets.json'),
      JSON.stringify({ categories: [], custom: [], providers: [], watchlist: [{ category: 'Stocks', name: 'Apple', provider: 'yahoo', symbol: 'AAPL' }] })
    )
    const [{ MarketsView }, { DARK_THEME }] = await Promise.all([import('../components/marketsView.js'), import('../theme.js')])
    const gw = { off: () => undefined, on: () => undefined, request: () => Promise.resolve({}) } as never
    const view = await mountView(React.createElement(MarketsView, { gw, onAsk: () => undefined, onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    expect(text).toContain('o Sort')
    expect(shortcutStyles(text, '↑↓/jk select · Tab/←→ category')).toEqual(['chips'])
    view.cleanup()
  })

  it('News shows exactly one (chips) shortcuts row — the prose duplicate is gone', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    process.env.FORECAST_HOME = mkdtempSync(join(tmpdir(), 'news-row-'))
    const [{ NewsView }, { DARK_THEME }] = await Promise.all([import('../components/newsView.js'), import('../theme.js')])
    const gw = { off: () => undefined, on: () => undefined, request: () => Promise.resolve({}) } as never
    const view = await mountView(React.createElement(NewsView, { gw, onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    expect(text).toContain('Add feed')
    expect(shortcutStyles(text, '↑↓/jk browse · / search')).toEqual(['chips'])
    view.cleanup()
  })

  it('Warnings (Alerts) shows exactly one (chips) shortcuts row — the prose row was converted', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ AlertsView }, { DARK_THEME }] = await Promise.all([import('../components/alertsView.js'), import('../theme.js')])

    // A non-empty aggregate so the tree footer (its full chip set) renders — the
    // empty backlog would show only [r Refresh] [q Close].
    const aggregate = {
      agent: { reasons: [{ auto_resolvable: false, count: 1, kind: 'reforecast', reason: 'evidence_stale', recommended_action: 'reforecast', scope_refs: ['fq_a'] }], stale: { reasons: [], total: 0 }, total: 1 },
      free: { reasons: [{ auto_resolvable: true, count: 1, kind: 'postmortem', reason: 'postmortem_due', recommended_action: 'score', scope_refs: ['fq_b'] }], total: 1 },
      headline: { agent: 1, free: 1, manual: 0, total: 2 },
      manual: { reasons: [], total: 0 }
    }

    const dashboard = { summary: { alerts: [], open_alert_count: 2, review_queue: [] } }

    const gw = {
      off: () => undefined,
      on: () => undefined,
      request: (method: string) =>
        Promise.resolve(
          method === 'forecast.warnings.aggregate' ? aggregate : method === 'forecast.dashboard' ? dashboard : {}
        )
    } as never

    const view = await mountView(React.createElement(AlertsView, { gw, onClose: () => undefined, sessionId: '', t: DARK_THEME }))
    const text = view.text()
    // The tree footer is now the single bracketed chips row; the old prose row
    // ("↑↓/jk move · ⏎/space expand · …") is gone.
    expect(text).toContain('Dismiss')
    expect(shortcutStyles(text, '↑↓/jk move · ⏎/space expand')).toEqual(['chips'])
    view.cleanup()
  })

  // The remaining fullscreen views converted from prose to chips this round: each
  // must render EXACTLY ONE (chips) shortcuts row and ZERO prose shortcut rows.
  it('Calibration shows exactly one (chips) shortcuts row', async () => {
    process.env.FORECAST_TUI_INLINE = '1'

    const [{ CalibrationView }, { DARK_THEME }, { clearOverlayCache }] = await Promise.all([
      import('../components/calibrationView.js'),
      import('../theme.js'),
      import('../lib/overlayCache.js')
    ])

    clearOverlayCache()
    const gw = { request: () => Promise.resolve({}) } as never
    const view = await mountView(React.createElement(CalibrationView, { gw, onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    expect(shortcutStyles(text, '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · r refresh · Esc/q close')).toEqual(['chips'])
    view.cleanup()
  })

  it('Help shows exactly one (chips) shortcuts row', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ HelpView }, { DARK_THEME }] = await Promise.all([import('../components/helpView.js'), import('../theme.js')])
    const view = await mountView(React.createElement(HelpView, { onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    expect(shortcutStyles(text, '↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · Esc/q close')).toEqual(['chips'])
    view.cleanup()
  })

  it('Demo-viz shows exactly one (chips) shortcuts row', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ DemoVizView }, { DARK_THEME }] = await Promise.all([import('../components/demoVizView.js'), import('../theme.js')])
    const view = await mountView(React.createElement(DemoVizView, { onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    expect(shortcutStyles(text, '↑↓/jk scroll · PgUp/PgDn · g/G top/bottom · Esc back')).toEqual(['chips'])
    view.cleanup()
  })

  it('Hooks shows exactly one (chips) shortcuts row — the inspector prose row is gone', async () => {
    process.env.FORECAST_TUI_INLINE = '1'
    const [{ HooksView }, { DARK_THEME }] = await Promise.all([import('../components/hooksView.js'), import('../theme.js')])

    const rule = {
      check: 'saturation < 40',
      default: 'warn',
      doc: 'Saturation floor',
      id: 'saturation_floor',
      is_user: false,
      severity: 'warn',
      source: 'built-in'
    }

    const gw = { request: () => Promise.resolve({ enabled: true, profile: 'default', rules: [rule] }) } as never
    const view = await mountView(React.createElement(HooksView, { gw, onClose: () => undefined, t: DARK_THEME }))
    const text = view.text()
    // The inspector's second prose key row ("c cycle severity · e enable · …") was
    // aggregated into the one chips row (e/d now chips).
    expect(shortcutStyles(text, 'c cycle severity · e enable')).toEqual(['chips'])
    view.cleanup()
  })
})
