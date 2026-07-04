import { beforeEach, describe, expect, it } from 'vitest'

import { $agentsActive, AGENTS_ACTIVE_EMPTY, agentsActiveFromResult, setAgentsActive } from '../app/agentsActiveStore.js'

describe('agentsActiveStore', () => {
  beforeEach(() => {
    $agentsActive.set(AGENTS_ACTIVE_EMPTY)
  })

  it('setAgentsActive notifies only on a real change (a steady poll never churns)', () => {
    let notifications = 0

    const unsub = $agentsActive.listen(() => {
      notifications += 1
    })

    setAgentsActive({ count: 2, headline: '2 agents running · reforecast · 5 questions' })
    expect($agentsActive.get()).toEqual({ count: 2, headline: '2 agents running · reforecast · 5 questions' })
    expect(notifications).toBe(1)

    // The same summary again → no store write, no subscriber churn.
    setAgentsActive({ count: 2, headline: '2 agents running · reforecast · 5 questions' })
    expect(notifications).toBe(1)

    // A changed headline (same count) still notifies.
    setAgentsActive({ count: 2, headline: '2 agents running · quorum · fq_x' })
    expect(notifications).toBe(2)

    unsub()
  })

  it('publishes the drop back to zero — the chip clears, no stale last-known summary', () => {
    // A live job lights the chip.
    setAgentsActive({ count: 2, headline: '2 agents running · reforecast · 5 questions' })
    expect($agentsActive.get().count).toBe(2)

    // The job finishes → the poll returns count 0. The store must publish ZERO,
    // NOT retain the last-known nonzero summary (no `count || previous` fallback);
    // otherwise the chip would read as running forever.
    setAgentsActive(agentsActiveFromResult({ count: 0, headline: '' }))
    expect($agentsActive.get()).toEqual(AGENTS_ACTIVE_EMPTY)
  })

  it('agentsActiveFromResult tolerates null / partial / malformed payloads', () => {
    expect(agentsActiveFromResult(null)).toEqual(AGENTS_ACTIVE_EMPTY)
    expect(agentsActiveFromResult(undefined)).toEqual(AGENTS_ACTIVE_EMPTY)
    expect(agentsActiveFromResult({})).toEqual({ count: 0, headline: '' })
    expect(agentsActiveFromResult({ count: 3, headline: '3 agents running · quorum' })).toEqual({
      count: 3,
      headline: '3 agents running · quorum'
    })

    // Defensive coercion: negatives clamp to 0, a non-string headline is dropped,
    // a float count truncates. A malformed poll can never render a bad chip.
    expect(agentsActiveFromResult({ count: -5, headline: 42 })).toEqual({ count: 0, headline: '' })
    expect(agentsActiveFromResult({ count: 2.9, headline: 'y' })).toEqual({ count: 2, headline: 'y' })
  })
})
