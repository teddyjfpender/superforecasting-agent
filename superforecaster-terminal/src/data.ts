export type DataSourceKind = "live" | "stale" | "mock" | "unavailable";

export type DataSourceState = {
  kind: DataSourceKind;
  label: string;
  receivedAt?: string;
};

export function dataSourceDisplayLabel(source: DataSourceState | undefined): string {
  if (!source) return "LOCAL";
  switch (source.kind) {
    case "live":
      return source.label ? `LIVE · ${source.label}` : "LIVE";
    case "stale":
      return "STALE";
    case "mock":
      return "MOCK";
    case "unavailable":
      return "N/A";
  }
}

export type Quote = {
  ticker: string;
  name: string;
  last: number;
  chg: number;
  pct: number;
  vol: string;
  bid: number;
  ask: number;
  source?: DataSourceState;
};

export const INDICES: Quote[] = [
  { ticker: "SPX",  name: "S&P 500",         last: 5_842.17,  chg: +12.84, pct: +0.22, vol: "3.41B", bid: 5841.9,  ask: 5842.4  },
  { ticker: "INDU", name: "DOW JONES",       last: 42_915.30, chg: -84.50, pct: -0.20, vol: "412M",  bid: 42914,   ask: 42916   },
  { ticker: "CCMP", name: "NASDAQ COMP",     last: 18_771.04, chg: +98.22, pct: +0.53, vol: "5.10B", bid: 18770,   ask: 18772   },
  { ticker: "RTY",  name: "RUSSELL 2000",    last: 2_278.45,  chg: -3.10,  pct: -0.14, vol: "1.02B", bid: 2278.3,  ask: 2278.6  },
  { ticker: "NYA",  name: "NYSE COMP",       last: 19_842.10, chg: +24.10, pct: +0.12, vol: "—",     bid: 19841,   ask: 19843   },
  { ticker: "SOX",  name: "PHLX SEMI",       last: 5_214.32,  chg: +62.41, pct: +1.21, vol: "—",     bid: 5214.1,  ask: 5214.5  },
  { ticker: "VIX",  name: "VOLATILITY",      last: 14.82,     chg: -0.41,  pct: -2.69, vol: "—",     bid: 14.81,   ask: 14.83   },
  { ticker: "DXY",  name: "US DOLLAR IDX",   last: 104.18,    chg: +0.21,  pct: +0.20, vol: "—",     bid: 104.17,  ask: 104.19  },
  { ticker: "MOVE", name: "ICE BOFA MOVE",   last: 92.14,     chg: -1.84,  pct: -1.96, vol: "—",     bid: 92.10,   ask: 92.18   },
];

export const WORLD_INDICES: Quote[] = [
  ...INDICES.slice(0, 6),
  { ticker: "SX5E", name: "EURO STOXX 50",   last: 5_184.30, chg: +12.40, pct: +0.24, vol: "—", bid: 5184, ask: 5185 },
  { ticker: "DAX",  name: "GERMAN DAX",      last: 18_942.10, chg: -42.10, pct: -0.22, vol: "—", bid: 18941, ask: 18943 },
  { ticker: "UKX",  name: "FTSE 100",        last: 8_412.30, chg: +18.20, pct: +0.22, vol: "—", bid: 8412, ask: 8413 },
  { ticker: "CAC",  name: "CAC 40",          last: 7_812.40, chg: +24.10, pct: +0.31, vol: "—", bid: 7812, ask: 7813 },
  { ticker: "NKY",  name: "NIKKEI 225",      last: 38_842.10, chg: +124.80, pct: +0.32, vol: "—", bid: 38841, ask: 38843 },
  { ticker: "HSI",  name: "HANG SENG",       last: 19_412.30, chg: -84.20, pct: -0.43, vol: "—", bid: 19412, ask: 19413 },
  { ticker: "SHCOMP", name: "SHANGHAI COMP", last: 3_184.20, chg: +12.40, pct: +0.39, vol: "—", bid: 3184, ask: 3185 },
  { ticker: "KOSPI", name: "KOSPI",          last: 2_812.40, chg: +14.20, pct: +0.51, vol: "—", bid: 2812, ask: 2813 },
  { ticker: "SENSEX", name: "BSE SENSEX",    last: 78_412.30, chg: +184.20, pct: +0.24, vol: "—", bid: 78410, ask: 78414 },
];

export const FX: Quote[] = [
  { ticker: "EURUSD", name: "EUR / USD", last: 1.0842, chg: -0.0011, pct: -0.10, vol: "—", bid: 1.0841, ask: 1.0843 },
  { ticker: "USDJPY", name: "USD / JPY", last: 155.92, chg: +0.34,   pct: +0.22, vol: "—", bid: 155.91, ask: 155.93 },
  { ticker: "GBPUSD", name: "GBP / USD", last: 1.2671, chg: +0.0009, pct: +0.07, vol: "—", bid: 1.2670, ask: 1.2672 },
  { ticker: "USDCHF", name: "USD / CHF", last: 0.9012, chg: -0.0021, pct: -0.23, vol: "—", bid: 0.9011, ask: 0.9013 },
  { ticker: "AUDUSD", name: "AUD / USD", last: 0.6614, chg: +0.0014, pct: +0.21, vol: "—", bid: 0.6613, ask: 0.6615 },
  { ticker: "USDCAD", name: "USD / CAD", last: 1.3812, chg: +0.0024, pct: +0.17, vol: "—", bid: 1.3811, ask: 1.3813 },
  { ticker: "NZDUSD", name: "NZD / USD", last: 0.5984, chg: -0.0008, pct: -0.13, vol: "—", bid: 0.5983, ask: 0.5985 },
  { ticker: "USDCNH", name: "USD / CNH", last: 7.2384, chg: +0.0021, pct: +0.03, vol: "—", bid: 7.2383, ask: 7.2385 },
  { ticker: "USDMXN", name: "USD / MXN", last: 17.84,  chg: -0.04,   pct: -0.22, vol: "—", bid: 17.83,  ask: 17.85  },
];

