import { atom } from 'nanostores'

// One glanceable heuristic — how many detached "agent" jobs are live right now
// (background processes + mass reforecast/desk-task jobs + quorum forecasts),
// summed by the gateway's `agents.active.summary` RPC. BOTH status bars (the Home
// landing and the active-conversation rule) read this ONE store, so the
// "✦ N agents running · …" chip is a single source of truth across surfaces —
// there is no second bespoke bar to drift.

export interface AgentsActive {
  count: number
  headline: string
}

export const AGENTS_ACTIVE_EMPTY: AgentsActive = { count: 0, headline: '' }

export const $agentsActive = atom<AgentsActive>(AGENTS_ACTIVE_EMPTY)

// Set only when the value actually changed, so a steady ~7s poll that keeps
// returning the same summary never churns the subscribed bars (and, at rest,
// keeps the chip byte-identically ABSENT — count 0 renders nothing).
export const setAgentsActive = (next: AgentsActive): void => {
  const cur = $agentsActive.get()

  if (cur.count === next.count && cur.headline === next.headline) {
    return
  }

  $agentsActive.set(next)
}

// Normalise a raw `agents.active.summary` result into the store shape. Tolerant
// of a null/partial payload (a failed or empty poll) → the empty summary, so the
// chip hides rather than rendering a stale or malformed heuristic.
export const agentsActiveFromResult = (
  r: { count?: unknown; headline?: unknown } | null | undefined
): AgentsActive => ({
  count: Math.max(0, Math.trunc(Number(r?.count ?? 0)) || 0),
  headline: typeof r?.headline === 'string' ? r.headline : ''
})
