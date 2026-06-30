import { EventEmitter } from 'node:events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ForecastDashboardResponse, ForecastWarningsAggregateResponse } from '../gatewayTypes.js'

const ESC = String.fromCharCode(27)
const BEL = String.fromCharCode(7)
const CSI_RE = new RegExp(`${ESC}\\[[0-?]*[ -/]*[@-~]`, 'g')
const OSC_RE = new RegExp(`${ESC}\\][\\s\\S]*?(?:${BEL}|${ESC}\\\\)`, 'g')

// The aggregate fold the tree renders from: a FREE tier (auto-clearable), an AGENT
// tier carrying a STALE sub-bucket, and an empty MANUAL tier. Headline reflects the
// whole backlog (4 open · 2 free · 2 agent · 0 manual).
const aggregate = (): ForecastWarningsAggregateResponse => ({
  agent: {
    reasons: [
      {
        auto_resolvable: false,
        count: 2,
        kind: 'reforecast',
        reason: 'evidence_stale',
        recommended_action: 'reforecast',
        scope_refs: ['fq_beta', 'fq_gamma']
      }
    ],
    stale: {
      reasons: [
        {
          auto_resolvable: false,
          count: 2,
          kind: 'reforecast',
          reason: 'evidence_stale',
          recommended_action: 'reforecast',
          scope_refs: ['fq_beta', 'fq_gamma']
        }
      ],
      total: 2
    },
    total: 2
  },
  free: {
    reasons: [
      {
        auto_resolvable: true,
        count: 2,
        kind: 'postmortem',
        reason: 'postmortem_due',
        recommended_action: 'score the resolved question',
        scope_refs: ['fq_alpha', 'fq_delta']
      }
    ],
    total: 2
  },
  headline: { agent: 2, free: 2, manual: 0, total: 4 },
  manual: { reasons: [], total: 0 }
})

