import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import type { MarketModelListItem } from './presentation.js'

// Local cache of the saved Market Models catalog, so the Models list paints
// instantly (and offline) on reopen. The gateway (ledger) is the source of
// truth; this mirrors marketStore.ts's quote-cache pattern. Persisted to
// ~/.superforecasting-agent/market_models.json (0600).

export interface ModelCatalog {
  models: MarketModelListItem[]
}

export const modelCatalogFile = (dir = forecastHomeDir()): string => join(dir, 'market_models.json')

export const loadModelCatalog = (file = modelCatalogFile()): ModelCatalog => {
  try {
    const data = JSON.parse(readFileSync(file, 'utf8')) as Partial<ModelCatalog>

    const models = Array.isArray(data.models)
      ? data.models.filter((m): m is MarketModelListItem => Boolean(m) && typeof (m as MarketModelListItem).id === 'string')
      : []

    return { models }
  } catch {
    return { models: [] }
  }
}

export const saveModelCatalog = (catalog: ModelCatalog, file = modelCatalogFile()): boolean => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, `${JSON.stringify(catalog, null, 2)}\n`, { mode: 0o600 })

    return true
  } catch {
    return false
  }
}
