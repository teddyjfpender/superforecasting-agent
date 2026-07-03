import { useEffect } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import { asRpcResult } from '../lib/rpc.js'

import { agentsActiveFromResult, setAgentsActive } from './agentsActiveStore.js'

// How often the status bar re-reads the live-agent aggregate. ~7s: fresh enough
// to feel live when the operator kicks off a batch from the chat, cheap enough
// that the RPC (one aggregate over three local job stores, no network) is free.
export const AGENTS_POLL_MS = 7000

// Imperative BOUNDED poller: an immediate `agents.active.summary` read paints the
// first frame, then one read every `intervalMs`, each pushed into $agentsActive.
// Returns a `stop()` that clears the interval AND guards a late resolve (so a poll
// in flight at teardown can't write the store after we've stopped). Pure of React
// so the lifecycle is unit-testable without a renderer.
export function pollAgentsActive(gw: GatewayClient, intervalMs: number = AGENTS_POLL_MS): () => void {
  let cancelled = false

  const poll = () => {
    gw.request<unknown>('agents.active.summary', {})
      .then(raw => {
        if (cancelled) {
          return
        }

        setAgentsActive(agentsActiveFromResult(asRpcResult(raw)))
      })
      .catch(() => {})
  }

  poll()
  const id = setInterval(poll, intervalMs)

  return () => {
    cancelled = true
    clearInterval(id)
  }
}

// React wrapper: run the poller while `active`, torn down on unmount OR when
// `active` flips false (a fullscreen overlay hides both status bars, so the read
// stops until we return — the detached jobs keep running server-side regardless,
// this only governs the READ cadence).
export function useAgentsActivePoll(gw: GatewayClient, active: boolean): void {
  useEffect(() => {
    if (!active) {
      return
    }

    return pollAgentsActive(gw)
  }, [gw, active])
}