// The dashboard still feeds the review-queue / readiness sections kept below.
const dashboard = (): ForecastDashboardResponse => ({
  summary: {
    alerts: [],
    open_alert_count: 4,
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

  // reset() drops the accumulated frames so a post-action assertion can test for
  // the ABSENCE of text (the PassThrough otherwise keeps every frame ever drawn).
  return { reset: () => { output = '' }, stream, text: () => output }
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

    if (method === 'forecast.warnings.aggregate') {
      return Promise.resolve(aggregate())
    }
    if (method === 'forecast.dashboard') {
      return Promise.resolve(dashboard())
    }
    if (method === 'forecast.warnings.automode.run') {
      return Promise.resolve({ dry_run: false, job_id: 'wj_test' })
    }
    if (method === 'forecast.warnings.automode.cancel') {
      return Promise.resolve({ cancelled: true, found: true, job_id: params.job_id })
    }
    if (method === 'forecast.warnings.dismiss') {
      return Promise.resolve({ count: 1, dismissed: [], matched: 1 })
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
    // Drop accumulated frames so the next text() only reflects fresh renders.
    clear: () => stdout.reset(),
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

  it('renders the aggregate headline and the 4 tier nodes from forecast.warnings.aggregate', async () => {
    const m = await mount()
    const text = m.text()
    expect(text).toContain('WARNINGS')
    // The headline folds the whole backlog into action tiers.
    expect(text).toContain('4 open')
    expect(text).toContain('2 free')
    expect(text).toContain('2 agent')
    expect(text).toContain('0 manual')
    // All four tier nodes (FREE / AGENT / MANUAL / STALE) + affordances render.
    expect(text).toContain('FREE')
    expect(text).toContain('AGENT')
    expect(text).toContain('MANUAL')
    expect(text).toContain('STALE')
    expect(text).toContain('auto')
    expect(text).toContain('needs-agent')
    // Expanded reason rows show count + recommended_action + scope_refs.
    expect(text).toContain('postmortem_due')
    expect(text).toContain('score the resolved question')
    expect(text).toContain('fq_alpha')
    m.cleanup()
  })

  it('Enter on a tier header collapses it, hiding its reason rows from the tree', async () => {
    const m = await mount()
    // Cursor starts on the FREE header → Enter collapses it.
    expect(m.text()).toContain('postmortem_due')
    m.clear()
    await m.press('\r')
    // The FREE reason row is now hidden, but the tier header (and others) remain.
    expect(m.text()).not.toContain('postmortem_due')
    expect(m.text()).toContain('FREE')
    expect(m.text()).toContain('AGENT')
    // Re-expand restores the reason row.
    m.clear()
    await m.press('\r')
    expect(m.text()).toContain('postmortem_due')
    m.cleanup()
  })

  it('Down-arrow walks the FLATTENED node list, skipping a collapsed tier\'s reason rows', async () => {
    const m = await mount()
    // Collapse FREE; its reason row leaves the flattened cursor list so the next
    // node below the FREE header is the AGENT header.
    await m.press('\r') // collapse FREE
    await m.press(`${ESC}[B`) // down → AGENT header (FREE's reason row is hidden)
    // Collapsing AGENT from here folds its reason rows too → the tree shrank but
    // the cursor stays valid (derived clamp) and no node is orphaned.
    m.clear()
    await m.press('\r') // collapse AGENT
    const text = m.text()
    expect(text).toContain('AGENT')
    expect(text).toContain('STALE')
    // Re-expand AGENT to confirm the cursor is still parked on that header.
    m.clear()
    await m.press('\r')
    expect(m.text()).toContain('evidence_stale')
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

  it('R runs the FREE pass scoped to the focused tier (tier="free")', async () => {
    const m = await mount()
    // Cursor starts on the FREE header → R runs the whole free tier.
    await m.press('R')
    await tick(40)
    const run = m.calls.find(c => c.method === 'forecast.warnings.automode.run')
    expect(run).toBeTruthy()
    expect(run?.params.tier).toBe('free')
    expect(run?.params.session_id).toBe('sess-1')
    m.cleanup()
  })

  it('R narrows the FREE pass to the focused reason row', async () => {
    const m = await mount()
    // Down once → the FREE reason row (postmortem_due); R narrows to that reason.
    await m.press(`${ESC}[B`)
    await m.press('R')
    await tick(40)
    const run = m.calls.find(c => c.method === 'forecast.warnings.automode.run')
    expect(run?.params.tier).toBe('free')
    expect(run?.params.reason).toBe('postmortem_due')
    m.cleanup()
  })

  it('Shift-A runs the AGENT pass (tier="reforecast"), not the old plain toggle', async () => {
    const m = await mount()
    await m.press('A')
    await tick(40)
    const run = m.calls.find(c => c.method === 'forecast.warnings.automode.run')
    expect(run?.params.tier).toBe('reforecast')
    m.cleanup()
  })

  it('x requires a non-empty note before forecast.warnings.dismiss fires', async () => {
    const m = await mount()
    // x opens the dismiss modal on the focused FREE tier (kind=postmortem).
    await m.press('x')
    expect(m.text()).toContain('Dismiss')
    // A bare ⏎ with an empty note must NOT dismiss anything.
    await m.press('\r')
    expect(m.calls.find(c => c.method === 'forecast.warnings.dismiss')).toBeFalsy()
    expect(m.text()).toContain('note is required')
    // Type a note, then ⏎ confirms with note + actor=tui + the tier's kinds.
    await m.press('dup of fq_alpha')
    await m.press('\r')
    await tick(40)
    const dismiss = m.calls.find(c => c.method === 'forecast.warnings.dismiss')
    expect(dismiss).toBeTruthy()
    expect(dismiss?.params.note).toBe('dup of fq_alpha')
    expect(dismiss?.params.actor).toBe('tui')
    expect(dismiss?.params.kind).toEqual(['postmortem'])
    m.cleanup()
  })

  it('x on a reason row dismisses that exact reason; Esc cancels the modal', async () => {
    const m = await mount()
    await m.press(`${ESC}[B`) // → FREE reason row
    await m.press('x')
    expect(m.text()).toContain('Dismiss')
    // Esc closes the modal without dispatching.
    await m.press(ESC)
    expect(m.calls.find(c => c.method === 'forecast.warnings.dismiss')).toBeFalsy()
    // Re-open and confirm it targets reason=postmortem_due (the focused row).
    await m.press('x')
    await m.press('stale')
    await m.press('\r')
    await tick(40)
    const dismiss = m.calls.find(c => c.method === 'forecast.warnings.dismiss')
    expect(dismiss?.params.reason).toBe('postmortem_due')
    expect(dismiss?.params.kind).toBeUndefined()
    m.cleanup()
  })

  it('c collapses every tier; e expands them all again', async () => {
    const m = await mount()
    expect(m.text()).toContain('postmortem_due')
    expect(m.text()).toContain('evidence_stale')
    m.clear()
    await m.press('c') // collapse all → every reason row hidden
    expect(m.text()).not.toContain('postmortem_due')
    expect(m.text()).not.toContain('evidence_stale')
    // The four tier headers survive a collapse-all.
    expect(m.text()).toContain('FREE')
    expect(m.text()).toContain('AGENT')
    m.clear()
    await m.press('e') // expand all → reason rows return
    expect(m.text()).toContain('postmortem_due')
    expect(m.text()).toContain('evidence_stale')
    m.cleanup()
  })

  it('Tab jumps the cursor between tier headers without landing on a reason row', async () => {
    const m = await mount()
    // From FREE, Tab → AGENT header; x there opens a dismiss for the AGENT kinds.
    await m.press('\t')
    await m.press('x')
    await m.press('dupe')
    await m.press('\r')
    await tick(40)
    const dismiss = m.calls.find(c => c.method === 'forecast.warnings.dismiss')
    expect(dismiss?.params.kind).toEqual(['reforecast'])
    m.cleanup()
  })

  it('one keypress is one VISIBLE move even when a collapse stranded the cursor past the end', async () => {
    // The active-row marker (cursor ▸ + collapse caret ▸) renders inline, so a
    // collapsed tier the cursor sits on shows "▸ ▸ LABEL".
    const ACTIVE_COLLAPSED = (label: string) => `▸ ▸ ${label}`
    const m = await mount()
    // Walk the cursor down to the LAST node of the fully-expanded tree (the STALE
    // reason row). Six downs: free reason → AGENT → agent reason → MANUAL → STALE →
    // stale reason.
    for (let n = 0; n < 6; n++) {
      await m.press(`${ESC}[B`)
    }
    // Collapse every tier: the flat list shrinks from 7 nodes to 4 headers, which is
    // exactly the condition that used to strand `sel` past the end (the bug that made
    // the next keypress a no-op). The cursor parks on the last visible node (STALE).
    await m.press('c')
    expect(m.text()).toContain(ACTIVE_COLLAPSED('STALE'))
    m.clear()
    // ONE up-press must advance exactly one visible node (STALE → MANUAL), not merely
    // pull a stale index back into range without visibly moving.
    await m.press(`${ESC}[A`)
    const text = m.text()
    expect(text).toContain(ACTIVE_COLLAPSED('MANUAL'))
    expect(text).not.toContain(ACTIVE_COLLAPSED('STALE'))
    m.cleanup()
  })

  it('dismissing the STALE sub-view header silences its own reasons, not the whole reforecast kind', async () => {
    const m = await mount()
    // Tab FREE → AGENT → MANUAL → STALE (the agent-tier sub-view header).
    await m.press('\t')
    await m.press('\t')
    await m.press('\t')
    await m.press('x')
    expect(m.text()).toContain('Dismiss')
    await m.press('aging out')
    await m.press('\r')
    await tick(40)
    const dismiss = m.calls.find(c => c.method === 'forecast.warnings.dismiss')
    expect(dismiss).toBeTruthy()
    // STALE is a VIEW over AGENT, so it must narrow to its own reason strings — NOT
    // kind=['reforecast'], which would silence the ENTIRE reforecast tier.
    expect(dismiss?.params.reason).toEqual(['evidence_stale'])
    expect(dismiss?.params.kind).toBeUndefined()
    m.cleanup()
  })
})