export const EM_FX: Quote[] = [
  { ticker: "USDBRL", name: "USD / BRL", last: 5.184,  chg: +0.014, pct: +0.27, vol: "—", bid: 5.183, ask: 5.185 },
  { ticker: "USDTRY", name: "USD / TRY", last: 34.84,  chg: +0.21,  pct: +0.61, vol: "—", bid: 34.83, ask: 34.85 },
  { ticker: "USDZAR", name: "USD / ZAR", last: 18.42,  chg: -0.08,  pct: -0.43, vol: "—", bid: 18.41, ask: 18.43 },
  { ticker: "USDINR", name: "USD / INR", last: 84.42,  chg: +0.08,  pct: +0.09, vol: "—", bid: 84.41, ask: 84.43 },
  { ticker: "USDIDR", name: "USD / IDR", last: 15842,  chg: +24,    pct: +0.15, vol: "—", bid: 15841, ask: 15843 },
  { ticker: "USDKRW", name: "USD / KRW", last: 1384.4, chg: -2.1,   pct: -0.15, vol: "—", bid: 1384.3, ask: 1384.5 },
  { ticker: "USDPLN", name: "USD / PLN", last: 4.014,  chg: -0.012, pct: -0.30, vol: "—", bid: 4.013, ask: 4.015 },
  { ticker: "USDPHP", name: "USD / PHP", last: 58.42,  chg: +0.08,  pct: +0.14, vol: "—", bid: 58.41, ask: 58.43 },
];

/* Cross-rate matrix — rows = base ccy, cols = quote ccy. */
export const CROSS_CCYS = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"];
export const CROSS_FX: number[][] = [
  // USD     EUR      GBP      JPY      CHF      CAD      AUD
  [1.0,     0.9224,  0.7892,  155.92,  0.9012,  1.3812,  1.5118], // USD
  [1.0842,  1.0,     0.8556,  169.05,  0.9772,  1.4977,  1.6394], // EUR
  [1.2671,  1.1684,  1.0,     197.59,  1.1417,  1.7501,  1.9161], // GBP
  [0.00641, 0.00592, 0.00506, 1.0,     0.00578, 0.00886, 0.00970], // JPY
  [1.1097,  1.0233,  0.8758,  173.05,  1.0,     1.5326,  1.6776], // CHF
  [0.7239,  0.6678,  0.5714,  112.88,  0.6525,  1.0,     1.0945], // CAD
  [0.6614,  0.6101,  0.5219,  103.16,  0.5961,  0.9136,  1.0],    // AUD
];

export const RATES: Quote[] = [
  { ticker: "US02Y", name: "US 2Y YIELD",  last: 4.184, chg: -0.024, pct: -0.57, vol: "—", bid: 4.183, ask: 4.185 },
  { ticker: "US05Y", name: "US 5Y YIELD",  last: 4.210, chg: -0.018, pct: -0.43, vol: "—", bid: 4.209, ask: 4.211 },
  { ticker: "US10Y", name: "US 10Y YIELD", last: 4.345, chg: -0.011, pct: -0.25, vol: "—", bid: 4.344, ask: 4.346 },
  { ticker: "US30Y", name: "US 30Y YIELD", last: 4.612, chg: +0.004, pct: +0.09, vol: "—", bid: 4.611, ask: 4.613 },
  { ticker: "DE10Y", name: "BUND 10Y",     last: 2.358, chg: -0.008, pct: -0.34, vol: "—", bid: 2.357, ask: 2.359 },
  { ticker: "GB10Y", name: "GILT 10Y",     last: 4.184, chg: +0.012, pct: +0.29, vol: "—", bid: 4.183, ask: 4.185 },
  { ticker: "IT10Y", name: "BTP 10Y",      last: 3.642, chg: -0.018, pct: -0.49, vol: "—", bid: 3.641, ask: 3.643 },
  { ticker: "JP10Y", name: "JGB 10Y",      last: 1.014, chg: +0.012, pct: +1.20, vol: "—", bid: 1.013, ask: 1.015 },
  { ticker: "CN10Y", name: "CGB 10Y",      last: 1.842, chg: -0.004, pct: -0.22, vol: "—", bid: 1.841, ask: 1.843 },
];

export type YieldCurvePoint = {
  tenor: string;
  yld: number | null;
  source?: DataSourceState;
};

export const US_CURVE: YieldCurvePoint[] = [
  { tenor: "1M",  yld: 4.42 },
  { tenor: "3M",  yld: 4.38 },
  { tenor: "6M",  yld: 4.31 },
  { tenor: "1Y",  yld: 4.24 },
  { tenor: "2Y",  yld: 4.18 },
  { tenor: "3Y",  yld: 4.19 },
  { tenor: "5Y",  yld: 4.21 },
  { tenor: "7Y",  yld: 4.28 },
  { tenor: "10Y", yld: 4.34 },
  { tenor: "20Y", yld: 4.54 },
  { tenor: "30Y", yld: 4.61 },
];

export type CbRate = {
  ccy: string;
  bank: string;
  rate: number | null;
  lastMove: string;
  next: string;
  bias: "HIKE" | "HOLD" | "CUT";
  source?: DataSourceState;
};
export const CB_RATES: CbRate[] = [
  { ccy: "USD", bank: "FED · FOMC",   rate: 4.50, lastMove: "2026-03-19", next: "2026-06-18", bias: "HOLD" },
  { ccy: "EUR", bank: "ECB",          rate: 2.75, lastMove: "2026-04-10", next: "2026-06-05", bias: "CUT"  },
  { ccy: "GBP", bank: "BOE · MPC",    rate: 4.25, lastMove: "2026-03-20", next: "2026-06-19", bias: "HOLD" },
  { ccy: "JPY", bank: "BOJ",          rate: 0.50, lastMove: "2026-01-23", next: "2026-06-13", bias: "HIKE" },
  { ccy: "CHF", bank: "SNB",          rate: 0.25, lastMove: "2026-03-21", next: "2026-06-19", bias: "HOLD" },
  { ccy: "CAD", bank: "BOC",          rate: 2.75, lastMove: "2026-04-16", next: "2026-06-04", bias: "CUT"  },
  { ccy: "AUD", bank: "RBA",          rate: 4.10, lastMove: "2026-04-01", next: "2026-06-03", bias: "HOLD" },
  { ccy: "CNY", bank: "PBOC · LPR1Y", rate: 3.10, lastMove: "2026-04-21", next: "2026-05-20", bias: "CUT"  },
];

