import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { forecastHeapDumpDir, forecastHistoryFile, forecastHomeDir, forecastPerfLogPath } from '../lib/forecastHome.js'

describe('forecast home paths', () => {
  const original = {
    FORECAST_DEV_PERF_LOG: process.env.FORECAST_DEV_PERF_LOG,
    FORECAST_HEAPDUMP_DIR: process.env.FORECAST_HEAPDUMP_DIR,
    FORECAST_HOME: process.env.FORECAST_HOME,
    HERMES_DEV_PERF_LOG: process.env.HERMES_DEV_PERF_LOG,
    HERMES_HEAPDUMP_DIR: process.env.HERMES_HEAPDUMP_DIR,
    HERMES_HOME: process.env.HERMES_HOME,
    SUPERFORECASTING_AGENT_DEV_PERF_LOG: process.env.SUPERFORECASTING_AGENT_DEV_PERF_LOG,
    SUPERFORECASTING_AGENT_HEAPDUMP_DIR: process.env.SUPERFORECASTING_AGENT_HEAPDUMP_DIR,
    SUPERFORECASTING_AGENT_HOME: process.env.SUPERFORECASTING_AGENT_HOME
  }

  let root: string

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'forecast-home-test-'))
    delete process.env.SUPERFORECASTING_AGENT_HOME
    delete process.env.FORECAST_HOME
    delete process.env.HERMES_HOME
    delete process.env.SUPERFORECASTING_AGENT_DEV_PERF_LOG
    delete process.env.FORECAST_DEV_PERF_LOG
    delete process.env.HERMES_DEV_PERF_LOG
    delete process.env.SUPERFORECASTING_AGENT_HEAPDUMP_DIR
    delete process.env.FORECAST_HEAPDUMP_DIR
    delete process.env.HERMES_HEAPDUMP_DIR
  })

  afterEach(() => {
    rmSync(root, { force: true, recursive: true })

    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) {
        delete process.env[key]
      } else {
        process.env[key] = value
      }
    }
  })

  it('prefers fork-native home aliases before compatibility HERMES_HOME', () => {
    process.env.HERMES_HOME = join(root, 'legacy')
    process.env.FORECAST_HOME = join(root, 'forecast')
    process.env.SUPERFORECASTING_AGENT_HOME = join(root, 'native')

    expect(forecastHomeDir()).toBe(join(root, 'native'))
  })

  it('uses the forecast history file for new homes', () => {
    const home = join(root, 'native')
    process.env.SUPERFORECASTING_AGENT_HOME = home

    expect(forecastHistoryFile()).toBe(join(home, '.forecast_history'))
  })

  it('keeps reading legacy input history when that is all an existing home has', () => {
    const home = join(root, 'legacy-home')
    process.env.FORECAST_HOME = home
    mkdirSync(home, { recursive: true })
    writeFileSync(join(home, '.hermes_history'), '', { flag: 'w' })

    expect(forecastHistoryFile()).toBe(join(home, '.hermes_history'))
  })

  it('uses fork-native diagnostics paths before legacy overrides', () => {
    process.env.HERMES_DEV_PERF_LOG = join(root, 'legacy-perf.log')
    process.env.FORECAST_DEV_PERF_LOG = join(root, 'forecast-perf.log')
    process.env.SUPERFORECASTING_AGENT_DEV_PERF_LOG = join(root, 'native-perf.log')
    process.env.HERMES_HEAPDUMP_DIR = join(root, 'legacy-heap')
    process.env.FORECAST_HEAPDUMP_DIR = join(root, 'forecast-heap')
    process.env.SUPERFORECASTING_AGENT_HEAPDUMP_DIR = join(root, 'native-heap')

    expect(forecastPerfLogPath()).toBe(join(root, 'native-perf.log'))
    expect(forecastHeapDumpDir()).toBe(join(root, 'native-heap'))
  })
})
