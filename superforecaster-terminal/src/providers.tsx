import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import type {
  BondRow,
  CbRate,
  CdsRow,
  CreditIndexRow,
  EventItem,
  NewsItem,
  Position,
  Quote,
  DataSourceState,
  YieldCurvePoint,
} from "./data";
import {
  AGS,
  BONDS,
  CB_RATES,
  CDS,
  COMMODITIES,
  CREDIT_INDICES,
  CROSS_CCYS,
  CROSS_FX,
  CRYPTO,
  EM_FX,
  ENERGY,
  EVENTS,
  FX,
  INDICES,
  METALS,
  NEWS,
  POSITIONS,
  RATES,
  RECENT_PRINTS,
  SECTORS,
  US_CURVE,
  WATCHLIST,
  WORLD_INDICES,
} from "./data";
import {
  createTermdApiClient,
  readTermdApiConfig,
  termdPredictionChannels,
  type TermdAssetClass,
  type TermdApiClient,
  type TermdApiConfig,
  type TermdCommoditiesSnapshot,
  type TermdChartSnapshot,
  type TermdDepthSnapshot,
  type TermdEconomicCalendarSnapshot,
  type TermdFixedIncomeSnapshot,
  type TermdFxSnapshot,
  type TermdFiling,
  type TermdInsiderTrade,
  type TermdInstitutionalHolding,
  type TermdMacroPoint,
  type TermdMacroSeries,
  type TermdMarketsOverview,
  type TermdOptionChainSnapshot,
  type TermdOptionSurface,
  type TermdOptionSurfaceSnapshot,
  type TermdPredictionMarket,
  type TermdRatesSnapshot,
  type TermdRssFeed,
  type TermdScreenDatasetMeta,
  type TermdScreenSnapshot,
  type TermdStream,
  type TermdTradeSnapshot,
  type TermdTradesSnapshot,
  type TermdWatchlist,
  type TermdUserAlert,
  type TermdUserPosition,
} from "./termdApi";

/* ─────────────────────────────────────────────────────────────────────────────
   Types — `DataProvider`'s public surface
   ──────────────────────────────────────────────────────────────────────────── */

export type QuoteCategory =
  | "indices" | "world-indices" | "fx" | "em-fx" | "rates"
  | "sectors" | "commodities" | "crypto" | "watchlist"
  | "energy" | "metals" | "ags";

export type DetailDataset = "chart" | "depth" | "trades" | "options" | "vol-surface";

export type DepthLevel = { px: number; qty: number };
export type DepthBookData = { symbol: string; bids: DepthLevel[]; asks: DepthLevel[] };

export type OptionRow = {
  strike: number;
  callBid: number; callAsk: number; callLast: number;
  callIV: number; callDelta: number; callOI: number;
  putBid: number; putAsk: number; putLast: number;
  putIV: number; putDelta: number; putOI: number;
};
export type OptionChainData = {
  symbol: string;
  expiry: string;
  spot: number;
  rows: OptionRow[];
};

export type Trade = { time: string; px: number; qty: number; side: "B" | "S" };

export type HeatmapCell = {
  symbol: string;
  name: string;
  sector: string;
  pct: number;
  weight: number;
  source?: DataSourceState;
};

export type Earning = {
  date: string;       // YYYY-MM-DD
  whenStr: string;    // "BMO" / "AMC" / "—"
  symbol: string;
  name: string;
  consensusEps: number | null;
  consensusRev: string;
  prevEps: number | null;
  reported?: number;
  source?: DataSourceState;
};

export type ResearchSnapshot = {
  symbol: string;
  filings: readonly TermdFiling[];
  insiderTrades: readonly TermdInsiderTrade[];
  institutionalHoldings: readonly TermdInstitutionalHolding[];
  source: DataSourceState;
  filingsSource: DataSourceState;
  insiderSource: DataSourceState;
  holdingsSource: DataSourceState;
};

export type AlertCondition = ">=" | "<=";
export type AlertStatus = "ACTIVE" | "TRIGGERED" | "CANCELLED";

export type Alert = {
  id: string;
  symbol: string;
  level: number;
  condition: AlertCondition;
  status: AlertStatus;
  createdAt: number;
  triggeredAt?: number;
  triggeredPx?: number;
  source?: DataSourceState;
};

export type ThemeName = "cream" | "amber" | "phosphor" | "paper";

/* ─────────────────────────────────────────────────────────────────────────────
   Portfolio types
   ──────────────────────────────────────────────────────────────────────────── */

/** Persisted portfolio metadata (no live marks). */
export type PortfolioMeta = {
  id: string;
  name: string;
  cash: number;
  createdAt: number;
};

/** Stored shape for a position — just the user-set quantities. Marks,
 *  market value, and P/L are recomputed live from quotes. */
export type StoredPosition = {
  ticker: string;
  qty: number;
  avg: number;
};

export type StoredPortfolio = PortfolioMeta & {
  positions: StoredPosition[];
};

/* ─────────────────────────────────────────────────────────────────────────────
   Watchlist types — many named lists, each holds a symbol order.
   ──────────────────────────────────────────────────────────────────────────── */

export type WatchlistMeta = {
  id: string;
  name: string;
  createdAt: number;
};

export type StoredWatchlist = WatchlistMeta & {
  symbols: string[];
};

/* ─────────────────────────────────────────────────────────────────────────────
   Desk types — a snapshot of the entire view (screen + symbol + theme
   + active watchlist + active portfolio). Switching applies all five.
   ──────────────────────────────────────────────────────────────────────────── */

export type DeskSnapshot = {
  activeKey: string;
  activeSymbol: string;
  activeWatchlistId: string;
  activePortfolioId: string;
  theme: ThemeName;
  filter?: ActiveFilter;
};

/** A view-wide filter ("lens") that scopes every screen to a subset.
 *  Currently sectors only; the discriminated union leaves room for
 *  country / asset-class / mcap-bucket etc. without API change. */
export type ActiveFilter =
  | { kind: "none" }
  | { kind: "sector"; sector: string };

/** Canonical sector list — same labels HEATMAP_CONSTITUENTS uses. */
export const SECTORS_LIST = [
  "TECH",
  "FIN",
  "ENERGY",
  "HEALTH",
  "DISC",
  "STAPLE",
  "INDUS",
  "COMMS",
  "UTIL",
  "MAT",
  "RE",
] as const;
export type SectorTag = (typeof SECTORS_LIST)[number] | "OTHER";

/** Friendly long name for each sector. */
export const SECTOR_DISPLAY: Record<string, string> = {
  TECH:   "Technology",
  FIN:    "Financials",
  ENERGY: "Energy",
  HEALTH: "Health Care",
  DISC:   "Consumer Disc.",
  STAPLE: "Consumer Staples",
  INDUS:  "Industrials",
  COMMS:  "Communications",
  UTIL:   "Utilities",
  MAT:    "Materials",
  RE:     "Real Estate",
  OTHER:  "Other",
};

export type Desk = {
  id: string;
  name: string;
  createdAt: number;
  snapshot: DeskSnapshot;
};

export interface DataProvider {
  // Snapshot reads
  getQuote(symbol: string): Quote | undefined;
  listQuotes(category: QuoteCategory): readonly Quote[];
  allSymbols(): readonly string[];
  getChart(symbol: string, points?: number): number[];
  getDepth(symbol: string): DepthBookData;
  getOptionChain(symbol: string, expiry?: string): OptionChainData;
  getOptionSurface(symbol: string): {
    expiries: string[];
    strikes: number[];
    iv: number[][];
  };
  getTimeSales(symbol: string, max?: number): readonly Trade[];
  getDetailSource(kind: DetailDataset, symbol: string): DataSourceState;
  getHeatmap(): readonly HeatmapCell[];
  getMovers(): {
    gainers: readonly Quote[];
    losers: readonly Quote[];
    actives: readonly Quote[];
  };
  getCorrelation(symbols: readonly string[]): number[][];

  // Static-ish reads
  getNews(filter?: { category?: string; symbol?: string }): readonly NewsItem[];
  subscribeNews(cb: () => void): () => void;
  getRssFeeds(): readonly TermdRssFeed[];
  subscribeRssFeeds(cb: () => void): () => void;
  getEvents(): readonly EventItem[];
  getRecentPrints(): readonly EventItem[];
  subscribeCalendarData(cb: () => void): () => void;
  getBonds(): readonly BondRow[];
  getCDS(): readonly CdsRow[];
  getCreditIndices(): readonly CreditIndexRow[];
  subscribeFixedIncomeData(cb: () => void): () => void;
  getCBRates(): readonly CbRate[];
  getCrossFX(): { ccys: readonly string[]; matrix: readonly (readonly (number | null)[])[] };
  subscribeFxData(cb: () => void): () => void;
  getYieldCurve(): readonly YieldCurvePoint[];
  getEarnings(): readonly Earning[];
  subscribeMacroData(cb: () => void): () => void;
  getPredictionMarkets(): readonly TermdPredictionMarket[];
  subscribePredictionMarkets(cb: () => void): () => void;
  getResearch(symbol: string): ResearchSnapshot;
  subscribeResearch(symbol: string, cb: () => void): () => void;
  getScreenDatasets(): readonly TermdScreenDatasetMeta[];
  subscribeScreenDatasets(cb: () => void): () => void;

  // Watchlists — many named lists, persisted to localStorage. The
  // `listQuotes("watchlist")` call resolves to the active watchlist.
  listWatchlists(): readonly WatchlistMeta[];
  getActiveWatchlistId(): string;
  setActiveWatchlistId(id: string): void;
  getWatchlistSymbols(id: string): readonly string[];
  watchlistsAreReadOnly(): boolean;
  createWatchlist(name: string, symbols?: readonly string[]): WatchlistMeta;
  renameWatchlist(id: string, name: string): boolean;
  deleteWatchlist(id: string): boolean;
  addSymbolToWatchlist(id: string, symbol: string): boolean;
  removeSymbolFromWatchlist(id: string, symbol: string): boolean;
  subscribeWatchlists(cb: () => void): () => void;

  // Desks — saved snapshots of the active view.
  listDesks(): readonly Desk[];
  saveDesk(name: string, snapshot: DeskSnapshot): Desk;
  updateDesk(id: string, snapshot: DeskSnapshot): boolean;
  renameDesk(id: string, name: string): boolean;
  deleteDesk(id: string): boolean;
  subscribeDesks(cb: () => void): () => void;

  // Portfolios — many named books per user, persisted to localStorage.
  // Positions are manually curated for local mark/risk views; this product is
  // read-only and does not route or simulate order execution.
  listPortfolios(): readonly PortfolioMeta[];
  getActivePortfolioId(): string;
  setActivePortfolioId(id: string): void;
  createPortfolio(name: string, cash?: number): PortfolioMeta;
  renamePortfolio(id: string, name: string): boolean;
  deletePortfolio(id: string): boolean;
  addManualPosition(
    portfolioId: string,
    pos: { ticker: string; qty: number; avg: number },
  ): boolean;
  removePosition(portfolioId: string, ticker: string): boolean;
  subscribePortfolios(cb: () => void): () => void;

  // Local workspace state — positions and alerts. This build does not expose
  // order submission or simulated fills.
  getPositions(): readonly Position[];
  subscribePositions(cb: () => void): () => void;

  addAlert(a: Omit<Alert, "id" | "status" | "createdAt">): Alert;
  cancelAlert(id: string): boolean;
  getAlerts(): readonly Alert[];
  subscribeAlerts(cb: (triggered?: Alert) => void): () => void;

  // Streams
  subscribeQuote(symbol: string, cb: (q: Quote) => void): () => void;
  subscribeTrades(symbol: string, cb: (t: Trade) => void): () => void;
  subscribeDetailData(symbol: string, cb: () => void): () => void;

  // Tick-stream control
  isPaused(): boolean;
  setPaused(p: boolean): void;
  subscribePauseState(cb: (p: boolean) => void): () => void;

