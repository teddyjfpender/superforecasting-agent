import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ForecastConfigResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const config = (): ForecastConfigResponse => ({
  cadence: 'weekly',
  decision: { action_threshold: 'act if P > 0.7', decision_deadline: null, decision_owner: 'ops lead' },
  gates: [
    { default: 'error', id: 'require_evidence', label: 'At least one evidence record', looser: false, severity: 'error', source: 'profile' },
    { default: 'warn', id: 'quorum_participation', label: 'Enough panel/quorum perspectives', looser: true, severity: 'off', source: 'override' }
  ],
  next_run_at: '2026-07-01T00:00:00Z',
  profile: 'standard',
  question_id: 'fq_demo',
  thresholds: [
    {
      default: 3,
      direction: 'lower_looser',
      integer: true,
      key: 'min_perspectives',
      label: 'Min panel perspectives',
      looser: true,
      maximum: 12,
      minimum: 1,
      source: 'override',
      value: 2
    },
    {
      default: 1,
      direction: 'higher_looser',
      integer: false,
      key: 'max_width_ratio',
      label: 'Max interval width (x range)',
      looser: false,
      maximum: 10,
      minimum: 0.1,
      source: 'default',
      value: 1
    }
  ],
  title: 'Will the metric exceed 5 percent?'
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

const readinessFixture = () => ({
  gaps: [
    { fix_hint: 'no watched sources — `forecast watch add <source>`, or a T task', key: 'watches', label: 'watched sources' },
    { fix_hint: 'no active reference class — `forecast base-rate …`, or a T task', key: 'ref_classes', label: 'reference classes' }
  ],
  question_id: 'fq_demo',
  score: 64,
  src_count: 0,
  title: 'Will the metric exceed 5 percent?'
})

// Records every forecast.config.set call so we can assert the write payload.
const fakeGw = (cfg: ForecastConfigResponse, sink: Record<string, unknown>[], readiness: unknown = readinessFixture()) =>
  ({
    request: (method: string, params: Record<string, unknown>) => {
      if (method === 'forecast.config') {
        return Promise.resolve(cfg)
      }
      if (method === 'forecast.question.readiness') {
        return Promise.resolve(readiness)
      }
      if (method === 'forecast.config.set') {
        sink.push(params)
        return Promise.resolve(cfg)
      }
      return Promise.resolve({})
    }
  }) as never

const mountModal = async (cfg: ForecastConfigResponse) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const sink: Record<string, unknown>[] = []
  const saved: { count: number } = { count: 0 }

  const [{ Box, render }, { ForecastSettingsModal }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/forecastSettingsModal.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 40)
  const stdin = writeStream(120, 40, true)

  // The modal is an ABSOLUTE overlay; in the real desk it paints above a full-
  // height body. Mount it inside an explicitly-sized parent so the headless
  // (inline) renderer has a flow box to place the absolute overlay against.
  const instance = render(
    React.createElement(
      Box,
      { flexDirection: 'column', height: 40, width: 120 },
      React.createElement(ForecastSettingsModal, {
        cols: 120,
        gw: fakeGw(cfg, sink),
        onClose: () => undefined,
        onSaved: () => {
          saved.count += 1
        },
        questionId: 'fq_demo',
        rows: 40,
        t: DARK_THEME,
        title: 'Demo question'
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(80)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(40)
    },
    saved,
    sink,
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('ForecastSettingsModal', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the four sections with the resolved cadence, decision, gates, and thresholds', async () => {
    const m = await mountModal(config())
    // A no-op key press forces the inline renderer to flush a frame.
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[A`)
    const text = m.text()
    expect(text).toContain('CADENCE')
    expect(text).toContain('weekly')
    expect(text).toContain('DECISION CARD')
    expect(text).toContain('ops lead')
    expect(text).toContain('GATES')
    expect(text).toContain('At least one evidence record')
    expect(text).toContain('THRESHOLDS')
    expect(text).toContain('Min panel perspectives')
    // Default value + the registry default are both surfaced.
    expect(text).toContain('def 3')
    m.cleanup()
  })

  it('flags a LOOSER override so a relaxed gate/threshold is never silent', async () => {
    const m = await mountModal(config())
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[A`)
    const text = m.text()
    // quorum_participation is overridden OFF (looser) and min_perspectives is below
    // its default — both must carry the looser marker.
    expect(text).toContain('looser')
    m.cleanup()
  })

  it('Save writes forecast.config.set with the cadence, decision, and overrides', async () => {
    const m = await mountModal(config())
    // Down-arrow clamps at the last field (the Save row); press plenty, then ⏎.
    for (let i = 0; i < 20; i += 1) {
      await m.press(`${ESC}[B`)
    }
    await m.press('\r')
    // Give the async save a beat.
    await tick(40)
    expect(m.sink.length).toBeGreaterThanOrEqual(1)
    const payload = m.sink[m.sink.length - 1]
    expect(payload.id).toBe('fq_demo')
    expect(payload.review_cadence).toBe('weekly')
    const hooks = payload.hooks as { overrides: Record<string, string>; thresholds: Record<string, number> }
    // The overridden gate is written; the unchanged require_evidence (== default) is not.
    expect(hooks.overrides.quorum_participation).toBe('off')
    expect(hooks.overrides.require_evidence).toBeUndefined()
    // The overridden threshold is written; the at-default one is not.
    expect(hooks.thresholds.min_perspectives).toBe(2)
    expect(hooks.thresholds.max_width_ratio).toBeUndefined()
    m.cleanup()
  })

  it('leads with a READINESS section — the score + the full gaps list with fix hints — above the config', async () => {
    const m = await mountModal(config())
    await m.press(`${ESC}[B`)
    await m.press(`${ESC}[A`)
    const text = m.text()
    // The section header + banded score + gap count, fetched from forecast.question.readiness.
    expect(text).toContain('READINESS')
    expect(text).toContain('64/100')
    // The FULL gaps list (both dimensions) with their exact-fix hints.
    expect(text).toContain('watched sources')
    expect(text).toContain('reference classes')
    expect(text).toContain('or a T task')
    // The existing config controls still render below it.
    expect(text).toContain('CADENCE')
    expect(text).toContain('GATES')
    m.cleanup()
  })
})
