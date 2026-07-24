import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $agentsActive, AGENTS_ACTIVE_EMPTY } from '../app/agentsActiveStore.js'
import { AGENTS_POLL_MS, pollAgentsActive } from '../app/useAgentsActivePoll.js'

// The lifecycle lives in the imperative core `pollAgentsActive` (the React hook is
// a one-line wrapper: run it while active, return its stop() as cleanup). Testing
// the core with fake timers exercises exactly the mount/interval/teardown path
// without dragging a renderer + its own internal timers into the assertions.

const flush = () => Promise.resolve()

describe('pollAgentsActive', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    $agentsActive.set(AGENTS_ACTIVE_EMPTY)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('polls immediately, then on the interval, and stops when torn down', async () => {
    const request = vi.fn().mockResolvedValue({ count: 1, headline: '1 agent running · quorum · fq_x' })
    const stop = pollAgentsActive({ request } as never)

    // Immediate poll on start.
    expect(request).toHaveBeenCalledTimes(1)
    expect(request).toHaveBeenCalledWith('agents.active.summary', {})

    // The first resolve lands in the shared store.
    await flush()
    expect($agentsActive.get()).toEqual({ count: 1, headline: '1 agent running · quorum · fq_x' })

    // Each interval tick polls again.
    vi.advanceTimersByTime(AGENTS_POLL_MS)
    expect(request).toHaveBeenCalledTimes(2)
    vi.advanceTimersByTime(AGENTS_POLL_MS)
    expect(request).toHaveBeenCalledTimes(3)

    // Teardown clears the interval — no further polls.
    stop()
    vi.advanceTimersByTime(AGENTS_POLL_MS * 3)
    expect(request).toHaveBeenCalledTimes(3)
  })

  it('keeps polling past a nonzero count and publishes the drop to zero when the job finishes', async () => {
    // The chip lights on the first poll, then the job finishes and the next tick
    // reports zero. The poller must NOT stop once count > 0 — it has to keep polling
    // to observe the completion, and it must publish the zero (the chip clears).
    const request = vi
      .fn()
      .mockResolvedValueOnce({ count: 1, headline: '1 agent running · quorum · fq_x' })
      .mockResolvedValue({ count: 0, headline: '' })

    const stop = pollAgentsActive({ request } as never)

    await flush()
    expect($agentsActive.get()).toEqual({ count: 1, headline: '1 agent running · quorum · fq_x' })

    // Interval keeps firing despite the nonzero count; the next poll sees zero.
    vi.advanceTimersByTime(AGENTS_POLL_MS)
    expect(request).toHaveBeenCalledTimes(2)
    await flush()
    expect($agentsActive.get()).toEqual(AGENTS_ACTIVE_EMPTY)

    stop()
  })

  it('a poll resolving AFTER teardown never writes the store (cancelled guard)', async () => {
    let resolveLate: (value: unknown) => void = () => {}

    const request = vi.fn().mockReturnValue(new Promise(resolve => {
      resolveLate = resolve
    }))

    const stop = pollAgentsActive({ request } as never)
    expect(request).toHaveBeenCalledTimes(1)

    // Tear down BEFORE the in-flight poll resolves, then resolve it late.
    stop()
    resolveLate({ count: 9, headline: '9 agents running' })
    await flush()

    // The late resolve is dropped — the store stays empty.
    expect($agentsActive.get()).toEqual(AGENTS_ACTIVE_EMPTY)
  })
})