  // Lifecycle
  start(): void;
  stop(): void;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Heatmap constituents
   ──────────────────────────────────────────────────────────────────────────── */

const HEATMAP_CONSTITUENTS: readonly [string, string, string, number][] = [
  ["NVDA", "Nvidia", "TECH", 8.2], ["AAPL", "Apple", "TECH", 7.4],
  ["MSFT", "Microsoft", "TECH", 6.9], ["GOOGL", "Alphabet", "TECH", 4.1],
  ["AMZN", "Amazon", "TECH", 3.8], ["META", "Meta", "TECH", 2.6],
  ["AVGO", "Broadcom", "TECH", 2.1], ["AMD", "AMD", "TECH", 1.2],
  ["ORCL", "Oracle", "TECH", 1.1], ["CRM", "Salesforce", "TECH", 0.8],
  ["ADBE", "Adobe", "TECH", 0.7], ["CSCO", "Cisco", "TECH", 0.6],
  ["JPM", "JPMorgan", "FIN", 1.4], ["BAC", "BofA", "FIN", 0.9],
  ["WFC", "Wells Fargo", "FIN", 0.6], ["GS", "Goldman", "FIN", 0.4],
  ["MS", "Morgan Stanley", "FIN", 0.4], ["BRK/B", "Berkshire", "FIN", 1.7],
  ["V", "Visa", "FIN", 0.9], ["MA", "Mastercard", "FIN", 0.8],
  ["AXP", "Amex", "FIN", 0.4],
  ["XOM", "ExxonMobil", "ENERGY", 1.0], ["CVX", "Chevron", "ENERGY", 0.6],
  ["COP", "ConocoPhill.", "ENERGY", 0.3], ["SLB", "SLB", "ENERGY", 0.2],
  ["UNH", "UnitedHealth", "HEALTH", 1.2], ["JNJ", "J&J", "HEALTH", 0.9],
  ["LLY", "Eli Lilly", "HEALTH", 1.6], ["PFE", "Pfizer", "HEALTH", 0.4],
  ["MRK", "Merck", "HEALTH", 0.7], ["ABBV", "AbbVie", "HEALTH", 0.8],
  ["TMO", "Thermo Fisher", "HEALTH", 0.5],
  ["TSLA", "Tesla", "DISC", 1.8], ["HD", "Home Depot", "DISC", 0.8],
  ["MCD", "McDonald's", "DISC", 0.5], ["NKE", "Nike", "DISC", 0.3],
  ["SBUX", "Starbucks", "DISC", 0.3],
  ["WMT", "Walmart", "STAPLE", 0.6], ["PG", "P&G", "STAPLE", 0.7],
  ["KO", "Coca-Cola", "STAPLE", 0.5], ["PEP", "PepsiCo", "STAPLE", 0.5],
  ["COST", "Costco", "STAPLE", 0.7],
  ["BA", "Boeing", "INDUS", 0.4], ["CAT", "Caterpillar", "INDUS", 0.4],
  ["GE", "GE Aerospace", "INDUS", 0.4], ["HON", "Honeywell", "INDUS", 0.4],
  ["UNP", "Union Pacific", "INDUS", 0.3],
  ["DIS", "Disney", "COMMS", 0.4], ["NFLX", "Netflix", "COMMS", 0.6],
  ["T", "AT&T", "COMMS", 0.3], ["VZ", "Verizon", "COMMS", 0.4],
  ["CMCSA", "Comcast", "COMMS", 0.3],
  ["NEE", "NextEra", "UTIL", 0.3], ["DUK", "Duke", "UTIL", 0.2],
  ["SO", "Southern", "UTIL", 0.2],
  ["LIN", "Linde", "MAT", 0.4], ["FCX", "Freeport", "MAT", 0.2],
  ["NEM", "Newmont", "MAT", 0.2],
  ["AMT", "Amer. Tower", "RE", 0.2], ["PLD", "Prologis", "RE", 0.2],
  ["CCI", "Crown Castle", "RE", 0.1],
];

const EARNINGS_SEED: readonly Earning[] = [
  { date: "2026-05-14", whenStr: "AMC", symbol: "NVDA",  name: "Nvidia Corp",        consensusEps: 0.84, consensusRev: "$32.4B",  prevEps: 0.78 },
  { date: "2026-05-15", whenStr: "BMO", symbol: "WMT",   name: "Walmart Inc",        consensusEps: 0.52, consensusRev: "$163.1B", prevEps: 0.60 },
  { date: "2026-05-15", whenStr: "AMC", symbol: "AMAT",  name: "Applied Materials",  consensusEps: 2.18, consensusRev: "$7.2B",   prevEps: 2.09 },
  { date: "2026-05-19", whenStr: "AMC", symbol: "PANW",  name: "Palo Alto Networks", consensusEps: 1.52, consensusRev: "$2.3B",   prevEps: 1.32 },
  { date: "2026-05-20", whenStr: "AMC", symbol: "SNOW",  name: "Snowflake Inc",      consensusEps: 0.18, consensusRev: "$1.1B",   prevEps: 0.14 },
  { date: "2026-05-21", whenStr: "AMC", symbol: "NVDA",  name: "Nvidia Corp",        consensusEps: 0.91, consensusRev: "$36.1B",  prevEps: 0.84 },
  { date: "2026-05-22", whenStr: "BMO", symbol: "BABA",  name: "Alibaba Group",      consensusEps: 1.71, consensusRev: "$30.4B",  prevEps: 1.85 },
  { date: "2026-05-23", whenStr: "AMC", symbol: "INTU",  name: "Intuit Inc",         consensusEps: 9.50, consensusRev: "$6.7B",   prevEps: 8.42 },
  { date: "2026-05-27", whenStr: "AMC", symbol: "CRM",   name: "Salesforce Inc",     consensusEps: 2.36, consensusRev: "$9.3B",   prevEps: 2.18 },
  { date: "2026-05-28", whenStr: "AMC", symbol: "NVDA",  name: "Nvidia Corp",        consensusEps: 0.94, consensusRev: "$37.5B",  prevEps: 0.91 },
  { date: "2026-05-29", whenStr: "AMC", symbol: "CRWD",  name: "CrowdStrike",        consensusEps: 0.92, consensusRev: "$1.0B",   prevEps: 0.93 },
  { date: "2026-05-30", whenStr: "BMO", symbol: "DELL",  name: "Dell Technologies",  consensusEps: 1.65, consensusRev: "$24.3B",  prevEps: 1.59 },
];

/* ─────────────────────────────────────────────────────────────────────────────
   Helpers
   ──────────────────────────────────────────────────────────────────────────── */

function seedFor(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 16807) + 1) >>> 0;
    return (s & 0x7fffffff) / 0x7fffffff;
  };
}
function pxDigits(px: number) {
  if (px >= 1000) return 2;
  if (px >= 10) return 2;
  if (px >= 1) return 4;
  return 5;
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function chartKey(symbol: string, points: number): string {
  return `${normalizeSymbol(symbol)}:${points}`;
}

function optionChainKey(symbol: string, expiry: string): string {
  return `${normalizeSymbol(symbol)}:${expiry.toUpperCase()}`;
}

function detailSourceKey(kind: DetailDataset, symbol: string): string {
  return `${kind}:${normalizeSymbol(symbol)}`;
}

function predictionMarketKey(market: Pick<TermdPredictionMarket, "venue" | "marketId" | "outcome">): string {
  return `${market.venue.toUpperCase()}:${market.marketId}:${market.outcome.toUpperCase()}`;
}

const CATEGORY_LISTS: Record<QuoteCategory, readonly Quote[]> = {
  indices: INDICES,
  "world-indices": WORLD_INDICES,
  fx: FX,
  "em-fx": EM_FX,
  rates: RATES,
  sectors: SECTORS,
  commodities: COMMODITIES,
  crypto: CRYPTO,
  watchlist: WATCHLIST,
  energy: ENERGY,
  metals: METALS,
  ags: AGS,
};

const CATEGORY_DATASET_KEYS: Partial<Record<QuoteCategory, string>> = {
  indices: "quotes",
  "world-indices": "quotes",
  fx: "fx",
  "em-fx": "fx",
  rates: "rates",
  sectors: "quotes",
  commodities: "commodities",
  crypto: "quotes",
  energy: "commodities",
  metals: "commodities",
  ags: "commodities",
};

function listHasSymbol(list: readonly Quote[], symbol: string): boolean {
  return list.some((quote) => quote.ticker.toUpperCase() === symbol);
}

function termdAssetClassForSymbol(symbol: string): TermdAssetClass {
  const normalized = normalizeSymbol(symbol);
  if (listHasSymbol(FX, normalized) || listHasSymbol(EM_FX, normalized)) return "fx";
  if (listHasSymbol(RATES, normalized)) return "rates";
  if (
    listHasSymbol(COMMODITIES, normalized) ||
    listHasSymbol(ENERGY, normalized) ||
    listHasSymbol(METALS, normalized) ||
    listHasSymbol(AGS, normalized)
  ) {
    return "cmdty";
  }
  if (listHasSymbol(CRYPTO, normalized)) return "cx";
  return "eq";
}

function quoteDatasetKeyForSymbol(symbol: string): string {
  const normalized = normalizeSymbol(symbol);
  if (listHasSymbol(FX, normalized) || listHasSymbol(EM_FX, normalized)) return "fx";
  if (listHasSymbol(RATES, normalized)) return "rates";
  if (
    listHasSymbol(COMMODITIES, normalized) ||
    listHasSymbol(ENERGY, normalized) ||
    listHasSymbol(METALS, normalized) ||
    listHasSymbol(AGS, normalized)
  ) {
    return "commodities";
  }
  return "quotes";
}

const FRED_10Y_SERIES_ID = "fred.DGS10";
const USD_POLICY_SERIES_ID = "bis.US_POLICY_RATE";
const USD_10Y_QUOTE_SYMBOL = "US10Y";
const RATE_TENOR_TO_SYMBOL = new Map<string, string>([
  ["1M", "US01M"],
  ["3M", "US03M"],
  ["6M", "US06M"],
  ["1Y", "US01Y"],
  ["2Y", "US02Y"],
  ["3Y", "US03Y"],
  ["5Y", "US05Y"],
  ["7Y", "US07Y"],
  ["10Y", "US10Y"],
  ["20Y", "US20Y"],
  ["30Y", "US30Y"],
]);

function latestMacroPoint(series: TermdMacroSeries): TermdMacroPoint | undefined {
  return series.points.at(-1);
}

function previousMacroPoint(series: TermdMacroSeries): TermdMacroPoint | undefined {
  return series.points.length > 1 ? series.points.at(-2) : undefined;
}

function macroAdjustedYieldCurve(
  curve: readonly YieldCurvePoint[],
  series: ReadonlyMap<string, TermdMacroSeries>,
): readonly YieldCurvePoint[] {
  const us10y = latestMacroPointFor(series, FRED_10Y_SERIES_ID);
  if (!us10y) return curve;
  return curve.map((point) =>
    point.tenor === "10Y" ? { ...point, yld: +us10y.value.toFixed(3) } : point,
  );
}

function macroAdjustedCentralBankRates(
  rows: readonly CbRate[],
  series: ReadonlyMap<string, TermdMacroSeries>,
): readonly CbRate[] {
  const policySeries = series.get(USD_POLICY_SERIES_ID);
  const policy = policySeries ? latestMacroPoint(policySeries) : undefined;
  if (!policy || !policySeries) return rows;
  const previous = previousDistinctMacroPoint(policySeries);
  const lastMove = currentValueStartDate(policySeries) ?? undefined;
  return rows.map((row) =>
    row.ccy === "USD"
      ? {
          ...row,
          rate: +policy.value.toFixed(3),
          lastMove: lastMove ?? row.lastMove,
          bias: policyBias(policy, previous),
        }
      : row,
  );
}

function latestMacroPointFor(
  series: ReadonlyMap<string, TermdMacroSeries>,
  id: string,
): TermdMacroPoint | undefined {
  const found = series.get(id);
  return found ? latestMacroPoint(found) : undefined;
}

function policyBias(
  latest: TermdMacroPoint,
  previous: TermdMacroPoint | undefined,
): CbRate["bias"] {
  if (!previous || Math.abs(latest.value - previous.value) < 0.0001) return "HOLD";
  return latest.value > previous.value ? "HIKE" : "CUT";
}

function previousDistinctMacroPoint(series: TermdMacroSeries): TermdMacroPoint | undefined {
  const latest = latestMacroPoint(series);
  if (!latest) return undefined;
  for (let index = series.points.length - 2; index >= 0; index -= 1) {
    const point = series.points[index];
    if (Math.abs(point.value - latest.value) >= 0.0001) return point;
  }
  return undefined;
}

function currentValueStartDate(series: TermdMacroSeries): string | null {
  const latest = latestMacroPoint(series);
  if (!latest) return null;
  for (let index = series.points.length - 2; index >= 0; index -= 1) {
    const point = series.points[index];
    if (Math.abs(point.value - latest.value) >= 0.0001) {
      return series.points[index + 1]?.time.slice(0, 10) ?? null;
    }
  }
  return null;
}

const HEATMAP_DEFAULT_PCT = new Map<string, number>(
  HEATMAP_CONSTITUENTS.map(([s], i) => {
    const r = ((seedFor(s) + i * 1337) % 1000) / 1000;
    return [s, +((r - 0.45) * 5).toFixed(2)];
  }),
);

/* ─────────────────────────────────────────────────────────────────────────────
   Backend-first data provider
   ──────────────────────────────────────────────────────────────────────────── */

let idCounter = 1;
const nextId = () => `${Date.now().toString(36)}-${idCounter++}`;

type MutablePosition = { ticker: string; qty: number; avg: number; name: string };
type MutablePortfolio = {
  meta: PortfolioMeta;
  positions: Map<string, MutablePosition>;
};

const LS_PORTFOLIOS = "term-portfolios";
const LS_ACTIVE_PORTFOLIO = "term-active-portfolio";
const LS_WATCHLISTS = "term-watchlists";
const LS_ACTIVE_WATCHLIST = "term-active-watchlist";
const LS_DESKS = "term-desks";

const mockSource = (label: string): DataSourceState => ({ kind: "mock", label });
const unavailableSource = (label: string): DataSourceState => ({ kind: "unavailable", label });
const liveSource = (label: string, receivedAt?: string): DataSourceState => ({
  kind: "live",
  label,
  receivedAt,
});

const LOCAL_SCREEN_DATASETS: readonly TermdScreenDatasetMeta[] = [
  { key: "quotes", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "markets-overview", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "rates", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "fixed-income", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "fx", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "commodities", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "news", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "economic-events", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "recent-prints", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
  { key: "earnings", source: mockSource("LOCAL MOCK"), asOf: null, staleAfterMs: 0 },
];
const SCREEN_DATASET_KEYS = LOCAL_SCREEN_DATASETS.map((dataset) => dataset.key);

const unavailableScreenDatasets = (label: string): readonly TermdScreenDatasetMeta[] =>
  SCREEN_DATASET_KEYS.map((key) => ({
    key,
    source: unavailableSource(label),
    asOf: null,
    staleAfterMs: 0,
  }));

const unavailableQuote = (quote: Quote, source: DataSourceState): Quote => ({
  ...quote,
  last: 0,
  chg: 0,
  pct: 0,
  vol: "N/A",
  bid: 0,
  ask: 0,
  source: { ...source },
});

const unavailableNewsRows = (source: DataSourceState): readonly NewsItem[] => [
  {
    id: "news-unavailable",
    time: "--:--",
    src: "N/A",
    cat: "TOP",
    tone: "neutral",
    headline: "NEWS DATA UNAVAILABLE",
    body: [`${source.label} did not provide a news snapshot.`],
  },
];

const unavailableEventRows = (
  label: string,
  source: DataSourceState,
): readonly EventItem[] => [
  {
    time: "--:--",
    ccy: "N/A",
    imp: 1,
    label,
    fcst: "N/A",
    prev: "N/A",
    actual: "N/A",
    source: { ...source },
  },
];

const unavailableBondRows = (source: DataSourceState): readonly BondRow[] => [
  {
    issuer: "N/A",
    desc: "FIXED-INCOME DATA UNAVAILABLE",
    cpn: null,
    maturity: "N/A",
    px: null,
    ytm: null,
    oas: null,
    rating: "N/A",
    source: { ...source },
  },
];

const unavailableCdsRows = (source: DataSourceState): readonly CdsRow[] => [
  {
    name: "N/A",
    region: "CREDIT DATA UNAVAILABLE",
    rating: "N/A",
    px: null,
    chg: null,
    ytd: null,
    source: { ...source },
  },
];

const unavailableCreditIndexRows = (source: DataSourceState): readonly CreditIndexRow[] => [
  {
    name: "N/A",
    desc: "CREDIT INDEX DATA UNAVAILABLE",
    last: null,
    chg: null,
    ytd: null,
    source: { ...source },
  },
];

const unavailableCbRateRows = (source: DataSourceState): readonly CbRate[] =>
  CB_RATES.map((row) => ({
    ...row,
    rate: null,
    lastMove: "N/A",
    next: "N/A",
    bias: "HOLD",
    source: { ...source },
  }));

const unavailableYieldCurveRows = (source: DataSourceState): readonly YieldCurvePoint[] =>
  US_CURVE.map((point) => ({
    tenor: point.tenor,
    yld: null,
    source: { ...source },
  }));

const unavailableCrossFx = (): { ccys: readonly string[]; matrix: readonly (readonly (number | null)[])[] } => ({
  ccys: CROSS_CCYS,
  matrix: CROSS_CCYS.map((_, row) =>
    CROSS_CCYS.map((__, col) => (row === col ? 1 : null)),
  ),
});

const unavailableEarningsRows = (source: DataSourceState): readonly Earning[] => [
  {
    date: "N/A",
    whenStr: "N/A",
    symbol: "N/A",
    name: "EARNINGS DATA UNAVAILABLE",
    consensusEps: null,
    consensusRev: "N/A",
    prevEps: null,
    source: { ...source },
  },
];

const emptyResearchSnapshot = (symbol: string, source: DataSourceState): ResearchSnapshot => ({
  symbol,
  filings: [],
  insiderTrades: [],
  institutionalHoldings: [],
  source: { ...source },
  filingsSource: { ...source },
  insiderSource: { ...source },
  holdingsSource: { ...source },
});

const researchSource = (
  filings: readonly TermdFiling[],
  insiderTrades: readonly TermdInsiderTrade[],
  institutionalHoldings: readonly TermdInstitutionalHolding[],
): DataSourceState =>
  filings[0]?.source ??
  insiderTrades[0]?.source ??
  institutionalHoldings[0]?.source ??
  unavailableSource("TERMD research empty");

const firstSourceOrUnavailable = (
  rows: readonly { source?: DataSourceState }[],
  label: string,
): DataSourceState => rows[0]?.source ?? unavailableSource(label);

class BackendFirstDataProvider implements DataProvider {
  private readonly remoteConfig: TermdApiConfig | null;
  private readonly remoteClient: TermdApiClient | null;
  private readonly remoteSymbols = new Set<string>();

  private quotes = new Map<string, Quote>();
  private prevQuotes = new Map<string, Quote>();
  private quoteSubs = new Map<string, Set<(q: Quote) => void>>();
  private tradeSubs = new Map<string, Set<(t: Trade) => void>>();
  private tradeBuf = new Map<string, Trade[]>();
  private detailSubs = new Map<string, Set<() => void>>();
  private chartCache = new Map<string, number[]>();
  private depthCache = new Map<string, DepthBookData>();
  private optionChainCache = new Map<string, OptionChainData>();
  private optionSurfaceCache = new Map<string, TermdOptionSurface>();
  private detailSources = new Map<string, DataSourceState>();
  private pendingDetailNotifications = new Set<string>();
  private detailNotificationQueued = false;
  private remoteDetailLoads = new Set<string>();
  private macroSeries = new Map<string, TermdMacroSeries>();
  private macroSubs = new Set<() => void>();
  private newsSubs = new Set<() => void>();
  private rssFeedSubs = new Set<() => void>();
  private calendarSubs = new Set<() => void>();
  private predictionMarkets: readonly TermdPredictionMarket[] = [];
  private predictionSubs = new Set<() => void>();
  private researchCache = new Map<string, ResearchSnapshot>();
  private researchSubs = new Map<string, Set<() => void>>();
  private remoteResearchLoads = new Set<string>();
  private remoteNews: NewsItem[] | null = null;
  private remoteRssFeeds: readonly TermdRssFeed[] | null = null;
  private remotePositions: readonly Position[] | null = null;
  private remoteAlerts: readonly Alert[] | null = null;
  private remoteEvents: readonly EventItem[] | null = null;
  private remoteRecentPrints: readonly EventItem[] | null = null;
  private remoteEarnings: readonly Earning[] | null = null;
  private remoteHeatmap: readonly HeatmapCell[] | null = null;
  private remoteYieldCurve: readonly YieldCurvePoint[] | null = null;
  private remoteCbRates: readonly CbRate[] | null = null;
  private remoteBonds: readonly BondRow[] | null = null;
  private remoteCds: readonly CdsRow[] | null = null;
  private remoteCreditIndices: readonly CreditIndexRow[] | null = null;
  private fixedIncomeSubs = new Set<() => void>();
  private remoteCrossFx: { ccys: readonly string[]; matrix: readonly (readonly (number | null)[])[] } | null = null;
  private fxSubs = new Set<() => void>();
  private screenDatasets: readonly TermdScreenDatasetMeta[] = LOCAL_SCREEN_DATASETS;
  private screenDatasetSubs = new Set<() => void>();

  private portfolios = new Map<string, MutablePortfolio>();
  private activePortfolioId = "";
  private positionSubs = new Set<() => void>();
  private portfolioSubs = new Set<() => void>();

  private watchlists = new Map<string, StoredWatchlist>();
  private activeWatchlistId = "";
  private remoteWatchlists: Map<string, StoredWatchlist> | null = null;
  private remoteActiveWatchlistId = "";
  private watchlistSubs = new Set<() => void>();

  private desks = new Map<string, Desk>();
  private deskSubs = new Set<() => void>();

  private alerts: Alert[] = [];
  private alertSubs = new Set<(triggered?: Alert) => void>();

  private pauseSubs = new Set<(p: boolean) => void>();
  private paused = false;

  private tickHandle?: number;
  private remoteHandle?: number;
  private remoteQuoteStream?: TermdStream;
  private remoteNewsStream?: TermdStream;
  private remoteMacroStream?: TermdStream;
  private remotePredictionStream?: TermdStream;
  private remotePredictionStreamKey = "";
  private remoteDetailStreams = new Map<string, TermdStream>();
  private remoteDerivativeStreams = new Map<string, TermdStream>();
  private remoteQuoteTimers = new Map<string, number>();
  private remoteWarnings = new Set<string>();
  private remoteSuspendedUntil = 0;
  private remoteBootstrapPending = false;
  private remoteRefreshInFlight = false;
  private rand = lcg(Date.now() & 0xffffffff);

  constructor(remoteConfig: TermdApiConfig | null = readTermdApiConfig()) {
    this.remoteConfig = remoteConfig;
    this.remoteClient = createTermdApiClient(remoteConfig);
    if (this.remoteClient) {
      this.remoteBootstrapPending = true;
      this.screenDatasets = unavailableScreenDatasets("TERMD pending");
    }
    for (const symbol of remoteConfig?.symbols ?? []) this.remoteSymbols.add(symbol.toUpperCase());

    const all: Quote[] = [
      ...INDICES, ...WORLD_INDICES, ...FX, ...EM_FX, ...RATES, ...SECTORS,
      ...COMMODITIES, ...ENERGY, ...METALS, ...AGS, ...CRYPTO, ...WATCHLIST,
    ];
    for (const q of all) {
      if (!this.quotes.has(q.ticker)) {
        const source = this.remoteSymbols.has(q.ticker)
          ? unavailableSource("TERMD pending")
          : mockSource("LOCAL MOCK");
        this.quotes.set(q.ticker, { ...q, source });
      }
    }
    for (const [s, n] of HEATMAP_CONSTITUENTS) {
      if (!this.quotes.has(s)) {
        const seeded = lcg(seedFor(s));
        const last = +(20 + seeded() * 480).toFixed(2);
        const pct = HEATMAP_DEFAULT_PCT.get(s) ?? 0;
        const chg = +((last * pct) / 100).toFixed(2);
        this.quotes.set(s, {
          ticker: s, name: n, last, chg, pct, vol: "—",
          bid: +(last - 0.01).toFixed(2),
          ask: +(last + 0.01).toFixed(2),
          source: this.remoteSymbols.has(s)
            ? unavailableSource("TERMD pending")
            : mockSource("LOCAL MOCK"),
        });
      }
    }
    this.hydratePortfolios();
    this.hydrateWatchlists();
    this.hydrateDesks();
  }

  /* ── watchlists ───────────────────────────────────────── */

  private hydrateWatchlists(): void {
    try {
      const raw = localStorage.getItem(LS_WATCHLISTS);
      const activeRaw = localStorage.getItem(LS_ACTIVE_WATCHLIST);
      if (raw) {
        const stored = JSON.parse(raw) as StoredWatchlist[];
        if (Array.isArray(stored) && stored.length > 0) {
          for (const w of stored) this.watchlists.set(w.id, { ...w });
          this.activeWatchlistId =
            activeRaw && this.watchlists.has(activeRaw)
              ? activeRaw
              : (this.watchlists.keys().next().value as string);
          return;
        }
      }
    } catch {
      // fall through to seed
    }
    // Seed default watchlist from WATCHLIST array
    const seed: StoredWatchlist = {
      id: "wl-default",
      name: "Default",
      createdAt: Date.now(),
      symbols: WATCHLIST.map((q) => q.ticker),
    };
    this.watchlists.set(seed.id, seed);
    this.activeWatchlistId = seed.id;
    this.persistWatchlists();
  }

  private persistWatchlists(): void {
    try {
      const stored = Array.from(this.watchlists.values()) as StoredWatchlist[];
      localStorage.setItem(LS_WATCHLISTS, JSON.stringify(stored));
      localStorage.setItem(LS_ACTIVE_WATCHLIST, this.activeWatchlistId);
    } catch {}
  }

  listWatchlists(): readonly WatchlistMeta[] {
    return Array.from(this.currentWatchlists().values()).map(
      ({ symbols: _s, ...meta }) => meta,
    );
  }
  getActiveWatchlistId(): string {
    return this.remoteWatchlists ? this.remoteActiveWatchlistId : this.activeWatchlistId;
  }
  setActiveWatchlistId(id: string): void {
    if (this.remoteWatchlists) {
      if (!this.remoteWatchlists.has(id) || this.remoteActiveWatchlistId === id) return;
      this.remoteActiveWatchlistId = id;
      for (const cb of this.watchlistSubs) cb();
      return;
    }
    if (!this.watchlists.has(id) || this.activeWatchlistId === id) return;
    this.activeWatchlistId = id;
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
  }
  getWatchlistSymbols(id: string): readonly string[] {
    return this.currentWatchlists().get(id)?.symbols ?? [];
  }
  watchlistsAreReadOnly(): boolean {
    return this.remoteWatchlists !== null;
  }
  createWatchlist(name: string, symbols: readonly string[] = []): WatchlistMeta {
    if (this.remoteWatchlists) {
      return {
        id: this.remoteActiveWatchlistId,
        name: this.remoteWatchlists.get(this.remoteActiveWatchlistId)?.name ?? "Remote",
        createdAt: 0,
      };
    }
    const id = `wl-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const w: StoredWatchlist = {
      id,
      name: name.trim() || "Untitled",
      createdAt: Date.now(),
      symbols: [...symbols],
    };
    this.watchlists.set(id, w);
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
    return { id: w.id, name: w.name, createdAt: w.createdAt };
  }
  renameWatchlist(id: string, name: string): boolean {
    if (this.remoteWatchlists) return false;
    const w = this.watchlists.get(id);
    if (!w || !name.trim()) return false;
    w.name = name.trim();
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
    return true;
  }
  deleteWatchlist(id: string): boolean {
    if (this.remoteWatchlists) return false;
    if (this.watchlists.size <= 1) return false;
    if (!this.watchlists.has(id)) return false;
    this.watchlists.delete(id);
    if (this.activeWatchlistId === id) {
      this.activeWatchlistId = this.watchlists.keys().next().value as string;
    }
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
    return true;
  }
  addSymbolToWatchlist(id: string, symbol: string): boolean {
    if (this.remoteWatchlists) return false;
    const w = this.watchlists.get(id);
    if (!w) return false;
    const t = symbol.toUpperCase().trim();
    if (!t || w.symbols.includes(t)) return false;
    if (!this.quotes.has(t)) return false; // refuse unknown symbols
    w.symbols = [...w.symbols, t];
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
    return true;
  }
  removeSymbolFromWatchlist(id: string, symbol: string): boolean {
    if (this.remoteWatchlists) return false;
    const w = this.watchlists.get(id);
    if (!w) return false;
    const t = symbol.toUpperCase().trim();
    const next = w.symbols.filter((s) => s !== t);
    if (next.length === w.symbols.length) return false;
    w.symbols = next;
    this.persistWatchlists();
    for (const cb of this.watchlistSubs) cb();
    return true;
  }
  subscribeWatchlists(cb: () => void): () => void {
    this.watchlistSubs.add(cb);
    return () => { this.watchlistSubs.delete(cb); };
  }

  private currentWatchlists(): Map<string, StoredWatchlist> {
    return this.remoteWatchlists ?? this.watchlists;
  }

  /* ── desks ───────────────────────────────────────── */

  private hydrateDesks(): void {
    try {
      const raw = localStorage.getItem(LS_DESKS);
      if (raw) {
        const stored = JSON.parse(raw) as Desk[];
        if (Array.isArray(stored)) {
          for (const w of stored) this.desks.set(w.id, w);
        }
      }
    } catch {}
  }
  private persistDesks(): void {
    try {
      localStorage.setItem(
        LS_DESKS,
        JSON.stringify(Array.from(this.desks.values())),
      );
    } catch {}
  }
  listDesks(): readonly Desk[] {
    return Array.from(this.desks.values()).sort(
      (a, b) => a.createdAt - b.createdAt,
    );
  }
  saveDesk(name: string, snapshot: DeskSnapshot): Desk {
    const id = `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const ws: Desk = {
      id,
      name: name.trim() || "Untitled",
      createdAt: Date.now(),
      snapshot,
    };
    this.desks.set(id, ws);
    this.persistDesks();
    for (const cb of this.deskSubs) cb();
    return ws;
  }
  updateDesk(id: string, snapshot: DeskSnapshot): boolean {
    const w = this.desks.get(id);
    if (!w) return false;
    w.snapshot = snapshot;
    this.persistDesks();
    for (const cb of this.deskSubs) cb();
    return true;
  }
  renameDesk(id: string, name: string): boolean {
    const w = this.desks.get(id);
    if (!w || !name.trim()) return false;
    w.name = name.trim();
    this.persistDesks();
    for (const cb of this.deskSubs) cb();
    return true;
  }
  deleteDesk(id: string): boolean {
    if (!this.desks.has(id)) return false;
    this.desks.delete(id);
    this.persistDesks();
    for (const cb of this.deskSubs) cb();
    return true;
  }
  subscribeDesks(cb: () => void): () => void {
    this.deskSubs.add(cb);
    return () => { this.deskSubs.delete(cb); };
  }

  private hydratePortfolios(): void {
    try {
      const raw = localStorage.getItem(LS_PORTFOLIOS);
      const activeIdRaw = localStorage.getItem(LS_ACTIVE_PORTFOLIO);
      if (raw) {
        const stored = JSON.parse(raw) as StoredPortfolio[];
        if (Array.isArray(stored) && stored.length > 0) {
          for (const sp of stored) {
            const positions = new Map<string, MutablePosition>();
            for (const pos of sp.positions ?? []) {
              const q = this.quotes.get(pos.ticker);
              positions.set(pos.ticker, {
                ticker: pos.ticker,
                qty: pos.qty,
                avg: pos.avg,
                name: q?.name ?? pos.ticker,
              });
            }
            this.portfolios.set(sp.id, {
              meta: {
                id: sp.id,
                name: sp.name,
                cash: sp.cash,
                createdAt: sp.createdAt,
              },
              positions,
            });
          }
          this.activePortfolioId =
            activeIdRaw && this.portfolios.has(activeIdRaw)
              ? activeIdRaw
              : (this.portfolios.keys().next().value as string);
          return;
        }
      }
    } catch {
      // fall through to seed
    }
    // Seed default portfolio from data.ts POSITIONS so the first-run
    // experience is identical to what shipped before portfolios existed.
    const seed: MutablePortfolio = {
      meta: {
        id: "pa1",
        name: "PRIMARY PA1",
        cash: 124_842.18,
        createdAt: Date.now(),
      },
      positions: new Map(
        POSITIONS.map((p) => [
          p.ticker,
          { ticker: p.ticker, qty: p.qty, avg: p.avg, name: p.name },
        ]),
      ),
    };
    this.portfolios.set(seed.meta.id, seed);
    this.activePortfolioId = seed.meta.id;
    this.persistPortfolios();
  }

  private persistPortfolios(): void {
    try {
      const stored: StoredPortfolio[] = Array.from(
        this.portfolios.values(),
      ).map((p) => ({
        ...p.meta,
        positions: Array.from(p.positions.values()).map((pos) => ({
          ticker: pos.ticker,
          qty: pos.qty,
          avg: pos.avg,
        })),
      }));
      localStorage.setItem(LS_PORTFOLIOS, JSON.stringify(stored));
      localStorage.setItem(LS_ACTIVE_PORTFOLIO, this.activePortfolioId);
    } catch {
      // localStorage may be unavailable (private mode, quota, etc.) — best effort
    }
  }

  private activePortfolio(): MutablePortfolio | undefined {
    return this.portfolios.get(this.activePortfolioId);
  }

  start(): void {
    if (this.tickHandle != null) return;
    this.tickHandle = window.setInterval(() => this.tick(), 650);
    if (this.remoteClient && this.remoteHandle == null) {
      void this.refreshRemote();
      this.remoteHandle = window.setInterval(
        () => void this.refreshRemote(),
        this.remoteConfig?.pollMs ?? 5_000,
      );
    }
  }
  stop(): void {
    if (this.tickHandle != null) {
      window.clearInterval(this.tickHandle);
      this.tickHandle = undefined;
    }
    if (this.remoteHandle != null) {
      window.clearInterval(this.remoteHandle);
      this.remoteHandle = undefined;
    }
    this.remoteQuoteStream?.close();
    this.remoteQuoteStream = undefined;
    this.remoteNewsStream?.close();
    this.remoteNewsStream = undefined;
    this.remoteMacroStream?.close();
    this.remoteMacroStream = undefined;
    this.remotePredictionStream?.close();
    this.remotePredictionStream = undefined;
    this.remotePredictionStreamKey = "";
    this.closeRemoteDetailStreams();
    for (const timer of this.remoteQuoteTimers.values()) window.clearTimeout(timer);
    this.remoteQuoteTimers.clear();
  }

  isPaused() { return this.paused; }
  setPaused(p: boolean): void {
    if (this.paused === p) return;
    this.paused = p;
    for (const cb of this.pauseSubs) cb(p);
  }
  subscribePauseState(cb: (p: boolean) => void): () => void {
    this.pauseSubs.add(cb);
    return () => { this.pauseSubs.delete(cb); };
  }

  private tick(): void {
    if (this.paused) return;
    if (this.remoteClient) return;
    const symbols = Array.from(this.quotes.keys());
    const N = Math.max(4, Math.floor(symbols.length * 0.18));
    for (let i = 0; i < N; i++) {
      const sym = symbols[Math.floor(this.rand() * symbols.length)];
      if (this.remoteSymbols.has(sym)) continue;
      const q = this.quotes.get(sym);
      if (!q) continue;
      if (q.source?.kind !== "live") continue;
      const r = this.rand() - 0.5;
      const volBucket =
        q.last >= 1000 ? 0.0006 :
        q.last >= 100 ? 0.0009 :
        q.last >= 10 ? 0.0014 : 0.0022;
      const step = q.last * volBucket * r * 2;
      const digits = pxDigits(q.last);
      const newLast = +(q.last + step).toFixed(digits);
      if (newLast === q.last) continue;
      const prevOpen = q.last - q.chg;
      const newChg = +(newLast - prevOpen).toFixed(digits + 1);
      const newPct = prevOpen !== 0 ? +((newChg / prevOpen) * 100).toFixed(2) : 0;
      const spread = Math.max(0.01, q.last * 0.0001);
      const newQuote: Quote = {
        ...q,
        last: newLast,
        chg: newChg,
        pct: newPct,
        bid: +(newLast - spread).toFixed(digits),
        ask: +(newLast + spread).toFixed(digits),
      };
      this.prevQuotes.set(sym, q);
      this.quotes.set(sym, newQuote);
      const subs = this.quoteSubs.get(sym);
      if (subs) for (const cb of subs) cb(newQuote);

      // Trade tape
      const trade: Trade = {
        time: this.fmtTradeTime(),
        px: newLast,
        qty: 100 * (1 + Math.floor(this.rand() * 24)),
        side: step >= 0 ? "B" : "S",
      };
      let buf = this.tradeBuf.get(sym);
      if (!buf) {
        buf = [];
        this.tradeBuf.set(sym, buf);
      }
      buf.unshift(trade);
      if (buf.length > 200) buf.length = 200;
      const tSubs = this.tradeSubs.get(sym);
      if (tSubs) for (const cb of tSubs) cb(trade);

      // Check alerts
      this.processAlerts(sym, q.last, newLast);
      // Position re-mark for subscribers
      const active = this.activePortfolio();
      if (active && active.positions.has(sym)) this.broadcastPositions();
    }
  }

  private async refreshRemote(): Promise<void> {
    if (!this.remoteClient || !this.remoteConfig) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteRefreshInFlight) return;
    this.remoteRefreshInFlight = true;
    try {
      let screenFetchFailed = false;
      const screen = await this.remoteClient
        .fetchScreen("terminal", this.remoteConfig.symbols)
        .catch((error) => {
          this.warnRemote("screen", "termd screen snapshot fetch failed", error);
          screenFetchFailed = true;
          return null as TermdScreenSnapshot | null;
        });
      if (this.isRemoteSuspended()) return;
      if (screen) {
        this.remoteBootstrapPending = false;
        this.applyRemoteScreen(screen);
      } else {
        this.suspendRemote(screenFetchFailed ? "TERMD unavailable" : "TERMD screen unavailable");
        return;
      }
      if (this.isRemoteSuspended()) return;
      this.startRemoteQuoteStream();
      this.startRemoteNewsStream();
      this.startRemoteMacroStream();
      const venues = this.remoteConfig.predictionVenues;
      const [
        macroSeries,
        rssFeeds,
        userWatchlists,
        userPositions,
        userAlerts,
        ...venueResults
      ] = await Promise.all([
        this.remoteClient.fetchMacroSeries(this.remoteConfig.macroSeries).catch((error) => {
          this.warnRemote("macro", "termd macro series fetch failed", error);
          return [] as TermdMacroSeries[];
        }),
        this.remoteConfig.token
          ? this.remoteClient.fetchRssFeeds().catch((error) => {
              this.warnRemote("rss-feeds", "termd RSS feed read failed", error);
              return [] as TermdRssFeed[];
            })
          : Promise.resolve([] as TermdRssFeed[]),
        this.remoteConfig.token
          ? this.remoteClient.fetchWatchlists().catch((error) => {
              this.warnRemote("watchlists", "termd watchlists read failed", error);
              return null as TermdWatchlist[] | null;
            })
          : Promise.resolve(null as TermdWatchlist[] | null),
        this.remoteConfig.token
          ? this.remoteClient.fetchPositions().catch((error) => {
              this.warnRemote("positions", "termd positions read failed", error);
              return null as TermdUserPosition[] | null;
            })
          : Promise.resolve(null as TermdUserPosition[] | null),
        this.remoteConfig.token
          ? this.remoteClient.fetchAlerts().catch((error) => {
              this.warnRemote("alerts", "termd alerts read failed", error);
              return null as TermdUserAlert[] | null;
            })
          : Promise.resolve(null as TermdUserAlert[] | null),
        ...venues.map((venue) =>
          this.remoteClient!.fetchPredictionMarkets(venue).catch((error) => {
            this.warnRemote(`prediction:${venue}`, `termd prediction fetch failed for venue=${venue}`, error);
            return [] as TermdPredictionMarket[];
          }),
        ),
      ]);
      for (const series of macroSeries) this.applyRemoteMacroSeries(series);
      if (this.remoteConfig.token || this.remoteRssFeeds === null) {
        this.applyRemoteRssFeeds(rssFeeds);
      }
      if (userWatchlists) this.applyRemoteWatchlists(userWatchlists);
      if (userPositions) this.applyRemoteUserPositions(userPositions);
      if (userAlerts) this.applyRemoteUserAlerts(userAlerts);
      const predictionMarkets = (venueResults as TermdPredictionMarket[][])
        .flat();
      if (predictionMarkets.length > 0) {
        this.applyRemotePredictionMarkets(predictionMarkets);
        this.startRemotePredictionStream(predictionMarkets);
      }
    } catch (error) {
      this.warnRemote("refresh", "termd backend refresh failed", error);
    } finally {
      this.remoteRefreshInFlight = false;
    }
  }

  private startRemoteQuoteStream(): void {
    if (!this.remoteClient || !this.remoteConfig || this.remoteQuoteStream) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteBootstrapPending) return;
    this.remoteQuoteStream = this.remoteClient.streamQuotes(this.remoteConfig.symbols, {
      onQuote: (quote) => this.scheduleRemoteQuote(quote),
      onError: (error) => this.warnRemote("quote-stream", "termd backend quote stream failed", error),
      onClose: () => {
        this.remoteQuoteStream = undefined;
      },
    }) ?? undefined;
  }

  private startRemoteNewsStream(): void {
    if (!this.remoteClient || !this.remoteConfig || this.remoteNewsStream) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteBootstrapPending) return;
    this.remoteNewsStream = this.remoteClient.streamNews({
      onNews: (item) => this.applyRemoteNewsDelta(item),
      onError: (error) => this.warnRemote("news-stream", "termd backend news stream failed", error),
      onClose: () => {
        this.remoteNewsStream = undefined;
      },
    }, this.remoteConfig.symbols) ?? undefined;
  }

  private startRemoteMacroStream(): void {
    if (!this.remoteClient || !this.remoteConfig || this.remoteMacroStream) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteBootstrapPending) return;
    this.remoteMacroStream = this.remoteClient.streamMacroSeries(this.remoteConfig.macroSeries, {
      onSeries: (series) => this.applyRemoteMacroSeries(series),
      onPoint: (point) => this.applyRemoteMacroPoint(point),
      onError: (error) => this.warnRemote("macro-stream", "termd backend macro stream failed", error),
      onClose: () => {
        this.remoteMacroStream = undefined;
      },
    }) ?? undefined;
  }

  private startRemoteDetailStream(symbol: string): void {
    if (!this.remoteClient || this.remoteDetailStreams.has(symbol)) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteBootstrapPending) return;
    const assetClass = termdAssetClassForSymbol(symbol);
    const stream = this.remoteClient.streamDetails(symbol, {
      onChart: (snapshot, frame) =>
        this.applyRemoteChartUpdate(symbol, snapshot, frame.frameType === "snapshot"),
      onDepth: (snapshot) => this.applyRemoteDepthDelta(symbol, snapshot),
      onTrade: (snapshot) => this.applyRemoteTradeDelta(symbol, snapshot),
      onError: (error) =>
        this.warnRemote(`detail-stream:${symbol}`, `termd backend detail stream failed for ${symbol}`, error),
      onClose: () => {
        this.remoteDetailStreams.delete(symbol);
      },
    }, assetClass);
    if (stream) this.remoteDetailStreams.set(symbol, stream);
  }

  private startRemoteDerivativeStream(symbol: string): void {
    if (!this.remoteClient || this.remoteDerivativeStreams.has(symbol)) return;
    if (this.isRemoteSuspended()) return;
    if (this.remoteBootstrapPending) return;
    const assetClass = termdAssetClassForSymbol(symbol);
    const stream = this.remoteClient.streamDerivatives(symbol, {
      onOptions: (snapshot) => this.applyRemoteOptionChainSnapshot(symbol, snapshot),
      onVolSurface: (snapshot) => this.applyRemoteOptionSurfaceSnapshot(symbol, snapshot),
      onError: (error) =>
        this.warnRemote(`derivative-stream:${symbol}`, `termd backend derivative stream failed for ${symbol}`, error),
      onClose: () => {
        this.remoteDerivativeStreams.delete(symbol);
      },
    }, assetClass);
    if (stream) this.remoteDerivativeStreams.set(symbol, stream);
  }

  private startRemotePredictionStream(markets: readonly TermdPredictionMarket[]): void {
    if (!this.remoteClient || this.isRemoteSuspended() || this.remoteBootstrapPending) return;
    const channels = termdPredictionChannels(markets);
    const key = channels.slice().sort().join("|");
    if (channels.length === 0) return;
    if (this.remotePredictionStream && this.remotePredictionStreamKey === key) return;
    this.remotePredictionStream?.close();
    this.remotePredictionStream = undefined;
    this.remotePredictionStreamKey = "";
    const stream = this.remoteClient.streamPredictionMarkets(markets, {
      onMarket: (market) => this.applyRemotePredictionMarketDelta(market),
      onError: (error) =>
        this.warnRemote("prediction-stream", "termd backend prediction stream failed", error),
      onClose: () => {
        this.remotePredictionStream = undefined;
        this.remotePredictionStreamKey = "";
      },
    });
    if (stream) {
      this.remotePredictionStream = stream;
      this.remotePredictionStreamKey = key;
    }
  }

  private warnRemote(key: string, message: string, error: unknown): void {
    if (this.remoteWarnings.has(key)) return;
    this.remoteWarnings.add(key);
    console.warn(message, error);
  }

  private isRemoteSuspended(): boolean {
    return Date.now() < this.remoteSuspendedUntil;
  }

  private suspendRemote(label: string, durationMs = 30_000): void {
    this.remoteBootstrapPending = true;
    this.remoteSuspendedUntil = Date.now() + durationMs;
    this.screenDatasets = unavailableScreenDatasets(label);
    for (const cb of this.screenDatasetSubs) cb();
    this.remoteQuoteStream?.close();
    this.remoteQuoteStream = undefined;
    this.remoteNewsStream?.close();
    this.remoteNewsStream = undefined;
    this.remoteMacroStream?.close();
    this.remoteMacroStream = undefined;
    this.remotePredictionStream?.close();
    this.remotePredictionStream = undefined;
    this.remotePredictionStreamKey = "";
    this.closeRemoteDetailStreams();
    for (const timer of this.remoteQuoteTimers.values()) window.clearTimeout(timer);
    this.remoteQuoteTimers.clear();
  }

  private closeRemoteDetailStreams(): void {
    for (const stream of this.remoteDetailStreams.values()) stream.close();
    this.remoteDetailStreams.clear();
    for (const stream of this.remoteDerivativeStreams.values()) stream.close();
    this.remoteDerivativeStreams.clear();
  }

  private scheduleRemoteQuotes(quotes: readonly Quote[]): void {
    quotes.forEach((quote, index) => this.scheduleRemoteQuote(quote, index));
  }

  private scheduleRemoteQuote(quote: Quote, index = 0): void {
    const sym = quote.ticker.toUpperCase();
    const existing = this.remoteQuoteTimers.get(sym);
    if (existing != null) window.clearTimeout(existing);
    const delayMs = index * 55 + (seedFor(sym) % 35);
    const timer = window.setTimeout(() => {
      this.remoteQuoteTimers.delete(sym);
      this.applyRemoteQuote(quote);
    }, delayMs);
    this.remoteQuoteTimers.set(sym, timer);
  }

  private applyRemoteQuote(quote: Quote): void {
    const sym = quote.ticker.toUpperCase();
    const previous = this.quotes.get(sym);
    const previousLast = previous?.last ?? quote.last;
    const chg = +(quote.last - previousLast).toFixed(pxDigits(quote.last) + 1);
    const pct = previousLast > 0 ? +((chg / previousLast) * 100).toFixed(2) : 0;
    const next: Quote = {
      ...quote,
      ticker: sym,
      name: previous?.name ?? quote.name,
      chg,
      pct,
      source: quote.source ?? liveSource("TERMD"),
    };
    if (previous) this.prevQuotes.set(sym, previous);
    this.quotes.set(sym, next);
    const subs = this.quoteSubs.get(sym);
    if (subs) for (const cb of subs) cb(next);
    const active = this.activePortfolio();
    if (active && active.positions.has(sym)) this.broadcastPositions();
  }

  private applyRemoteMacroSeries(series: TermdMacroSeries): void {
    this.macroSeries.set(series.id, series);
    if (series.id === FRED_10Y_SERIES_ID) {
      this.applyRemoteYieldQuote(USD_10Y_QUOTE_SYMBOL, series);
    }
    for (const cb of this.macroSubs) cb();
  }

  private applyRemoteMacroPoint(point: TermdMacroPoint): void {
    const current = this.macroSeries.get(point.id);
    const points = current
      ? [
          ...current.points.filter((existing) => existing.time !== point.time),
          point,
        ].sort((left, right) => left.time.localeCompare(right.time))
      : [point];
    this.applyRemoteMacroSeries({ id: point.id, points });
  }

  private applyRemoteNews(news: readonly NewsItem[]): void {
    this.remoteNews = news.slice();
    for (const cb of this.newsSubs) cb();
  }

  private applyRemoteNewsDelta(item: NewsItem): void {
    const existing = this.remoteNews ?? [];
    this.remoteNews = [item, ...existing.filter((current) => current.id !== item.id)].slice(0, 100);
    for (const cb of this.newsSubs) cb();
  }

  private applyRemoteRssFeeds(feeds: readonly TermdRssFeed[]): void {
    const next = feeds.map((feed) => ({
      ...feed,
      categories: [...feed.categories],
      manualSymbols: [...feed.manualSymbols],
    }));
    this.remoteRssFeeds = next;
    for (const cb of this.rssFeedSubs) cb();
  }

  private applyRemoteWatchlists(watchlists: readonly TermdWatchlist[]): void {
    const next = new Map<string, StoredWatchlist>();
    for (const watchlist of watchlists) {
      next.set(watchlist.id, {
        id: watchlist.id,
        name: watchlist.name,
        createdAt: 0,
        symbols: watchlist.symbols.map((symbol) => normalizeSymbol(symbol)),
      });
      for (const symbol of watchlist.symbols) {
        const normalized = normalizeSymbol(symbol);
        if (!this.quotes.has(normalized)) {
          this.quotes.set(normalized, {
            ticker: normalized,
            name: normalized,
            last: 0,
            chg: 0,
            pct: 0,
            vol: "N/A",
            bid: 0,
            ask: 0,
            source: unavailableSource("TERMD pending"),
          });
        }
      }
    }
    if (next.size === 0) return;
    this.remoteWatchlists = next;
    if (!this.remoteActiveWatchlistId || !next.has(this.remoteActiveWatchlistId)) {
      this.remoteActiveWatchlistId = next.keys().next().value as string;
    }
    for (const cb of this.watchlistSubs) cb();
  }

  private applyRemoteUserPositions(positions: readonly TermdUserPosition[]): void {
    const next = positions.map((position) => this.remotePositionToUi(position));
    const grossMv = next.reduce((sum, position) => sum + Math.abs(position.mv), 0);
    if (grossMv > 0) {
      for (const position of next) position.wgt = (Math.abs(position.mv) / grossMv) * 100;
    }
    this.remotePositions = next;
    this.broadcastPositions();
  }

  private remotePositionToUi(position: TermdUserPosition): Position {
    const symbol = normalizeSymbol(position.symbol);
    const quote = this.quotes.get(symbol);
    const mark = position.marketPx > 0 ? position.marketPx : quote?.last ?? position.avgPx;
    const mv = mark * position.qty;
    const pl = (mark - position.avgPx) * position.qty;
    const plPct = position.avgPx > 0 ? ((mark - position.avgPx) / position.avgPx) * 100 : 0;
    return {
      ticker: symbol,
      name: quote?.name ?? symbol,
      qty: position.qty,
      avg: position.avgPx,
      mark,
      mv,
      pl,
      plPct,
      wgt: 0,
      source: liveSource("TERMD"),
    };
  }

  private applyRemoteUserAlerts(alerts: readonly TermdUserAlert[]): void {
    this.remoteAlerts = alerts.map((alert) => ({
      id: alert.id,
      symbol: alert.symbol,
      level: alert.threshold,
      condition: alert.condition,
      status: alert.active ? "ACTIVE" : "CANCELLED",
      createdAt: 0,
      source: liveSource("TERMD"),
    }));
    for (const cb of this.alertSubs) cb();
  }

  private applyRemoteScreen(screen: TermdScreenSnapshot): void {
    this.screenDatasets = screen.datasets.map((dataset) => ({
      ...dataset,
      source: { ...dataset.source },
    }));
    for (const cb of this.screenDatasetSubs) cb();
    if (screen.marketsOverview) this.applyRemoteMarketsOverview(screen.marketsOverview);
    if (screen.quotes.length > 0) this.scheduleRemoteQuotes(screen.quotes);
    if (screen.news.length > 0) this.applyRemoteNews(screen.news);
    if (screen.economicCalendar) this.applyRemoteEconomicCalendar(screen.economicCalendar);
    if (screen.earnings.length > 0) this.applyRemoteEarnings(screen.earnings);
    if (screen.rates) this.applyRemoteRates(screen.rates);
    if (screen.fixedIncome) this.applyRemoteFixedIncome(screen.fixedIncome);
    if (screen.fx) this.applyRemoteFx(screen.fx);
    if (screen.commodities) this.applyRemoteCommodities(screen.commodities);
    for (const sym of this.researchSubs.keys()) this.ensureRemoteResearch(sym);
  }

  private applyRemoteEconomicCalendar(calendar: TermdEconomicCalendarSnapshot): void {
    this.remoteEvents = calendar.events.map((row) => ({ ...row }));
    this.remoteRecentPrints = calendar.recentPrints.map((row) => ({ ...row }));
    for (const cb of this.calendarSubs) cb();
  }

  private applyRemoteEarnings(earnings: readonly Earning[]): void {
    this.remoteEarnings = earnings.map((row) => ({ ...row }));
    for (const cb of this.calendarSubs) cb();
  }

  private applyRemoteMarketsOverview(overview: TermdMarketsOverview): void {
    this.remoteHeatmap = overview.cells.map((cell) => ({ ...cell }));
    this.scheduleRemoteQuotes(overview.quotes);
  }

  private applyRemoteRates(rates: TermdRatesSnapshot): void {
    this.remoteYieldCurve = rates.curve.map((point) => ({ ...point }));
    this.remoteCbRates = rates.policyRates.map((row) => ({ ...row }));
    this.scheduleRemoteQuotes(
      rates.curve
        .map((point) => this.remoteYieldPointToQuote(point))
        .filter((quote): quote is Quote => quote !== null),
    );
    for (const cb of this.macroSubs) cb();
  }

  private applyRemoteFixedIncome(snapshot: TermdFixedIncomeSnapshot): void {
    this.remoteBonds = snapshot.bonds.map((row) => ({ ...row }));
    this.remoteCds = snapshot.cds.map((row) => ({ ...row }));
    this.remoteCreditIndices = snapshot.indices.map((row) => ({ ...row }));
    for (const cb of this.fixedIncomeSubs) cb();
  }

  private applyRemoteFx(snapshot: TermdFxSnapshot): void {
    this.remoteCrossFx = {
      ccys: snapshot.ccys.slice(),
      matrix: snapshot.matrix.map((row) => row.slice()),
    };
    this.scheduleRemoteQuotes(snapshot.quotes);
    for (const cb of this.fxSubs) cb();
  }

  private applyRemoteCommodities(snapshot: TermdCommoditiesSnapshot): void {
    const seen = new Set<string>();
    const quotes = [
      ...snapshot.frontMonths,
      ...snapshot.energy,
      ...snapshot.metals,
      ...snapshot.ags,
    ].filter((quote) => {
      const symbol = quote.ticker.toUpperCase();
      if (seen.has(symbol)) return false;
      seen.add(symbol);
      return true;
    });
    this.scheduleRemoteQuotes(quotes);
  }

  private applyRemoteChartUpdate(
    symbol: string,
    snapshot: TermdChartSnapshot,
    replace: boolean,
  ): void {
    const sym = normalizeSymbol(symbol);
    if (snapshot.data.length === 0) {
      this.setDetailSource("chart", sym, snapshot.source);
      return;
    }

    const prefix = `${sym}:`;
    const keys = Array.from(this.chartCache.keys()).filter((key) => key.startsWith(prefix));
    const targets = keys.length > 0 ? keys : [chartKey(sym, 180)];
    for (const key of targets) {
      const pointCount = Number(key.slice(prefix.length));
      const limit = Number.isFinite(pointCount) && pointCount > 0 ? pointCount : 180;
      const existing = this.chartCache.get(key) ?? [];
      const next = replace
        ? snapshot.data.slice(-limit)
        : [...existing, ...snapshot.data].slice(-limit);
      this.chartCache.set(key, next);
    }
    this.setDetailSource("chart", sym, snapshot.source);
    this.notifyDetailData(sym);
  }

  private applyRemoteDepthDelta(symbol: string, snapshot: TermdDepthSnapshot): void {
    const sym = normalizeSymbol(symbol);
    if (snapshot.data.bids.length === 0 || snapshot.data.asks.length === 0) {
      this.setDetailSource("depth", sym, snapshot.source);
      return;
    }
    this.depthCache.set(sym, snapshot.data);
    this.setDetailSource("depth", sym, snapshot.source);
    this.notifyDetailData(sym);
  }

  private applyRemoteTradeDelta(symbol: string, snapshot: TermdTradeSnapshot): void {
    const sym = normalizeSymbol(symbol);
    let buf = this.tradeBuf.get(sym);
    if (!buf) {
      buf = [];
      this.tradeBuf.set(sym, buf);
    }
    const existing = buf[0];
    if (
      existing?.time === snapshot.data.time &&
      existing.px === snapshot.data.px &&
      existing.qty === snapshot.data.qty &&
      existing.side === snapshot.data.side
    ) {
      return;
    }
    buf.unshift(snapshot.data);
    if (buf.length > 200) buf.length = 200;
    this.setDetailSource("trades", sym, snapshot.source);
    const subs = this.tradeSubs.get(sym);
    if (subs) for (const cb of subs) cb(snapshot.data);
    this.notifyDetailData(sym);
  }

  private applyRemoteOptionChainSnapshot(
    symbol: string,
    snapshot: TermdOptionChainSnapshot,
  ): void {
    const sym = normalizeSymbol(symbol);
    if (snapshot.data.rows.length === 0) {
      this.setDetailSource("options", sym, snapshot.source);
      return;
    }
    this.optionChainCache.set(optionChainKey(sym, snapshot.data.expiry), snapshot.data);
    this.setDetailSource("options", sym, snapshot.source);
    this.notifyDetailData(sym);
  }

  private applyRemoteOptionSurfaceSnapshot(
    symbol: string,
    snapshot: TermdOptionSurfaceSnapshot,
  ): void {
    const sym = normalizeSymbol(symbol);
    if (snapshot.data.expiries.length === 0 || snapshot.data.strikes.length === 0) {
      this.setDetailSource("vol-surface", sym, snapshot.source);
      return;
    }
    this.optionSurfaceCache.set(sym, snapshot.data);
    this.setDetailSource("vol-surface", sym, snapshot.source);
    this.notifyDetailData(sym);
  }

  private ensureRemoteChart(symbol: string, points: number): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.markDetailUnavailable("chart", sym);
      return;
    }
    this.startRemoteDetailStream(sym);
    const key = chartKey(sym, points);
    if (this.chartCache.has(key) || this.remoteDetailLoads.has(`chart:${key}`)) return;
    this.markDetailPending("chart", sym);
    this.remoteDetailLoads.add(`chart:${key}`);
    void this.remoteClient.fetchChart(sym, points)
      .then((snapshot: TermdChartSnapshot | null) => {
        if (!snapshot) {
          this.markDetailUnavailable("chart", sym);
          return;
        }
        if (snapshot.data.length === 0) {
          this.setDetailSource("chart", sym, snapshot.source);
          return;
        }
        this.chartCache.set(key, snapshot.data.slice());
        this.setDetailSource("chart", sym, snapshot.source);
        this.notifyDetailData(sym);
      })
      .catch((error) => {
        this.markDetailUnavailable("chart", sym);
        this.warnRemote(`chart:${sym}`, "termd backend chart fetch failed", error);
      })
      .finally(() => this.remoteDetailLoads.delete(`chart:${key}`));
  }

  private ensureRemoteDepth(symbol: string): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.markDetailUnavailable("depth", sym);
      return;
    }
    this.startRemoteDetailStream(sym);
    if (this.depthCache.has(sym) || this.remoteDetailLoads.has(`depth:${sym}`)) return;
    this.markDetailPending("depth", sym);
    this.remoteDetailLoads.add(`depth:${sym}`);
    void this.remoteClient.fetchDepth(sym)
      .then((snapshot: TermdDepthSnapshot | null) => {
        if (!snapshot) {
          this.markDetailUnavailable("depth", sym);
          return;
        }
        if (snapshot.data.bids.length === 0 || snapshot.data.asks.length === 0) {
          this.setDetailSource("depth", sym, snapshot.source);
          return;
        }
        this.depthCache.set(sym, snapshot.data);
        this.setDetailSource("depth", sym, snapshot.source);
        this.notifyDetailData(sym);
      })
      .catch((error) => {
        this.markDetailUnavailable("depth", sym);
        this.warnRemote(`depth:${sym}`, "termd backend depth fetch failed", error);
      })
      .finally(() => this.remoteDetailLoads.delete(`depth:${sym}`));
  }

  private ensureRemoteTrades(symbol: string, max: number): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.markDetailUnavailable("trades", sym);
      return;
    }
    this.startRemoteDetailStream(sym);
    if (this.tradeBuf.has(sym) || this.remoteDetailLoads.has(`trades:${sym}:${max}`)) return;
    this.markDetailPending("trades", sym);
    this.remoteDetailLoads.add(`trades:${sym}:${max}`);
    void this.remoteClient.fetchTrades(sym, max)
      .then((snapshot: TermdTradesSnapshot | null) => {
        if (!snapshot) {
          this.markDetailUnavailable("trades", sym);
          return;
        }
        if (snapshot.data.length === 0) {
          this.setDetailSource("trades", sym, snapshot.source);
          return;
        }
        const trades = snapshot.data.slice(0, Math.max(max, 200));
        this.tradeBuf.set(sym, trades);
        this.setDetailSource("trades", sym, snapshot.source);
        const subs = this.tradeSubs.get(sym);
        if (subs) for (const cb of subs) cb(trades[0]);
        this.notifyDetailData(sym);
      })
      .catch((error) => {
        this.markDetailUnavailable("trades", sym);
        this.warnRemote(`trades:${sym}`, "termd backend trades fetch failed", error);
      })
      .finally(() => this.remoteDetailLoads.delete(`trades:${sym}:${max}`));
  }

  private ensureRemoteOptionChain(symbol: string, expiry: string): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.markDetailUnavailable("options", sym);
      return;
    }
    this.startRemoteDerivativeStream(sym);
    const key = optionChainKey(sym, expiry);
    if (this.optionChainCache.has(key) || this.remoteDetailLoads.has(`options:${key}`)) return;
    this.markDetailPending("options", sym);
    this.remoteDetailLoads.add(`options:${key}`);
    void this.remoteClient.fetchOptionChain(sym, expiry)
      .then((snapshot: TermdOptionChainSnapshot | null) => {
        if (!snapshot) {
          this.markDetailUnavailable("options", sym);
          return;
        }
        this.applyRemoteOptionChainSnapshot(sym, snapshot);
      })
      .catch((error) => {
        this.markDetailUnavailable("options", sym);
        this.warnRemote(`options:${key}`, "termd backend options fetch failed", error);
      })
      .finally(() => this.remoteDetailLoads.delete(`options:${key}`));
  }

  private ensureRemoteOptionSurface(symbol: string): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.markDetailUnavailable("vol-surface", sym);
      return;
    }
    this.startRemoteDerivativeStream(sym);
    if (this.optionSurfaceCache.has(sym) || this.remoteDetailLoads.has(`surface:${sym}`)) return;
    this.markDetailPending("vol-surface", sym);
    this.remoteDetailLoads.add(`surface:${sym}`);
    void this.remoteClient.fetchOptionSurface(sym)
      .then((snapshot: TermdOptionSurfaceSnapshot | null) => {
        if (!snapshot) {
          this.markDetailUnavailable("vol-surface", sym);
          return;
        }
        this.applyRemoteOptionSurfaceSnapshot(sym, snapshot);
      })
      .catch((error) => {
        this.markDetailUnavailable("vol-surface", sym);
        this.warnRemote(`vol-surface:${sym}`, "termd backend vol-surface fetch failed", error);
      })
      .finally(() => this.remoteDetailLoads.delete(`surface:${sym}`));
  }

  private ensureRemoteResearch(symbol: string): void {
    if (!this.remoteClient) return;
    const sym = normalizeSymbol(symbol);
    const cached = this.researchCache.get(sym);
    const pending = cached?.source.kind === "unavailable" && cached.source.label === "TERMD pending";
    if ((cached && !pending) || this.remoteResearchLoads.has(sym)) return;
    if (this.remoteBootstrapPending || this.isRemoteSuspended()) {
      this.researchCache.set(
        sym,
        emptyResearchSnapshot(sym, unavailableSource("TERMD pending")),
      );
      return;
    }
    this.remoteResearchLoads.add(sym);
    this.researchCache.set(sym, emptyResearchSnapshot(sym, unavailableSource("TERMD pending")));
    const client = this.remoteClient;
    void Promise.all([
      client.fetchFilings({ symbol: sym }).catch((error) => {
        this.warnRemote(`filings:${sym}`, "termd backend filings fetch failed", error);
        return [] as TermdFiling[];
      }),
      client.fetchInsiderTrades(sym, { limit: 8 }).catch((error) => {
        this.warnRemote(`insider:${sym}`, "termd backend insider fetch failed", error);
        return [] as TermdInsiderTrade[];
      }),
      client.fetchInstitutionalHoldings({ symbol: sym, limit: 8 }).catch((error) => {
        this.warnRemote(`holdings:13f:${sym}`, "termd backend 13F fetch failed", error);
        return [] as TermdInstitutionalHolding[];
      }),
    ])
      .then(([filings, insiderTrades, institutionalHoldings]) => {
        const symbolFilings = filings.slice(0, 8);
        const symbolInsiderTrades = insiderTrades.slice(0, 8);
        const symbolInstitutionalHoldings = institutionalHoldings.slice(0, 8);
        const snapshot: ResearchSnapshot = {
          symbol: sym,
          filings: symbolFilings,
          insiderTrades: symbolInsiderTrades,
          institutionalHoldings: symbolInstitutionalHoldings,
          source: researchSource(symbolFilings, symbolInsiderTrades, symbolInstitutionalHoldings),
          filingsSource: firstSourceOrUnavailable(symbolFilings, "TERMD filings empty"),
          insiderSource: firstSourceOrUnavailable(symbolInsiderTrades, "TERMD insider empty"),
          holdingsSource: firstSourceOrUnavailable(
            symbolInstitutionalHoldings,
            "13F symbol mapping unavailable",
          ),
        };
        this.researchCache.set(sym, snapshot);
        this.notifyResearch(sym);
      })
      .catch((error) => {
        this.researchCache.set(
          sym,
          emptyResearchSnapshot(sym, unavailableSource("TERMD research unavailable")),
        );
        this.warnRemote(`research:${sym}`, "termd backend research fetch failed", error);
        this.notifyResearch(sym);
      })
      .finally(() => this.remoteResearchLoads.delete(sym));
  }

  private notifyResearch(symbol: string): void {
    const subs = this.researchSubs.get(normalizeSymbol(symbol));
    if (subs) for (const cb of subs) cb();
  }

  private markDetailPending(kind: DetailDataset, symbol: string): void {
    this.setDetailSource(kind, symbol, unavailableSource("TERMD pending"));
  }

  private markDetailUnavailable(
    kind: DetailDataset,
    symbol: string,
    label = "TERMD unavailable",
  ): void {
    this.setDetailSource(kind, symbol, unavailableSource(label));
  }

  private setDetailSource(kind: DetailDataset, symbol: string, source: DataSourceState): void {
    const sym = normalizeSymbol(symbol);
    const key = detailSourceKey(kind, sym);
    const previous = this.detailSources.get(key);
    if (
      previous?.kind === source.kind &&
      previous.label === source.label &&
      previous.receivedAt === source.receivedAt
    ) {
      return;
    }
    this.detailSources.set(key, source);
    this.notifyDetailData(sym);
  }

  private notifyDetailData(symbol: string): void {
    this.pendingDetailNotifications.add(normalizeSymbol(symbol));
    if (this.detailNotificationQueued) return;
    this.detailNotificationQueued = true;
    queueMicrotask(() => {
      this.detailNotificationQueued = false;
      const symbols = Array.from(this.pendingDetailNotifications);
      this.pendingDetailNotifications.clear();
      for (const sym of symbols) {
        const subs = this.detailSubs.get(sym);
        if (subs) for (const cb of subs) cb();
      }
    });
  }

  private applyRemotePredictionMarkets(markets: readonly TermdPredictionMarket[]): void {
    this.predictionMarkets = markets.slice();
    for (const cb of this.predictionSubs) cb();
  }

  private applyRemotePredictionMarketDelta(market: TermdPredictionMarket): void {
    const key = predictionMarketKey(market);
    let replaced = false;
    const next = this.predictionMarkets.map((current) => {
      if (predictionMarketKey(current) !== key) return current;
      replaced = true;
      return market;
    });
    this.predictionMarkets = replaced ? next : [market, ...this.predictionMarkets];
    for (const cb of this.predictionSubs) cb();
  }

  private applyRemoteYieldQuote(symbol: string, series: TermdMacroSeries): void {
    const latest = latestMacroPoint(series);
    if (!latest) return;
    const previousPoint = previousMacroPoint(series);
    const previous = this.quotes.get(symbol);
    const fallback = RATES.find((quote) => quote.ticker === symbol);
    const priorLast = previousPoint?.value ?? previous?.last ?? latest.value;
    const chg = +(latest.value - priorLast).toFixed(3);
    const pct = priorLast > 0 ? +((chg / priorLast) * 100).toFixed(2) : 0;
    const next: Quote = {
      ...(fallback ?? previous ?? {
        ticker: symbol,
        name: symbol,
        last: latest.value,
        chg: 0,
        pct: 0,
        vol: "-",
        bid: latest.value,
        ask: latest.value,
      }),
      ticker: symbol,
      last: +latest.value.toFixed(3),
      chg,
      pct,
      vol: latest.time.slice(0, 10),
      bid: +(latest.value - 0.001).toFixed(3),
      ask: +(latest.value + 0.001).toFixed(3),
      source: liveSource(latest.source.toUpperCase(), latest.time),
    };
    if (previous) this.prevQuotes.set(symbol, previous);
    this.quotes.set(symbol, next);
    const subs = this.quoteSubs.get(symbol);
    if (subs) for (const cb of subs) cb(next);
  }

  private remoteYieldPointToQuote(point: YieldCurvePoint): Quote | null {
    if (point.yld === null) return null;
    const symbol = RATE_TENOR_TO_SYMBOL.get(point.tenor);
    if (!symbol) return null;
    const previous = this.quotes.get(symbol);
    const fallback = RATES.find((quote) => quote.ticker === symbol);
    const source = point.source ?? liveSource("TERMD");
    const last = +point.yld.toFixed(3);
    return {
      ...(fallback ?? previous ?? {
        ticker: symbol,
        name: `${point.tenor} YIELD`,
        last,
        chg: 0,
        pct: 0,
        vol: "-",
        bid: last,
        ask: last,
      }),
      ticker: symbol,
      last,
      chg: 0,
      pct: 0,
      vol: source.receivedAt ? source.receivedAt.slice(0, 10) : "-",
      bid: +(last - 0.001).toFixed(3),
      ask: +(last + 0.001).toFixed(3),
      source,
    };
  }

  private fmtTradeTime(): string {
    const d = new Date();
    return (
      String(d.getHours()).padStart(2, "0") + ":" +
      String(d.getMinutes()).padStart(2, "0") + ":" +
      String(d.getSeconds()).padStart(2, "0") + "." +
      String(d.getMilliseconds()).padStart(3, "0")
    );
  }

  /* ── snapshots / lists ───────────────────────────────────── */

  getQuote(symbol: string) {
    const sym = normalizeSymbol(symbol);
    const quote = this.quotes.get(sym);
    return quote ? this.displayQuote(quote) : undefined;
  }

  listQuotes(category: QuoteCategory): readonly Quote[] {
    if (category === "watchlist") {
      const w = this.currentWatchlists().get(this.getActiveWatchlistId());
      if (!w) return [];
      return w.symbols
        .map((sym) => this.quotes.get(sym))
        .filter((q): q is Quote => !!q)
        .map((q) => this.displayQuote(q));
    }
    const unavailable = this.unavailableQuoteSourceForCategory(category);
    const datasetKey = CATEGORY_DATASET_KEYS[category];
    return CATEGORY_LISTS[category].map((q) => {
      if (unavailable) return unavailableQuote(q, unavailable);
      return this.displayQuote(q, datasetKey);
    });
  }

  private unavailableQuoteSourceForCategory(category: QuoteCategory): DataSourceState | null {
    if (!this.remoteClient) return null;
    const datasetKey = CATEGORY_DATASET_KEYS[category];
    if (!datasetKey) return null;
    const dataset = this.screenDatasets.find((entry) => entry.key === datasetKey);
    return dataset?.source.kind === "unavailable" ? dataset.source : null;
  }

  allSymbols(): readonly string[] {
    return Array.from(this.quotes.keys());
  }

  getChart(symbol: string, points = 180): number[] {
    const key = chartKey(symbol, points);
    this.ensureRemoteChart(symbol, points);
    return this.chartCache.get(key)?.slice(-points) ?? [];
  }

  getDepth(symbol: string): DepthBookData {
    const sym = normalizeSymbol(symbol);
    this.ensureRemoteDepth(sym);
    return this.depthCache.get(sym) ?? { symbol: sym, bids: [], asks: [] };
  }

  getOptionChain(symbol: string, expiry = "20JUN26"): OptionChainData {
    const sym = normalizeSymbol(symbol);
    const key = optionChainKey(sym, expiry);
    this.ensureRemoteOptionChain(sym, expiry);
    const cached = this.optionChainCache.get(key);
    const spot = this.quotes.get(sym)?.last ?? cached?.spot ?? 0;
    return cached ? { ...cached, spot } : { symbol: sym, expiry, spot, rows: [] };
  }

  getOptionSurface(symbol: string) {
    const sym = normalizeSymbol(symbol);
    this.ensureRemoteOptionSurface(sym);
    return this.optionSurfaceCache.get(sym) ?? { expiries: [], strikes: [], iv: [] };
  }

  getTimeSales(symbol: string, max = 60): readonly Trade[] {
    const sym = normalizeSymbol(symbol);
    this.ensureRemoteTrades(sym, max);
    return this.tradeBuf.get(sym)?.slice(0, max) ?? [];
  }

  getDetailSource(kind: DetailDataset, symbol: string): DataSourceState {
    const sym = normalizeSymbol(symbol);
    const cached = this.detailSources.get(detailSourceKey(kind, sym));
    if (cached) return cached;
    if (this.remoteClient) {
      return unavailableSource(this.remoteBootstrapPending ? "TERMD pending" : "TERMD unavailable");
    }
    return mockSource("LOCAL MOCK");
  }

  private screenDatasetSource(key: string): DataSourceState | null {
    if (!this.remoteClient) return null;
    const dataset = this.screenDatasets.find((entry) => entry.key === key);
    if (dataset) return dataset.source;
    return unavailableSource(this.remoteBootstrapPending ? "TERMD pending" : "TERMD unavailable");
  }

  private hasScreenDataset(key: string): boolean {
    return this.screenDatasets.some((entry) => entry.key === key);
  }

  private unavailableScreenDatasetSource(key: string): DataSourceState | null {
    const source = this.screenDatasetSource(key);
    return source?.kind === "unavailable" ? source : null;
  }

  private displayQuote(fallback: Quote, datasetKey = quoteDatasetKeyForSymbol(fallback.ticker)): Quote {
    const sym = normalizeSymbol(fallback.ticker);
    const quote = this.quotes.get(sym) ?? fallback;
    if (!this.remoteClient) return quote;
    const datasetSource = this.screenDatasetSource(datasetKey);
    const localMock =
      quote.source?.kind === "mock" &&
      (quote.source.label.includes("LOCAL") || quote.source.label.toLowerCase() === "seed");
    if (datasetSource?.kind === "unavailable") return unavailableQuote(quote, datasetSource);
    if (quote.source?.kind === "unavailable") return unavailableQuote(quote, quote.source);
    if (localMock) return unavailableQuote(quote, unavailableSource("TERMD quote unavailable"));
    return quote;
  }

  getHeatmap(): readonly HeatmapCell[] {
    if (this.remoteHeatmap) return this.remoteHeatmap;
    const unavailable =
      this.unavailableScreenDatasetSource("markets-overview") ??
      this.unavailableScreenDatasetSource("quotes");
    return HEATMAP_CONSTITUENTS.map(([s, n, sec, w]) => {
      const q = this.displayQuote({
        ticker: s,
        name: n,
        last: 0,
        chg: 0,
        pct: 0,
        vol: "N/A",
        bid: 0,
        ask: 0,
        source: unavailable ?? mockSource("LOCAL MOCK"),
      }, "markets-overview");
      const source = unavailable ?? q.source ?? mockSource("LOCAL MOCK");
      const pct = source.kind === "live" ? q?.pct ?? 0 : 0;
      return { symbol: s, name: n, sector: sec, pct, weight: w, source };
    });
  }

  getMovers() {
    const all = [...WATCHLIST, ...HEATMAP_CONSTITUENTS.map(([s]) => s)]
      .map((x) => (typeof x === "string" ? this.quotes.get(x) : this.quotes.get(x.ticker)))
      .filter((q): q is Quote => !!q)
      .map((q) => this.displayQuote(q));
    const seen = new Set<string>();
    const dedup = all.filter((q) => (seen.has(q.ticker) ? false : (seen.add(q.ticker), true)));
    const byPctDesc = [...dedup].sort((a, b) => b.pct - a.pct);
    const byPctAsc = [...dedup].sort((a, b) => a.pct - b.pct);
    const byAbsPct = [...dedup].sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));
    return {
      gainers: byPctDesc.slice(0, 12),
      losers: byPctAsc.slice(0, 12),
      actives: byAbsPct.slice(0, 12),
    };
  }

  getCorrelation(symbols: readonly string[]): number[][] {
    if (this.remoteClient) {
      return symbols.map((_, i) => symbols.map((_, j) => (i === j ? 1 : Number.NaN)));
    }
    // Deterministic pseudo-correlation derived from symbol-pair seed
    const N = symbols.length;
    const m: number[][] = [];
    for (let i = 0; i < N; i++) {
      const row: number[] = [];
      for (let j = 0; j < N; j++) {
        if (i === j) {
          row.push(1);
          continue;
        }
        const key = [symbols[i], symbols[j]].sort().join("|");
        const seed = seedFor(key);
        const r = (((seed % 10000) / 10000) - 0.5) * 1.8; // -0.9 .. +0.9
        row.push(+r.toFixed(2));
      }
      m.push(row);
    }
    return m;
  }

  getNews(filter?: { category?: string; symbol?: string }) {
    const unavailable = this.unavailableScreenDatasetSource("news");
    const source = unavailable
      ? unavailableNewsRows(unavailable)
      : this.remoteNews ?? (this.remoteClient ? [] : NEWS);
    if (!filter) return source;
    const filterSymbol = filter.symbol?.toUpperCase();
    return source.filter((n) => {
      if (unavailable) return true;
      if (filter.category && filter.category !== "TOP" && n.cat !== filter.category) return false;
      if (
        filterSymbol &&
        !n.headline.toUpperCase().includes(filterSymbol) &&
        !n.symbols?.some((symbol) => symbol.toUpperCase() === filterSymbol)
      ) {
        return false;
      }
      return true;
    });
  }
  subscribeNews(cb: () => void): () => void {
    this.newsSubs.add(cb);
    return () => { this.newsSubs.delete(cb); };
  }
  getRssFeeds() {
    return this.remoteRssFeeds ?? [];
  }
  subscribeRssFeeds(cb: () => void): () => void {
    this.rssFeedSubs.add(cb);
    return () => { this.rssFeedSubs.delete(cb); };
  }
  getEvents() {
    const unavailable = this.unavailableScreenDatasetSource("economic-events");
    if (unavailable) return unavailableEventRows("ECONOMIC CALENDAR UNAVAILABLE", unavailable);
    return this.remoteEvents ??
      (this.remoteClient ? [] : EVENTS.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") })));
  }
  getRecentPrints() {
    const unavailable = this.hasScreenDataset("recent-prints")
      ? this.unavailableScreenDatasetSource("recent-prints")
      : this.unavailableScreenDatasetSource("economic-events");
    if (unavailable) return unavailableEventRows("RECENT PRINTS UNAVAILABLE", unavailable);
    return this.remoteRecentPrints && this.remoteRecentPrints.length > 0
      ? this.remoteRecentPrints
      : this.remoteClient ? [] : RECENT_PRINTS.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") }));
  }
  subscribeCalendarData(cb: () => void): () => void {
    this.calendarSubs.add(cb);
    return () => { this.calendarSubs.delete(cb); };
  }
  getBonds() {
    const unavailable = this.unavailableScreenDatasetSource("fixed-income");
    if (unavailable) return unavailableBondRows(unavailable);
    return this.remoteBonds ??
      (this.remoteClient ? [] : BONDS.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") })));
  }
  getCDS() {
    const unavailable = this.unavailableScreenDatasetSource("fixed-income");
    if (unavailable) return unavailableCdsRows(unavailable);
    return this.remoteCds ??
      (this.remoteClient ? [] : CDS.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") })));
  }
  getCreditIndices() {
    const unavailable = this.unavailableScreenDatasetSource("fixed-income");
    if (unavailable) return unavailableCreditIndexRows(unavailable);
    return this.remoteCreditIndices ??
      (this.remoteClient
        ? []
        : CREDIT_INDICES.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") })));
  }
  subscribeFixedIncomeData(cb: () => void): () => void {
    this.fixedIncomeSubs.add(cb);
    return () => { this.fixedIncomeSubs.delete(cb); };
  }
  getCBRates() {
    const unavailable = this.unavailableScreenDatasetSource("rates");
    if (unavailable) return unavailableCbRateRows(unavailable);
    const base = macroAdjustedCentralBankRates(CB_RATES, this.macroSeries);
    if (this.remoteClient) return this.remoteCbRates ?? [];
    if (!this.remoteCbRates) return base;
    const remoteByCcy = new Map(this.remoteCbRates.map((row) => [row.ccy, row]));
    return base.map((row) => remoteByCcy.get(row.ccy) ?? row);
  }
  getCrossFX() {
    if (this.unavailableScreenDatasetSource("fx")) return unavailableCrossFx();
    return this.remoteCrossFx ?? (this.remoteClient ? unavailableCrossFx() : { ccys: CROSS_CCYS, matrix: CROSS_FX });
  }
  subscribeFxData(cb: () => void): () => void {
    this.fxSubs.add(cb);
    return () => { this.fxSubs.delete(cb); };
  }
  getYieldCurve() {
    const unavailable = this.unavailableScreenDatasetSource("rates");
    if (unavailable) return unavailableYieldCurveRows(unavailable);
    const base = macroAdjustedYieldCurve(US_CURVE, this.macroSeries);
    if (this.remoteClient) return this.remoteYieldCurve ?? [];
    if (!this.remoteYieldCurve) return base;
    const remoteByTenor = new Map(this.remoteYieldCurve.map((point) => [point.tenor, point]));
    return base.map((point) => remoteByTenor.get(point.tenor) ?? point);
  }
  getEarnings() {
    const unavailable = this.unavailableScreenDatasetSource("earnings");
    if (unavailable) return unavailableEarningsRows(unavailable);
    return this.remoteEarnings && this.remoteEarnings.length > 0
      ? this.remoteEarnings
      : this.remoteClient ? [] : EARNINGS_SEED.map((row) => ({ ...row, source: mockSource("LOCAL MOCK") }));
  }
  subscribeMacroData(cb: () => void): () => void {
    this.macroSubs.add(cb);
    return () => { this.macroSubs.delete(cb); };
  }
  getPredictionMarkets(): readonly TermdPredictionMarket[] {
    return this.predictionMarkets;
  }
  subscribePredictionMarkets(cb: () => void): () => void {
    this.predictionSubs.add(cb);
    return () => { this.predictionSubs.delete(cb); };
  }
  getResearch(symbol: string): ResearchSnapshot {
    const sym = normalizeSymbol(symbol);
    this.ensureRemoteResearch(sym);
    const cached = this.researchCache.get(sym);
    if (cached) return cached;
    const source = this.remoteClient
      ? unavailableSource(this.remoteBootstrapPending ? "TERMD pending" : "TERMD research unavailable")
      : mockSource("LOCAL MOCK");
    return emptyResearchSnapshot(sym, source);
  }
  subscribeResearch(symbol: string, cb: () => void): () => void {
    const sym = normalizeSymbol(symbol);
    let subs = this.researchSubs.get(sym);
    if (!subs) {
      subs = new Set();
      this.researchSubs.set(sym, subs);
    }
    subs.add(cb);
    return () => {
      const current = this.researchSubs.get(sym);
      current?.delete(cb);
      if (current?.size === 0) this.researchSubs.delete(sym);
    };
  }
  getScreenDatasets(): readonly TermdScreenDatasetMeta[] {
    return this.screenDatasets;
  }
  subscribeScreenDatasets(cb: () => void): () => void {
    this.screenDatasetSubs.add(cb);
    return () => { this.screenDatasetSubs.delete(cb); };
  }

  /* ── live state ───────────────────────────────────────── */

  getPositions(): readonly Position[] {
    if (this.remotePositions) return this.remotePositions;
    const active = this.activePortfolio();
    if (!active) return [];
    const computed = Array.from(active.positions.values()).map((stored) => {
      const priced = this.displayQuote({
        ticker: stored.ticker,
        name: stored.name,
        last: stored.avg,
        chg: 0,
        pct: 0,
        vol: "N/A",
        bid: stored.avg,
        ask: stored.avg,
        source: this.remoteClient ? mockSource("LOCAL MOCK") : undefined,
      });
      const unavailable = priced.source?.kind === "unavailable";
      const mark = unavailable ? 0 : priced.last;
      const mv = unavailable ? 0 : mark * stored.qty;
      const pl = unavailable ? 0 : (mark - stored.avg) * stored.qty;
      const plPct = unavailable ? 0 : ((mark - stored.avg) / Math.max(1e-9, stored.avg)) * 100;
      return {
        ticker: stored.ticker,
        name: stored.name,
        qty: stored.qty,
        avg: stored.avg,
        mark,
        mv,
        pl,
        plPct,
        wgt: 0,
        source: priced.source,
      } as Position;
    });
    const grossMv = computed.reduce((s, p) => s + Math.abs(p.mv), 0);
    if (grossMv > 0) {
      for (const p of computed) p.wgt = (Math.abs(p.mv) / grossMv) * 100;
    }
    return computed;
  }

  subscribePositions(cb: () => void): () => void {
    this.positionSubs.add(cb);
    return () => { this.positionSubs.delete(cb); };
  }

  private broadcastPositions() {
    for (const cb of this.positionSubs) cb();
  }

  /* ── portfolios ───────────────────────────────────────── */

  listPortfolios(): readonly PortfolioMeta[] {
    return Array.from(this.portfolios.values()).map((p) => ({ ...p.meta }));
  }
  getActivePortfolioId(): string {
    return this.activePortfolioId;
  }
  setActivePortfolioId(id: string): void {
    if (!this.portfolios.has(id) || this.activePortfolioId === id) return;
    this.activePortfolioId = id;
    this.persistPortfolios();
    this.broadcastPortfolios();
    this.broadcastPositions();
  }
  createPortfolio(name: string, cash = 100_000): PortfolioMeta {
    const id = `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const meta: PortfolioMeta = {
      id,
      name: name.trim() || "Untitled",
      cash,
      createdAt: Date.now(),
    };
    this.portfolios.set(id, { meta, positions: new Map() });
    this.persistPortfolios();
    this.broadcastPortfolios();
    return meta;
  }
  renamePortfolio(id: string, name: string): boolean {
    const p = this.portfolios.get(id);
    if (!p || !name.trim()) return false;
    p.meta.name = name.trim();
    this.persistPortfolios();
    this.broadcastPortfolios();
    return true;
  }
  deletePortfolio(id: string): boolean {
    if (this.portfolios.size <= 1) return false;
    if (!this.portfolios.has(id)) return false;
    this.portfolios.delete(id);
    if (this.activePortfolioId === id) {
      this.activePortfolioId = this.portfolios.keys().next().value as string;
    }
    this.persistPortfolios();
    this.broadcastPortfolios();
    this.broadcastPositions();
    return true;
  }
  addManualPosition(
    portfolioId: string,
    pos: { ticker: string; qty: number; avg: number },
  ): boolean {
    const p = this.portfolios.get(portfolioId);
    if (!p) return false;
    const ticker = pos.ticker.toUpperCase().trim();
    if (!ticker || !isFinite(pos.qty) || pos.qty === 0) return false;
    if (!isFinite(pos.avg) || pos.avg <= 0) return false;
    const q = this.quotes.get(ticker);
    const existing = p.positions.get(ticker);
    if (existing) {
      const newQty = existing.qty + pos.qty;
      if (newQty === 0) {
        p.positions.delete(ticker);
      } else {
        const sameSide = Math.sign(existing.qty) === Math.sign(pos.qty);
        const newAvg = sameSide
          ? (existing.avg * existing.qty + pos.avg * pos.qty) / newQty
          : existing.avg;
        p.positions.set(ticker, {
          ticker,
          qty: newQty,
          avg: +newAvg.toFixed(4),
          name: existing.name,
        });
      }
    } else {
      p.positions.set(ticker, {
        ticker,
        qty: pos.qty,
        avg: pos.avg,
        name: q?.name ?? ticker,
      });
    }
    this.persistPortfolios();
    this.broadcastPortfolios();
    if (portfolioId === this.activePortfolioId) this.broadcastPositions();
    return true;
  }
  removePosition(portfolioId: string, ticker: string): boolean {
    const p = this.portfolios.get(portfolioId);
    if (!p) return false;
    const had = p.positions.delete(ticker.toUpperCase());
    if (had) {
      this.persistPortfolios();
      this.broadcastPortfolios();
      if (portfolioId === this.activePortfolioId) this.broadcastPositions();
    }
    return had;
  }
  subscribePortfolios(cb: () => void): () => void {
    this.portfolioSubs.add(cb);
    return () => { this.portfolioSubs.delete(cb); };
  }
  private broadcastPortfolios() {
    for (const cb of this.portfolioSubs) cb();
  }

  addAlert(a: Omit<Alert, "id" | "status" | "createdAt">): Alert {
    const alert: Alert = {
      ...a,
      id: nextId(),
      status: "ACTIVE",
      createdAt: Date.now(),
    };
    this.alerts.unshift(alert);
    for (const cb of this.alertSubs) cb();
    return alert;
  }

  cancelAlert(id: string): boolean {
    const a = this.alerts.find((x) => x.id === id);
    if (!a || a.status !== "ACTIVE") return false;
    a.status = "CANCELLED";
    for (const cb of this.alertSubs) cb();
    return true;
  }

  getAlerts(): readonly Alert[] {
    return this.remoteAlerts ?? this.alerts;
  }

  subscribeAlerts(cb: (triggered?: Alert) => void): () => void {
    this.alertSubs.add(cb);
    return () => { this.alertSubs.delete(cb); };
  }

  private processAlerts(symbol: string, prev: number, next: number) {
    for (const a of this.alerts) {
      if (a.status !== "ACTIVE" || a.symbol !== symbol) continue;
      const crossedUp = prev < a.level && next >= a.level;
      const crossedDown = prev > a.level && next <= a.level;
      if (
        (a.condition === ">=" && (crossedUp || next >= a.level)) ||
        (a.condition === "<=" && (crossedDown || next <= a.level))
      ) {
        // Only trigger on a fresh cross
        if (
          (a.condition === ">=" && crossedUp) ||
          (a.condition === "<=" && crossedDown) ||
          (a.condition === ">=" && next >= a.level && prev < a.level) ||
          (a.condition === "<=" && next <= a.level && prev > a.level)
        ) {
          a.status = "TRIGGERED";
          a.triggeredAt = Date.now();
          a.triggeredPx = next;
          for (const cb of this.alertSubs) cb(a);
        }
      }
    }
  }

  subscribeQuote(symbol: string, cb: (q: Quote) => void): () => void {
    const sym = normalizeSymbol(symbol);
    let set = this.quoteSubs.get(sym);
    if (!set) {
      set = new Set();
      this.quoteSubs.set(sym, set);
    }
    set.add(cb);
    return () => { set!.delete(cb); };
  }

  subscribeTrades(symbol: string, cb: (t: Trade) => void): () => void {
    const sym = normalizeSymbol(symbol);
    let set = this.tradeSubs.get(sym);
    if (!set) {
      set = new Set();
      this.tradeSubs.set(sym, set);
    }
    set.add(cb);
    return () => { set!.delete(cb); };
  }

  subscribeDetailData(symbol: string, cb: () => void): () => void {
    const sym = normalizeSymbol(symbol);
    let set = this.detailSubs.get(sym);
    if (!set) {
      set = new Set();
      this.detailSubs.set(sym, set);
    }
    set.add(cb);
    return () => { set!.delete(cb); };
  }
}

export function createBackendFirstDataProviderForTest(
  remoteConfig: TermdApiConfig | null,
  options: { remoteBootstrapPending?: boolean } = {},
): DataProvider {
  const provider = new BackendFirstDataProvider(remoteConfig);
  if (options.remoteBootstrapPending !== undefined) {
    (provider as unknown as { remoteBootstrapPending: boolean }).remoteBootstrapPending =
      options.remoteBootstrapPending;
  }
  return provider;
}

/* ─────────────────────────────────────────────────────────────────────────────
   React context + hooks
   ──────────────────────────────────────────────────────────────────────────── */

const ProviderContext = createContext<DataProvider | null>(null);
const ActiveSymbolContext = createContext<readonly [string, (s: string) => void]>(["NVDA", () => {}]);
const ActiveFilterContext = createContext<readonly [ActiveFilter, (f: ActiveFilter) => void]>([{ kind: "none" }, () => {}]);
const ThemeContext = createContext<{ theme: ThemeName; setTheme: (t: ThemeName) => void }>({
  theme: "cream",
  setTheme: () => {},
});

const LS_THEME = "term-theme";

export function DataProviderRoot({ children }: { children: React.ReactNode }) {
  const providerRef = useRef<DataProvider | null>(null);
  if (!providerRef.current) providerRef.current = new BackendFirstDataProvider();
  useEffect(() => {
    providerRef.current!.start();
    return () => providerRef.current!.stop();
  }, []);

  const [active, setActive] = useState<string>("NVDA");
  const activeValue = useMemo(() => [active, setActive] as const, [active]);

  const [filter, setFilter] = useState<ActiveFilter>({ kind: "none" });
  const filterValue = useMemo(() => [filter, setFilter] as const, [filter]);

  const [theme, setThemeRaw] = useState<ThemeName>(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem(LS_THEME)) as ThemeName | null;
    return saved ?? "cream";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(LS_THEME, theme); } catch {}
  }, [theme]);
  const themeValue = useMemo(() => ({ theme, setTheme: setThemeRaw }), [theme]);

  return (
    <ProviderContext.Provider value={providerRef.current}>
      <ActiveSymbolContext.Provider value={activeValue}>
        <ActiveFilterContext.Provider value={filterValue}>
          <ThemeContext.Provider value={themeValue}>
            {children}
          </ThemeContext.Provider>
        </ActiveFilterContext.Provider>
      </ActiveSymbolContext.Provider>
    </ProviderContext.Provider>
  );
}

export function useProvider(): DataProvider {
  const p = useContext(ProviderContext);
  if (!p) throw new Error("useProvider must be used inside <DataProviderRoot>");
  return p;
}

export function useActiveSymbol() {
  return useContext(ActiveSymbolContext);
}

export function useActiveFilter() {
  return useContext(ActiveFilterContext);
}

/** Predicate: does the given symbol satisfy the active filter?
 *  Defined here (with provider-level sector lookup) so every consumer
 *  filters consistently with one expression. */
export function symbolPassesFilter(
  symbol: string,
  filter: ActiveFilter,
): boolean {
  if (filter.kind === "none") return true;
  if (filter.kind === "sector") {
    return sectorFor(symbol).toUpperCase() === filter.sector.toUpperCase();
  }
  return true;
}

export function useTheme() {
  return useContext(ThemeContext);
}

export function useTickFlash(price: number | undefined, ms = 650) {
  const prev = useRef<number | undefined>(price);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (price == null) return;
    const p = prev.current;
    if (p != null && p !== price) {
      const dir = price > p ? "up" : "down";
      setFlash(dir);
      if (timer.current != null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setFlash(null), ms);
    }
    prev.current = price;
    return () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, [price, ms]);
  return flash;
}

export function useQuote(symbol: string) {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeQuote(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  const quote = provider.getQuote(symbol);
  const flash = useTickFlash(quote?.last);
  return { quote, flash };
}

export function useQuoteList(category: QuoteCategory): readonly Quote[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  const symbols = useMemo(
    () => provider.listQuotes(category).map((q) => q.ticker),
    [provider, category],
  );
  useEffect(() => {
    const unsubs = symbols.map((s) => provider.subscribeQuote(s, () => force()));
    return () => unsubs.forEach((u) => u());
  }, [provider, symbols]);
  return provider.listQuotes(category);
}

export function useNews(filter?: { category?: string; symbol?: string }): readonly NewsItem[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeNews(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getNews(filter);
}

export function useRssFeeds(): readonly TermdRssFeed[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeRssFeeds(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getRssFeeds();
}

export function useEvents(): readonly EventItem[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeCalendarData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getEvents();
}

export function useRecentPrints(): readonly EventItem[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeCalendarData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getRecentPrints();
}

export function useCBRates(): readonly CbRate[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeMacroData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getCBRates();
}

export function useYieldCurve(): readonly YieldCurvePoint[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeMacroData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getYieldCurve();
}

export function useCrossFX(): { ccys: readonly string[]; matrix: readonly (readonly (number | null)[])[] } {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeFxData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getCrossFX();
}

export function useBonds(): readonly BondRow[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeFixedIncomeData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getBonds();
}

export function useCDS(): readonly CdsRow[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeFixedIncomeData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getCDS();
}

export function useCreditIndices(): readonly CreditIndexRow[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeFixedIncomeData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getCreditIndices();
}

export function useEarnings(): readonly Earning[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeCalendarData(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getEarnings();
}

export function usePredictionMarkets(): readonly TermdPredictionMarket[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribePredictionMarkets(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getPredictionMarkets();
}

export function useResearch(symbol: string): ResearchSnapshot {
  const provider = useProvider();
  const [researchVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeResearch(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(
    () => provider.getResearch(symbol),
    [provider, symbol, researchVersion],
  );
}

export function useScreenDatasets(): readonly TermdScreenDatasetMeta[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeScreenDatasets(() => force());
    return () => unsub();
  }, [provider]);
  return provider.getScreenDatasets();
}

export function useChartData(symbol: string, points = 180): number[] {
  const provider = useProvider();
  const { quote } = useQuote(symbol);
  const [detailVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeDetailData(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(
    () => provider.getChart(symbol, points),
    [provider, symbol, points, quote?.last, detailVersion],
  );
}

export function useDepth(symbol: string) {
  const provider = useProvider();
  const { quote } = useQuote(symbol);
  const [detailVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeDetailData(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(() => provider.getDepth(symbol), [provider, symbol, quote?.last, detailVersion]);
}

export function useOptionChain(symbol: string, expiry?: string) {
  const provider = useProvider();
  const { quote } = useQuote(symbol);
  const [detailVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeDetailData(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(
    () => provider.getOptionChain(symbol, expiry),
    [provider, symbol, expiry, quote?.last, detailVersion],
  );
}

export function useOptionSurface(symbol: string) {
  const provider = useProvider();
  const { quote } = useQuote(symbol);
  const [detailVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeDetailData(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(() => provider.getOptionSurface(symbol), [provider, symbol, quote?.last, detailVersion]);
}

export function useDetailSource(kind: DetailDataset, symbol: string): DataSourceState {
  const provider = useProvider();
  const [detailVersion, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeDetailData(symbol, () => force());
    return () => unsub();
  }, [provider, symbol]);
  return useMemo(
    () => provider.getDetailSource(kind, symbol),
    [provider, kind, symbol, detailVersion],
  );
}

export function useTimeSales(symbol: string, max = 60): readonly Trade[] {
  const provider = useProvider();
  const [trades, setTrades] = useState<readonly Trade[]>(() => provider.getTimeSales(symbol, max));
  useEffect(() => {
    setTrades(provider.getTimeSales(symbol, max));
    const unsub = provider.subscribeTrades(symbol, () => {
      setTrades(provider.getTimeSales(symbol, max));
    });
    return () => unsub();
  }, [provider, symbol, max]);
  return trades;
}

export function useHeatmap(): readonly HeatmapCell[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const id = window.setInterval(() => force(), 800);
    return () => window.clearInterval(id);
  }, []);
  return provider.getHeatmap();
}

export function useMovers() {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const id = window.setInterval(() => force(), 1000);
    return () => window.clearInterval(id);
  }, []);
  return provider.getMovers();
}

export function useCorrelation(symbols: readonly string[]) {
  const provider = useProvider();
  return useMemo(() => provider.getCorrelation(symbols), [provider, symbols]);
}

export function usePositions(): readonly Position[] {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const u1 = provider.subscribePositions(() => force());
    return () => u1();
  }, [provider]);
  return provider.getPositions();
}

export function usePortfolios() {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const u = provider.subscribePortfolios(() => force());
    return () => u();
  }, [provider]);
  return {
    portfolios: provider.listPortfolios(),
    activeId: provider.getActivePortfolioId(),
    setActive: (id: string) => provider.setActivePortfolioId(id),
    create: (name: string, cash?: number) => provider.createPortfolio(name, cash),
    rename: (id: string, name: string) => provider.renamePortfolio(id, name),
    remove: (id: string) => provider.deletePortfolio(id),
    addPosition: (portfolioId: string, pos: { ticker: string; qty: number; avg: number }) =>
      provider.addManualPosition(portfolioId, pos),
    removePosition: (portfolioId: string, ticker: string) =>
      provider.removePosition(portfolioId, ticker),
  };
}

/** Map a symbol to its GICS L1 sector tag. Pulled from the heatmap
 *  constituents catalog. Returns "OTHER" for unmapped symbols. */
const _SECTOR_LOOKUP = new Map<string, string>(
  HEATMAP_CONSTITUENTS.map(([s, , sec]) => [s, sec as string]),
);
export function sectorFor(symbol: string): string {
  return _SECTOR_LOOKUP.get(symbol.toUpperCase()) ?? "OTHER";
}

export function useAlerts() {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  const [lastTrigger, setLastTrigger] = useState<Alert | null>(null);
  useEffect(() => {
    const u = provider.subscribeAlerts((triggered) => {
      force();
      if (triggered) setLastTrigger(triggered);
    });
    return () => u();
  }, [provider]);
  return { alerts: provider.getAlerts(), lastTrigger };
}

export function usePauseState(): readonly [boolean, (p: boolean) => void] {
  const provider = useProvider();
  const [paused, setPaused] = useState(provider.isPaused());
  useEffect(() => {
    const u = provider.subscribePauseState(setPaused);
    return () => u();
  }, [provider]);
  return [paused, (p: boolean) => provider.setPaused(p)] as const;
}

/* ─────────────────────────────────────────────────────────────────────────────
   useWatchlists / useDesks — hooks for the new state
   ──────────────────────────────────────────────────────────────────────────── */

export function useWatchlists() {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const u = provider.subscribeWatchlists(() => force());
    return () => u();
  }, [provider]);
  const activeId = provider.getActiveWatchlistId();
  return {
    watchlists: provider.listWatchlists(),
    activeId,
    activeSymbols: provider.getWatchlistSymbols(activeId),
    readOnly: provider.watchlistsAreReadOnly(),
    setActive: (id: string) => provider.setActiveWatchlistId(id),
    create: (name: string, symbols?: readonly string[]) =>
      provider.createWatchlist(name, symbols),
    rename: (id: string, name: string) => provider.renameWatchlist(id, name),
    remove: (id: string) => provider.deleteWatchlist(id),
    addSymbol: (id: string, symbol: string) =>
      provider.addSymbolToWatchlist(id, symbol),
    removeSymbol: (id: string, symbol: string) =>
      provider.removeSymbolFromWatchlist(id, symbol),
  };
}

export function useDesks() {
  const provider = useProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const u = provider.subscribeDesks(() => force());
    return () => u();
  }, [provider]);
  return {
    desks: provider.listDesks(),
    save: (name: string, snapshot: DeskSnapshot) =>
      provider.saveDesk(name, snapshot),
    update: (id: string, snapshot: DeskSnapshot) =>
      provider.updateDesk(id, snapshot),
    rename: (id: string, name: string) => provider.renameDesk(id, name),
    remove: (id: string) => provider.deleteDesk(id),
  };
}
