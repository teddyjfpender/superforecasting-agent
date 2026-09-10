import { tuiEnvValue } from './envAlias.js'

export function isMouseClicksDisabled(): boolean {
  return /^(1|true|yes|on)$/.test(tuiEnvValue(process.env, 'DISABLE_MOUSE_CLICKS').toLowerCase())
}
