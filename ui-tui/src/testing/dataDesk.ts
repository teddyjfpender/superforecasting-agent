/** Controlled backend for product-view tests; catalog content stays server-owned. */
import { readFileSync } from 'node:fs'

import type { DataCatalog, DeskCustomSeries, DeskPatch, DeskSelection } from '../protocol/generated.js'

export const testDataCatalog = JSON.parse(
  readFileSync(new URL('../../../forecasting/marketdata/catalog.json', import.meta.url), 'utf8')
) as DataCatalog

// The wire includes Pydantic defaults that the compact manifest may omit.
for (const series of testDataCatalog.series) { series.tags ??= [] }

for (const region of testDataCatalog.regions) { region.members ??= [] }

for (const provider of testDataCatalog.providers) { provider.auth ??= 'none' }

export function dataDeskGateway(watchlist: DeskCustomSeries[] = []) {
  let selection: DeskSelection = {
    revision: 'initial', state: watchlist.length ? 'custom' : 'empty', series_ids: [],
    categories: [], providers: [], custom: [], watchlist, pm_saved: [],
    server_side: null, home_region: null, weather_locations: null
  }

  return {
    on: () => undefined,
    off: () => undefined,
    request: async (method: string, params: { patch?: DeskPatch } = {}) => {
      if (method === 'market.catalog') {
        return { catalog: testDataCatalog, catalog_revision: 'fixture', selection, configured_providers: [] }
      }

      if (method === 'market.selection.update') {
        selection = { ...selection, ...params.patch, revision: 'updated' } as DeskSelection

        return { selection }
      }

      if (method === 'market.quotes') { return { quotes: [], statuses: [] } }

      if (method === 'pm.list') { return { items: [], total: 0 } }

      return {}
    }
  }
}
