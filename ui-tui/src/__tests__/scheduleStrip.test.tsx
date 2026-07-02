import { EventEmitter } from 'node:events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ForecastScheduleStatusResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

const tick = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const HOUR = 3_600_000

// A healthy schedule: one enabled cron job that fired recently and is due again.
const healthy = (): ForecastScheduleStatusResponse => ({
  cron: {
    errored: [],
    healthy: true,
    installed: 1,
    jobs: [
      {
        enabled: true,
        errored: false,
        last_run_at: new Date(Date.now() - 2 * HOUR).toISOString(),
        missed: false,
        name: 'forecast-nightly',
        next_run_at: new Date(Date.now() + 6 * HOUR).toISOString()
      }
    ],
    missed: []
  },
  healthy: true,
  scheduled_review_count: 0,
  scheduled_reviews: []
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

const fakeGw = (status: unknown) => {
  const gw = new EventEmitter() as EventEmitter & {
    request: (method: string, params?: Record<string, unknown>) => Promise<unknown>
  }
  gw.request = (method: string) => {
    if (method === 'forecast.schedule.status') {
      return Promise.resolve(status)
    }

    return Promise.resolve({})
  }

  return gw
}

const mount = async (status: unknown) => {
  const [{ render }, { ScheduleStrip }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@hermes/ink'),
    import('../components/scheduleStrip.js'),
    import('../theme.js'),
    import('../lib/text.js')
  ])

  const stdout = writeStream(120, 40)

  const instance = render(React.createElement(ScheduleStrip, { gw: fakeGw(status) as never, t: DARK_THEME, width: 100 }), {
    exitOnCtrlC: false,
    patchConsole: false,
    stdout: stdout.stream
  })

  await tick(60)

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    text: () => normalize(stdout.text(), stripAnsi)
  }
}

// ── Pure health fold ──────────────────────────────────────────────────────────

describe('deriveScheduleHealth', () => {
  it('reports ok with next-run and last-fired when the jobs are healthy', async () => {
    const { deriveScheduleHealth } = await import('../components/scheduleStrip.js')
    const h = deriveScheduleHealth(healthy())

    expect(h.state).toBe('ok')
    expect(h.hasContent).toBe(true)
    expect(h.nextRun).toContain('in ')
    expect(h.lastRun).toContain('ago')
  })

  it('flips to errored (over missed) and carries the short error detail', async () => {
    const { deriveScheduleHealth } = await import('../components/scheduleStrip.js')
    const status = healthy()
    status.cron!.jobs![0].errored = true
    status.cron!.jobs![0].last_error = 'auth token expired'
    status.cron!.errored = ['forecast-nightly']
    // Even with a missed flag present, errored wins.
    status.cron!.jobs![0].missed = true

    const h = deriveScheduleHealth(status)
    expect(h.state).toBe('errored')
    expect(h.detail).toContain('auth token expired')
  })

  it('reports missed when a job is behind but not errored', async () => {
    const { deriveScheduleHealth } = await import('../components/scheduleStrip.js')
    const status = healthy()
    status.cron!.jobs![0].missed = true
    status.cron!.missed = ['forecast-nightly']

    expect(deriveScheduleHealth(status).state).toBe('missed')
  })

  it('has no content when nothing is scheduled', async () => {
    const { deriveScheduleHealth } = await import('../components/scheduleStrip.js')
    const empty: ForecastScheduleStatusResponse = {
      cron: { errored: [], healthy: true, installed: 0, jobs: [], missed: [] },
      healthy: true,
      scheduled_review_count: 0,
      scheduled_reviews: []
    }

    expect(deriveScheduleHealth(empty).hasContent).toBe(false)
    expect(deriveScheduleHealth(null).hasContent).toBe(false)
  })
})

// ── Rendered strip ─────────────────────────────────────────────────────────────

describe('ScheduleStrip render states', () => {
  afterEach(() => undefined)

  it('renders the ok verdict with next / last-fired segments', async () => {
    const m = await mount(healthy())
    const text = m.text()
    expect(text).toContain('SCHEDULE')
    expect(text).toContain('ok')
    expect(text).toContain('next in')
    expect(text).toContain('last fired')
    m.cleanup()
  })

  it('renders the errored verdict with the short error text', async () => {
    const status = healthy()
    status.cron!.jobs![0].errored = true
    status.cron!.jobs![0].last_error = 'ledger locked'
    status.cron!.errored = ['forecast-nightly']

    const m = await mount(status)
    const text = m.text()
    expect(text).toContain('last run errored')
    expect(text).toContain('ledger locked')
    m.cleanup()
  })

  it('renders the missed verdict', async () => {
    const status = healthy()
    status.cron!.jobs![0].missed = true
    status.cron!.missed = ['forecast-nightly']

    const m = await mount(status)
    expect(m.text()).toContain('missed')
    m.cleanup()
  })

  it('renders nothing when the desk has no schedule', async () => {
    const m = await mount({
      cron: { errored: [], healthy: true, installed: 0, jobs: [], missed: [] },
      healthy: true,
      scheduled_reviews: []
    })
    // The strip is hidden (no SCHEDULE header) when nothing is scheduled.
    expect(m.text()).not.toContain('SCHEDULE')
    m.cleanup()
  })
})