export const SECTORS: Quote[] = [
  { ticker: "XLK",  name: "TECHNOLOGY",      last: 232.41, chg: +1.84, pct: +0.80, vol: "8.4M",  bid: 232.40, ask: 232.42 },
  { ticker: "XLF",  name: "FINANCIALS",      last:  50.18, chg: -0.12, pct: -0.24, vol: "21.2M", bid:  50.17, ask:  50.19 },
  { ticker: "XLE",  name: "ENERGY",          last:  92.41, chg: +0.74, pct: +0.81, vol: "10.4M", bid:  92.40, ask:  92.42 },
  { ticker: "XLV",  name: "HEALTH CARE",     last: 148.62, chg: -0.41, pct: -0.28, vol: "6.1M",  bid: 148.61, ask: 148.63 },
  { ticker: "XLY",  name: "CONS. DISCRET.",  last: 218.41, chg: +1.21, pct: +0.56, vol: "4.2M",  bid: 218.40, ask: 218.42 },
  { ticker: "XLP",  name: "CONS. STAPLES",   last:  82.14, chg: +0.18, pct: +0.22, vol: "5.4M",  bid:  82.13, ask:  82.15 },
  { ticker: "XLI",  name: "INDUSTRIALS",     last: 138.42, chg: -0.21, pct: -0.15, vol: "8.1M",  bid: 138.41, ask: 138.43 },
  { ticker: "XLU",  name: "UTILITIES",       last:  78.12, chg: -0.34, pct: -0.43, vol: "12.8M", bid:  78.11, ask:  78.13 },
  { ticker: "XLB",  name: "MATERIALS",       last:  91.84, chg: +0.41, pct: +0.45, vol: "3.4M",  bid:  91.83, ask:  91.85 },
  { ticker: "XLRE", name: "REAL ESTATE",     last:  42.81, chg: -0.12, pct: -0.28, vol: "5.2M",  bid:  42.80, ask:  42.82 },
  { ticker: "XLC",  name: "COMMUNICATIONS",  last:  98.42, chg: +0.84, pct: +0.86, vol: "4.8M",  bid:  98.41, ask:  98.43 },
];

export const COMMODITIES: Quote[] = [
  { ticker: "CL1", name: "WTI CRUDE",      last:  76.84, chg: +0.62, pct: +0.81, vol: "412k", bid: 76.83,  ask: 76.85  },
  { ticker: "CO1", name: "BRENT",          last:  81.12, chg: +0.74, pct: +0.92, vol: "284k", bid: 81.11,  ask: 81.13  },
  { ticker: "XAU", name: "GOLD SPOT",      last: 2_614.20, chg: -8.10, pct: -0.31, vol: "—",  bid: 2614.0, ask: 2614.4 },
  { ticker: "XAG", name: "SILVER",         last:  31.04, chg: -0.18, pct: -0.58, vol: "—",   bid: 31.03,  ask: 31.05  },
  { ticker: "NG1", name: "NAT GAS",        last:   3.412, chg: +0.084, pct: +2.52, vol: "—", bid: 3.411,  ask: 3.413  },
  { ticker: "HG1", name: "COPPER",         last:   4.182, chg: -0.014, pct: -0.33, vol: "—", bid: 4.181,  ask: 4.183  },
  { ticker: "LA1", name: "ALUMINUM",       last: 2_412.0, chg: +12.0,  pct: +0.50, vol: "—",  bid: 2411,   ask: 2413   },
  { ticker: "C 1", name: "CORN",           last: 442.50,  chg: -1.25,  pct: -0.28, vol: "—",  bid: 442.4,  ask: 442.6  },
  { ticker: "W 1", name: "WHEAT",          last: 562.25,  chg: +3.50,  pct: +0.63, vol: "—",  bid: 562.0,  ask: 562.5  },
];

export const ENERGY: Quote[] = [
  { ticker: "CL1",  name: "WTI CRUDE M1",   last:  76.84, chg: +0.62, pct: +0.81, vol: "412k", bid: 76.83, ask: 76.85 },
  { ticker: "CL2",  name: "WTI CRUDE M2",   last:  76.42, chg: +0.58, pct: +0.76, vol: "84k",  bid: 76.41, ask: 76.43 },
  { ticker: "CO1",  name: "BRENT M1",       last:  81.12, chg: +0.74, pct: +0.92, vol: "284k", bid: 81.11, ask: 81.13 },
  { ticker: "CO2",  name: "BRENT M2",       last:  80.84, chg: +0.71, pct: +0.89, vol: "62k",  bid: 80.83, ask: 80.85 },
  { ticker: "NG1",  name: "NAT GAS M1",     last:   3.412, chg: +0.084, pct: +2.52, vol: "—",  bid: 3.411, ask: 3.413 },
  { ticker: "HO1",  name: "HEATING OIL",    last:   2.412, chg: +0.014, pct: +0.58, vol: "—",  bid: 2.411, ask: 2.413 },
  { ticker: "RB1",  name: "RBOB GASOLINE",  last:   2.182, chg: +0.024, pct: +1.11, vol: "—",  bid: 2.181, ask: 2.183 },
];

export const METALS: Quote[] = [
  { ticker: "XAU", name: "GOLD SPOT",    last: 2614.20, chg: -8.10, pct: -0.31, vol: "—", bid: 2614.0, ask: 2614.4 },
  { ticker: "XAG", name: "SILVER",       last:   31.04, chg: -0.18, pct: -0.58, vol: "—", bid: 31.03, ask: 31.05 },
  { ticker: "XPT", name: "PLATINUM",     last: 1014.20, chg: +4.20, pct: +0.42, vol: "—", bid: 1014, ask: 1014.4 },
  { ticker: "XPD", name: "PALLADIUM",    last:  942.40, chg: -8.20, pct: -0.86, vol: "—", bid: 942.2, ask: 942.6 },
  { ticker: "HG1", name: "COPPER",       last:    4.182, chg: -0.014, pct: -0.33, vol: "—", bid: 4.181, ask: 4.183 },
  { ticker: "LA1", name: "ALUMINUM",     last: 2412.0,  chg: +12.0, pct: +0.50, vol: "—", bid: 2411, ask: 2413 },
  { ticker: "NI1", name: "NICKEL",       last: 16842,   chg: +124,  pct: +0.74, vol: "—", bid: 16840, ask: 16844 },
  { ticker: "SI1", name: "TIN",          last: 32842,   chg: -84,   pct: -0.25, vol: "—", bid: 32840, ask: 32844 },
];

export const AGS: Quote[] = [
  { ticker: "C 1",  name: "CORN",          last: 442.50, chg: -1.25, pct: -0.28, vol: "—", bid: 442.4, ask: 442.6 },
  { ticker: "W 1",  name: "WHEAT",         last: 562.25, chg: +3.50, pct: +0.63, vol: "—", bid: 562.0, ask: 562.5 },
  { ticker: "S 1",  name: "SOYBEANS",      last: 1042.50, chg: +4.25, pct: +0.41, vol: "—", bid: 1042, ask: 1043 },
  { ticker: "SB1",  name: "SUGAR #11",     last:  18.42, chg: -0.18, pct: -0.97, vol: "—", bid: 18.41, ask: 18.43 },
  { ticker: "KC1",  name: "COFFEE 'C'",    last: 242.80, chg: +1.40, pct: +0.58, vol: "—", bid: 242.7, ask: 242.9 },
  { ticker: "CC1",  name: "COCOA",         last: 9842,   chg: +124,  pct: +1.28, vol: "—", bid: 9841, ask: 9843 },
  { ticker: "CT1",  name: "COTTON",        last:  72.40, chg: -0.21, pct: -0.29, vol: "—", bid: 72.39, ask: 72.41 },
];

