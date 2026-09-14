import { readFileSync } from 'node:fs'

import { describe, expect, it, vi } from 'vitest'

import { catalogSeries, deskConfig, saveDeskFields } from '../lib/dataDesk.js'
import type { DataCatalog, DeskSelection } from '../protocol/generated.js'

const catalog = JSON.parse(
  readFileSync(new URL('../../../forecasting/marketdata/catalog.json', import.meta.url), 'utf8')
) as DataCatalog

// Manifest defaults are expanded by Pydantic before crossing the wire.
catalog.series = catalog.series.map(series => ({ ...series, tags: series.tags ?? [] }))

const selection = (): DeskSelection => ({
  categories: [],
  custom: [],
  home_region: null,
  pm_saved: [],
  providers: [],
  revision: 'initial',
  series_ids: [],
  server_side: null,
  state: 'empty',
  watchlist: [],
  weather_locations: null
})

describe('connected data desk', () => {
  it('keeps intentional empty selections empty and uses backend-only series', () => {
    const empty = deskConfig(catalog, selection())
    expect(empty.catalogSeries).toEqual([])
    expect(empty.categories).toEqual([])
    const first = catalog.series.find(series => series.provider === 'worldbank')!
    const populated = deskConfig(catalog, { ...selection(), series_ids: [first.id] })
    expect(populated.catalogSeries?.map(series => series.catalog_id)).toEqual([first.id])
    expect(catalogSeries(catalog).some(series => series.provider === 'openmeteo')).toBe(true)
  })

  it('preserves a prediction-market save while applying a disjoint watchlist edit', async () => {
    const before = deskConfig(catalog, selection())
    const latest = { ...selection(), pm_saved: [{ venue: 'kalshi', event_id: 'saved-elsewhere' }], revision: 'newer' }
    const watchlist = [{ category: 'Stocks', name: 'Example', provider: 'yahoo', symbol: 'EXAMPLE', unit: '' }]

    const request = vi.fn(async (method: string) =>
      method === 'market.catalog'
        ? { catalog, catalog_revision: 'catalog', configured_providers: [], selection: latest }
        : { selection: { ...latest, watchlist: watchlist.map(item => ({ ...item, line: null })) } }
    )

    const result = await saveDeskFields({ request } as never, before, { ...before, watchlist })
    expect(request.mock.calls[1]).toEqual([
      'market.selection.update',
      {
        expected_revision: 'newer',
        patch: { watchlist: watchlist.map(item => ({ ...item, line: null })) }
      }
    ])
    expect(result.pmSaved).toEqual(latest.pm_saved)
  })

  it('rejects an overlapping edit instead of replacing another clients watchlist', async () => {
    const before = deskConfig(catalog, selection())
    const item = { category: 'Stocks', line: null, name: 'Other', provider: 'yahoo', symbol: 'OTHER', unit: '' }
    const request = vi.fn().mockResolvedValue({ catalog, selection: { ...selection(), watchlist: [item] } })
    await expect(
      saveDeskFields({ request } as never, before, {
        ...before,
        watchlist: [{ ...item, line: undefined, symbol: 'MINE' }]
      })
    ).rejects.toThrow('changed elsewhere')
    expect(request).toHaveBeenCalledTimes(1)
  })
})
