import { EventEmitter } from 'node:events'
import { PassThrough } from 'stream'

import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { getOverlayState, resetOverlayState } from '../app/overlayStore.js'
import { isWarningsRunActive, setWarningsRunActive } from '../app/warningsRunStore.js'
import type {
  ForecastDashboardResponse,
  ForecastTriageContestedRow,
  ForecastWarningsAggregateResponse
} from '../gatewayTypes.js'
import { type Match, trackRequests, waitForQuiet, waitForText } from '../testing/settle.js'

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
// results, and on/off/emit drive the streamed automode events. `contestedStore`
// is MUTABLE — relabel splices the labeled row out so a reload reflects the ack.
const fakeGw = (
  calls: Call[],
  contestedStore: ForecastTriageContestedRow[],
  activeJobs: Array<Record<string, unknown>> = []
) => {
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

    if (method === 'forecast.triage.contested') {
      return Promise.resolve({ contested: [...contestedStore], count: contestedStore.length })
    }

    if (method === 'forecast.triage.relabel') {
      const idx = contestedStore.findIndex(row => row.id === params.label_id)

      if (idx >= 0) {
        contestedStore.splice(idx, 1)
      }

      return Promise.resolve({ count: idx >= 0 ? 1 : 0, success: true })
    }

    if (method === 'jobs.active') {
      return Promise.resolve({ count: activeJobs.length, jobs: activeJobs })
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

interface MountOpts {
  activeJobs?: Array<Record<string, unknown>>
  contested?: ForecastTriageContestedRow[]
  initialFocus?: 'contested'
}

const mount = async (opts: MountOpts = {}) => {
  process.env.FORECAST_TUI_INLINE = '1'
  const calls: Call[] = []
  const contestedStore: ForecastTriageContestedRow[] = [...(opts.contested ?? [])]
  const gw = fakeGw(calls, contestedStore, opts.activeJobs ?? [])
  // Track every RPC the view issues so the mount/press waits can drain them.
  const rpc = trackRequests(gw.request.bind(gw))

  gw.request = rpc.request

  const [{ Box, render }, { AlertsView }, { DARK_THEME }, { stripAnsi }] = await Promise.all([
    import('@superforecasting/ink'),
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
        initialFocus: opts.initialFocus,
        onClose: () => undefined,
        sessionId: 'sess-1',
        t: DARK_THEME
      })
    ),
    { exitOnCtrlC: false, patchConsole: false, stdin: stdin.stream, stdout: stdout.stream }
  )

  const read = () => normalize(stdout.text(), stripAnsi)

  // forecast.warnings.* are async. A fixed `tick(80)` asserted against whatever
  // was painted at 80ms — under load the `WARNINGS attention backlog` header-only
  // frame, before any tier had rendered. Wait for the RPCs the view issued to
  // have settled (sound: a component blocked on a promise cannot be mistaken for
  // a finished one), then for the resulting frame to settle.
  await rpc.drain()
  await waitForQuiet(read, { quietFor: 40, timeout: 4000 })

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
      // Wait for the key's own repaint plus any RPC it fired, instead of a flat
      // 50ms that the keypress pipeline alone can outlast under load.
      const before = read()

      stdin.stream.write(keys)

      try {
        await waitForText(read, value => value !== before, { label: 'the keypress repaint', timeout: 2000 })
      } catch {
        // Keys whose only effect is an RPC paint nothing.
      }

      await rpc.drain()
      await waitForQuiet(read, { quietFor: 24, timeout: 1500 })
    },
    text: () => read(),
    waitFor: (match: Match, label?: string) => waitForText(read, match, { label })
  }
}