export const CRYPTO: Quote[] = [
  { ticker: "BTC",  name: "BITCOIN",      last: 94_842.12, chg: +1284.0, pct: +1.37, vol: "32.4B", bid: 94840,   ask: 94844   },
  { ticker: "ETH",  name: "ETHEREUM",     last:  3_412.84, chg:  +84.10, pct: +2.53, vol: "18.1B", bid: 3412.7,  ask: 3413.0  },
  { ticker: "SOL",  name: "SOLANA",       last:    214.62, chg:   +8.41, pct: +4.08, vol:  "4.2B", bid:  214.6,  ask:  214.64 },
  { ticker: "XRP",  name: "RIPPLE",       last:      2.412, chg:  -0.04, pct: -1.63, vol:  "2.8B", bid:    2.411, ask:   2.413 },
  { ticker: "BNB",  name: "BNB",          last:    642.40, chg:   +4.84, pct: +0.76, vol:  "1.2B", bid:  642.3,  ask:  642.5  },
  { ticker: "ADA",  name: "CARDANO",      last:      0.984, chg:  +0.012, pct: +1.23, vol:  "684M", bid:    0.983, ask:   0.985 },
  { ticker: "DOGE", name: "DOGECOIN",     last:      0.412, chg:  -0.008, pct: -1.90, vol:  "1.8B", bid:    0.411, ask:   0.413 },
  { ticker: "AVAX", name: "AVALANCHE",    last:     42.41,  chg:  +0.84,  pct: +2.02, vol:  "412M", bid:   42.40,  ask:  42.42  },
  { ticker: "LINK", name: "CHAINLINK",    last:     22.18,  chg:  -0.14,  pct: -0.63, vol:  "284M", bid:   22.17,  ask:  22.19  },
];

export const WATCHLIST: Quote[] = [
  { ticker: "NVDA",  name: "NVIDIA CORP",        last: 142.62, chg: +2.84,  pct: +2.03, vol: "184.2M", bid: 142.61, ask: 142.63 },
  { ticker: "AAPL",  name: "APPLE INC",          last: 224.18, chg: +0.41,  pct: +0.18, vol:  "52.1M", bid: 224.17, ask: 224.19 },
  { ticker: "MSFT",  name: "MICROSOFT CORP",     last: 432.04, chg: -1.21,  pct: -0.28, vol:  "21.8M", bid: 432.02, ask: 432.06 },
  { ticker: "GOOGL", name: "ALPHABET INC-CL A",  last: 184.21, chg: +1.04,  pct: +0.57, vol:  "18.9M", bid: 184.20, ask: 184.22 },
  { ticker: "AMZN",  name: "AMAZON.COM INC",     last: 211.42, chg: +3.11,  pct: +1.49, vol:  "44.7M", bid: 211.41, ask: 211.43 },
  { ticker: "META",  name: "META PLATFORMS-A",   last: 612.84, chg: -2.04,  pct: -0.33, vol:  "12.4M", bid: 612.82, ask: 612.86 },
  { ticker: "TSLA",  name: "TESLA INC",          last: 348.92, chg: +12.41, pct: +3.69, vol: "104.2M", bid: 348.91, ask: 348.93 },
  { ticker: "AMD",   name: "ADVANCED MICRO",     last: 128.14, chg: +1.84,  pct: +1.46, vol:  "52.6M", bid: 128.13, ask: 128.15 },
  { ticker: "AVGO",  name: "BROADCOM INC",       last: 184.62, chg: +0.92,  pct: +0.50, vol:  "21.4M", bid: 184.61, ask: 184.63 },
  { ticker: "JPM",   name: "JPMORGAN CHASE",     last: 248.41, chg: -0.84,  pct: -0.34, vol:  "10.1M", bid: 248.40, ask: 248.42 },
  { ticker: "BRK/B", name: "BERKSHIRE HATH-B",   last: 472.18, chg: +1.21,  pct: +0.26, vol:   "3.1M", bid: 472.16, ask: 472.20 },
  { ticker: "BAC",   name: "BANK OF AMERICA",    last:  46.84, chg: -0.18,  pct: -0.38, vol:  "32.4M", bid:  46.83, ask:  46.85 },
  { ticker: "WMT",   name: "WALMART INC",        last:  91.04, chg: +0.41,  pct: +0.45, vol:  "14.7M", bid:  91.03, ask:  91.05 },
  { ticker: "XOM",   name: "EXXON MOBIL",        last: 117.42, chg: +0.94,  pct: +0.81, vol:  "16.1M", bid: 117.41, ask: 117.43 },
  { ticker: "UNH",   name: "UNITEDHEALTH",       last: 562.84, chg: -2.14,  pct: -0.38, vol:   "2.8M", bid: 562.82, ask: 562.86 },
  { ticker: "V",     name: "VISA INC-A",         last: 312.14, chg: +0.84,  pct: +0.27, vol:   "6.4M", bid: 312.13, ask: 312.15 },
];

export type NewsItem = {
  id: string;
  time: string;
  src: string;
  headline: string;
  tone: "neutral" | "pos" | "neg" | "alert";
  cat?: "TOP" | "ECON" | "FX" | "EQ" | "FI" | "CMDTY" | "CRED";
  body: string[];
  symbols?: string[];
  byline?: string;
  dateline?: string;
  url?: string;
};

