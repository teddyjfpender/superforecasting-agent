// Module-level cache for overlay data (desk, calendar, calibration, alerts,
// obsidian). The overlays unmount when closed, so without this every reopen
// shows a "Loading…" screen and re-hits the gateway. Caching the last good
// payload here — it survives unmount — lets a reopen render instantly while
// the view refreshes in the background (stale-while-revalidate).
//
// The cache is intentionally simple and process-lived; it is not persisted and
// holds only the most recent response per key. Keys are the RPC method name
// (optionally suffixed with params that change the payload).
const store = new Map<string, unknown>()

export const getOverlayCache = <T>(key: string): T | undefined => store.get(key) as T | undefined

export const setOverlayCache = (key: string, value: unknown): void => {
  store.set(key, value)
}

// Drop all cached overlay payloads. Primarily for test isolation — the cache
// is a process-lived singleton, so tests that render different fixtures must
// reset it between cases.
export const clearOverlayCache = (): void => {
  store.clear()
}
