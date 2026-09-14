/** Display projection of the backend data catalog; no client-owned defaults. */
export interface MarketSeries {
  search_terms?: string
  catalog_id?: string
  kind?: string
  refresh_seconds?: number
  line?: string
  category: string
  name: string
  provider: string
  symbol: string
  unit?: string // '%', '$', 'index', etc. — for display of economic series
}