export const NEWS: NewsItem[] = [
  {
    id: "n-001",
    time: "23:14",
    src: "BN",
    cat: "ECON",
    tone: "neutral",
    headline: "FED MINUTES SHOW BROAD SUPPORT FOR JUNE PAUSE; OFFICIALS WARY OF RE-ACCELERATION",
    byline: "M. KOLOMBOS, J. CLARKE",
    dateline: "WASHINGTON",
    symbols: ["SPX", "US10Y", "DXY"],
    body: [
      "Most Federal Reserve officials saw the case for holding rates steady at the upcoming June meeting, citing persistent shelter inflation and an uneven labor market, minutes from the May FOMC meeting showed Wednesday.",
      "\"Participants generally agreed that the disinflation process remains gradual and uneven,\" the record of the meeting said. Several participants noted upside risks from goods prices and a still-tight labor market.",
      "The minutes were broadly in line with market expectations. Fed-funds futures continue to price ~70% odds of no change in June and the first cut by September. Two-year yields ticked 2 bp lower on the release; the DXY softened 0.1 to 104.16.",
      "Officials also discussed balance-sheet runoff, with most viewing the current pace as appropriate, though several flagged the possibility of slowing the pace later this year to reduce the risk of money-market stress.",
    ],
  },
  {
    id: "n-002",
    time: "23:11",
    src: "RTRS",
    cat: "EQ",
    tone: "pos",
    headline: "NVIDIA EXTENDS GAINS AFTER UPGRADE FROM MORGAN STANLEY; PT RAISED TO 175",
    byline: "K. NAIDU",
    dateline: "NEW YORK",
    symbols: ["NVDA", "AMD", "AVGO"],
    body: [
      "Nvidia Corp. extended its rally Wednesday after Morgan Stanley raised its price target to $175 from $160 and reiterated its Overweight rating, citing accelerating Blackwell-class GPU deliveries and \"durable AI-capex visibility\" through 2027.",
      "Analyst Joseph Moore wrote that fiscal-year channel checks suggest hyperscaler order books for the new chips are now booked into Q1 2027, with average selling prices running 8-10% above sell-side models. He raised CY26 EPS to $4.42 from $4.10.",
      "Shares of NVDA were last up 2.0% at 142.62, extending a year-to-date gain to ~14%. Peers AMD (+1.5%) and Broadcom (+0.5%) also traded higher.",
    ],
  },
  {
    id: "n-003",
    time: "23:08",
    src: "BN",
    cat: "FX",
    tone: "neg",
    headline: "JPY WEAKENS PAST 155.90 VS USD; MOF DECLINES TO COMMENT",
    byline: "A. SAITO",
    dateline: "TOKYO",
    symbols: ["USDJPY", "DXY", "JP10Y"],
    body: [
      "The Japanese yen weakened past 155.90 per dollar in New York hours Wednesday, the weakest since the late-April intervention, as US Treasury yields ground higher into the Fed minutes release.",
      "Asked about the move, a Ministry of Finance spokesperson declined to comment beyond reiterating that authorities will respond \"appropriately\" to excessive volatility. Top currency diplomat Masato Kanda met with reporters earlier in the Tokyo session but offered no fresh guidance.",
      "Options-implied 1-week realized vol on USDJPY has climbed to 9.4 from 7.8 a week ago. Risk reversals have shifted in favor of yen calls at the 25-delta. Traders are watching 158.00 as the next intervention-risk level.",
    ],
  },
  {
    id: "n-004",
    time: "23:05",
    src: "DJ",
    cat: "CMDTY",
    tone: "pos",
    headline: "OPEC+ AGREES TO EXTEND VOLUNTARY OUTPUT CUTS THROUGH Q3 — DELEGATES",
    byline: "S. SAID, B. FAUCON",
    dateline: "VIENNA",
    symbols: ["CL1", "CO1", "XOM", "CVX"],
    body: [
      "OPEC+ delegates reached an agreement Wednesday to extend the group's 2.2 million barrel/day voluntary production cuts through the third quarter of 2026, two people familiar with the matter said, providing further support to crude prices in the near term.",
      "Saudi Arabia and Russia, the two largest contributors to the cuts, had pushed for a longer extension into Q4, but several smaller members resisted, citing budget pressures. A communiqué is expected after the formal ministerial meeting on Sunday.",
      "WTI front-month was last 0.8% higher at $76.84/bbl; Brent at $81.12/bbl. The contango in the prompt month has tightened to $0.18, the narrowest in three weeks.",
    ],
  },
  {
    id: "n-005",
    time: "23:02",
    src: "BN",
    cat: "FI",
    tone: "alert",
    headline: "*BREAKING* TREASURY SELLS $42B 10Y AT 4.34%, BID-TO-COVER 2.54",
    byline: "R. HARRIS",
    dateline: "WASHINGTON",
    symbols: ["US10Y", "US30Y", "DXY"],
    body: [
      "The U.S. Treasury sold $42 billion of 10-year notes at a high yield of 4.34%, slightly through the 4.345% pre-auction yield, with a bid-to-cover ratio of 2.54 — the strongest demand in three months.",
      "Indirect bidders, a proxy for foreign demand, took 71.2% of the issue, up from 65.4% at the prior auction. Direct bidders took 18.8%; primary dealers were left with 10.0%, near the recent lows.",
      "The 10-year yield fell 3 bp on the print to 4.32%. The auction is one of the strongest reception signals seen for a long-end US Treasury in 2026 and provides counter-evidence to recent narratives about waning foreign appetite.",
    ],
  },
  {
    id: "n-006",
    time: "22:58",
    src: "FT",
    cat: "ECON",
    tone: "neutral",
    headline: "ECB'S LAGARDE: WAGE GROWTH MODERATING IN LINE WITH PROJECTIONS",
    byline: "M. ARNOLD",
    dateline: "FRANKFURT",
    symbols: ["EURUSD", "DE10Y", "DAX"],
    body: [
      "European Central Bank President Christine Lagarde said Wednesday that euro-area wage growth is moderating in line with the bank's projections, supporting the case for further policy easing in the coming months.",
      "Speaking at a conference in Frankfurt, Lagarde emphasized that the disinflationary process is \"well advanced\" and that incoming data continue to support the outlook for inflation to return sustainably to the 2% target by mid-2027.",
      "Markets are now pricing two more 25 bp cuts from the ECB by year-end, with the first fully priced for the June 5 meeting. EUR/USD held steady at 1.0842 on the comments.",
    ],
  },
  {
    id: "n-007",
    time: "22:51",
    src: "BN",
    cat: "EQ",
    tone: "pos",
    headline: "TESLA Q2 DELIVERIES TRACKING ABOVE STREET — INTERNAL MEMO SEEN BY BBG",
    byline: "D. WELCH",
    dateline: "AUSTIN",
    symbols: ["TSLA"],
    body: [
      "Tesla Inc. is on track to deliver more vehicles in the second quarter than Wall Street is currently modeling, according to an internal memo to factory managers reviewed by Bloomberg.",
      "The memo, dated May 12, instructs Shanghai and Austin Gigafactory leaders to \"hold all available inventory for outbound logistics through end-of-quarter,\" suggesting management is targeting an upside surprise. Consensus is currently ~482,000 deliveries; the memo references an internal stretch target of 495,000.",
      "Tesla shares jumped 3.7% on the report to $348.92. Short interest, which had been near multi-month highs, may face cover pressure into the July 2 delivery release.",
    ],
  },
  {
    id: "n-008",
    time: "22:47",
    src: "RTRS",
    cat: "ECON",
    tone: "pos",
    headline: "CHINA APRIL INDUSTRIAL PROFITS +4.2% YOY VS +3.5% PRIOR",
    byline: "K. YAO",
    dateline: "BEIJING",
    symbols: ["SHCOMP", "USDCNH", "HG1"],
    body: [
      "China's industrial profits rose 4.2% year-on-year in April, accelerating from 3.5% in March, the National Bureau of Statistics reported, suggesting recent stimulus measures are beginning to filter through to corporate margins.",
      "The state-owned segment led gains, with profits up 6.1%. Private-sector profits rose 2.8%. Among industries, electronics manufacturing (+18%) and non-ferrous metals (+22%) led, while real-estate-related sectors continued to decline.",
      "Copper, a barometer for industrial demand, ticked 0.2% lower despite the print as broader USD strength weighed; CNH steadied at 7.2384.",
    ],
  },
  {
    id: "n-009",
    time: "22:41",
    src: "BN",
    cat: "CMDTY",
    tone: "neg",
    headline: "OIL TANKER RE-ROUTING IN RED SEA CONTINUES; FREIGHT RATES UP 8% W/W",
    byline: "S. ELSON",
    dateline: "LONDON",
    symbols: ["CL1", "CO1"],
    body: [
      "Major shipping lines continued to divert oil tankers away from the Red Sea this week following renewed Houthi missile activity targeting commercial vessels, pushing benchmark freight rates 8% higher week-on-week.",
      "Worldscale rates on the TD3C route (Middle East Gulf to China) climbed to 78 from 72 a week earlier; the Suezmax TD20 (West Africa to UK Continent) rose to 122 from 113. Insurance war-risk premiums for Red Sea transit have also widened by 0.05% of hull value.",
      "Brent has so far held below $82 despite the disruptions, with the market focused on the OPEC+ extension talks. Refined-product crack spreads have widened sharply.",
    ],
  },
  {
    id: "n-010",
    time: "22:36",
    src: "DJ",
    cat: "EQ",
    tone: "pos",
    headline: "APPLE NEARS DEAL TO INTEGRATE ANTHROPIC MODELS INTO iOS 19 — SOURCES",
    byline: "A. FITZGERALD",
    dateline: "CUPERTINO",
    symbols: ["AAPL", "MSFT", "GOOGL"],
    body: [
      "Apple Inc. is in advanced talks to integrate Anthropic's Claude models as a foundational option in iOS 19, alongside the existing OpenAI partnership, people familiar with the matter said. A deal could be announced at the company's developer conference in June.",
      "Under the terms being discussed, users would be able to select Claude as their default model for Siri's advanced reasoning features. Apple is not paying a model-license fee; instead, Anthropic would gain distribution to iPhone's installed base in exchange.",
      "Apple shares were little changed at $224.18. The partnership signals the company's continued strategy of offering multiple third-party models rather than relying on a single provider.",
    ],
  },
  {
    id: "n-011",
    time: "22:30",
    src: "BN",
    cat: "ECON",
    tone: "neutral",
    headline: "BOJ'S UEDA: WILL NOT HESITATE TO ADJUST POLICY IF NEEDED",
    byline: "T. URABE",
    dateline: "TOKYO",
    symbols: ["USDJPY", "JP10Y", "NKY"],
    body: [
      "Bank of Japan Governor Kazuo Ueda said the central bank stands ready to adjust monetary policy if needed to ensure inflation stabilizes sustainably at the 2% target, in remarks that traders read as paving the way for a possible July hike.",
      "\"If our forecast for prices and the economy materializes, we will continue to gradually adjust policy,\" Ueda told reporters in Tokyo. He declined to comment on the yen's recent depreciation past 155.\"",
      "Overnight-index swaps now price ~60% odds of a 15 bp hike at the July 31 BOJ meeting, up from ~40% a week ago. JGB 10-year yields rose 1.5 bp to 1.014%.",
    ],
  },
  {
    id: "n-012",
    time: "22:21",
    src: "RTRS",
    cat: "EQ",
    tone: "neutral",
    headline: "META EXPANDS THREADS API ACCESS TO ENTERPRISE PARTNERS",
    byline: "S. RODRIGUEZ",
    dateline: "MENLO PARK",
    symbols: ["META"],
    body: [
      "Meta Platforms Inc. is opening Threads API access to enterprise partners, the company said in a blog post Wednesday, marking a significant expansion of the developer ecosystem around its X competitor.",
      "Enterprise partners including Sprinklr, Hootsuite and Sprout Social will now be able to schedule posts, retrieve insights and manage replies through the API. Pricing was not disclosed; access is invite-only for the initial cohort.",
      "Threads passed 200 million monthly active users in April, Meta said. Shares of META were little changed at $612.84.",
    ],
  },
  {
    id: "n-013",
    time: "22:14",
    src: "BN",
    cat: "EQ",
    tone: "pos",
    headline: "MICROSOFT AZURE AI REVENUE GROWTH TOPPED 60% IN Q1 — INTERNAL FIGURES",
    byline: "D. BASS",
    dateline: "REDMOND",
    symbols: ["MSFT", "NVDA"],
    body: [
      "Microsoft Corp.'s Azure AI services revenue grew more than 60% year-on-year in the fiscal third quarter, according to internal figures reviewed by Bloomberg, well above the ~40% growth the company disclosed externally for the broader Azure segment.",
      "The numbers suggest the AI piece is increasingly outsizing the rest of Azure and supports recent capex commentary, where Microsoft signaled it will spend $30 billion+ on AI infrastructure in fiscal 2026.",
      "Shares were little changed at $432.04 after a strong April. The figures will likely be referenced when the company hosts its annual Build developer conference in Seattle next week.",
    ],
  },
  {
    id: "n-014",
    time: "22:08",
    src: "FT",
    cat: "ECON",
    tone: "pos",
    headline: "GERMAN IFO BUSINESS CLIMATE EDGES UP TO 88.4 VS 87.9 PRIOR",
    byline: "M. ARNOLD",
    dateline: "MUNICH",
    symbols: ["EURUSD", "DAX", "DE10Y"],
    body: [
      "Germany's IFO business climate index edged higher to 88.4 in May from 87.9 in April, slightly above the 88.2 consensus estimate, as both the current situation and expectations subcomponents improved modestly.",
      "Manufacturing posted the largest gain among sectors, with the subindex rising to -10.0 from -13.1, though it remains in negative territory. Services and trade also improved; only construction continues to deteriorate.",
      "The DAX was little changed at 18,942. EUR/USD held at 1.0842. The print supports the case that the euro-area economic recovery, while modest, remains intact.",
    ],
  },
  {
    id: "n-015",
    time: "22:01",
    src: "DJ",
    cat: "CMDTY",
    tone: "neutral",
    headline: "SAUDI ARAMCO TO RAISE JUNE OFFICIAL SELLING PRICES TO ASIA — TRADERS",
    byline: "M. WANG",
    dateline: "DUBAI",
    symbols: ["CL1", "CO1"],
    body: [
      "Saudi Aramco is expected to raise its official selling prices (OSPs) for June-loading crude to Asian customers by $0.50-$0.70/bbl, according to traders surveyed by Dow Jones, signaling the kingdom's view that physical demand in the region remains firm.",
      "The OSP for the Arab Light grade is expected to be set at roughly +$2.40/bbl over the regional benchmark, up from +$1.80 in May. Final pricing is typically published in the first week of the month.",
      "The expected increase aligns with backwardation in the Dubai market structure that has tightened over the past two weeks.",
    ],
  },
  {
    id: "n-016",
    time: "21:54",
    src: "BN",
    cat: "EQ",
    tone: "pos",
    headline: "AMD ANNOUNCES $5B SHARE BUYBACK PROGRAM, RAISES FY OUTLOOK",
    byline: "I. KING",
    dateline: "SANTA CLARA",
    symbols: ["AMD", "NVDA"],
    body: [
      "Advanced Micro Devices Inc. authorized a new $5 billion share-repurchase program and raised its full-year revenue guidance to $30-32 billion from $28-30 billion, citing stronger-than-expected demand for its MI300 series accelerators in data-center customers.",
      "The buyback represents roughly 2% of the company's market cap and will be funded from operating cash flow. AMD ended Q1 with $5.7 billion in cash and equivalents.",
      "Shares jumped 4.2% in extended trade to $128.14. Lisa Su, AMD's CEO, will host an analyst day on June 14 in San Francisco where she is expected to detail the next-generation MI400 roadmap.",
    ],
  },
  {
    id: "n-017",
    time: "21:48",
    src: "RTRS",
    cat: "CRED",
    tone: "neg",
    headline: "BOEING IG SPREADS WIDEN 12BP AFTER MOODY'S NEGATIVE WATCH",
    byline: "T. STODDARD",
    dateline: "NEW YORK",
    symbols: ["BA"],
    body: [
      "Boeing Co.'s investment-grade credit spreads widened sharply Wednesday after Moody's Investors Service placed the aerospace giant's Baa3 rating on negative watch, citing \"sustained underperformance\" in the commercial-airplanes division.",
      "The 5-year CDS on Boeing widened to 324 bp from 312 bp, the highest in three months. Cash bonds saw similar pressure: the 5.15% notes due 2030 traded at OAS of +318 bp, ~10 bp wider.",
      "Moody's flagged concerns about Boeing's ability to ramp 737 MAX production back to 38/month while maintaining its credit metrics. A downgrade to junk would force forced selling from many IG-mandate funds.",
    ],
  },
  {
    id: "n-018",
    time: "21:41",
    src: "BN",
    cat: "FX",
    tone: "neutral",
    headline: "PBOC SETS USDCNY FIX AT 7.2284; STRONGEST SINCE FEBRUARY",
    byline: "T. CHEN",
    dateline: "BEIJING",
    symbols: ["USDCNH"],
    body: [
      "The People's Bank of China set the daily reference rate for the onshore yuan at 7.2284 per dollar, the strongest fixing since early February and notably stronger than the 7.2330 expected by analyst median.",
      "The fix continues a recent pattern of \"counter-cyclical\" guidance — keeping the rate stronger than what model-implied fair value suggests — as authorities seek to limit yuan depreciation pressure tied to the broader USD rally.",
      "Offshore yuan was little changed at 7.2384 per dollar after the fix.",
    ],
  },
];

