import { gatewayCacheOwner } from './deskViewCache.js'
/** Prediction browse snapshots survive navigation; live stream ownership stays in the hook. */
import { fetchPMListResult, type PmGateway, type PMListResult, type PMVenue } from './pmData.js'

type Venue = 'all' | PMVenue
interface Snapshot {
  value: PMListResult
  fetchedAt: number
}
const caches = new WeakMap<object, Map<Venue, Snapshot>>()
const pending = new WeakMap<object, Map<Venue, Promise<PMListResult>>>()
export const peekPMList = (gw: PmGateway | undefined, venue: Venue) =>
  gw ? caches.get(gatewayCacheOwner(gw))?.get(venue) : undefined

export function retainedPMList(gw: PmGateway, venue: Venue, force = false): Promise<PMListResult> {
  const owner = gatewayCacheOwner(gw)
  const cached = peekPMList(gw, venue)

  if (
    !force &&
    cached &&
    Date.now() - cached.fetchedAt < 30_000 &&
    !cached.value.stale &&
    !cached.value.catalog?.refreshing
  ) {
    return Promise.resolve(cached.value)
  }

  let requests = pending.get(owner)

  if (!requests) {
    requests = new Map()
    pending.set(owner, requests)
  }

  const existing = requests.get(venue)

  if (existing) {
    return existing
  }

  const request = fetchPMListResult(gw, { limit: 40, ...(venue === 'all' ? {} : { venue }) })
    .then(value => {
      let snapshots = caches.get(owner)

      if (!snapshots) {
        snapshots = new Map()
        caches.set(owner, snapshots)
      }

      snapshots.set(venue, { value, fetchedAt: Date.now() })

      return value
    })
    .finally(() => requests!.delete(venue))

  requests.set(venue, request)

  return request
}
