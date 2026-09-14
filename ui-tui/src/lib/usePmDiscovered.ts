// The DISCOVERED-markets lifecycle for the Prediction Markets section: the
// session pool of events the operator surfaced via deep '/' search, persisted to
// markets.json (cap 100 LRU) and re-hydrated by pm.detail on mount. Split out of
// usePmSection (which was over the line budget) so the fold / persist / hydrate /
// remove logic has one cohesive home. No useInput, no view concerns — pure data.

import { useEffect, useRef, useState } from 'react'

import { fetchPMDetail, type PMListItem, type PMVenue } from './pmData.js'
import { pmRowId } from './pmRows.js'
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
  // Merge freshly-found events into the pool (deduped by venue and event_id) + persist.
  foldDiscovered: (found: PMListItem[]) => void
  // Drop one event from the pool AND markets.json's pmSaved (a mis-search must
  // not pollute the tape until cap-eviction).
  removeDiscovered: (rowId: string) => void
}

export function usePmDiscovered(
  gw: PMHookGateway | undefined,
  active: boolean,
  onError?: (message: string) => void
): PmDiscovered {
  // DISCOVERED events persist: searches COMPOUND the tape's coverage instead of
  // evaporating when the query clears (the operator: "the searched markets should
  // persist... so we maximally cover the markets"). Session state here; refs saved
  // to markets.json (cap 100 LRU) + re-hydrated via pm.detail on mount, without deleting references when a provider is unavailable.
  const [discovered, setDiscovered] = useState<ReadonlyMap<string, PMListItem>>(() => new Map())

  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1

    return () => {
      generation.current += 1
    }
  }, [gw])

  const fold = (found: PMListItem[]) =>
    setDiscovered(previous => {
      const next = new Map(previous)

      for (const item of found) {
        next.set(pmRowId(item), item)
      }

      return next
    })

  const foldDiscovered = (found: PMListItem[]) => {
    if (!gw || !found.length) {
      return
    }

    const add = found.map(item => ({ event_id: item.event.event_id, venue: item.event.venue }))
    const owner = generation.current
    gw.request('market.selection.events.update', { add, remove: [] })
      .then(() => {
        if (generation.current === owner) {
          fold(found)
        }
      })
      .catch(() => onError?.('Could not save discovered markets. Retry the search to save them.'))
  }

  const removeDiscovered = (rowId: string) => {
    const item = discovered.get(rowId)

    if (!gw || !item) {
      return
    }

    const owner = generation.current
    gw.request('market.selection.events.update', {
      add: [],
      remove: [{ event_id: item.event.event_id, venue: item.event.venue }]
    })
      .then(() => {
        if (generation.current === owner) {
          setDiscovered(previous => {
            const next = new Map(previous)
            next.delete(rowId)

            return next
          })
        }
      })
      .catch(() => onError?.('Could not remove the saved market. Try again.'))
  }

  // Re-hydrate persisted discoveries once per mount (server-cached + cheap) via
  // a bounded-concurrency pool (HYDRATE_CONCURRENCY in flight), folding results
  // in small groups (progressive fill) instead of one setState per item. Events
  // that do not resolve remain saved for a subsequent retry.
  const hydratedRef = useRef(false)
  useEffect(() => {
    hydratedRef.current = false
    setDiscovered(new Map())
  }, [gw])
  useEffect(() => {
    if (!gw || !active || hydratedRef.current) {
      return
    }

    hydratedRef.current = true
    let cancelled = false

    void (async () => {
      const result = await gw.request('market.catalog', {})

      if (cancelled) {
        return
      }

      const refs = result.selection.pm_saved
      let buffer: PMListItem[] = []

      const flush = () => {
        if (buffer.length) {
          fold(buffer)
          buffer = []
        }
      }

      await runHydrationPool(
        refs,
        HYDRATE_CONCURRENCY,
        r => fetchPMDetail(gw, r.venue as PMVenue, r.event_id).then(item => ({ item, ref: r })),
        ({ item }) => {
          if (item) {
            buffer.push(item)

            if (buffer.length >= HYDRATE_FLUSH) {
              flush()
            }
          }
        },
        () => cancelled
      )

      if (!cancelled) {
        flush()
      }

      if (cancelled) {
        return
      }

      // A missing detail response can mean a transient outage. Only explicit
      // user removal deletes a saved reference; hydration is read-only.
    })().catch(() => {
      hydratedRef.current = false

      if (!cancelled) {
        onError?.('Could not load saved markets. Reopen Prediction to retry.')
      }
    })

    return () => {
      cancelled = true
      hydratedRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw, active])

  return { discovered, foldDiscovered, removeDiscovered }
}
