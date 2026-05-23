import { tuiEnvValue } from './envAlias.js'

const TERMUX_PREFIX = '/data/data/com.termux/files/usr'

const truthy = (value?: string) => /^(?:1|true|yes|on)$/i.test(String(value ?? '').trim())

export const isTermuxEnv = (env: NodeJS.ProcessEnv = process.env): boolean => {
  const prefix = String(env.PREFIX ?? '')

  return Boolean(env.TERMUX_VERSION) || prefix.includes(TERMUX_PREFIX)
}

/**
 * Return true when the TUI should enable Termux-focused defaults.
 *
 * Defaults to on in Termux, with an explicit opt-out for debugging:
 *   FORECAST_TUI_TERMUX_MODE=0 or HERMES_TUI_TERMUX_MODE=0
 */
export const isTermuxTuiMode = (env: NodeJS.ProcessEnv = process.env): boolean => {
  if (!isTermuxEnv(env)) {
    return false
  }

  const override = tuiEnvValue('TERMUX_MODE', env).toLowerCase()

  if (override) {
    return truthy(override)
  }

  return true
}
