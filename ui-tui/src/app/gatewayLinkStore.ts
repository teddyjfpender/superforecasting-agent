import { atom, computed } from 'nanostores'

// ── The gateway link: is the desk actually connected to anything? ─────────────
//
// Before this existed, a dead gateway left the desk rendering normally while
// every RPC rejected — the failure was invisible until you tried to do something
// and it failed silently. That matters most in the shipped deploy story
// (`tmux new-session -A -s desk` over ssh): an operator reconnects days later to
// a session that looks alive and is functionally dead.
//
// GatewayClient supervises the transport and drives this store. The phases:
//
//   starting       — spawning / connecting; no gateway.ready yet
//   live           — gateway.ready seen, RPCs work
//   reconnecting   — the transport died and a respawn is scheduled (bounded)
//   lost           — the retry budget is spent; TERMINAL until a manual retry
//
// `resumeSid` is the session that was live when the transport died. The next
// gateway.ready CONSUMES it and resumes that session instead of silently
// starting a blank one — a desk that reconnects but quietly drops its session is
// worse than one that says it is dead.

export type GatewayLinkPhase = 'live' | 'lost' | 'reconnecting' | 'starting'

export interface GatewayLinkState {
  // 1-based attempt number while reconnecting; the total spent once lost.
  attempt: number
  // Human-readable cause of the most recent death ("gateway exited (1)").
  detail: string
  max: number
  // Delay until the scheduled respawn — rendered so the wait is not a mystery.
  nextRetryMs: number
  phase: GatewayLinkPhase
  // Session id captured at death, consumed by the next ready. Null when the
  // desk had no session yet (nothing to restore).
  resumeSid: null | string
  // How many respawns have happened this process — drives the honest
  // "reconnected" line, so a recovery is never silent.
  restarts: number
}

const initial = (): GatewayLinkState => ({
  attempt: 0,
  detail: '',
  max: 0,
  nextRetryMs: 0,
  phase: 'starting',
  restarts: 0,
  resumeSid: null
})

export const $gatewayLink = atom<GatewayLinkState>(initial())

// Scoped so chrome subscribing to "am I connected?" never re-renders on the
// resumeSid bookkeeping or the restart counter.
export const $gatewayLinkPhase = computed($gatewayLink, state => state.phase)

export const getGatewayLink = () => $gatewayLink.get()

const patch = (next: Partial<GatewayLinkState>) => $gatewayLink.set({ ...$gatewayLink.get(), ...next })

/** The transport died and a respawn is scheduled. Captures the live session. */
export const markLinkReconnecting = (info: {
  attempt: number
  detail: string
  max: number
  nextRetryMs: number
  sid?: null | string
}) => {
  const current = $gatewayLink.get()

  patch({
    attempt: info.attempt,
    detail: info.detail,
    max: info.max,
    nextRetryMs: info.nextRetryMs,
    phase: 'reconnecting',
    // Only the FIRST death in a burst has a live sid to capture; later attempts
    // in the same ladder must not overwrite it with null.
    resumeSid: info.sid ?? current.resumeSid
  })
}

/** gateway.ready landed. Returns true when this was a RECOVERY, not a cold start. */
export const markLinkLive = (): boolean => {
  const current = $gatewayLink.get()
  const recovered = current.phase === 'reconnecting'

  patch({
    attempt: 0,
    detail: '',
    nextRetryMs: 0,
    phase: 'live',
    restarts: recovered ? current.restarts + 1 : current.restarts
  })

  return recovered
}

/** The retry budget is spent (or supervision is off). Terminal until a manual retry. */
export const markLinkLost = (info: { attempts: number; detail: string }) =>
  patch({ attempt: info.attempts, detail: info.detail, nextRetryMs: 0, phase: 'lost' })

/** A manual reconnect was requested — back to the starting state. */
export const markLinkStarting = () => patch({ attempt: 0, nextRetryMs: 0, phase: 'starting' })

/**
 * Read AND clear the session captured at death. Single-use on purpose: the
 * gateway.ready handler must resume it exactly once, and a later cold ready
 * must not silently re-resume a session the user has since moved on from.
 */
export const takeResumeSid = (): null | string => {
  const sid = $gatewayLink.get().resumeSid

  if (sid !== null) {
    patch({ resumeSid: null })
  }

  return sid
}

export const resetGatewayLink = () => $gatewayLink.set(initial())
