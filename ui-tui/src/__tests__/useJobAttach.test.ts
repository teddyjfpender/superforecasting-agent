import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { attachJobLoop, JOB_POLL_MS } from '../app/useJobAttach.js'

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
const makeGw = (handlers: Record<string, unknown>) => {
  const listeners = new Map<string, ((payload: unknown) => void)[]>()

  const request = vi.fn((method: string) => {
    const h = handlers[method]

    return Promise.resolve(typeof h === 'function' ? (h as () => unknown)() : h)
  })

  const on = vi.fn((event: string, l: (payload: unknown) => void) => {
    const arr = listeners.get(event) ?? []
    arr.push(l)
    listeners.set(event, arr)
  })

  const off = vi.fn((event: string, l: (payload: unknown) => void) => {
    listeners.set(event, (listeners.get(event) ?? []).filter(x => x !== l))
  })

  const emit = (event: string, payload: unknown) => (listeners.get(event) ?? []).forEach(l => l(payload))

  return { emit, off, on, request }
}

const statusCalls = (gw: ReturnType<typeof makeGw>) =>
  gw.request.mock.calls.filter(c => c[0] === 'jobs.status').length

describe('attachJobLoop', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('discovers the newest live job on mount, paints it, and starts polling', async () => {
    const active = { job_id: 'job_1', spec: { question_ids: ['a', 'b'] }, status: 'running', type: 'refresh' }

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
      'jobs.status': { found: true, job: { done_count: 0, job_id: 'job_started', status: 'running', type: 'reforecast' } }
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
      'jobs.active': { jobs: [] },
      'jobs.status': { found: true, job: { job_id: 'job_done', result: { ok: true }, status: 'done', type: 'refresh' } }
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
      'jobs.active': { jobs: [] },
      'jobs.status': { found: true, job: { job_id: 'job_e', status: 'running', type: 'refresh' } }
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
    let resolveStatus: (v: unknown) => void = () => {}

    const gw = makeGw({
      'jobs.active': { jobs: [] },
      'jobs.status': () => new Promise(resolve => { resolveStatus = resolve })
    })

    const onProgress = vi.fn()

    const ctrl = attachJobLoop(gw, ['refresh'], { onProgress })
    ctrl.attach('job_late')
    expect(statusCalls(gw)).toBe(1)

    // Tear down BEFORE the in-flight poll resolves, then resolve it late.
    ctrl.stop()
    expect(gw.off).toHaveBeenCalledWith('event', expect.any(Function))
    resolveStatus({ found: true, job: { job_id: 'job_late', status: 'running', type: 'refresh' } })
    await flush()

    // The late resolve is dropped; no further polling after teardown.
    expect(onProgress).not.toHaveBeenCalled()
    vi.advanceTimersByTime(JOB_POLL_MS * 3)
    expect(statusCalls(gw)).toBe(1)
  })

  it('works without an event bridge (plain { request } fakes) — the poll alone drives it', async () => {
    const request = vi.fn((method: string) =>
      Promise.resolve(
        method === 'jobs.active'
          ? { jobs: [] }
          : { found: true, job: { job_id: 'job_p', status: 'running', type: 'refresh' } }
      )
    )

    const onProgress = vi.fn()

    const ctrl = attachJobLoop({ request } as never, ['refresh'], { onProgress })
    ctrl.attach('job_p')
    await flush()
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job_p' }))
    ctrl.stop() // no gw.off to call — must not throw
  })
})
