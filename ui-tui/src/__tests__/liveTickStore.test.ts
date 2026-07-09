import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $liveBaseTokens,
  $liveStartedAt,
  $liveTick,
  LIVE_TICK_FPS,
  LIVE_TICK_MS,
  startLiveTicker,
  stopLiveTicker
} from '../app/liveTickStore.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'

beforeEach(() => {
  vi.useFakeTimers()
  resetUiState()
  stopLiveTicker()
})

afterEach(() => {
  stopLiveTicker()
  vi.useRealTimers()
})

describe('liveTick heartbeat cadence', () => {
  it('is a ~10 fps ticker', () => {
    expect(LIVE_TICK_FPS).toBe(10)
    expect(LIVE_TICK_MS).toBe(100)
  })
})

describe('the ticker advances while active', () => {
  it('increments $liveTick at the heartbeat interval and captures turn start + token baseline', () => {
    // Baseline is the honest work tally (input + output), NOT usage.total — the
    // huge total here is mostly re-sent cached context and must not seed the base.
    patchUiState({ usage: { calls: 12, input: 3000, output: 1200, total: 4_200_000 } })

    startLiveTicker(1_000)
    expect($liveStartedAt.get()).toBe(1_000)
    expect($liveBaseTokens.get()).toBe(4200)

    const before = $liveTick.get()
    vi.advanceTimersByTime(LIVE_TICK_MS * 5)
    expect($liveTick.get()).toBe(before + 5)
  })

  it('start is idempotent — a second start does not double-drive the interval', () => {
    startLiveTicker(1000)
    startLiveTicker(9000)
    expect($liveStartedAt.get()).toBe(1000)

    const before = $liveTick.get()
    vi.advanceTimersByTime(LIVE_TICK_MS * 3)
    // A single interval → exactly 3 ticks, not 6.
    expect($liveTick.get()).toBe(before + 3)
  })
})

describe('the ticker stops at idle — zero ticks, zero churn', () => {
  it('clears the interval and resets to a known idle state', () => {
    startLiveTicker()
    vi.advanceTimersByTime(LIVE_TICK_MS * 2)
    expect($liveTick.get()).toBeGreaterThan(0)

    stopLiveTicker()
    expect($liveTick.get()).toBe(0)
    expect($liveStartedAt.get()).toBeNull()
    expect($liveBaseTokens.get()).toBe(0)

    vi.advanceTimersByTime(LIVE_TICK_MS * 10)
    expect($liveTick.get()).toBe(0)
  })

  it('an idle stop notifies NOBODY — a quiet desk sees no phantom render', () => {
    // Already idle; subscribe, then stop again. The subscription fires ONCE on
    // subscribe (nanostores contract) and must not fire again from the no-op stop.
    let notifications = 0

    const unsub = $liveTick.subscribe(() => {
      notifications += 1
    })

    notifications = 0

    stopLiveTicker()
    vi.advanceTimersByTime(LIVE_TICK_MS * 10)
    expect(notifications).toBe(0)

    unsub()
  })
})

describe('auto-wiring to the busy flag', () => {
  it('starts on busy=true and stops on busy=false', async () => {
    patchUiState({ busy: true })
    await Promise.resolve()
    const before = $liveTick.get()
    vi.advanceTimersByTime(LIVE_TICK_MS * 4)
    expect($liveTick.get()).toBe(before + 4)

    patchUiState({ busy: false })
    await Promise.resolve()
    expect($liveTick.get()).toBe(0)
    vi.advanceTimersByTime(LIVE_TICK_MS * 10)
    expect($liveTick.get()).toBe(0)
  })

  it('preserves elapsed time across view/status churn mid-turn', async () => {
    patchUiState({ usage: { calls: 1, input: 7000, output: 300, total: 25000 } })
    patchUiState({ busy: true })
    await Promise.resolve()
    vi.advanceTimersByTime(LIVE_TICK_MS * 2)

    const startedAt = $liveStartedAt.get()
    const baseTokens = $liveBaseTokens.get()
    const tickAtUnmount = $liveTick.get()

    patchUiState({ compact: true, status: 'checking another view…' })
    vi.advanceTimersByTime(LIVE_TICK_MS * 5)
    expect($liveStartedAt.get()).toBe(startedAt)
    expect($liveBaseTokens.get()).toBe(baseTokens)
    expect($liveTick.get()).toBe(tickAtUnmount + 5)

    expect($liveStartedAt.get()).toBe(startedAt)
    expect($liveBaseTokens.get()).toBe(baseTokens)
    vi.advanceTimersByTime(LIVE_TICK_MS * 3)
    expect($liveTick.get()).toBe(tickAtUnmount + 8)

    patchUiState({ busy: false })
    await Promise.resolve()
    expect($liveTick.get()).toBe(0)
    expect($liveStartedAt.get()).toBeNull()
    expect($liveBaseTokens.get()).toBe(0)
  })
})
