// Market data providers + a curated default series set, mirroring the News
// feed catalog. Providers expose series (symbols / economic indicators) tagged
// by category; the user enables providers (supplying an API key where needed)
// and picks which categories to watch. Keyless providers (Yahoo, Frankfurter,
// CoinGecko) work out of the box; FRED/BLS/BEA need a free key.

export interface MarketProvider {
  categories: string[]
  description: string
  key: string
  keyEnv?: string // env/.env var the API key is stored under (shared with the forecasting tools)
  keyUrl?: string // where to get a free key
  name: string
  needsKey: boolean
}

export interface MarketSeries {
  category: string
  name: string
  provider: string
  symbol: string
  unit?: string // '%', '$', 'index', etc. — for display of economic series
}

// The full breadth of categories across providers (not just the old
// Indices/FX/Crypto/Commodities). Users pick which to watch.
export const MARKET_CATEGORIES = [
  'Indices',
  'Stocks',
  'FX',
  'Crypto',
  'Commodities',
  'Rates',
  'Inflation',
  'Employment',
  'GDP',
  'Trade'
] as const

export const MARKET_PROVIDERS: MarketProvider[] = [
  {
    categories: ['Indices', 'Stocks', 'FX', 'Crypto', 'Commodities', 'Rates'],
    description: 'Live quotes for stocks, indices, FX, crypto, commodities and bond yields. No key.',
    key: 'yahoo',
    name: 'Yahoo Finance',
    needsKey: false
  },
  {
    categories: ['FX'],
    description: 'Reference FX rates from the European Central Bank. No key.',
    key: 'frankfurter',
    name: 'Frankfurter (ECB)',
    needsKey: false
  },
  {
    categories: ['Crypto'],
    description: 'Crypto spot prices + 24h change across thousands of coins. No key.',
    key: 'coingecko',
    name: 'CoinGecko',
    needsKey: false
  },
  {
    categories: ['Rates', 'Inflation', 'Employment', 'GDP'],
    description: 'US macro series from the St. Louis Fed (CPI, unemployment, rates, GDP…).',
    key: 'fred',
    keyEnv: 'FRED_API_KEY',
    keyUrl: 'https://fredaccount.stlouisfed.org/apikeys',
    name: 'FRED (St. Louis Fed)',
    needsKey: true
  },
  {
    categories: ['Inflation', 'Employment'],
    description: 'US Bureau of Labor Statistics — CPI, unemployment, payrolls. Key optional (raises limits).',
    key: 'bls',
    keyEnv: 'BLS_API_KEY',
    keyUrl: 'https://data.bls.gov/registrationEngine/',
    name: 'BLS',
    needsKey: false
  },
  {
    categories: ['GDP', 'Trade'],
    description: 'US Bureau of Economic Analysis — GDP and trade balances (NIPA).',
    key: 'bea',
    keyEnv: 'BEA_API_KEY',
    keyUrl: 'https://apps.bea.gov/API/signup/',
    name: 'BEA',
    needsKey: true
  }
]

export const providerByKey = (key: string): MarketProvider | undefined =>
  MARKET_PROVIDERS.find(p => p.key === key)

