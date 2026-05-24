import { afterEach, describe, expect, it } from 'vitest'

import { isMouseClicksDisabled } from './fullscreen.js'

const ENV_KEYS = [
  'FORECAST_TUI_DISABLE_MOUSE_CLICKS',
  'HERMES_TUI_DISABLE_MOUSE_CLICKS',
  'SUPERFORECASTING_AGENT_TUI_DISABLE_MOUSE_CLICKS'
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

describe('isMouseClicksDisabled', () => {
  it('prefers fork-native aliases before legacy names', () => {
    process.env.HERMES_TUI_DISABLE_MOUSE_CLICKS = '0'
    process.env.SUPERFORECASTING_AGENT_TUI_DISABLE_MOUSE_CLICKS = '1'

    expect(isMouseClicksDisabled()).toBe(true)
  })

  it('accepts short forecast aliases and legacy names', () => {
    process.env.FORECAST_TUI_DISABLE_MOUSE_CLICKS = 'yes'
    expect(isMouseClicksDisabled()).toBe(true)

    delete process.env.FORECAST_TUI_DISABLE_MOUSE_CLICKS
    process.env.HERMES_TUI_DISABLE_MOUSE_CLICKS = 'on'
    expect(isMouseClicksDisabled()).toBe(true)
  })
})
