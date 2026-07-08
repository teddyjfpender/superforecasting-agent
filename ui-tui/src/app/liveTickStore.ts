import { atom, onMount } from 'nanostores'

import { workTokens } from '../lib/liveStatus.js'
import { $uiState } from './uiStore.js'

// ── Liveness heartbeat ────────────────────────────────────────────────────────
// A single interval-driven counter that advances ONLY while a turn is active
// (busy). The spinner + running-status segment are the only subscribers, so a
// tick re-renders that one status row and NOTHING else — the render-isolation
// wins (composer/transcript/rail render +0 on ticks) hold.
//
// Idle = 0 Hz, 0 renders: the ticker is torn down the instant the turn ends and
// every reset is guarded so a quiet desk never sees a phantom notify. This fix
// therefore adds zero background churn when nothing is running.

export const LIVE_TICK_FPS = 10
export const LIVE_TICK_MS = Math.round(1000 / LIVE_TICK_FPS)

export const $liveTick = atom(0)
// Turn-start wall clock (drives the elapsed counter) + the session token baseline
// captured at turn start. Turn tokens = cumulative fresh work (usage.input +
// usage.output) − this baseline — NOT usage.total, which re-counts re-sent cached
// context every call and would balloon a long turn into millions (see workTokens).
export const $liveStartedAt = atom<null | number>(null)
export const $liveBaseTokens = atom(0)

let timer: null | ReturnType<typeof setInterval> = null

export function startLiveTicker(now: number = Date.now()): void {
  if (timer) {
    return
  }

  $liveStartedAt.set(now)
  $liveBaseTokens.set(workTokens($uiState.get().usage))
  timer = setInterval(() => $liveTick.set($liveTick.get() + 1), LIVE_TICK_MS)
}

export function stopLiveTicker(): void {
  if (timer) {
    clearInterval(timer)
    timer = null
  }

  // Reset to a known idle state, but only SET when a value actually changes — an
  // idle stop must not notify (that would be a phantom render on a quiet desk).
  if ($liveTick.get() !== 0) {
    $liveTick.set(0)
  }

  if ($liveStartedAt.get() !== null) {
    $liveStartedAt.set(null)
  }

  if ($liveBaseTokens.get() !== 0) {
    $liveBaseTokens.set(0)
  }
}

// Auto-wire to the busy flag, LAZILY: the controller installs only while the
// heartbeat has a live subscriber (the status bar is mounted) and tears itself
// down when that subscriber goes away. The frequent uiState churn (status text,
// usage) re-runs this cheap check, but start/stop are idempotent so the timer
// only actually flips on the busy edge.
onMount($liveTick, () => {
  const sync = () => {
    if ($uiState.get().busy) {
      startLiveTicker()
    } else {
      stopLiveTicker()
    }
  }

  sync()
  const unsub = $uiState.subscribe(sync)

  return () => {
    unsub()
    stopLiveTicker()
  }
})
