// Unit tests for the saved-pool hydration WORKER POOL — the concurrency
// contract, extracted pure from usePmDiscovered so the parallelism is verified
// without rendering the hook. The old code hydrated in SEQUENTIAL batches (one
// slow venue fetch stalled the whole next batch); the pool keeps the pipe full.

import { describe, expect, it } from 'vitest'

import { runHydrationPool } from '../lib/usePmDiscovered.js'

const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0))

describe('runHydrationPool', () => {
  it('keeps at most `limit` workers in flight and processes every item', async () => {
    const items = Array.from({ length: 20 }, (_, i) => i)
    let inFlight = 0
    let maxInFlight = 0
    const seen: number[] = []

    await runHydrationPool(
      items,
      4,
      async n => {
        inFlight++
        maxInFlight = Math.max(maxInFlight, inFlight)
        await tick()
        inFlight--

        return n * 2
      },
      r => {
        seen.push(r)
      }
    )

    // Parallel (not serial) but capped: exactly the concurrency width in flight.
    expect(maxInFlight).toBe(4)
    expect(seen.sort((a, b) => a - b)).toEqual(items.map(n => n * 2))
  })

  it('never exceeds the item count when limit > items', async () => {
    const items = [1, 2]
    let maxInFlight = 0
    let inFlight = 0

    await runHydrationPool(
      items,
      12,
      async n => {
        inFlight++
        maxInFlight = Math.max(maxInFlight, inFlight)
        await tick()
        inFlight--

        return n
      },
      () => {}
    )

    expect(maxInFlight).toBe(2)
  })

  it('stops folding results once cancelled (progressive, bailable)', async () => {
    const items = Array.from({ length: 12 }, (_, i) => i)
    const seen: number[] = []
    let cancelled = false

    await runHydrationPool(
      items,
      2,
      async n => {
        await tick()

        return n
      },
      r => {
        seen.push(r)
        if (seen.length >= 4) {
          cancelled = true
        }
      },
      () => cancelled
    )

    expect(seen.length).toBeGreaterThanOrEqual(4)
    expect(seen.length).toBeLessThan(items.length)
  })

  it('swallows a worker throw — a dead ref just does not fold', async () => {
    const items = [1, 2, 3, 4]
    const seen: number[] = []

    await runHydrationPool(
      items,
      2,
      async n => {
        if (n === 2) {
          throw new Error('gone')
        }

        return n
      },
      r => {
        seen.push(r)
      }
    )

    expect(seen.sort((a, b) => a - b)).toEqual([1, 3, 4])
  })
})
