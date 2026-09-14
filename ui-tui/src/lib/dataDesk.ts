import type { MarketSeries } from '../content/marketProviders.js'
import type { DataCatalog, DeskSelection } from '../protocol/generated.js'

import type { QuotesTransport } from './marketFetch.js'
import type { MarketConfig } from './marketStore.js'

/** The backend catalog is the only source of selectable built-in series. */
export const catalogSeries = (catalog: DataCatalog): MarketSeries[] => {
  const countries = new Map(catalog.countries.map(country => [country.id, country.name]))
  const names = new Map(catalog.categories.map(category => [category.id, category.name]))

  return catalog.series.map(series => ({
    catalog_id: series.id,
    kind: series.kind,
    refresh_seconds: series.refresh_seconds,
    category: names.get(series.category) ?? series.category,
    search_terms: [
      series.region,
      series.country,
      countries.get(series.country ?? ''),
      series.location?.name,
      ...series.tags
    ]
      .filter(Boolean)
      .join(' '),
    line: series.line ?? undefined,
    name: series.name,
    provider: series.provider,
    symbol: series.symbol,
    unit: series.unit
  }))
}

/** Adapt the connected backend's selection for the existing tape renderer. */
export const deskConfig = (catalog: DataCatalog, selection: DeskSelection): MarketConfig => {
  const selected = new Set(selection.series_ids)
  const chosen = catalogSeries(catalog).filter(series => selected.has(series.catalog_id ?? ''))
  const custom = selection.custom.map(series => ({ ...series, line: series.line ?? undefined }))
  const watchlist = selection.watchlist.map(series => ({ ...series, line: series.line ?? undefined }))

  return {
    catalogSeries: chosen,
    categories: [...new Set([...chosen, ...custom].map(series => series.category))],
    custom,
    pmSaved: selection.pm_saved,
    providers: [...new Set([...selection.providers, ...chosen.map(series => series.provider)])],
    revision: selection.revision,
    serverSide: selection.server_side ?? undefined,
    setupState: selection.state,
    watchlist
  }
}

/** Retry a disjoint edit after another surface saves, without overwriting it. */
export const saveDeskFields = async (
  gw: QuotesTransport,
  before: MarketConfig,
  after: MarketConfig
): Promise<MarketConfig> => {
  const custom = (items: MarketSeries[]) =>
    items.map(item => ({
      category: item.category || '',
      line: item.line ?? null,
      name: item.name || item.symbol,
      provider: item.provider,
      symbol: item.symbol,
      unit: item.unit ?? ''
    }))

  const fields = (config: MarketConfig) => ({
    categories: config.categories,
    custom: custom(config.custom),
    pm_saved: config.pmSaved ?? [],
    providers: config.providers,
    server_side: config.serverSide ?? null,
    watchlist: custom(config.watchlist)
  })

  const oldFields = fields(before)
  const newFields = fields(after)

  const changed = (Object.keys(newFields) as Array<keyof typeof newFields>).filter(
    key => JSON.stringify(newFields[key]) !== JSON.stringify(oldFields[key])
  )

  const latest = await gw.request('market.catalog', {})
  const current = fields(deskConfig(latest.catalog, latest.selection))

  for (const key of changed) {
    if (
      JSON.stringify(current[key]) !== JSON.stringify(oldFields[key]) &&
      JSON.stringify(current[key]) !== JSON.stringify(newFields[key])
    ) {
      throw new Error('This setting changed elsewhere. Reopen Markets before editing it.')
    }
  }

  const patch = Object.fromEntries(changed.map(key => [key, newFields[key]]))
  const result = await gw.request('market.selection.update', { expected_revision: latest.selection.revision, patch })

  return deskConfig(latest.catalog, result.selection)
}