export type EventItem = {
  time: string;
  ccy: string;
  imp: 1 | 2 | 3;
  label: string;
  fcst: string;
  prev: string;
  actual?: string;
  source?: DataSourceState;
};

export const EVENTS: EventItem[] = [
  { time: "08:30", ccy: "USD", imp: 3, label: "CPI YoY",            fcst: "+2.9%",  prev: "+3.0%" },
  { time: "08:30", ccy: "USD", imp: 3, label: "CPI Core YoY",       fcst: "+3.1%",  prev: "+3.2%" },
  { time: "10:00", ccy: "USD", imp: 2, label: "Wholesale Inv. MoM", fcst: "+0.2%",  prev: "+0.4%" },
  { time: "11:00", ccy: "EUR", imp: 2, label: "ECB Lane Speech",    fcst: "—",      prev: "—"     },
  { time: "13:00", ccy: "USD", imp: 3, label: "10Y Auction",        fcst: "—",      prev: "4.40%" },
  { time: "14:30", ccy: "USD", imp: 1, label: "Fed Williams",       fcst: "—",      prev: "—"     },
  { time: "20:00", ccy: "USD", imp: 2, label: "Cons. Credit",       fcst: "+12.4B", prev: "+9.2B" },
  { time: "23:50", ccy: "JPY", imp: 2, label: "Machine Orders MoM", fcst: "+0.8%",  prev: "+2.9%" },
];

