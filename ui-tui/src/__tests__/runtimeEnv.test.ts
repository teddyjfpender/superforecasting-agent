import { describe, expect, it } from 'vitest'

import { runtimeEnvEnabled, runtimeEnvValue } from '../lib/runtimeEnv.js'

describe('runtimeEnvValue', () => {
  it('prefers fork-native aliases before legacy Hermes names', () => {
    expect(
      runtimeEnvValue('CWD', {
        HERMES_CWD: '/legacy',
        FORECAST_CWD: '/forecast',
        SUPERFORECASTING_AGENT_CWD: '/native'
      } as NodeJS.ProcessEnv)
    ).toBe('/native')
  })

  it('falls back through forecast and legacy aliases', () => {
    expect(
      runtimeEnvValue('CWD', {
        HERMES_CWD: '/legacy',
        FORECAST_CWD: '/forecast'
      } as NodeJS.ProcessEnv)
    ).toBe('/forecast')

    expect(runtimeEnvValue('CWD', { HERMES_CWD: '/legacy' } as NodeJS.ProcessEnv)).toBe('/legacy')
  })

  it('ignores blank higher-priority aliases', () => {
    expect(
      runtimeEnvValue('CWD', {
        SUPERFORECASTING_AGENT_CWD: '  ',
        FORECAST_CWD: '/forecast',
        HERMES_CWD: '/legacy'
      } as NodeJS.ProcessEnv)
    ).toBe('/forecast')
  })
})

describe('runtimeEnvEnabled', () => {
  it('is enabled only by an explicit 1 value', () => {
    expect(runtimeEnvEnabled('VOICE', { SUPERFORECASTING_AGENT_VOICE: '1' } as NodeJS.ProcessEnv)).toBe(true)
    expect(runtimeEnvEnabled('VOICE', { SUPERFORECASTING_AGENT_VOICE: 'true' } as NodeJS.ProcessEnv)).toBe(false)
    expect(runtimeEnvEnabled('VOICE', { SUPERFORECASTING_AGENT_VOICE: '0' } as NodeJS.ProcessEnv)).toBe(false)
  })

  it('respects alias precedence before evaluating the value', () => {
    expect(
      runtimeEnvEnabled('VOICE', {
        HERMES_VOICE: '1',
        FORECAST_VOICE: '1',
        SUPERFORECASTING_AGENT_VOICE: '0'
      } as NodeJS.ProcessEnv)
    ).toBe(false)

    expect(
      runtimeEnvEnabled('VOICE', {
        HERMES_VOICE: '1',
        FORECAST_VOICE: '1',
        SUPERFORECASTING_AGENT_VOICE: ' '
      } as NodeJS.ProcessEnv)
    ).toBe(true)
  })
})
