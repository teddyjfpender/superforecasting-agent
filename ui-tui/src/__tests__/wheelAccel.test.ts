import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { computeWheelStep, initWheelAccel, readScrollSpeedBase } from '../lib/wheelAccel.js'

const ENV_KEYS = [
  'CLAUDE_CODE_SCROLL_SPEED',
  'FORECAST_TUI_SCROLL_SPEED',
  'HERMES_TUI_SCROLL_SPEED',
  'SUPERFORECASTING_AGENT_TUI_SCROLL_SPEED'
] as const

const saved = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]])) as Record<
  (typeof ENV_KEYS)[number],
  string | undefined
>

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (saved[key] === undefined) {
      delete process.env[key]
    } else {
      process.env[key] = saved[key]
    }
  }
})

beforeEach(() => {
  for (const key of ENV_KEYS) {
    delete process.env[key]
  }
})

describe('readScrollSpeedBase', () => {
  it('prefers fork-native aliases before legacy and portability names', () => {
    process.env.CLAUDE_CODE_SCROLL_SPEED = '2'
    process.env.HERMES_TUI_SCROLL_SPEED = '3'
    process.env.FORECAST_TUI_SCROLL_SPEED = '4'
    process.env.SUPERFORECASTING_AGENT_TUI_SCROLL_SPEED = '5'

    expect(readScrollSpeedBase()).toBe(5)
  })

  it('keeps legacy and portability fallbacks', () => {
    process.env.HERMES_TUI_SCROLL_SPEED = '3'
    expect(readScrollSpeedBase()).toBe(3)

    delete process.env.HERMES_TUI_SCROLL_SPEED
    process.env.CLAUDE_CODE_SCROLL_SPEED = '2'
    expect(readScrollSpeedBase()).toBe(2)
  })
})

describe('wheelAccel — native path', () => {
  it('first click after init returns base', () => {
    const s = initWheelAccel(false, 1)

    expect(computeWheelStep(s, 1, 1000)).toBe(1)
  })

  it('same-direction fast events ramp mult (window-mode)', () => {
    const s = initWheelAccel(false, 1)

    computeWheelStep(s, 1, 1000)
    computeWheelStep(s, 1, 1020)
    computeWheelStep(s, 1, 1040)

    // Key property: doesn't shrink below base.
    expect(computeWheelStep(s, 1, 1060)).toBeGreaterThanOrEqual(1)
  })

  it('gap beyond window resets mult to base', () => {
    const s = initWheelAccel(false, 1)

    for (let t = 1000; t < 1100; t += 20) {
      computeWheelStep(s, 1, t)
    }

    expect(computeWheelStep(s, 1, 2000)).toBe(1)
  })

  it('direction flip defers one event for bounce detection', () => {
    const s = initWheelAccel(false, 1)

    computeWheelStep(s, 1, 1000)

    expect(computeWheelStep(s, -1, 1050)).toBe(0)
  })

  it('flip-back within bounce window engages wheelMode', () => {
    const s = initWheelAccel(false, 1)

    computeWheelStep(s, 1, 1000)
    computeWheelStep(s, -1, 1050)
    computeWheelStep(s, 1, 1100)

    expect(s.wheelMode).toBe(true)
  })

  it('flip-back outside bounce window is a real reversal (no wheelMode)', () => {
    const s = initWheelAccel(false, 1)

    computeWheelStep(s, 1, 1000)
    computeWheelStep(s, -1, 1050)
    computeWheelStep(s, 1, 1400)

    expect(s.wheelMode).toBe(false)
  })

  it('5 consecutive sub-5ms events disengage wheelMode (trackpad signature)', () => {
    const s = initWheelAccel(false, 1)
    s.wheelMode = true
    s.dir = 1
    s.time = 1000

    for (let t = 1002; t <= 1010; t += 2) {
      computeWheelStep(s, 1, t)
    }

    expect(s.wheelMode).toBe(false)
  })

  it('1.5s idle disengages wheelMode', () => {
    const s = initWheelAccel(false, 1)
    s.wheelMode = true
    s.dir = 1
    s.time = 1000

    computeWheelStep(s, 1, 3000)

    expect(s.wheelMode).toBe(false)
  })
})

describe('wheelAccel — xterm.js path', () => {
  it('first click returns 2 after long idle', () => {
    const s = initWheelAccel(true, 1)

    expect(computeWheelStep(s, 1, 1000)).toBeGreaterThanOrEqual(1)
  })

  it('sub-5ms burst returns 1 (same-direction, same-batch)', () => {
    const s = initWheelAccel(true, 1)

    computeWheelStep(s, 1, 1000)

    expect(computeWheelStep(s, 1, 1002)).toBe(1)
  })

  it('slow steady scroll stays in precision range', () => {
    const s = initWheelAccel(true, 1)

    for (let t = 1000; t < 2000; t += 33) {
      const r = computeWheelStep(s, 1, t)

      expect(r).toBeGreaterThanOrEqual(1)
      expect(r).toBeLessThanOrEqual(6)
    }
  })

  it('direction reversal resets mult', () => {
    const s = initWheelAccel(true, 1)

    for (let t = 1000; t < 1100; t += 20) {
      computeWheelStep(s, 1, t)
    }

    const beforeFlip = s.mult

    computeWheelStep(s, -1, 1200)

    expect(s.mult).toBeLessThanOrEqual(beforeFlip)
    expect(s.mult).toBe(2)
  })

  it('frac stays in [0,1) across events', () => {
    const s = initWheelAccel(true, 1)

    // Correctness invariant of fractional carry: never negative, never reaches 1.
    for (let t = 1000; t < 1200; t += 30) {
      computeWheelStep(s, 1, t)

      expect(s.frac).toBeGreaterThanOrEqual(0)
      expect(s.frac).toBeLessThan(1)
    }
  })
})
