import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'

// Provider API keys are stored in the shared secret store at
// ~/.superforecasting-agent/.env (the same file `/api-key` and the forecasting
// tools read), so a FRED key added in Markets also benefits forecasts. Written
// 0600; other lines preserved.

export const envFile = (dir = forecastHomeDir()) => join(dir, '.env')

export const parseEnv = (text: string): Record<string, string> => {
  const out: Record<string, string> = {}

  for (const raw of text.split('\n')) {
    const line = raw.trim()

    if (!line || line.startsWith('#')) {
      continue
    }

    const eq = line.indexOf('=')

    if (eq <= 0) {
      continue
    }

    const name = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()

    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }

    out[name] = value
  }

  return out
}

// Upsert NAME=value into a .env body, replacing an existing line or appending.
export const upsertEnv = (text: string, name: string, value: string): string => {
  const entry = `${name}=${value}`
  const lines = text.length ? text.replace(/\n+$/, '').split('\n') : []
  const re = new RegExp(`^\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*=`)
  const idx = lines.findIndex(l => re.test(l))

  if (idx >= 0) {
    lines[idx] = entry
  } else {
    lines.push(entry)
  }

  return `${lines.join('\n')}\n`
}

export const loadEnvKeys = (file = envFile()): Record<string, string> => {
  try {
    return parseEnv(readFileSync(file, 'utf8'))
  } catch {
    return {}
  }
}

// Resolve a provider key: live process env first, then the .env store.
export const getProviderKey = (envVar: string): string =>
  (process.env[envVar]?.trim() || '') || loadEnvKeys()[envVar] || ''

export const saveProviderKey = (name: string, value: string, file = envFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    let text = ''

    try {
      text = readFileSync(file, 'utf8')
    } catch {
      /* no existing .env */
    }

    writeFileSync(file, upsertEnv(text, name, value.trim()), { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