export const RECENT_PRINTS: EventItem[] = [
  { time: "08:30 MON", ccy: "USD", imp: 3, label: "Retail Sales MoM", fcst: "+0.3%",  prev: "+0.7%",  actual: "+0.1%" },
  { time: "10:00 MON", ccy: "USD", imp: 2, label: "Biz Inventories",  fcst: "+0.2%",  prev: "+0.4%",  actual: "+0.3%" },
  { time: "04:00 TUE", ccy: "EUR", imp: 2, label: "EZ Trade Balance", fcst: "+22.0B", prev: "+24.0B", actual: "+19.1B" },
  { time: "08:30 TUE", ccy: "USD", imp: 3, label: "PPI YoY",          fcst: "+2.4%",  prev: "+2.1%",  actual: "+2.6%" },
  { time: "14:00 TUE", ccy: "USD", imp: 2, label: "NY Fed Speech",    fcst: "—",      prev: "—",      actual: "—" },
  { time: "02:00 WED", ccy: "GBP", imp: 3, label: "UK CPI YoY",       fcst: "+2.8%",  prev: "+3.2%",  actual: "+3.1%" },
];

export type BondRow = {
  issuer: string;
  desc: string;
  cpn: number | null;
  maturity: string;
  px: number | null;
  ytm: number | null;
  oas: number | null;
  rating: string;
  source?: DataSourceState;
};

