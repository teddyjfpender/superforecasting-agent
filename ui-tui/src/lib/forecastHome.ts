import { existsSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'

const firstConfigured = (names: string[]) => {
  for (const name of names) {
    const value = process.env[name]?.trim()
    if (value) return value
  }
  return undefined
}

const userHome = () => homedir() || tmpdir()

export const forecastHomeDir = () => {
  const configured = firstConfigured(['SUPERFORECASTING_AGENT_HOME', 'FORECAST_HOME', 'HERMES_HOME'])
  if (configured) return configured

  const native = join(userHome(), '.superforecasting-agent')
  if (existsSync(native)) return native

  const legacy = join(userHome(), '.hermes')
  if (existsSync(legacy)) return legacy

  return native
}

export const forecastHistoryFile = (dir = forecastHomeDir()) => {
  const native = join(dir, '.forecast_history')
  const legacy = join(dir, '.hermes_history')
  return !existsSync(native) && existsSync(legacy) ? legacy : native
}

export const forecastPerfLogPath = () =>
  firstConfigured(['SUPERFORECASTING_AGENT_DEV_PERF_LOG', 'FORECAST_DEV_PERF_LOG', 'HERMES_DEV_PERF_LOG']) ??
  join(forecastHomeDir(), 'perf.log')

export const forecastHeapDumpDir = () =>
  firstConfigured(['SUPERFORECASTING_AGENT_HEAPDUMP_DIR', 'FORECAST_HEAPDUMP_DIR', 'HERMES_HEAPDUMP_DIR']) ??
  join(forecastHomeDir(), 'heapdumps')

export const forecastDiagnosticPrefix = () => 'superforecasting-agent'