// Curated default series each provider contributes, by category. The view
// fetches the series whose provider is enabled and whose category is selected.
export const DEFAULT_SERIES: MarketSeries[] = [
  // Yahoo — Indices
  { category: 'Indices', name: 'S&P 500', provider: 'yahoo', symbol: '^GSPC' },
  { category: 'Indices', name: 'Dow Jones', provider: 'yahoo', symbol: '^DJI' },
  { category: 'Indices', name: 'Nasdaq', provider: 'yahoo', symbol: '^IXIC' },
  { category: 'Indices', name: 'Russell 2000', provider: 'yahoo', symbol: '^RUT' },
  { category: 'Indices', name: 'FTSE 100', provider: 'yahoo', symbol: '^FTSE' },
  { category: 'Indices', name: 'DAX', provider: 'yahoo', symbol: '^GDAXI' },
  { category: 'Indices', name: 'Nikkei 225', provider: 'yahoo', symbol: '^N225' },
  { category: 'Indices', name: 'VIX', provider: 'yahoo', symbol: '^VIX' },
  // Yahoo — Stocks
  { category: 'Stocks', name: 'Apple', provider: 'yahoo', symbol: 'AAPL' },
  { category: 'Stocks', name: 'Microsoft', provider: 'yahoo', symbol: 'MSFT' },
  { category: 'Stocks', name: 'Nvidia', provider: 'yahoo', symbol: 'NVDA' },
  { category: 'Stocks', name: 'Alphabet', provider: 'yahoo', symbol: 'GOOGL' },
  { category: 'Stocks', name: 'Amazon', provider: 'yahoo', symbol: 'AMZN' },
  { category: 'Stocks', name: 'Tesla', provider: 'yahoo', symbol: 'TSLA' },
  // Yahoo — Commodities
  { category: 'Commodities', name: 'Gold', provider: 'yahoo', symbol: 'GC=F' },
  { category: 'Commodities', name: 'Silver', provider: 'yahoo', symbol: 'SI=F' },
  { category: 'Commodities', name: 'Crude Oil (WTI)', provider: 'yahoo', symbol: 'CL=F' },
  { category: 'Commodities', name: 'Natural Gas', provider: 'yahoo', symbol: 'NG=F' },
  { category: 'Commodities', name: 'Copper', provider: 'yahoo', symbol: 'HG=F' },
  // Yahoo — Rates (Treasury yields)
  { category: 'Rates', name: 'US 10Y Yield', provider: 'yahoo', symbol: '^TNX', unit: '%' },
  { category: 'Rates', name: 'US 30Y Yield', provider: 'yahoo', symbol: '^TYX', unit: '%' },
  { category: 'Rates', name: 'US 5Y Yield', provider: 'yahoo', symbol: '^FVX', unit: '%' },
  // Frankfurter — FX (ECB rates, USD base: value = currency per 1 USD)
  { category: 'FX', name: 'EUR per USD', provider: 'frankfurter', symbol: 'EUR' },
  { category: 'FX', name: 'GBP per USD', provider: 'frankfurter', symbol: 'GBP' },
  { category: 'FX', name: 'JPY per USD', provider: 'frankfurter', symbol: 'JPY' },
  { category: 'FX', name: 'CHF per USD', provider: 'frankfurter', symbol: 'CHF' },
  { category: 'FX', name: 'CAD per USD', provider: 'frankfurter', symbol: 'CAD' },
  { category: 'FX', name: 'AUD per USD', provider: 'frankfurter', symbol: 'AUD' },
  // CoinGecko — Crypto
  { category: 'Crypto', name: 'Bitcoin', provider: 'coingecko', symbol: 'bitcoin' },
  { category: 'Crypto', name: 'Ethereum', provider: 'coingecko', symbol: 'ethereum' },
  { category: 'Crypto', name: 'Solana', provider: 'coingecko', symbol: 'solana' },
  { category: 'Crypto', name: 'XRP', provider: 'coingecko', symbol: 'ripple' },
  { category: 'Crypto', name: 'Cardano', provider: 'coingecko', symbol: 'cardano' },
  // FRED — macro
  { category: 'Rates', name: 'Fed Funds Rate', provider: 'fred', symbol: 'FEDFUNDS', unit: '%' },
  { category: 'Rates', name: '10Y Treasury', provider: 'fred', symbol: 'DGS10', unit: '%' },
  { category: 'Rates', name: '2Y Treasury', provider: 'fred', symbol: 'DGS2', unit: '%' },
  { category: 'Inflation', name: 'CPI (all items)', provider: 'fred', symbol: 'CPIAUCSL', unit: 'idx' },
  { category: 'Inflation', name: 'Core CPI', provider: 'fred', symbol: 'CPILFESL', unit: 'idx' },
  { category: 'Inflation', name: 'PCE Price Index', provider: 'fred', symbol: 'PCEPI', unit: 'idx' },
  { category: 'Employment', name: 'Unemployment Rate', provider: 'fred', symbol: 'UNRATE', unit: '%' },
  { category: 'Employment', name: 'Nonfarm Payrolls', provider: 'fred', symbol: 'PAYEMS', unit: 'k' },
  { category: 'Employment', name: 'Initial Claims', provider: 'fred', symbol: 'ICSA', unit: '' },
  { category: 'GDP', name: 'Nominal GDP', provider: 'fred', symbol: 'GDP', unit: '$B' },
  { category: 'GDP', name: 'Real GDP', provider: 'fred', symbol: 'GDPC1', unit: '$B' },
  // BLS — inflation/employment
  { category: 'Inflation', name: 'CPI-U', provider: 'bls', symbol: 'CUUR0000SA0', unit: 'idx' },
  { category: 'Employment', name: 'Unemployment Rate', provider: 'bls', symbol: 'LNS14000000', unit: '%' },
  { category: 'Employment', name: 'Total Nonfarm', provider: 'bls', symbol: 'CES0000000001', unit: 'k' },
  // BEA — GDP/Trade (NIPA tables)
  { category: 'GDP', name: 'GDP (NIPA T10101)', provider: 'bea', symbol: 'T10101', unit: '%' },
  { category: 'Trade', name: 'Net Exports (T10105)', provider: 'bea', symbol: 'T10105', unit: '$B' }
]
