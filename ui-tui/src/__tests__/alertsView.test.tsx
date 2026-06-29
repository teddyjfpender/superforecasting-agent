import { EventEmitter } from 'node:events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ForecastDashboardResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

// A dashboard payload with three open alerts: two QUESTION-scoped (cursor-eligible)
// and one source-scoped (skipped by the cursor, marked "review").
const dashboard = (): ForecastDashboardResponse => ({
  summary: {
    alerts: [
      {
        id: 'al_pm',
        reason: 'postmortem_due',
        recommended_action: 'score the resolved question',
        scope_ref: 'fq_alpha',
        scope_type: 'question',
        severity: 'high'
      },
      {
        id: 'al_src',
        reason: 'watched_source_changed:fred:DGS10',
        recommended_action: 're-check the source',
        scope_ref: 'fred:DGS10',
        scope_type: 'source',
        severity: 'warning'
      },
      {
        id: 'al_stale',
        reason: 'evidence_stale_7d_plus',
        recommended_action: 'reforecast',
        scope_ref: 'fq_beta',
        scope_type: 'question',
        severity: 'warning'
      }
    ],
    open_alert_count: 3,
    review_queue: []
  }
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

interface Call {
  method: string
  params: Record<string, unknown>
}

// An EventEmitter-backed fake gateway: request() records calls + returns canned
// results, and on/off/emit drive the streamed automode events.
const fakeGw = (calls: Call[]) => {
  const gw = new EventEmitter() as EventEmitter & {
    request: (method: string, params?: Record<string, unknown>) => Promise<unknown>
  }
  gw.setMaxListeners(50)
  gw.request = (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })

    if (method === 'forecast.dashboard') {
      return Promise.resolve(dashboard())
    }
    if (method === 'forecast.warnings.resolve') {
      return Promise.resolve({
        count: 1,
        results: [{ acknowledged: true, alert_id: params.alert_id, detail: 'bookkeeping notice acknowledged', status: 'resolved' }]
      })
    }
    if (method === 'forecast.warnings.automode.run') {
      return Promise.resolve({ dry_run: false, job_id: 'wj_test' })
    }
    if (method === 'forecast.warnings.automode.cancel') {
      return Promise.resolve({ cancelled: true, found: true, job_id: params.job_id })
    }

    return Promise.resolve({})
  }

  return gw
}

const mount = async () => {
  process.env.FORECAST_TUI_INLINE = '1'
  const calls: Call[] = []
  const gw = fakeGw(calls)

  const [{ Box, render }, { AlertsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/alertsView.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 40)
  const stdin = writeStream(120, 40, true)

  const instance = render(
    React.createElement(
      Box,
      { flexDirection: 'column', height: 40, width: 120 },
      React.createElement(AlertsView, {
        gw: gw as never,
        onClose: () => undefined,
        sessionId: 'sess-1',
        t: DARK_THEME
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  await tick(80)

  return {
    calls,
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    emit: (event: string, payload: unknown) => gw.emit(event, payload),
    press: async (keys: string) => {
      stdin.stream.write(keys)
      await tick(50)
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

describe('AlertsView warning resolution', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the backlog, the resolvable count, and skips the non-question row', async () => {
    const m = await mount()
    const text = m.text()
    expect(text).toContain('WARNINGS')
    expect(text).toContain('Open alerts (3)')
    // Two of the three alerts are question-scoped → resolvable.
    expect(text).toContain('2 resolvable')
    // The source-scoped alert is flagged as review-only (cursor skips it).
    expect(text).toContain('(review)')
    m.cleanup()
  })

  it('`a` resolves the selected (first question-scoped) alert via the gated RPC', async () => {
    const m = await mount()
    await m.press('a')
    await tick(40)
    const resolve = m.calls.find(c => c.method === 'forecast.warnings.resolve')
    expect(resolve).toBeTruthy()
    // The cursor starts on al_pm (the source row al_src is skipped).
    expect(resolve?.params.alert_id).toBe('al_pm')
    expect(m.text()).toContain('resolved')
    m.cleanup()
  })

  it('Down-arrow moves the cursor to the next question-scoped alert before resolving', async () => {
    const m = await mount()
    await m.press(`${ESC}[B`) // down → al_stale (skips the source row)
    await m.press('a')
    await tick(40)
    const resolve = m.calls.find(c => c.method === 'forecast.warnings.resolve')
    expect(resolve?.params.alert_id).toBe('al_stale')
    m.cleanup()
  })

  it('Enter opens the resolve sheet showing the kind + reason, and confirming calls resolve', async () => {
    const m = await mount()
    await m.press('\r') // open sheet on al_pm
    const text = m.text()
    expect(text).toContain('Resolve alert')
    expect(text).toContain('WILL RUN')
    expect(text).toContain('postmortem')
    expect(text).toContain('postmortem_due')
    // Confirm.
    await m.press('y')
    await tick(40)
    const resolve = m.calls.find(c => c.method === 'forecast.warnings.resolve')
    expect(resolve?.params.alert_id).toBe('al_pm')
    m.cleanup()
  })

  it('Shift-A starts AUTOMODE, streams a live progress line, and finishes on complete', async () => {
    const m = await mount()
    await m.press('A')
    await tick(40)
    const run = m.calls.find(c => c.method === 'forecast.warnings.automode.run')
    expect(run).toBeTruthy()
    expect(run?.params.session_id).toBe('sess-1')

    // A progress heartbeat renders the live automode line.
    m.emit('forecast.warnings.automode.progress', {
      done: 1,
      job_id: 'wj_test',
      phase: 'alert',
      reason: 'postmortem_due',
      total: 3
    })
    await tick(40)
    expect(m.text()).toContain('automode')
    expect(m.text()).toContain('1/3')

    // Completion clears the line and flashes the tally.
    m.emit('forecast.warnings.automode.complete', { cancelled: false, job_id: 'wj_test', processed: 3, total: 3 })
    await tick(40)
    expect(m.text()).toContain('automode done')
    m.cleanup()
  })

  it('Shift-A while running cancels the job', async () => {
    const m = await mount()
    await m.press('A')
    await tick(40)
    // Confirm a job is live.
    m.emit('forecast.warnings.automode.progress', { done: 0, job_id: 'wj_test', phase: 'start', total: 3 })
    await tick(40)
    await m.press('A') // toggle → cancel
    await tick(40)
    const cancel = m.calls.find(c => c.method === 'forecast.warnings.automode.cancel')
    expect(cancel?.params.job_id).toBe('wj_test')
    m.cleanup()
  })
})
