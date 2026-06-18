import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import { providerKey } from './newsProviderColor.js'

// User overrides for per-source News colours, keyed by normalized provider name
// (e.g. "nws" → "#F778BA"). Persisted to ~/.superforecasting-agent/
// news_provider_colors.json. Best-effort: a read/parse failure just means no
// overrides (sources fall back to their hashed hue).

export type ProviderColors = Record<string, string>

const file = (dir = forecastHomeDir()) => join(dir, 'news_provider_colors.json')

export const loadProviderColors = (path = file()): ProviderColors => {
  try {
    const data: unknown = JSON.parse(readFileSync(path, 'utf8'))

    if (!data || typeof data !== 'object') {
      return {}
    }

    const out: ProviderColors = {}

    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      if (typeof v === 'string' && /^#[0-9a-f]{3,8}$/i.test(v)) {
        out[providerKey(k)] = v
      }
    }

    return out
  } catch {
    return {}
  }
}

export const saveProviderColors = (colors: ProviderColors, path = file()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(path, JSON.stringify(colors), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
