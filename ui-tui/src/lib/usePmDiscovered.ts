// The DISCOVERED-markets lifecycle for the Prediction Markets section: the
// session pool of events the operator surfaced via deep '/' search, persisted to
// markets.json (cap 100 LRU) and re-hydrated by pm.detail on mount. Split out of
// usePmSection (which was over the line budget) so the fold / persist / hydrate /
// remove logic has one cohesive home. No useInput, no view concerns — pure data.

import { useEffect, useRef, useState } from 'react'

import { loadMarketConfig, PM_SAVED_CAP, saveMarketConfig } from './marketStore.js'
import { fetchPMDetail, type PMListItem, type PMVenue } from './pmData.js'
import { type PMHookGateway } from './usePmMarkets.js'

// Re-hydrate the saved store with a bounded-concurrency WORKER POOL: keep this
// many pm.detail calls in flight at all times (a large saved store — up to the
// 100 LRU cap — must never burst the gateway with one giant fan-out, but the old
// sequential batches stalled the whole next batch on one slow venue fetch). The
// pool keeps the pipe full, so total hydration ≈ (n / concurrency) round trips
// instead of n/8 SERIAL batch waits.
const HYDRATE_CONCURRENCY = 12
// Fold in small groups (not one setState per result) so a 100-item pool paints
// progressively without 100 re-renders.
const HYDRATE_FLUSH = 8

// A generic bounded-concurrency pool: run `worker` over `items` with at most
// `limit` in flight, invoking `onResult` as each lands (progressive fill),
// bailing when `isCancelled()` flips. A worker throw is swallowed (a dead ref
// just doesn't fold). Exported pure so the concurrency contract is unit-tested
// without rendering the hook.
export async function runHydrationPool<T, R>(
  items: readonly T[],
  limit: number,
  worker: (item: T) => Promise<R>,
  onResult: (result: R, item: T) => void,
  isCancelled: () => boolean = () => false
): Promise<void> {
  let cursor = 0
  const width = Math.max(1, Math.min(limit, items.length))

  const runner = async (): Promise<void> => {
    while (!isCancelled()) {
      const i = cursor++

      if (i >= items.length) {
        return
      }

      try {
        const result = await worker(items[i])

        if (!isCancelled()) {
          onResult(result, items[i])
        }
      } catch {
        // A ref that fails to hydrate (closed/gone) simply doesn't fold.
      }
    }
  }

  await Promise.all(Array.from({ length: width }, runner))
}

export interface PmDiscovered {
  discovered: ReadonlyMap<string, PMListItem>
  // Merge freshly-found events into the pool (deduped by event_id) + persist.
  foldDiscovered: (found: PMListItem[]) => void
  // Drop one event from the pool AND markets.json's pmSaved (a mis-search must
  // not pollute the tape until cap-eviction).
  removeDiscovered: (eventId: string) => void
}

export function usePmDiscovered(gw: PMHookGateway | undefined, active: boolean): PmDiscovered {
  // DISCOVERED events persist: searches COMPOUND the tape's coverage instead of
  // evaporating when the query clears (the operator: "the searched markets should
  // persist... so we maximally cover the markets"). Session state here; refs saved
  // to markets.json (cap 100 LRU) + re-hydrated via pm.detail on mount, with
  // dead/gone events pruning themselves on failed hydration.
  const [discovered, setDiscovered] = useState<ReadonlyMap<string, PMListItem>>(() => new Map())

  const persist = (next: ReadonlyMap<string, PMListItem>) => {
    const cfg = loadMarketConfig()
    const refs = [...next.values()].map(i => ({ event_id: i.event.event_id, venue: i.event.venue }))
    saveMarketConfig({ ...cfg, pmSaved: refs.slice(-PM_SAVED_CAP) })
  }

  const foldDiscovered = (found: PMListItem[]) => {
    setDiscovered(prev => {
      const next = new Map(prev)

      for (const item of found) {
        next.set(item.event.event_id, item)
      }

      if (next.size === prev.size) {
        return prev
      }

      persist(next)

      return next
    })
  }

  const removeDiscovered = (eventId: string) => {
    setDiscovered(prev => {
      if (!prev.has(eventId)) {
        return prev
      }

      const next = new Map(prev)
      next.delete(eventId)
      persist(next)

      return next
    })
  }

  // Re-hydrate persisted discoveries once per mount (server-cached + cheap) via
  // a bounded-concurrency pool (HYDRATE_CONCURRENCY in flight), folding results
  // in small groups (progressive fill) instead of one setState per item. Events
  // that no longer resolve are pruned from the store once the pool drains.
  const hydratedRef = useRef(false)
  useEffect(() => {
    if (!gw || !active || hydratedRef.current) {
      return
    }

    hydratedRef.current = true
    const refs = loadMarketConfig().pmSaved ?? []

    if (!refs.length) {
      return
    }

    let cancelled = false

    void (async () => {
      const live = new Set<string>()
      let buffer: PMListItem[] = []

      const flush = () => {
        if (buffer.length) {
          foldDiscovered(buffer)
          buffer = []
        }
      }

      await runHydrationPool(
        refs,
        HYDRATE_CONCURRENCY,
        r => fetchPMDetail(gw, r.venue as PMVenue, r.event_id).then(item => ({ item, ref: r })),
        ({ item, ref }) => {
          if (item) {
            live.add(ref.event_id)
            buffer.push(item)

            if (buffer.length >= HYDRATE_FLUSH) {
              flush()
            }
          }
        },
        () => cancelled
      )
      flush()

      if (cancelled) {
        return
      }

      // Prune refs that failed to hydrate (closed/gone) from the store.
      if (live.size < refs.length) {
        const cfg = loadMarketConfig()
        saveMarketConfig({ ...cfg, pmSaved: (cfg.pmSaved ?? []).filter(r => live.has(r.event_id)) })
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, active])

  return { discovered, foldDiscovered, removeDiscovered }
}
