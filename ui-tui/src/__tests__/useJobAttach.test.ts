import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { attachJobLoop, JOB_POLL_MS } from '../app/useJobAttach.js'
import type { JobRecordDTO, JobsActiveResponse, JobsStatusResponse } from '../protocol/generated.js'
import { RpcFixtures } from '../testing/rpcFixtures.js'

const job = (overrides: Partial<JobRecordDTO> & Pick<JobRecordDTO, 'job_id'>): JobRecordDTO => ({
  annotations: {},
  cancel_requested: false,
  created_at: '2026-09-19T00:00:00Z',
  current: null,
  done_count: 0,
  error: null,
  policy_decisions: [],
  policy_grants: [],
  progress: [],
  resolved_policy: null,
  result: null,
  spec: {},
  status: 'running',
  total: null,
  type: 'refresh',
  updated_at: null,
  ...overrides
})

// The lifecycle lives in the imperative core `attachJobLoop` (useJobAttach is a
// thin React wrapper: run it while mounted, return its stop() as cleanup). Testing
// the core with fake timers exercises the whole mount-discovery / poll / event-
// refresh / cleanup path without a renderer.

// Flush several microtask turns — a discovery resolve hops through startPolling →
// pollOnce → jobs.status → its own .then, so one Promise.resolve isn't enough.
const flush = async (turns = 8) => {
  for (let i = 0; i < turns; i++) {
    await Promise.resolve()
  }
}

// A mock gateway: request() answers from a per-method handler map (value or fn),
// and on/off/emit drive the 'event' channel the hook subscribes to.
const makeGw = (handlers: {
  'jobs.active': JobsActiveResponse
  'jobs.status': JobsStatusResponse | (() => Promise<JobsStatusResponse>)
}) => {
  const listeners = new Map<string, ((payload: unknown) => void)[]>()

  const rpc = new RpcFixtures()
    .handle('jobs.active', () => handlers['jobs.active'])
    .handle('jobs.status', () => {
      const status = handlers['jobs.status']

      return typeof status === 'function' ? status() : status
    })

  const request = vi.fn(rpc.request.bind(rpc))

  const on = vi.fn((event: string, l: (payload: unknown) => void) => {
    const arr = listeners.get(event) ?? []
    arr.push(l)
    listeners.set(event, arr)
  })

  const off = vi.fn((event: string, l: (payload: unknown) => void) => {
    listeners.set(
      event,
      (listeners.get(event) ?? []).filter(x => x !== l)
    )
  })

  const emit = (event: string, payload: unknown) => (listeners.get(event) ?? []).forEach(l => l(payload))

  return { emit, off, on, request }
}

const statusCalls = (gw: ReturnType<typeof makeGw>) => gw.request.mock.calls.filter(c => c[0] === 'jobs.status').length

describe('attachJobLoop', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('discovers the newest live job on mount, paints it, and starts polling', async () => {
    const active = job({ job_id: 'job_1', spec: { question_ids: ['a', 'b'] } })

    const gw = makeGw({
      'jobs.active': { count: 1, jobs: [active] },
      'jobs.status': { found: true, job: { ...active, done_count: 1 } }
    })

    const onProgress = vi.fn()
    const onComplete = vi.fn()

    const ctrl = attachJobLoop(gw, ['refresh'], { onComplete, onProgress })

    // Discovery is scoped to the requested types.
    expect(gw.request).toHaveBeenCalledWith('jobs.active', { types: ['refresh'] })
    await flush()

    // The discovered active record paints the first frame; the poll then refines it.
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job_1' }))
    expect(gw.request).toHaveBeenCalledWith('jobs.status', { job_id: 'job_1' })
    expect(onComplete).not.toHaveBeenCalled()

    // Each interval tick re-polls.
    const before = statusCalls(gw)
    vi.advanceTimersByTime(JOB_POLL_MS)
    expect(statusCalls(gw)).toBe(before + 1)

    ctrl.stop()
  })

  it('attach() points the loop at a just-started job and polls it', async () => {
    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] }, // nothing pre-existing
      'jobs.status': { found: true, job: job({ job_id: 'job_started', type: 'reforecast' }) }
    })

    const onProgress = vi.fn()

    const ctrl = attachJobLoop(gw, ['reforecast', 'task'], { onProgress })
    await flush()
    // Discovery found nothing → no poll yet.
    expect(statusCalls(gw)).toBe(0)

    ctrl.attach('job_started')
    expect(gw.request).toHaveBeenCalledWith('jobs.status', { job_id: 'job_started' })
    await flush()
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job_started' }))

    ctrl.stop()
  })

  it('fires onComplete on a terminal record and STOPS polling (release)', async () => {
    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': { found: true, job: job({ job_id: 'job_done', result: { ok: true }, status: 'done' }) }
    })

    const onComplete = vi.fn()
    const onProgress = vi.fn()

    const ctrl = attachJobLoop(gw, ['refresh'], { onComplete, onProgress })
    ctrl.attach('job_done')
    await flush()

    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ status: 'done' }))
    expect(onProgress).not.toHaveBeenCalled() // a terminal record never fires onProgress

    // Released: the interval is torn down, so no further jobs.status polls.
    const settled = statusCalls(gw)
    vi.advanceTimersByTime(JOB_POLL_MS * 3)
    expect(statusCalls(gw)).toBe(settled)

    ctrl.stop()
  })

  it('a jobs.* event for OUR job triggers an immediate re-poll; another job is ignored', async () => {
    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': { found: true, job: job({ job_id: 'job_e' }) }
    })

    const ctrl = attachJobLoop(gw, ['refresh'], {})
    ctrl.attach('job_e')
    await flush()

    const before = statusCalls(gw)
    gw.emit('event', { payload: { job_id: 'job_e' }, type: 'jobs.progress' })
    expect(statusCalls(gw)).toBe(before + 1)

    // An event for a DIFFERENT job never re-polls ours.
    gw.emit('event', { payload: { job_id: 'someone_else' }, type: 'jobs.progress' })
    expect(statusCalls(gw)).toBe(before + 1)

    // A non-jobs event is ignored too.
    gw.emit('event', { payload: { job_id: 'job_e' }, type: 'pm.tick' })
    expect(statusCalls(gw)).toBe(before + 1)

    ctrl.stop()
  })

  it('stop() clears the interval, unsubscribes the event bridge, and drops a late resolve', async () => {
    let resolveStatus: (v: JobsStatusResponse) => void = () => {
      throw new Error('No pending status request')
    }

    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': () =>
        new Promise(resolve => {
          resolveStatus = resolve
        })
    })

    const onProgress = vi.fn()

    const ctrl = attachJobLoop(gw, ['refresh'], { onProgress })
    ctrl.attach('job_late')
    expect(statusCalls(gw)).toBe(1)

    // Tear down BEFORE the in-flight poll resolves, then resolve it late.
    ctrl.stop()
    expect(gw.off).toHaveBeenCalledWith('event', expect.any(Function))
    resolveStatus({ found: true, job: job({ job_id: 'job_late' }) })
    await flush()

    // The late resolve is dropped; no further polling after teardown.
    expect(onProgress).not.toHaveBeenCalled()
    vi.advanceTimersByTime(JOB_POLL_MS * 3)
    expect(statusCalls(gw)).toBe(1)
  })

  it('works without an event bridge (plain { request } fakes) — the poll alone drives it', async () => {
    const { request } = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': { found: true, job: job({ job_id: 'job_p' }) }
    })

    const onProgress = vi.fn()

    const ctrl = attachJobLoop({ request }, ['refresh'], { onProgress })
    ctrl.attach('job_p')
    await flush()
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job_p' }))
    ctrl.stop() // no gw.off to call — must not throw
  })
})

