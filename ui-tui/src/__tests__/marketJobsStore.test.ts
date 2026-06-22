import { beforeEach, describe, expect, it } from 'vitest'

import { $marketJobs, isMarketJobActive, pruneStaleMarketJobs, setMarketJob, STALE_MARKET_JOB_MS } from '../app/marketJobsStore.js'

// Market-model jobs are tracked optimistically; a missed terminal event (gateway
// restart killed the daemon, network drop) must not leave a row stuck on
// "refining" forever. Staleness makes a dead job read inactive + get swept.

describe('marketJobsStore staleness', () => {
  beforeEach(() => $marketJobs.set({}))

  it('a fresh active job reads as active', () => {
    setMarketJob('m1', { message: 'refining…', status: 'refining' })
    expect(isMarketJobActive('m1')).toBe(true)
  })

  it('a job with no update past the stale window reads inactive and is pruned', () => {
    $marketJobs.set({ m2: { at: Date.now() - STALE_MARKET_JOB_MS - 1_000, message: 'refining…', status: 'refining' } })
    expect(isMarketJobActive('m2')).toBe(false) // not counted / not shown
    expect(pruneStaleMarketJobs()).toBe(1) // swept from the store
    expect($marketJobs.get().m2).toBeUndefined()
  })

  it('keeps live + recent-terminal entries; only sweeps the truly dead', () => {
    const now = Date.now()
    $marketJobs.set({
      dead: { at: now - STALE_MARKET_JOB_MS - 1, message: '', status: 'building' },
      done: { at: now, status: 'done', message: '', version: 2 },
      live: { at: now, message: 'computing', status: 'refining' }
    })
    expect(pruneStaleMarketJobs(now)).toBe(1)
    const left = $marketJobs.get()
    expect(left.dead).toBeUndefined()
    expect(left.live).toBeDefined()
    expect(left.done).toBeDefined() // terminal but recent → self-clears later
    expect(isMarketJobActive('done')).toBe(false) // 'done' is never "active"
  })
})
