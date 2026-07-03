// The DISCOVERED-markets lifecycle for the Prediction Markets section: the
// session pool of events the operator surfaced via deep '/' search, persisted to
// markets.json (cap 100 LRU) and re-hydrated by pm.detail on mount. Split out of
// usePmSection (which was over the line budget) so the fold / persist / hydrate /
// remove logic has one cohesive home. No useInput, no view concerns — pure data.

import { useEffect, useRef, useState } from 'react'

import { loadMarketConfig, PM_SAVED_CAP, saveMarketConfig } from './marketStore.js'
import { fetchPMDetail, type PMListItem, type PMVenue } from './pmData.js'
import { type PMHookGateway } from './usePmMarkets.js'

// Re-hydrate at most this many pm.detail calls concurrently: a large saved store
// (up to the 100 LRU cap) must never burst the gateway with one giant fan-out.
// Batches run sequentially and fold as they land, so the tape fills progressively.
const HYDRATE_CHUNK = 8

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

  // Re-hydrate persisted discoveries once per mount (server-cached + cheap), in
  // sequential batches of HYDRATE_CHUNK so the fan-out is bounded; each batch
  // folds as it lands (progressive fill). Events that no longer resolve are pruned
  // from the store after every batch has been attempted.
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

      for (let i = 0; i < refs.length; i += HYDRATE_CHUNK) {
        if (cancelled) {
          return
        }

        const batch = refs.slice(i, i + HYDRATE_CHUNK)
        const results = await Promise.allSettled(
          batch.map(r => fetchPMDetail(gw, r.venue as PMVenue, r.event_id).then(item => ({ item, ref: r })))
        )
        if (cancelled) {
          return
        }

        const ok: PMListItem[] = []
        for (const res of results) {
          if (res.status === 'fulfilled' && res.value.item) {
            ok.push(res.value.item)
            live.add(res.value.ref.event_id)
          }
        }
        if (ok.length) {
          foldDiscovered(ok)
        }
      }

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