export const BONDS: BondRow[] = [
  { issuer: "AAPL",  desc: "5.000 15-Aug-2031", cpn: 5.00, maturity: "2031-08-15", px: 102.14, ytm: 4.72, oas:  32, rating: "AA+" },
  { issuer: "MSFT",  desc: "4.500 06-Feb-2033", cpn: 4.50, maturity: "2033-02-06", px:  99.84, ytm: 4.54, oas:  24, rating: "AAA" },
  { issuer: "GOOGL", desc: "4.750 15-May-2032", cpn: 4.75, maturity: "2032-05-15", px: 101.42, ytm: 4.61, oas:  31, rating: "AA+" },
  { issuer: "JPM",   desc: "5.250 22-Jan-2034", cpn: 5.25, maturity: "2034-01-22", px:  99.12, ytm: 5.38, oas:  92, rating: "A-"  },
  { issuer: "BAC",   desc: "5.500 04-Apr-2035", cpn: 5.50, maturity: "2035-04-04", px:  98.24, ytm: 5.74, oas: 121, rating: "A-"  },
  { issuer: "XOM",   desc: "4.875 15-Mar-2030", cpn: 4.88, maturity: "2030-03-15", px: 100.84, ytm: 4.68, oas:  38, rating: "AA-" },
  { issuer: "T",     desc: "4.500 01-Mar-2048", cpn: 4.50, maturity: "2048-03-01", px:  88.42, ytm: 5.42, oas: 142, rating: "BBB+"},
  { issuer: "F",     desc: "6.250 17-Jun-2030", cpn: 6.25, maturity: "2030-06-17", px: 102.42, ytm: 5.84, oas: 218, rating: "BB+" },
  { issuer: "BA",    desc: "5.150 01-May-2030", cpn: 5.15, maturity: "2030-05-01", px:  94.84, ytm: 6.41, oas: 318, rating: "BBB-"},
  { issuer: "TSLA",  desc: "5.300 15-Aug-2027", cpn: 5.30, maturity: "2027-08-15", px:  99.42, ytm: 5.51, oas: 142, rating: "BBB" },
];

export type CdsRow = {
  name: string;
  region: string;
  rating: string;
  px: number | null;
  chg: number | null;
  ytd: number | null;
  source?: DataSourceState;
};

export const CDS: CdsRow[] = [
  { name: "JPM",     region: "US / FIN",       rating: "A-",   px:  42, chg:  -1.2, ytd:  -4 },
  { name: "BAC",     region: "US / FIN",       rating: "A-",   px:  62, chg:  +0.8, ytd:  +8 },
  { name: "GS",      region: "US / FIN",       rating: "BBB+", px:  74, chg:  +1.4, ytd: +12 },
  { name: "AAPL",    region: "US / TECH",      rating: "AA+",  px:  24, chg:  -0.4, ytd:  -2 },
  { name: "MSFT",    region: "US / TECH",      rating: "AAA",  px:  18, chg:  -0.2, ytd:  -3 },
  { name: "F",       region: "US / IND",       rating: "BB+",  px: 218, chg: +12.4, ytd: +42 },
  { name: "BA",      region: "US / IND",       rating: "BBB-", px: 324, chg:  +8.4, ytd: +84 },
  { name: "DEUTSCHE",region: "DE / FIN",       rating: "A",    px:  84, chg:  -2.4, ytd: -14 },
  { name: "BNP",     region: "FR / FIN",       rating: "A+",   px:  62, chg:  -1.2, ytd:  -8 },
  { name: "ITALY",   region: "SOV / EU",       rating: "BBB",  px: 124, chg:  -2.4, ytd: -12 },
  { name: "TURKEY",  region: "SOV / EM",       rating: "B",    px: 284, chg:  +4.2, ytd: -42 },
  { name: "BRAZIL",  region: "SOV / EM",       rating: "BB",   px: 214, chg:  -1.8, ytd: -24 },
];

export type CreditIndexRow = {
  name: string;
  desc: string;
  last: number | null;
  chg: number | null;
  ytd: number | null;
  source?: DataSourceState;
};

export const CREDIT_INDICES: CreditIndexRow[] = [
  { name: "CDX IG",   desc: "5Y CDS IG / OTR",  last:  62, chg: +0.4, ytd:  +4 },
  { name: "CDX HY",   desc: "5Y CDS HY / OTR",  last: 342, chg: -1.8, ytd: -12 },
  { name: "ITRX EUR", desc: "ITRAXX MAIN",      last:  58, chg: +0.2, ytd:  +2 },
  { name: "ITRX XO",  desc: "ITRAXX CROSSOVER", last: 312, chg: -2.4, ytd:  -8 },
  { name: "EMBI",     desc: "EM SOVEREIGN",     last: 298, chg: -1.2, ytd: +24 },
  { name: "LBUSTRUU", desc: "US AGG OAS",       last:  82, chg: -0.4, ytd:  -2 },
  { name: "LF98TRUU", desc: "US HY OAS",        last: 342, chg: -1.8, ytd: -12 },
  { name: "LP01TRUU", desc: "PAN-EU AGG",       last:  96, chg: -0.2, ytd:  -4 },
  { name: "MOVE",     desc: "RATES VOL",        last:  92, chg: -1.8, ytd:  -8 },
];

export type Position = {
  ticker: string;
  name: string;
  qty: number;
  avg: number;
  mark: number;
  mv: number;
  pl: number;
  plPct: number;
  wgt: number;
  source?: DataSourceState;
};

/** Derived from WATCHLIST with deterministic mock costs/quantities. */
export const POSITIONS: Position[] = WATCHLIST.slice(0, 12).map((w, i) => {
  const qty = Math.round(100 + ((i * 173) % 900));
  const avg = +(w.last * (0.78 + ((i * 37) % 40) / 100)).toFixed(2);
  const mark = w.last;
  const mv = +(qty * mark).toFixed(2);
  const pl = +((mark - avg) * qty).toFixed(2);
  const plPct = +(((mark - avg) / avg) * 100).toFixed(2);
  return { ticker: w.ticker, name: w.name, qty, avg, mark, mv, pl, plPct, wgt: 0 };
}).map((p, _i, arr) => {
  const total = arr.reduce((s, x) => s + x.mv, 0);
  return { ...p, wgt: +((p.mv / total) * 100).toFixed(2) };
});

/** Deterministic price-path generator for charts, seeded so it never re-renders differently. */
export function generatePath(points: number, seed = 7): number[] {
  let s = seed;
  const out: number[] = [];
  let p = 100;
  for (let i = 0; i < points; i++) {
    s = (s * 9301 + 49297) % 233280;
    const r = s / 233280;
    p += (r - 0.48) * 1.6;
    out.push(p);
  }
  return out;
}
