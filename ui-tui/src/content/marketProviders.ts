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
  // A key is strongly recommended even though one isn't strictly required: the
  // keyless path technically works but is effectively unusable (e.g. BLS's
  // shared no-key quota is perpetually exhausted). Surfaces a warning, but
  // unlike needsKey does NOT block enabling without a key.
  keyRecommended?: boolean
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
    categories: ['Rates', 'Inflation', 'Employment', 'GDP', 'Commodities', 'Trade'],
    description: 'US macro series from the St. Louis Fed (rates, credit spreads, CPI/PCE, payrolls, GDP, industrial production…). Works without a key via the public endpoint; a free key raises reliability + limits.',
    key: 'fred',
    keyEnv: 'FRED_API_KEY',
    keyUrl: 'https://fredaccount.stlouisfed.org/apikeys',
    name: 'FRED (St. Louis Fed)',
    needsKey: false
  },
  {
    categories: ['Inflation', 'Employment'],
    description: 'US Bureau of Labor Statistics — CPI components, unemployment, payrolls, earnings. A free key is strongly recommended: the shared no-key quota is perpetually exhausted, so series stay blank until you add one.',
    key: 'bls',
    keyEnv: 'BLS_API_KEY',
    keyRecommended: true,
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
  // FRED — Rates & credit
  { category: 'Rates', name: 'Fed Funds Rate', provider: 'fred', symbol: 'FEDFUNDS', unit: '%' },
  { category: 'Rates', name: 'Effective Fed Funds (daily)', provider: 'fred', symbol: 'DFF', unit: '%' },
  { category: 'Rates', name: 'SOFR', provider: 'fred', symbol: 'SOFR', unit: '%' },
  { category: 'Rates', name: '3M Treasury', provider: 'fred', symbol: 'DGS3MO', unit: '%' },
  { category: 'Rates', name: '2Y Treasury', provider: 'fred', symbol: 'DGS2', unit: '%' },
  { category: 'Rates', name: '5Y Treasury', provider: 'fred', symbol: 'DGS5', unit: '%' },
  { category: 'Rates', name: '10Y Treasury', provider: 'fred', symbol: 'DGS10', unit: '%' },
  { category: 'Rates', name: '30Y Treasury', provider: 'fred', symbol: 'DGS30', unit: '%' },
  { category: 'Rates', name: '10Y–2Y Spread', provider: 'fred', symbol: 'T10Y2Y', unit: '%' },
  { category: 'Rates', name: '30Y Mortgage Rate', provider: 'fred', symbol: 'MORTGAGE30US', unit: '%' },
  { category: 'Rates', name: 'High-Yield OAS', provider: 'fred', symbol: 'BAMLH0A0HYM2', unit: '%' },
  { category: 'Rates', name: 'Financial Conditions (NFCI)', provider: 'fred', symbol: 'NFCI', unit: 'idx' },
  // FRED — Inflation
  { category: 'Inflation', name: 'CPI (all items)', provider: 'fred', symbol: 'CPIAUCSL', unit: 'idx' },
  { category: 'Inflation', name: 'Core CPI', provider: 'fred', symbol: 'CPILFESL', unit: 'idx' },
  { category: 'Inflation', name: 'PCE Price Index', provider: 'fred', symbol: 'PCEPI', unit: 'idx' },
  { category: 'Inflation', name: 'Core PCE', provider: 'fred', symbol: 'PCEPILFE', unit: 'idx' },
  { category: 'Inflation', name: 'PPI (all commodities)', provider: 'fred', symbol: 'PPIACO', unit: 'idx' },
  { category: 'Inflation', name: '10Y Breakeven', provider: 'fred', symbol: 'T10YIE', unit: '%' },
  { category: 'Inflation', name: '5y5y Fwd Inflation', provider: 'fred', symbol: 'T5YIFR', unit: '%' },
  // FRED — Employment
  { category: 'Employment', name: 'Unemployment Rate', provider: 'fred', symbol: 'UNRATE', unit: '%' },
  { category: 'Employment', name: 'Nonfarm Payrolls', provider: 'fred', symbol: 'PAYEMS', unit: 'k' },
  { category: 'Employment', name: 'Manufacturing Payrolls', provider: 'fred', symbol: 'MANEMP', unit: 'k' },
  { category: 'Employment', name: 'JOLTS Job Openings', provider: 'fred', symbol: 'JTSJOL', unit: 'k' },
  { category: 'Employment', name: 'Initial Claims', provider: 'fred', symbol: 'ICSA', unit: '' },
  { category: 'Employment', name: 'Continued Claims', provider: 'fred', symbol: 'CCSA', unit: '' },
  { category: 'Employment', name: 'Labor Force Participation', provider: 'fred', symbol: 'CIVPART', unit: '%' },
  { category: 'Employment', name: 'Avg Hourly Earnings', provider: 'fred', symbol: 'AHETPI', unit: '$' },
  // FRED — GDP & activity
  { category: 'GDP', name: 'Nominal GDP', provider: 'fred', symbol: 'GDP', unit: '$B' },
  { category: 'GDP', name: 'Real GDP', provider: 'fred', symbol: 'GDPC1', unit: '$B' },
  { category: 'GDP', name: 'Real GDP Growth (SAAR)', provider: 'fred', symbol: 'A191RL1Q225SBEA', unit: '%' },
  { category: 'GDP', name: 'Private Investment', provider: 'fred', symbol: 'GPDI', unit: '$B' },
  { category: 'GDP', name: 'Industrial Production', provider: 'fred', symbol: 'INDPRO', unit: 'idx' },
  { category: 'GDP', name: 'Mfg Production', provider: 'fred', symbol: 'IPMAN', unit: 'idx' },
  { category: 'GDP', name: 'Capacity Utilization', provider: 'fred', symbol: 'TCU', unit: '%' },
  { category: 'GDP', name: 'Durable Goods Orders', provider: 'fred', symbol: 'DGORDER', unit: '$M' },
  // FRED — Commodities (energy/metals spot)
  { category: 'Commodities', name: 'WTI Crude', provider: 'fred', symbol: 'DCOILWTICO', unit: '$' },
  { category: 'Commodities', name: 'Brent Crude', provider: 'fred', symbol: 'DCOILBRENTEU', unit: '$' },
  { category: 'Commodities', name: 'Natural Gas (Henry Hub)', provider: 'fred', symbol: 'DHHNGSP', unit: '$' },
  { category: 'Commodities', name: 'Copper (global)', provider: 'fred', symbol: 'PCOPPUSDM', unit: '$' },
  // FRED — Trade
  { category: 'Trade', name: 'Trade Balance', provider: 'fred', symbol: 'BOPGSTB', unit: '$M' },
  { category: 'Trade', name: 'Net Exports', provider: 'fred', symbol: 'NETEXP', unit: '$B' },
  // BLS — Inflation (CPI components)
  { category: 'Inflation', name: 'CPI-U (all items)', provider: 'bls', symbol: 'CUUR0000SA0', unit: 'idx' },
  { category: 'Inflation', name: 'Core CPI', provider: 'bls', symbol: 'CUUR0000SA0L1E', unit: 'idx' },
  { category: 'Inflation', name: 'CPI Food', provider: 'bls', symbol: 'CUUR0000SAF1', unit: 'idx' },
  { category: 'Inflation', name: 'CPI Energy', provider: 'bls', symbol: 'CUUR0000SA0E', unit: 'idx' },
  { category: 'Inflation', name: 'CPI Shelter', provider: 'bls', symbol: 'CUUR0000SAH1', unit: 'idx' },
  // BLS — Employment
  { category: 'Employment', name: 'Unemployment Rate', provider: 'bls', symbol: 'LNS14000000', unit: '%' },
  { category: 'Employment', name: 'Labor Force Participation', provider: 'bls', symbol: 'LNS11300000', unit: '%' },
  { category: 'Employment', name: 'Total Nonfarm', provider: 'bls', symbol: 'CES0000000001', unit: 'k' },
  { category: 'Employment', name: 'Manufacturing Payrolls', provider: 'bls', symbol: 'CES3000000001', unit: 'k' },
  { category: 'Employment', name: 'Avg Hourly Earnings', provider: 'bls', symbol: 'CES0500000003', unit: '$' },
  { category: 'Employment', name: 'Avg Weekly Hours', provider: 'bls', symbol: 'CES0500000002', unit: 'h' },
  // BEA — GDP/Trade (NIPA tables)
  { category: 'GDP', name: 'Real GDP % Change (T10101)', provider: 'bea', symbol: 'T10101', unit: '%' },
  { category: 'GDP', name: 'GDP Levels (T10105)', provider: 'bea', symbol: 'T10105', unit: '$B' },
  { category: 'GDP', name: 'Real GDP Chained (T10106)', provider: 'bea', symbol: 'T10106', unit: 'idx' },
  { category: 'GDP', name: 'Personal Income & Outlays (T20100)', provider: 'bea', symbol: 'T20100', unit: '$B' }
]
