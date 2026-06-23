import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const fixture = () => ({
  enabled: true,
  glossary: [{ doc: 'Number of pooled drivers in ensemble_components.', kind: 'number', name: 'components.count' }],
  operators: ['>=', '<'],
  overrides: {},
  profile: 'standard',
  profiles: ['exploratory-lenient', 'standard', 'strict'],
  reasoning_methods: [{ doc: 'Update a prior on likelihood ratios.', name: 'bayesian' }],
  rules: [
    { blocks: true, category: 'saturation', default: 'error', doc: 'A deliberation panel must run (or record an explicit skip reason).', id: 'require_panel', is_user: false, remediation: 'run_panel', severity: 'error', source: 'profile' },
    { blocks: false, category: 'custom', check: { op: '>=', signal: 'components.count', value: 3 }, doc: 'need three drivers', id: 'min_drivers', is_user: true, issues: [], remediation: 'decompose', severity: 'warn', source: 'user', valid: true },
  ],
})

const writeStream = (columns: number, rows: number, isTTY = false) => {
  const stream = new PassThrough() as PassThrough & { columns: number; isRaw?: boolean; isTTY: boolean; ref?: () => PassThrough; rows: number; setRawMode?: (m: boolean) => void; unref?: () => PassThrough }
  let output = ''
  Object.assign(stream, { columns, isRaw: false, isTTY, rows, ref: () => stream, setRawMode: (m: boolean) => { stream.isRaw = m }, unref: () => stream })
  stream.on('data', chunk => { output += chunk.toString() })

  return { stream, text: () => output }
}

const normalize = (value: string, stripAnsi: (input: string) => string) =>
  stripAnsi(value.replace(OSC_RE, '').replace(CSI_RE, '')).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const renderView = async (cols = 120) => {
  process.env.FORECAST_TUI_INLINE = '1'

  const [{ render }, { HooksView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/hooksView.js'),
    import('../theme.js'),
    import('../lib/text.js'),
  ])

  const stdout = writeStream(cols, 50)
  const stdin = writeStream(cols, 50, true)
  const fakeGw = { request: () => Promise.resolve(fixture()) } as unknown as Parameters<typeof HooksView>[0]['gw']
  const instance = render(React.createElement(HooksView, { gw: fakeGw, onClose: () => undefined, t: DARK_THEME }), { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream })
  await tick(60)
  const text = normalize(stdout.text(), stripAnsi)
  instance.unmount?.()
  instance.cleanup?.()

  return text
}

describe('HooksView manager', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  // The inline render harness lays a flexDirection="row" out at content width, so
  // the right (inspector) pane of a two-pane view is not captured here — same
  // limitation the forecastDesk render test works around. We assert the master
  // pane + chrome (which do render) and cover the inspector's data shaping via the
  // exported pure helpers + the gateway RPC tests.
  it('renders the master pane + chrome: header, profile, grouped rules, severity chips, footer', async () => {
    const text = await renderView()
    expect(text).toContain('FORECAST HOOKS')
    expect(text).toContain('profile: standard')
    // category-grouped rule list with severity chips
    expect(text).toContain('saturation')
    expect(text).toContain('error')
    expect(text).toContain('require_panel')
    expect(text).toContain('custom')
    expect(text).toContain('min_drivers')
    // footer action chips
    expect(text).toContain('Severity')
    expect(text).toContain('Profile')
    expect(text).toContain('New rule')
  })

  it('ruleToInitial round-trips a user rule into the wizard form shape', async () => {
    const { ruleToInitial } = await import('../components/hooksView.js')
    const init = ruleToInitial({ blocks: false, category: 'custom', check: { op: '>=', signal: 'components.count', value: 3 }, doc: 'need drivers', id: 'r', is_user: true, remediation: 'decompose', severity: 'warn', source: 'user' })
    expect(init).toEqual({ conditions: [{ op: '>=', signal: 'components.count', value: '3' }], desc: 'need drivers', id: 'r', remediation: 'decompose', severity: 'warn' })
  })

  it('summarizeCheck renders an AND predicate from a check tree', async () => {
    const { summarizeCheck } = await import('../components/hooksView.js')
    expect(summarizeCheck({ signal: 'components.count', op: '>=', value: 3 })).toBe('components.count >= 3')
    expect(summarizeCheck({ all: [{ signal: 'components.count', op: '>=', value: 3 }, { signal: 'style.clean', op: 'is_true' }] }))
      .toBe('components.count >= 3  AND  style.clean is_true')
  })
})
