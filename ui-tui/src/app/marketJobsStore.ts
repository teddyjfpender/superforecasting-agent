import { atom } from 'nanostores'

// App-level tracking of background market-model jobs (build / refine). These run
// as detached gateway daemon threads, so they keep going when you leave the
// Markets view — this store keeps their progress + completion visible app-wide
// (the way home-route agent turns survive navigation), instead of dying with the
// marketsView component's local state.

export type MarketJobStatus = 'building' | 'done' | 'error' | 'refining'

export interface MarketJob {
  at: number
  message: string
  status: MarketJobStatus
  version?: number
}

export const $marketJobs = atom<Record<string, MarketJob>>({})

export const setMarketJob = (id: string, patch: Partial<MarketJob> & { status: MarketJobStatus }): void => {
  const cur = $marketJobs.get()
  const prev = cur[id]
  $marketJobs.set({
    ...cur,
    [id]: {
      at: Date.now(),
      message: patch.message ?? prev?.message ?? '',
      status: patch.status,
      version: patch.version ?? prev?.version
    }
  })
}

export const clearMarketJob = (id: string): void => {
  const next = { ...$marketJobs.get() }

  if (id in next) {
    delete next[id]
    $marketJobs.set(next)
  }
}

// A build/refine that hasn't reported progress in this long is presumed dead —
// a missed terminal event (gateway restart killed the daemon thread, network
// drop) would otherwise leave the row stuck on "refining" forever. Comfortably
// beyond the hard run timeout (deep = 600s) so a live run mid-completion is safe.
export const STALE_MARKET_JOB_MS = 15 * 60_000

const fresh = (j: MarketJob | undefined, now: number): boolean =>
  Boolean(j && (j.status === 'building' || j.status === 'refining') && now - j.at < STALE_MARKET_JOB_MS)

// True while a model has a LIVE in-flight build/refine (drives the "refining" UI
// so it survives leaving + returning) — stale entries read as inactive.
export const isMarketJobActive = (id: null | string | undefined): boolean =>
  Boolean(id && fresh($marketJobs.get()[id], Date.now()))

// Drop entries whose job has gone stale (dead, terminal-event missed). Returns
// the count cleared so a caller can reconcile from server truth.
export const pruneStaleMarketJobs = (now = Date.now()): number => {
  const cur = $marketJobs.get()
  const next: Record<string, MarketJob> = {}
  let cleared = 0

  for (const [id, j] of Object.entries(cur)) {
    // Keep live jobs + recent terminal (done/error) entries (they self-clear).
    if (fresh(j, now) || now - j.at < STALE_MARKET_JOB_MS) {
      next[id] = j
    } else {
      cleared++
    }
  }

  if (cleared) {
    $marketJobs.set(next)
  }

  return cleared
}
