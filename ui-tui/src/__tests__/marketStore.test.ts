import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, afterEach, beforeEach, describe, expect, it } from 'vitest'

import { loadEnvKeys, parseEnv, saveProviderKey, upsertEnv } from '../lib/marketKeys.js'
import { loadMarketConfig, saveMarketConfig } from '../lib/marketStore.js'

const tmp = mkdtempSync(join(tmpdir(), 'markets-store-'))
const prevHome = process.env.SUPERFORECASTING_AGENT_HOME

beforeEach(() => {
  process.env.SUPERFORECASTING_AGENT_HOME = tmp
})

afterEach(() => {
  delete process.env.FRED_API_KEY
})

afterAll(() => {
  rmSync(tmp, { force: true, recursive: true })

  if (prevHome === undefined) {
    delete process.env.SUPERFORECASTING_AGENT_HOME
  } else {
    process.env.SUPERFORECASTING_AGENT_HOME = prevHome
  }
})

describe('parseEnv / upsertEnv', () => {
  it('parses KEY=value lines, ignoring comments + quotes', () => {
    const env = parseEnv('# a comment\nFRED_API_KEY=abc123\nBLS_API_KEY="quoted"\n\nBAD LINE')
    expect(env.FRED_API_KEY).toBe('abc123')
    expect(env.BLS_API_KEY).toBe('quoted')
    expect(env.BAD).toBeUndefined()
  })

  it('replaces an existing key in place and preserves others', () => {
    const before = 'OPENAI_API_KEY=keep\nFRED_API_KEY=old\n'
    const after = upsertEnv(before, 'FRED_API_KEY', 'new')
    expect(after).toContain('OPENAI_API_KEY=keep')
    expect(after).toContain('FRED_API_KEY=new')
    expect(after).not.toContain('FRED_API_KEY=old')
  })

  it('appends a new key when absent', () => {
    expect(upsertEnv('A=1\n', 'B', '2')).toBe('A=1\nB=2\n')
    expect(upsertEnv('', 'B', '2')).toBe('B=2\n')
  })
})

describe('saveProviderKey / loadEnvKeys', () => {
  it('writes the key to the shared .env and reads it back', () => {
    const file = join(tmp, '.env')
    expect(saveProviderKey('FRED_API_KEY', 'secret-key', file)).toBe(true)
    expect(loadEnvKeys(file).FRED_API_KEY).toBe('secret-key')
    // file should not be world-readable junk — it's valid KEY=value
    expect(readFileSync(file, 'utf8')).toContain('FRED_API_KEY=secret-key')
  })
})

describe('market config', () => {
  it('round-trips enabled providers + selected categories', () => {
    const file = join(tmp, 'markets.json')
    saveMarketConfig({ categories: ['Indices', 'Crypto'], providers: ['yahoo', 'coingecko'] }, file)
    const loaded = loadMarketConfig(file)
    expect(loaded.providers).toEqual(['yahoo', 'coingecko'])
    expect(loaded.categories).toEqual(['Indices', 'Crypto'])
  })

  it('returns empty config when the file is missing', () => {
    expect(loadMarketConfig(join(tmp, 'nope.json'))).toEqual({ categories: [], providers: [] })
  })
})
