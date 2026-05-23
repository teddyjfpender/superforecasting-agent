import { describe, expect, it } from 'vitest'

import { tuiEnvValue } from '../config/env.js'

describe('tuiEnvValue', () => {
  it('prefers fork-native aliases before legacy Hermes names', () => {
    expect(
      tuiEnvValue('RESUME', {
        HERMES_TUI_RESUME: 'legacy-session',
        FORECAST_TUI_RESUME: 'forecast-session',
        SUPERFORECASTING_AGENT_TUI_RESUME: 'native-session'
      } as NodeJS.ProcessEnv)
    ).toBe('native-session')
  })

  it('falls back through forecast and legacy aliases', () => {
    expect(
      tuiEnvValue('RESUME', {
        HERMES_TUI_RESUME: 'legacy-session',
        FORECAST_TUI_RESUME: 'forecast-session'
      } as NodeJS.ProcessEnv)
    ).toBe('forecast-session')
    expect(tuiEnvValue('RESUME', { HERMES_TUI_RESUME: 'legacy-session' } as NodeJS.ProcessEnv)).toBe(
      'legacy-session'
    )
  })

  it('ignores blank higher-priority aliases', () => {
    expect(
      tuiEnvValue('INLINE', {
        SUPERFORECASTING_AGENT_TUI_INLINE: '  ',
        FORECAST_TUI_INLINE: '0',
        HERMES_TUI_INLINE: '1'
      } as NodeJS.ProcessEnv)
    ).toBe('0')
  })
})