describe('job attachment response ownership', () => {
  it('never publishes a status record belonging to another job', async () => {
    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': { found: true, job: job({ job_id: 'other', status: 'done' }) }
    })

    const onProgress = vi.fn()
    const onComplete = vi.fn()
    const ctrl = attachJobLoop(gw, [], { onProgress, onComplete })

    try {
      ctrl.attach('A')
      await flush()
      expect(onProgress).not.toHaveBeenCalled()
      expect(onComplete).not.toHaveBeenCalled()
    } finally {
      ctrl.stop()
    }
  })

  it('rejects an old attachment reply even after returning to the same job', async () => {
    const replies: Array<(value: JobsStatusResponse) => void> = []

    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': () => new Promise(resolve => replies.push(resolve))
    })

    const onProgress = vi.fn()
    const onComplete = vi.fn()
    const ctrl = attachJobLoop(gw, [], { onProgress, onComplete })

    try {
      ctrl.attach('A')
      ctrl.attach('B')
      ctrl.attach('A')
      replies[0]({ found: true, job: job({ job_id: 'A', status: 'done' }) })
      await flush()
      expect(onComplete).not.toHaveBeenCalled()
      replies[2]({ found: true, job: job({ job_id: 'A', done_count: 4 }) })
      await flush()
      expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ done_count: 4 }))
    } finally {
      ctrl.stop()
    }
  })

  it('does not regress progress when overlapping refreshes return out of order', async () => {
    const replies: Array<(value: JobsStatusResponse) => void> = []

    const gw = makeGw({
      'jobs.active': { count: 0, jobs: [] },
      'jobs.status': () => new Promise(resolve => replies.push(resolve))
    })

    const onProgress = vi.fn()
    const ctrl = attachJobLoop(gw, [], { onProgress })

    try {
      ctrl.attach('A')
      gw.emit('event', { type: 'jobs.progress', payload: { job_id: 'A' } })
      replies[1]({ found: true, job: job({ job_id: 'A', done_count: 4 }) })
      await flush()
      replies[0]({ found: true, job: job({ job_id: 'A', done_count: 1 }) })
      await flush()
      expect(onProgress).toHaveBeenCalledTimes(1)
      expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ done_count: 4 }))
    } finally {
      ctrl.stop()
      ctrl.stop()
      expect(gw.off).toHaveBeenCalledTimes(1)
    }
  })

  it('does not resurrect discovery after an explicitly attached job completes', async () => {
    let discover: (value: JobsActiveResponse) => void = () => {
      throw new Error('Discovery not pending')
    }

    const rpc = new RpcFixtures()
      .handle(
        'jobs.active',
        () =>
          new Promise(resolve => {
            discover = resolve
          })
      )
      .handle('jobs.status', () => ({ found: true, job: job({ job_id: 'A', status: 'done' }) }))

    const onProgress = vi.fn()
    const onComplete = vi.fn()
    const ctrl = attachJobLoop({ request: rpc.request.bind(rpc) }, [], { onProgress, onComplete })

    try {
      ctrl.attach('A')
      await flush()
      expect(onComplete).toHaveBeenCalledTimes(1)
      discover({ count: 1, jobs: [job({ job_id: 'old' })] })
      await flush()
      expect(onProgress).not.toHaveBeenCalled()
    } finally {
      ctrl.stop()
    }
  })
})