describe('AlertsView warning resolution', () => {
  afterEach(() => {
    resetOverlayState()
    setWarningsRunActive(false)
    delete process.env.FORECAST_TUI_INLINE
  })

  it('h opens the unified Help modal — tree-nav keys do not', async () => {
    resetOverlayState()
    const m = await mount()
    expect(getOverlayState().cheatSheet).toBe(false)
    // A tree-nav key ([ = previous tier) must NOT open Help.
    await m.press('[')
    expect(getOverlayState().cheatSheet).toBe(false)
    // h opens the unified Help modal.
    await m.press('h')
    expect(getOverlayState().cheatSheet).toBe(true)
    m.cleanup()
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
    // Expanded reason rows show count + recommended_action + scope_refs; the raw
    // snake_case reason key renders sentence-cased ("postmortem_due" → "Postmortem due").
    expect(text).toContain('Postmortem due')
    // The raw debug token never leaks to the surface (sentence-cased for display).
    expect(text).not.toContain('postmortem_due')
    expect(text).toContain('score the resolved question')
    expect(text).toContain('fq_alpha')
    m.cleanup()
  })

  it('loads the dashboard in FAST mode (the view only reads fast-carried fields)', async () => {
    const m = await mount()
    const dash = m.calls.find(c => c.method === 'forecast.dashboard')
    expect(dash).toBeTruthy()
    // At 120q/1250 alerts the full build measured ~1s vs ~0.2s fast; this view
    // reads only review_queue + stale counts, all carried in fast mode.
    expect(dash?.params.fast).toBe(true)
    expect(dash?.params.limit).toBe(50)
    m.cleanup()
  })

  it('Enter on a tier header collapses it, hiding its reason rows from the tree', async () => {
    const m = await mount()
    // Cursor starts on the FREE header → Enter collapses it. (Reason rows render
    // the sentence-cased reason key: "postmortem_due" → "Postmortem due".)
    expect(m.text()).toContain('Postmortem due')
    m.clear()
    await m.press('\r')
    // The FREE reason row is now hidden, but the tier header (and others) remain.
    expect(m.text()).not.toContain('Postmortem due')
    expect(m.text()).toContain('FREE')
    expect(m.text()).toContain('AGENT')
    // Re-expand restores the reason row.
    m.clear()
    await m.press('\r')
    expect(m.text()).toContain('Postmortem due')
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
    expect(m.text()).toContain('Evidence stale')
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
    // Reason keys render sentence-cased ("postmortem_due" → "Postmortem due").
    expect(m.text()).toContain('Postmortem due')
    expect(m.text()).toContain('Evidence stale')
    m.clear()
    await m.press('c') // collapse all → every reason row hidden
    expect(m.text()).not.toContain('Postmortem due')
    expect(m.text()).not.toContain('Evidence stale')
    // The four tier headers survive a collapse-all.
    expect(m.text()).toContain('FREE')
    expect(m.text()).toContain('AGENT')
    m.clear()
    await m.press('e') // expand all → reason rows return
    expect(m.text()).toContain('Postmortem due')
    expect(m.text()).toContain('Evidence stale')
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
    // The active-row marker (cursor ▸ + collapse caret ▸ + tier-colour bullet ●)
    // renders inline, so a collapsed tier the cursor sits on shows "▸ ▸ ● LABEL".
    const ACTIVE_COLLAPSED = (label: string) => `▸ ▸ ● ${label}`
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

// Two contested triage rows the auto-labeler disputed, awaiting a hand-label.
const contestedRows = (): ForecastTriageContestedRow[] => [
  {
    alert_id: 'al_1',
    auto_label: 'relevant_uninteresting',
    candidate_ref: 'ev_1',
    id: 'tl_1',
    question_id: 'fq_alpha',
    rationale: 'near the decision boundary — a verifier disagreed',
    title: 'Reuters: Fed signals a hold'
  },
  {
    alert_id: 'al_2',
    auto_label: 'irrelevant',
    candidate_ref: 'ev_2',
    id: 'tl_2',
    question_id: 'fq_beta',
    rationale: 'source reliability disputed',
    title: 'Blog rumor on a rate cut'
  }
]

describe('AlertsView contested-triage lens', () => {
  afterEach(() => {
    delete process.env.FORECAST_TUI_INLINE
  })

  it('renders the Contested section with title, auto label, rationale, question ref, and header badge', async () => {
    const m = await mount({ contested: contestedRows() })
    const text = m.text()
    // The header badge and the section header both carry the count.
    expect(text).toContain('2 contested')
    expect(text).toContain('Contested — hand-label (2)')
    // Each row shows its title, the auto label, the linked question, and rationale.
    expect(text).toContain('Reuters: Fed signals a hold')
    expect(text).toContain('auto:relevant_uninteresting')
    expect(text).toContain('fq_alpha')
    expect(text).toContain('near the decision boundary')
    m.cleanup()
  })

  it('1 labels the focused contested row relevant_interesting via forecast.triage.relabel, then removes it', async () => {
    const m = await mount({ contested: contestedRows(), initialFocus: 'contested' })
    // initialFocus parked the cursor on the first contested row (tl_1). Drop the
    // pre-label frames so the assertions read only the post-label render (the
    // PassThrough is cumulative, so the removed row lingers in earlier frames).
    m.clear()
    await m.press('1')
    await tick(60)
    const relabel = m.calls.find(c => c.method === 'forecast.triage.relabel')
    expect(relabel).toBeTruthy()
    expect(relabel?.params.label_id).toBe('tl_1')
    expect(relabel?.params.label).toBe('relevant_interesting')
    // The row is gone (optimistic removal, confirmed by the reload) and the flash fired.
    expect(m.text()).not.toContain('Reuters: Fed signals a hold')
    expect(m.text()).toContain('alert closed')
    // The count settled to 1 (the other row survives).
    expect(m.text()).toContain('Blog rumor on a rate cut')
    m.cleanup()
  })

  it('2 maps to relevant_uninteresting and 3 maps to irrelevant', async () => {
    const two = await mount({ contested: contestedRows(), initialFocus: 'contested' })
    await two.press('2')
    await tick(60)
    expect(two.calls.find(c => c.method === 'forecast.triage.relabel')?.params.label).toBe('relevant_uninteresting')
    two.cleanup()

    const three = await mount({ contested: contestedRows(), initialFocus: 'contested' })
    await three.press('3')
    await tick(60)
    expect(three.calls.find(c => c.method === 'forecast.triage.relabel')?.params.label).toBe('irrelevant')
    three.cleanup()
  })

  it('the digit keys are inert while the cursor is on the backlog tree (not a contested row)', async () => {
    // No initialFocus → the cursor starts on the FREE tier header, not a contested row.
    const m = await mount({ contested: contestedRows() })
    await m.press('1')
    await tick(40)
    expect(m.calls.find(c => c.method === 'forecast.triage.relabel')).toBeFalsy()
    m.cleanup()
  })
})



describe('free-pass progress coalescing (the operator flash bug)', () => {
  it('a burst of per-alert progress events paints at a bounded rate and keeps the LAST value', async () => {
    const m = await mount()
    await m.press('R')
    await tick(120)
    const runCall = m.calls.find(c => c.method === 'forecast.warnings.automode.run')
    expect(runCall).toBeTruthy()
    // fakeGw's canned run response job id (read it from what the view stored by
    // emitting a matching complete later) — emit the burst under that id.
    const jobId = 'wj_test' // fakeGw returns this fixed id (assert via behavior below)

    // 60 events in a tight burst — one per alert, the real dispatcher shape.
    for (let done = 1; done <= 60; done += 1) {
      m.emit('forecast.warnings.automode.progress', { done, job_id: jobId, phase: 'alert', total: 60 })
    }

    await tick(400) // > trailing window: the final value must have landed
    const text = m.text()
    // The backlog headline never left the frame, and the chip shows the FINAL
    // count (the trailing paint), not an early one.
    expect(text).toContain('open')
    expect(text).toContain('60')
    m.cleanup()
  })
})

describe('R free-pass — fixed inline bar + honest error fold (no scrolling)', () => {
  it('R renders a ▓░ progress bar from progress events and OWNS the run (stderr suppressed)', async () => {
    const m = await mount()
    await m.press('R')
    await tick(60)
    // The pass now owns the view: stderr suppression is armed for its lifetime.
    expect(isWarningsRunActive()).toBe(true)

    m.emit('forecast.warnings.automode.progress', { done: 40, job_id: 'wj_test', phase: 'alert', reason: 'postmortem_due', total: 130 })
    await tick(60)
    const text = m.text()
    // A fixed inline bar (filled ▓ + empty ░) with the live done/total — never a
    // transcript stream. The current alert reason rides the same single line.
    expect(text).toContain('▓')
    expect(text).toContain('░')
    expect(text).toContain('40/130')
    m.cleanup()
  })

  it('folds identical failure reasons to ONE line under the bar', async () => {
    const m = await mount()
    await m.press('R')
    await tick(60)
    // The server carries a running reason→count fold on the progress event; the
    // desk collapses it to a single "N failed: <reason>" line (never N rows).
    m.emit('forecast.warnings.automode.progress', {
      done: 130,
      failures: { 'no active autopilot policy': 130 },
      job_id: 'wj_test',
      phase: 'alert',
      total: 130
    })
    await tick(60)
    const text = m.text()
    expect(text).toContain('130 failed:')
    expect(text).toContain('No active autopilot policy')
    // Exactly ONE folded line — the storm never becomes 130 rows.
    expect(text.match(/failed:/g)?.length ?? 0).toBe(1)
    m.cleanup()
  })

  it('completion toast reports honest counts (0 resolved · 130 failed: reason) and releases the run', async () => {
    const m = await mount()
    await m.press('R')
    await tick(60)
    expect(isWarningsRunActive()).toBe(true)

    m.emit('forecast.warnings.automode.complete', {
      cancelled: false,
      failures: { 'no active autopilot policy': 130 },
      job_id: 'wj_test',
      processed: 130,
      tally: { failed: 130 },
      total: 130
    })
    await tick(60)
    const text = m.text()
    expect(text).toContain('0 resolved')
    expect(text).toContain('130 failed')
    expect(text).toContain('No active autopilot policy')
    // The pass released the view → stderr streaming resumes for anything else.
    expect(isWarningsRunActive()).toBe(false)
    m.cleanup()
  })

  it('re-attaches to an in-flight warnings pass on mount (bar + progress resume)', async () => {
    // A pass was already running when the view opened — jobs.active surfaces it.
    const m = await mount({
      activeJobs: [{ current: 'evidence_stale', done_count: 12, job_id: 'wj_live', status: 'running', total: 130, type: 'warnings' }]
    })

    await tick(80)
    // Adopted the live job without the operator re-triggering it.
    expect(isWarningsRunActive()).toBe(true)
    expect(m.text()).toContain('12/130')

    // Progress for the ADOPTED id drives the same bar.
    m.emit('forecast.warnings.automode.progress', { done: 77, job_id: 'wj_live', phase: 'alert', total: 130 })
    await tick(60)
    expect(m.text()).toContain('77/130')
    m.cleanup()
  })
})
