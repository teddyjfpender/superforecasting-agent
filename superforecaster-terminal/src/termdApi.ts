import { decode, encode } from "@msgpack/msgpack";
import type {
  BondRow,
  CbRate,
  CdsRow,
  CreditIndexRow,
  DataSourceState,
  EventItem,
  NewsItem,
  Quote,
  YieldCurvePoint,
} from "./data";
import type { DepthBookData, Earning, OptionChainData, Trade } from "./providers";

type Env = {
  VITE_TERMD_API_BASE_URL?: string;
  VITE_TERMD_API_ENABLED?: string;
  VITE_TERMD_MACRO_SERIES?: string;
  VITE_TERMD_PREDICTION_VENUE?: string;
  VITE_TERMD_API_POLL_MS?: string;
  VITE_TERMD_API_TOKEN?: string;
  VITE_TERMD_SYMBOLS?: string;
};

export type TermdApiConfig = {
  baseUrl: string;
  token?: string;
  macroSeries: readonly string[];
  /** Venues to poll for prediction-market quotes. Each is fetched in
   *  parallel and the results are merged client-side. Backed by the
   *  `VITE_TERMD_PREDICTION_VENUE` env var (comma-separated). */
  predictionVenues: readonly string[];
  symbols: readonly string[];
  pollMs: number;
};

export type TermdQuotePayload = {
  symbol?: unknown;
  bid?: unknown;
  bidSz?: unknown;
  ask?: unknown;
  askSz?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdQuoteResponse = {
  quote?: TermdQuotePayload;
};

type TermdQuotesResponse = {
  quotes?: TermdQuotePayload[];
};

type TermdMarketsOverviewResponse = {
  universe?: unknown;
  asOf?: unknown;
  cells?: unknown[];
  quotes?: TermdQuotePayload[];
};

type TermdMarketOverviewCellPayload = {
  symbol?: unknown;
  name?: unknown;
  sector?: unknown;
  weight?: unknown;
  pct?: unknown;
  availability?: unknown;
  quote?: TermdQuotePayload | null;
};

type TermdEventsResponse = {
  events?: unknown[];
};

type TermdCalendarEventsResponse = {
  events?: unknown[];
};

type TermdBarsResponse = {
  symbol?: unknown;
  interval?: unknown;
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
  bars?: unknown[];
};

type TermdBarEvent = {
  kind?: unknown;
  close?: unknown;
  openTime?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdDepthResponse = {
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
  depth?: unknown;
};

type TermdDepthEvent = {
  kind?: unknown;
  symbol?: unknown;
  bids?: unknown;
  asks?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdDepthLevelPayload = {
  px?: unknown;
  qty?: unknown;
};

type TermdTradesResponse = {
  symbol?: unknown;
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
  trades?: unknown[];
};

type TermdTickEvent = {
  kind?: unknown;
  symbol?: unknown;
  px?: unknown;
  qty?: unknown;
  side?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdOptionsResponse = {
  symbol?: unknown;
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
  contracts?: unknown[];
};

type TermdOptionContractPayload = {
  underlying?: unknown;
  expiry?: unknown;
  strike?: unknown;
  right?: unknown;
  bid?: unknown;
  ask?: unknown;
  mark?: unknown;
  impliedVol?: unknown;
  openInterest?: unknown;
};

type TermdVolSurfaceResponse = {
  symbol?: unknown;
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
  points?: unknown[];
};

type TermdVolSurfacePointPayload = {
  expiry?: unknown;
  strike?: unknown;
  callIv?: unknown;
  putIv?: unknown;
};

type TermdSeriesResponse = {
  id?: unknown;
  points?: unknown[];
};

type TermdRatesResponse = {
  currency?: unknown;
  asOf?: unknown;
  curve?: unknown[];
  policyRates?: unknown[];
};

type TermdFixedIncomeResponse = {
  asOf?: unknown;
  bonds?: unknown[];
  cds?: unknown[];
  indices?: unknown[];
};

type TermdFxResponse = {
  asOf?: unknown;
  ccys?: unknown[];
  quotes?: TermdQuotePayload[];
  matrix?: unknown[][];
};

type TermdCommoditiesResponse = {
  asOf?: unknown;
  frontMonths?: TermdQuotePayload[];
  energy?: TermdQuotePayload[];
  metals?: TermdQuotePayload[];
  ags?: TermdQuotePayload[];
};

type TermdScreenResponse = {
  screen?: unknown;
  asOf?: unknown;
  datasets?: unknown[];
  quotes?: TermdQuotePayload[];
  marketsOverview?: TermdMarketsOverviewResponse | null;
  rates?: TermdRatesResponse | null;
  fixedIncome?: TermdFixedIncomeResponse | null;
  fx?: TermdFxResponse | null;
  commodities?: TermdCommoditiesResponse | null;
  news?: TermdEventsResponse | null;
  economicEvents?: TermdEventsResponse | null;
  recentPrints?: TermdEventsResponse | null;
  earnings?: TermdCalendarEventsResponse | null;
};

type TermdScreenDatasetMetaPayload = {
  key?: unknown;
  availability?: unknown;
  source?: unknown;
  asOf?: unknown;
  staleAfterMs?: unknown;
};

type TermdRateCurvePointPayload = {
  tenor?: unknown;
  seriesId?: unknown;
  yld?: unknown;
  observedAt?: unknown;
  availability?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdPolicyRatePayload = {
  ccy?: unknown;
  bank?: unknown;
  seriesId?: unknown;
  rate?: unknown;
  observedAt?: unknown;
  availability?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdBondPayload = {
  issuer?: unknown;
  desc?: unknown;
  cpn?: unknown;
  maturity?: unknown;
  px?: unknown;
  ytm?: unknown;
  oas?: unknown;
  rating?: unknown;
  availability?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdCdsPayload = {
  name?: unknown;
  region?: unknown;
  rating?: unknown;
  px?: unknown;
  chg?: unknown;
  ytd?: unknown;
  availability?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdCreditIndexPayload = {
  name?: unknown;
  desc?: unknown;
  last?: unknown;
  chg?: unknown;
  ytd?: unknown;
  availability?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdSeriesPointPayload = {
  id?: unknown;
  time?: unknown;
  value?: unknown;
  unit?: unknown;
  provenance?: {
    source?: unknown;
  };
};

type TermdNewsEvent = {
  kind?: unknown;
  id?: unknown;
  headline?: unknown;
  body?: unknown;
  url?: unknown;
  symbols?: unknown;
  categories?: unknown;
  sentiment?: unknown;
  published?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdRssFeedsResponse = {
  feeds?: unknown[];
};

type TermdRssFeedPayload = {
  id?: unknown;
  userId?: unknown;
  name?: unknown;
  url?: unknown;
  categories?: unknown;
  pollSecs?: unknown;
  symbolTagging?: unknown;
  manualSymbols?: unknown;
};

type TermdWatchlistsResponse = {
  watchlists?: unknown[];
};

type TermdWatchlistPayload = {
  id?: unknown;
  userId?: unknown;
  name?: unknown;
  symbols?: unknown;
};

type TermdPositionsResponse = {
  positions?: unknown[];
};

type TermdPositionPayload = {
  userId?: unknown;
  symbol?: unknown;
  qty?: unknown;
  avgPx?: unknown;
  marketPx?: unknown;
};

type TermdAlertsResponse = {
  alerts?: unknown[];
};

type TermdAlertPayload = {
  id?: unknown;
  userId?: unknown;
  symbol?: unknown;
  condition?: unknown;
  threshold?: unknown;
  active?: unknown;
};

type TermdEconomicEvent = {
  kind?: unknown;
  id?: unknown;
  time?: unknown;
  ccy?: unknown;
  label?: unknown;
  importance?: unknown;
  forecast?: unknown;
  previous?: unknown;
  actual?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdCalendarEventPayload = {
  id?: unknown;
  kind?: unknown;
  time?: unknown;
  symbol?: unknown;
  ccy?: unknown;
  title?: unknown;
  importance?: unknown;
  forecast?: unknown;
  previous?: unknown;
  actual?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdFilingEventPayload = {
  kind?: unknown;
  accession?: unknown;
  cik?: unknown;
  company?: unknown;
  form?: unknown;
  filed?: unknown;
  period?: unknown;
  primaryDocUrl?: unknown;
  symbols?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdXbrlFactPayload = {
  concept?: unknown;
  value?: unknown;
  unit?: unknown;
  periodStart?: unknown;
  periodEnd?: unknown;
};

type TermdFilingDetailResponse = {
  filing?: unknown;
  facts?: unknown[];
};

type TermdInsiderTradePayload = {
  kind?: unknown;
  accession?: unknown;
  cik?: unknown;
  symbol?: unknown;
  person?: unknown;
  relationship?: unknown;
  side?: unknown;
  shares?: unknown;
  price?: unknown;
  traded?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdInstitutionalHoldingPayload = {
  accession?: unknown;
  cik?: unknown;
  quarter?: unknown;
  issuer?: unknown;
  classTitle?: unknown;
  cusip?: unknown;
  value?: unknown;
  shares?: unknown;
  shareType?: unknown;
  putCall?: unknown;
  investmentDiscretion?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdInstitutionalHoldingsResponse = {
  holdings?: unknown[];
};

type TermdPredictionEvent = {
  kind?: unknown;
  venue?: unknown;
  marketId?: unknown;
  question?: unknown;
  outcome?: unknown;
  bid?: unknown;
  ask?: unknown;
  last?: unknown;
  volume?: unknown;
  resolved?: unknown;
  resolution?: unknown;
  provenance?: {
    source?: unknown;
    receivedAt?: unknown;
  };
};

type TermdQuoteEvent = TermdQuotePayload & {
  kind?: unknown;
};

type TermdWireFramePayload = {
  version?: unknown;
  frameType?: unknown;
  channel?: unknown;
  seq?: unknown;
  payload?: unknown;
};

const DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "QQQ", "SPY"] as const;
const DEFAULT_MACRO_SERIES = ["fred.DGS10", "bis.US_POLICY_RATE"] as const;
const DEFAULT_PREDICTION_VENUES = ["polymarket", "kalshi"] as const;
const DEFAULT_POLL_MS = 5_000;
const WIRE_VERSION = 1;
const WS_SUBPROTOCOL = "bbrg.v1";
const STREAM_FRAME_TYPES = new Set(["snapshot", "delta", "ack", "err", "ping", "pong", "sub", "unsub"]);

export type TermdMacroPoint = {
  id: string;
  time: string;
  value: number;
  unit: string;
  source: string;
};

export type TermdMacroSeries = {
  id: string;
  points: readonly TermdMacroPoint[];
};

export type TermdRatesSnapshot = {
  currency: string;
  asOf: string | null;
  curve: readonly YieldCurvePoint[];
  policyRates: readonly CbRate[];
};

export type TermdEconomicCalendarSnapshot = {
  events: readonly EventItem[];
  recentPrints: readonly EventItem[];
};

export type TermdFixedIncomeSnapshot = {
  asOf: string | null;
  bonds: readonly BondRow[];
  cds: readonly CdsRow[];
  indices: readonly CreditIndexRow[];
};

export type TermdFxSnapshot = {
  asOf: string | null;
  ccys: readonly string[];
  matrix: readonly (readonly (number | null)[])[];
  quotes: readonly Quote[];
};

export type TermdCommoditiesSnapshot = {
  asOf: string | null;
  frontMonths: readonly Quote[];
  energy: readonly Quote[];
  metals: readonly Quote[];
  ags: readonly Quote[];
};

export type TermdScreenSnapshot = {
  screen: string;
  asOf: string | null;
  datasets: readonly TermdScreenDatasetMeta[];
  quotes: readonly Quote[];
  marketsOverview: TermdMarketsOverview | null;
  rates: TermdRatesSnapshot | null;
  fixedIncome: TermdFixedIncomeSnapshot | null;
  fx: TermdFxSnapshot | null;
  commodities: TermdCommoditiesSnapshot | null;
  news: readonly NewsItem[];
  economicCalendar: TermdEconomicCalendarSnapshot | null;
  earnings: readonly Earning[];
};

export type TermdScreenDatasetMeta = {
  key: string;
  source: DataSourceState;
  asOf: string | null;
  staleAfterMs: number;
};

export type TermdOptionSurface = {
  expiries: string[];
  strikes: number[];
  iv: number[][];
};

export type TermdDetailSnapshot<T> = {
  data: T;
  source: DataSourceState;
  asOf: string | null;
  staleAfterMs: number;
};

export type TermdChartSnapshot = TermdDetailSnapshot<readonly number[]>;
export type TermdDepthSnapshot = TermdDetailSnapshot<DepthBookData>;
export type TermdTradesSnapshot = TermdDetailSnapshot<readonly Trade[]>;
export type TermdTradeSnapshot = TermdDetailSnapshot<Trade>;
export type TermdOptionChainSnapshot = TermdDetailSnapshot<OptionChainData>;
export type TermdOptionSurfaceSnapshot = TermdDetailSnapshot<TermdOptionSurface>;

export type TermdMarketOverviewCell = {
  symbol: string;
  name: string;
  sector: string;
  weight: number;
  pct: number;
  source: DataSourceState;
};

export type TermdMarketsOverview = {
  universe: string;
  asOf: string | null;
  cells: readonly TermdMarketOverviewCell[];
  quotes: readonly Quote[];
};

export type TermdPredictionMarket = {
  venue: string;
  marketId: string;
  question: string;
  outcome: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  mid: number | null;
  spread: number | null;
  volume: number | null;
  resolved: boolean;
  resolution: string | null;
  source: string;
  receivedAt: string;
};

export type TermdRssFeed = {
  id: string;
  userId: string;
  name: string;
  url: string;
  categories: readonly string[];
  pollSecs: number;
  symbolTagging: "auto" | "off" | "manual";
  manualSymbols: readonly string[];
};

export type TermdWatchlist = {
  id: string;
  userId: string;
  name: string;
  symbols: readonly string[];
};

export type TermdUserPosition = {
  userId: string;
  symbol: string;
  qty: number;
  avgPx: number;
  marketPx: number;
};

export type TermdUserAlert = {
  id: string;
  userId: string;
  symbol: string;
  condition: ">=" | "<=";
  threshold: number;
  active: boolean;
};

export type TermdFiling = {
  accession: string;
  cik: number;
  company: string;
  form: string;
  filed: string;
  period: string | null;
  primaryDocUrl: string;
  symbols: readonly string[];
  source: DataSourceState;
};

export type TermdXbrlFact = {
  concept: string;
  value: number;
  unit: string;
  periodStart: string | null;
  periodEnd: string | null;
};

export type TermdFilingDetail = {
  filing: TermdFiling;
  facts: readonly TermdXbrlFact[];
};

export type TermdInsiderTrade = {
  accession: string;
  cik: number;
  symbol: string;
  person: string;
  relationship: string;
  side: "buy" | "sell" | "unknown";
  shares: number;
  price: number | null;
  traded: string;
  source: DataSourceState;
};

export type TermdInstitutionalHolding = {
  accession: string;
  cik: number;
  quarter: string;
  issuer: string;
  classTitle: string;
  cusip: string;
  value: number;
  shares: number;
  shareType: string;
  putCall: string | null;
  investmentDiscretion: string | null;
  source: DataSourceState;
};

export type TermdWireFrameType = "snapshot" | "delta" | "ack" | "err" | "ping" | "pong" | "sub" | "unsub";

export type TermdWireFrame = {
  version: number;
  frameType: TermdWireFrameType;
  channel: string;
  seq: number;
  payload: Uint8Array;
};

export type TermdStream = {
  close(): void;
  readyState(): number;
};

export type TermdQuoteStreamHandlers = {
  onQuote(quote: Quote, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdDetailStreamHandlers = {
  onChart?(snapshot: TermdChartSnapshot, frame: TermdWireFrame): void;
  onDepth?(snapshot: TermdDepthSnapshot, frame: TermdWireFrame): void;
  onTrade?(snapshot: TermdTradeSnapshot, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdDerivativeStreamHandlers = {
  onOptions?(snapshot: TermdOptionChainSnapshot, frame: TermdWireFrame): void;
  onVolSurface?(snapshot: TermdOptionSurfaceSnapshot, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdNewsStreamHandlers = {
  onNews(item: NewsItem, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdMacroSeriesStreamHandlers = {
  onSeries?(series: TermdMacroSeries, frame: TermdWireFrame): void;
  onPoint?(point: TermdMacroPoint, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdPredictionStreamHandlers = {
  onMarket(market: TermdPredictionMarket, frame: TermdWireFrame): void;
  onError?(error: unknown): void;
  onClose?(): void;
};

export type TermdAssetClass = "eq" | "cx" | "fx" | "rates" | "cmdty";

export function readTermdApiConfig(env: Env = browserEnv()): TermdApiConfig | null {
  const enabled =
    env.VITE_TERMD_API_ENABLED === "1" ||
    Boolean(env.VITE_TERMD_API_BASE_URL) ||
    Boolean(env.VITE_TERMD_API_TOKEN);
  if (!enabled) return null;

  const pollMs = numberFromString(env.VITE_TERMD_API_POLL_MS);
  return {
    baseUrl: stripTrailingSlash(env.VITE_TERMD_API_BASE_URL || "/termd-api"),
    macroSeries: parseList(env.VITE_TERMD_MACRO_SERIES, DEFAULT_MACRO_SERIES, false),
    predictionVenues: parsePredictionVenues(env.VITE_TERMD_PREDICTION_VENUE),
    token: nonEmpty(env.VITE_TERMD_API_TOKEN),
    symbols: parseList(env.VITE_TERMD_SYMBOLS, DEFAULT_SYMBOLS, true),
    pollMs: pollMs && pollMs >= 1_000 ? pollMs : DEFAULT_POLL_MS,
  };
}

function parsePredictionVenues(value: string | undefined): readonly string[] {
  const raw = (value ?? "")
    .split(",")
    .map((venue) => venue.trim().toLowerCase())
    .filter(Boolean);
  if (raw.length === 0) return DEFAULT_PREDICTION_VENUES;
  return Array.from(new Set(raw));
}

export class TermdApiClient {
  constructor(private readonly config: TermdApiConfig) {}

  async fetchQuotes(symbols: readonly string[]): Promise<Quote[]> {
    const normalized = normalizeSymbols(symbols);
    if (normalized.length === 0) return [];
    const response = await this.fetchJson<TermdQuotesResponse>(
      `/api/v1/quotes?symbols=${encodeURIComponent(normalized.join(","))}`,
      true,
    );
    if (response?.quotes) {
      return response.quotes
        .map((quote) => termdQuoteToUiQuote(quote))
        .filter((quote): quote is Quote => quote !== null);
    }
    const settled = await Promise.all(
      normalized.map(async (symbol) => this.fetchQuote(symbol)),
    );
    return settled.filter((quote): quote is Quote => quote !== null);
  }

  private async fetchQuote(symbol: string): Promise<Quote | null> {
    const response = await this.fetchJson<TermdQuoteResponse>(
      `/api/v1/quote/${encodeURIComponent(symbol)}`,
      true,
    );
    return response?.quote ? termdQuoteToUiQuote(response.quote) : null;
  }

  async fetchMarketsOverview(): Promise<TermdMarketsOverview | null> {
    const response = await this.fetchJson<TermdMarketsOverviewResponse>(
      "/api/v1/markets/overview",
      true,
    );
    return response ? termdMarketsOverviewToUi(response) : null;
  }

  async fetchChart(symbol: string, points = 180): Promise<TermdChartSnapshot | null> {
    const response = await this.fetchJson<TermdBarsResponse>(
      `/api/v1/chart/${encodeURIComponent(symbol.toUpperCase())}?interval=1m&limit=${encodeURIComponent(String(points))}`,
      true,
    );
    return response
      ? detailSnapshot(response, termdBarsResponseToChartData(response).slice(-points))
      : null;
  }

  async fetchDepth(symbol: string): Promise<TermdDepthSnapshot | null> {
    const response = await this.fetchJson<TermdDepthResponse>(
      `/api/v1/depth/${encodeURIComponent(symbol.toUpperCase())}`,
      true,
    );
    if (!response) return null;
    const fallback = { symbol: symbol.toUpperCase(), bids: [], asks: [] };
    return detailSnapshot(response, termdDepthResponseToUi(response, symbol) ?? fallback);
  }

  async fetchTrades(symbol: string, limit = 60): Promise<TermdTradesSnapshot | null> {
    const response = await this.fetchJson<TermdTradesResponse>(
      `/api/v1/trades/${encodeURIComponent(symbol.toUpperCase())}?limit=${encodeURIComponent(String(limit))}`,
      true,
    );
    return response ? detailSnapshot(response, termdTradesResponseToUi(response).slice(0, limit)) : null;
  }

  async fetchOptionChain(symbol: string, expiry = "20JUN26"): Promise<TermdOptionChainSnapshot | null> {
    const response = await this.fetchJson<TermdOptionsResponse>(
      `/api/v1/options/${encodeURIComponent(symbol.toUpperCase())}?expiry=${encodeURIComponent(expiry)}`,
      true,
    );
    if (!response) return null;
    const fallback = { symbol: symbol.toUpperCase(), expiry, spot: 0, rows: [] };
    return detailSnapshot(response, termdOptionsResponseToUi(response, expiry) ?? fallback);
  }

  async fetchOptionSurface(symbol: string): Promise<TermdOptionSurfaceSnapshot | null> {
    const response = await this.fetchJson<TermdVolSurfaceResponse>(
      `/api/v1/vol-surface/${encodeURIComponent(symbol.toUpperCase())}`,
      true,
    );
    if (!response) return null;
    return detailSnapshot(
      response,
      termdVolSurfaceResponseToUi(response) ?? { expiries: [], strikes: [], iv: [] },
    );
  }

  async fetchNews(limit = 25): Promise<NewsItem[]> {
    const response = await this.fetchJson<TermdEventsResponse>(
      `/api/v1/news?limit=${encodeURIComponent(String(limit))}`,
      true,
    );
    return (response?.events ?? [])
      .map((event) => termdEventToNewsItem(event))
      .filter((item): item is NewsItem => item !== null);
  }

  async fetchRssFeeds(): Promise<TermdRssFeed[]> {
    const response = await this.fetchJson<TermdRssFeedsResponse>("/api/v1/users/me/rss", true);
    return (response?.feeds ?? [])
      .map((feed) => termdRssFeedToUi(feed))
      .filter((feed): feed is TermdRssFeed => feed !== null);
  }

  async fetchWatchlists(): Promise<TermdWatchlist[]> {
    const response = await this.fetchJson<TermdWatchlistsResponse>("/api/v1/watchlists", true);
    return (response?.watchlists ?? [])
      .map((watchlist) => termdWatchlistToUi(watchlist))
      .filter((watchlist): watchlist is TermdWatchlist => watchlist !== null);
  }

  async fetchPositions(): Promise<TermdUserPosition[]> {
    const response = await this.fetchJson<TermdPositionsResponse>("/api/v1/positions", true);
    return (response?.positions ?? [])
      .map((position) => termdUserPositionToUi(position))
      .filter((position): position is TermdUserPosition => position !== null);
  }

  async fetchAlerts(): Promise<TermdUserAlert[]> {
    const response = await this.fetchJson<TermdAlertsResponse>("/api/v1/alerts", true);
    return (response?.alerts ?? [])
      .map((alert) => termdUserAlertToUi(alert))
      .filter((alert): alert is TermdUserAlert => alert !== null);
  }

  streamNews(
    handlers: TermdNewsStreamHandlers,
    symbols: readonly string[] = [],
  ): TermdStream | null {
    const channels = termdNewsChannels(symbols);
    if (typeof WebSocket === "undefined" || channels.length === 0) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      socket.send(encodeTermdSubscribeFrame(channels));
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          if (!frame.channel.startsWith("news.")) return;
          const item = termdEventToNewsItem(decode(frame.payload));
          if (item) handlers.onNews(item, frame);
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  async fetchEconomicCalendar(): Promise<TermdEconomicCalendarSnapshot | null> {
    const [scheduled, recentPrints] = await Promise.all([
      this.fetchJson<TermdEventsResponse>("/api/v1/events/economic?actual=false", true),
      this.fetchJson<TermdEventsResponse>("/api/v1/events/economic?actual=true", true),
    ]);
    return scheduled || recentPrints
      ? termdEconomicEventsResponseToUi(scheduled ?? { events: [] }, recentPrints)
      : null;
  }

  async fetchEarnings(): Promise<Earning[]> {
    const response = await this.fetchJson<TermdCalendarEventsResponse>(
      "/api/v1/events/earnings",
      true,
    );
    return (response?.events ?? [])
      .map((event) => termdCalendarEventToEarning(event))
      .filter((event): event is Earning => event !== null);
  }

  async fetchFilings(filters: {
    cik?: number;
    symbol?: string;
    form?: string;
    from?: string;
    to?: string;
  } = {}): Promise<TermdFiling[]> {
    const params = new URLSearchParams();
    if (filters.cik !== undefined) params.set("cik", String(filters.cik));
    if (filters.symbol) params.set("symbol", filters.symbol.trim().toUpperCase());
    if (filters.form) params.set("form", filters.form);
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    const response = await this.fetchJson<TermdEventsResponse>(
      queryPath("/api/v1/filings", params),
      true,
    );
    return (response?.events ?? [])
      .map((event) => termdFilingEventToUi(event))
      .filter((filing): filing is TermdFiling => filing !== null);
  }

  async fetchFilingDetail(accession: string): Promise<TermdFilingDetail | null> {
    const normalized = accession.trim();
    if (!normalized) return null;
    const response = await this.fetchJson<TermdFilingDetailResponse>(
      `/api/v1/filings/${encodeURIComponent(normalized)}`,
      true,
    );
    return response ? termdFilingDetailResponseToUi(response) : null;
  }

  async fetchInsiderTrades(
    symbol: string,
    filters: { from?: string; to?: string; limit?: number } = {},
  ): Promise<TermdInsiderTrade[]> {
    const normalized = symbol.trim().toUpperCase();
    if (!normalized) return [];
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    if (filters.limit !== undefined) params.set("limit", String(filters.limit));
    const response = await this.fetchJson<TermdEventsResponse>(
      queryPath(`/api/v1/insider/${encodeURIComponent(normalized)}`, params),
      true,
    );
    return (response?.events ?? [])
      .map((event) => termdInsiderTradeEventToUi(event))
      .filter((trade): trade is TermdInsiderTrade => trade !== null);
  }

  async fetchInstitutionalHoldings(filters: {
    symbol?: string;
    cik?: number;
    quarter?: string;
    cusip?: string;
    limit?: number;
  } = {}): Promise<TermdInstitutionalHolding[]> {
    const params = new URLSearchParams();
    if (filters.symbol) params.set("symbol", filters.symbol.trim().toUpperCase());
    if (filters.cik !== undefined) params.set("cik", String(filters.cik));
    if (filters.quarter) params.set("quarter", filters.quarter);
    if (filters.cusip) params.set("cusip", filters.cusip);
    if (filters.limit !== undefined) params.set("limit", String(filters.limit));
    const response = await this.fetchJson<TermdInstitutionalHoldingsResponse>(
      queryPath("/api/v1/holdings/13f", params),
      true,
    );
    return (response?.holdings ?? [])
      .map((holding) => termdInstitutionalHoldingToUi(holding))
      .filter((holding): holding is TermdInstitutionalHolding => holding !== null);
  }

  async fetchMacroSeries(ids: readonly string[]): Promise<TermdMacroSeries[]> {
    const settled = await Promise.all(
      ids.map(async (id) => {
        const response = await this.fetchJson<TermdSeriesResponse>(
          `/api/v1/macro/series/${encodeURIComponent(id)}`,
          true,
        );
        return response ? termdSeriesResponseToUiSeries(response) : null;
      }),
    );
    return settled.filter((series): series is TermdMacroSeries => series !== null);
  }

  streamMacroSeries(
    ids: readonly string[],
    handlers: TermdMacroSeriesStreamHandlers,
  ): TermdStream | null {
    const channels = termdMacroSeriesChannels(ids);
    if (typeof WebSocket === "undefined" || channels.length === 0) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      socket.send(encodeTermdSubscribeFrame(channels));
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          const id = macroSeriesIdFromChannel(frame.channel);
          if (!id) return;
          const payload = decode(frame.payload);
          if (frame.frameType === "snapshot") {
            const series = termdSeriesPayloadToUiSeries(payload, id);
            if (series) handlers.onSeries?.(series, frame);
            return;
          }
          const point = termdSeriesPointToUiPoint(payload, id);
          if (point) handlers.onPoint?.(point, frame);
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  async fetchRates(): Promise<TermdRatesSnapshot | null> {
    const response = await this.fetchJson<TermdRatesResponse>("/api/v1/rates", true);
    return response ? termdRatesResponseToUi(response) : null;
  }

  async fetchFixedIncome(): Promise<TermdFixedIncomeSnapshot | null> {
    const response = await this.fetchJson<TermdFixedIncomeResponse>("/api/v1/fixed-income", true);
    return response ? termdFixedIncomeResponseToUi(response) : null;
  }

  async fetchFx(): Promise<TermdFxSnapshot | null> {
    const response = await this.fetchJson<TermdFxResponse>("/api/v1/fx", true);
    return response ? termdFxResponseToUi(response) : null;
  }

  async fetchCommodities(): Promise<TermdCommoditiesSnapshot | null> {
    const response = await this.fetchJson<TermdCommoditiesResponse>("/api/v1/commodities", true);
    return response ? termdCommoditiesResponseToUi(response) : null;
  }

  async fetchScreen(
    screen: string,
    symbols: readonly string[],
    calendarWindow?: { from?: string; to?: string },
  ): Promise<TermdScreenSnapshot | null> {
    const params = new URLSearchParams();
    const normalized = normalizeSymbols(symbols);
    if (normalized.length > 0) params.set("symbols", normalized.join(","));
    params.set("newsLimit", "25");
    if (calendarWindow?.from) params.set("from", calendarWindow.from);
    if (calendarWindow?.to) params.set("to", calendarWindow.to);
    const response = await this.fetchJson<TermdScreenResponse>(
      `/api/v1/screen/${encodeURIComponent(screen)}?${params.toString()}`,
      true,
    );
    return response ? termdScreenResponseToUi(response) : null;
  }

  async fetchPredictionMarkets(venue: string, limit = 120): Promise<TermdPredictionMarket[]> {
    const response = await this.fetchJson<TermdEventsResponse>(
      `/api/v1/prediction/markets?venue=${encodeURIComponent(venue)}`,
      true,
    );
    return (response?.events ?? [])
      .map((event) => termdEventToPredictionMarket(event))
      .filter((market): market is TermdPredictionMarket => market !== null)
      .slice(0, limit);
  }

  streamPredictionMarkets(
    markets: readonly Pick<TermdPredictionMarket, "venue" | "marketId">[],
    handlers: TermdPredictionStreamHandlers,
  ): TermdStream | null {
    const channels = termdPredictionChannels(markets);
    if (typeof WebSocket === "undefined" || channels.length === 0) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      socket.send(encodeTermdSubscribeFrame(channels));
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          if (!frame.channel.startsWith("prediction.")) return;
          const market = termdEventToPredictionMarket(decode(frame.payload));
          if (market) handlers.onMarket(market, frame);
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  streamQuotes(
    symbols: readonly string[],
    handlers: TermdQuoteStreamHandlers,
  ): TermdStream | null {
    if (typeof WebSocket === "undefined" || symbols.length === 0) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      const frame = encodeTermdSubscribeFrame(symbols.map((symbol) => `quote.${symbol.toUpperCase()}`));
      socket.send(frame);
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          if (!frame.channel.startsWith("quote.")) return;
          const quote = termdEventToQuote(decode(frame.payload));
          if (quote) handlers.onQuote(quote, frame);
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  streamDetails(
    symbol: string,
    handlers: TermdDetailStreamHandlers,
    assetClass: TermdAssetClass = "eq",
  ): TermdStream | null {
    const normalized = symbol.trim().toUpperCase();
    if (typeof WebSocket === "undefined" || !normalized) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      const frame = encodeTermdSubscribeFrame(termdDetailChannels(normalized, assetClass));
      socket.send(frame);
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          const payload = decode(frame.payload);
          if (frame.channel.startsWith("bar.")) {
            if (frame.frameType === "snapshot") {
              const response = payload as TermdBarsResponse;
              handlers.onChart?.(
                detailSnapshot(response, termdBarsResponseToChartData(response)),
                frame,
              );
              return;
            }
            const chart = termdEventToChartSnapshot(payload);
            if (chart) handlers.onChart?.(chart, frame);
            return;
          }
          if (frame.channel.startsWith("depth.")) {
            const depth = termdEventToDepth(payload, normalized);
            if (depth) handlers.onDepth?.(depth, frame);
            return;
          }
          if (frame.channel.startsWith("tick.")) {
            const trade = termdEventToTrade(payload);
            if (trade) handlers.onTrade?.(trade, frame);
          }
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  streamDerivatives(
    symbol: string,
    handlers: TermdDerivativeStreamHandlers,
    assetClass: TermdAssetClass = "eq",
  ): TermdStream | null {
    const normalized = symbol.trim().toUpperCase();
    if (typeof WebSocket === "undefined" || !normalized) return null;

    const socket = new WebSocket(termdWebSocketUrl(this.config.baseUrl), WS_SUBPROTOCOL);
    socket.binaryType = "arraybuffer";
    let closing = false;

    socket.addEventListener("open", () => {
      if (closing) {
        socket.close(1000, "terminal shutdown");
        return;
      }
      socket.send(encodeTermdSubscribeFrame(termdDerivativeChannels(normalized, assetClass)));
    });
    socket.addEventListener("message", (event) => {
      if (closing) return;
      void decodeWebSocketData(event.data)
        .then((bytes) => {
          if (closing) return;
          const frame = decodeTermdWireFrame(bytes);
          if (frame.frameType !== "snapshot" && frame.frameType !== "delta") return;
          const payload = decode(frame.payload);
          if (frame.channel.startsWith("options.")) {
            const response = payload as TermdOptionsResponse;
            const fallback = { symbol: normalized, expiry: "20JUN26", spot: 0, rows: [] };
            handlers.onOptions?.(
              detailSnapshot(response, termdOptionsResponseToUi(response) ?? fallback),
              frame,
            );
            return;
          }
          if (frame.channel.startsWith("vol-surface.")) {
            const response = payload as TermdVolSurfaceResponse;
            handlers.onVolSurface?.(
              detailSnapshot(response, termdVolSurfaceResponseToUi(response) ?? { expiries: [], strikes: [], iv: [] }),
              frame,
            );
          }
        })
        .catch((error) => handlers.onError?.(error));
    });
    socket.addEventListener("error", (event) => {
      if (!closing) handlers.onError?.(event);
    });
    socket.addEventListener("close", () => {
      if (!closing) handlers.onClose?.();
    });

    return {
      close: () => {
        closing = true;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
          socket.close(1000, "terminal shutdown");
        }
      },
      readyState: () => socket.readyState,
    };
  }

  private async fetchJson<T>(path: string, optional404 = false): Promise<T | null> {
    const headers: HeadersInit = { accept: "application/json" };
    if (this.config.token) headers.authorization = `Bearer ${this.config.token}`;
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      cache: "no-store",
      headers,
    });
    if (optional404 && response.status === 404) return null;
    if (!response.ok) throw new Error(`termd ${response.status} for ${path}`);
    return (await response.json()) as T;
  }
}

export function createTermdApiClient(
  config: TermdApiConfig | null = readTermdApiConfig(),
): TermdApiClient | null {
  return config ? new TermdApiClient(config) : null;
}

export function termdQuoteToUiQuote(
  payload: TermdQuotePayload,
  previous?: Quote,
): Quote | null {
  const symbol = asString(payload.symbol)?.toUpperCase();
  const bid = asNumber(payload.bid);
  const ask = asNumber(payload.ask);
  if (!symbol || bid === null || ask === null || bid <= 0 || ask <= 0) return null;

  const bidSz = asNumber(payload.bidSz) ?? 0;
  const askSz = asNumber(payload.askSz) ?? 0;
  const last = roundPrice((bid + ask) / 2);
  const previousLast = previous?.last ?? last;
  const chg = roundPrice(last - previousLast);
  const pct = previousLast > 0 ? roundPercent((chg / previousLast) * 100) : 0;
  const receivedAt = asString(payload.provenance?.receivedAt);
  const sourceLabel = asString(payload.provenance?.source)?.toUpperCase() ?? "TERMD";

  return {
    ticker: symbol,
    name: previous?.name ?? symbol,
    last,
    chg,
    pct,
    vol: formatSize(bidSz + askSz),
    bid: roundPrice(bid),
    ask: roundPrice(ask),
    source: {
      kind: dataSourceKindFromBackend(sourceLabel),
      label: sourceLabel,
      ...(receivedAt ? { receivedAt } : {}),
    },
  };
}

export function termdEventToQuote(event: unknown, previous?: Quote): Quote | null {
  const item = event as TermdQuoteEvent;
  if (asString(item.kind) !== "quote") return null;
  return termdQuoteToUiQuote(item, previous);
}

export function termdBarsResponseToChartData(response: TermdBarsResponse): number[] {
  return (response.bars ?? [])
    .map((bar) => bar as TermdBarEvent)
    .filter((bar) => asString(bar.kind) === "bar")
    .sort((left, right) => (asString(left.openTime) ?? "").localeCompare(asString(right.openTime) ?? ""))
    .map((bar) => asNumber(bar.close))
    .filter((close): close is number => close !== null);
}

export function termdEventToChartSnapshot(event: unknown): TermdChartSnapshot | null {
  const bar = event as TermdBarEvent;
  if (asString(bar.kind) !== "bar") return null;
  const close = asNumber(bar.close);
  if (close === null) return null;
  return eventDetailSnapshot(bar.provenance, [close], 60_000);
}

export function termdDepthResponseToUi(
  response: TermdDepthResponse,
  fallbackSymbol: string,
): DepthBookData | null {
  const depth = response.depth as TermdDepthEvent | undefined;
  const symbol = asString(depth?.symbol)?.toUpperCase() ?? fallbackSymbol.toUpperCase();
  if (!depth || asString(depth.kind) !== "depthUpdate") return null;
  return {
    symbol,
    bids: depthLevelsToUi(depth.bids),
    asks: depthLevelsToUi(depth.asks),
  };
}

export function termdEventToDepth(
  event: unknown,
  fallbackSymbol: string,
): TermdDepthSnapshot | null {
  const depth = event as TermdDepthEvent;
  const data = termdDepthResponseToUi({ depth }, fallbackSymbol);
  if (!data) return null;
  return eventDetailSnapshot(depth.provenance, data, 5_000);
}

export function termdTradesResponseToUi(response: TermdTradesResponse): Trade[] {
  return (response.trades ?? [])
    .map((trade) => termdTickToUiTrade(trade))
    .filter((trade): trade is Trade => trade !== null);
}

export function termdEventToTrade(event: unknown): TermdTradeSnapshot | null {
  const trade = termdTickToUiTrade(event);
  if (!trade) return null;
  const payload = event as TermdTickEvent;
  return eventDetailSnapshot(payload.provenance, trade, 5_000);
}

export function termdOptionsResponseToUi(
  response: TermdOptionsResponse,
  fallbackExpiry = "20JUN26",
): OptionChainData | null {
  const symbol = asString(response.symbol)?.toUpperCase();
  if (!symbol || !Array.isArray(response.contracts)) return null;
  const byStrike = new Map<number, { call?: TermdOptionContractPayload; put?: TermdOptionContractPayload }>();
  let expiry = fallbackExpiry;
  for (const raw of response.contracts) {
    const contract = raw as TermdOptionContractPayload;
    const strike = asNumber(contract.strike);
    const right = asString(contract.right);
    if (strike === null || (right !== "call" && right !== "put")) continue;
    expiry = formatExpiryLabel(asString(contract.expiry)) ?? expiry;
    const row = byStrike.get(strike) ?? {};
    if (right === "call") row.call = contract;
    if (right === "put") row.put = contract;
    byStrike.set(strike, row);
  }
  const rows = Array.from(byStrike.entries())
    .sort(([left], [right]) => left - right)
    .map(([strike, row]) => ({
      strike,
      callBid: optionNumber(row.call?.bid),
      callAsk: optionNumber(row.call?.ask),
      callLast: optionNumber(row.call?.mark),
      callIV: optionIv(row.call?.impliedVol),
      callDelta: 0,
      callOI: optionInteger(row.call?.openInterest),
      putBid: optionNumber(row.put?.bid),
      putAsk: optionNumber(row.put?.ask),
      putLast: optionNumber(row.put?.mark),
      putIV: optionIv(row.put?.impliedVol),
      putDelta: 0,
      putOI: optionInteger(row.put?.openInterest),
    }));
  return { symbol, expiry, spot: 0, rows };
}

export function termdVolSurfaceResponseToUi(
  response: TermdVolSurfaceResponse,
): TermdOptionSurface | null {
  if (!Array.isArray(response.points)) return null;
  const records = response.points
    .map((point) => {
      const payload = point as TermdVolSurfacePointPayload;
      const expiry = formatExpiryLabel(asString(payload.expiry));
      const strike = asNumber(payload.strike);
      const callIv = asNumber(payload.callIv);
      const putIv = asNumber(payload.putIv);
      if (!expiry || strike === null || callIv === null || putIv === null) return null;
      return { expiry, strike, iv: roundPercent(((callIv + putIv) / 2) * 100) };
    })
    .filter((record): record is { expiry: string; strike: number; iv: number } => record !== null);
  if (records.length === 0) return null;
  const expiries = Array.from(new Set(records.map((record) => record.expiry)));
  const strikes = Array.from(new Set(records.map((record) => record.strike))).sort((a, b) => a - b);
  const byKey = new Map(records.map((record) => [`${record.expiry}:${record.strike}`, record.iv]));
  return {
    expiries,
    strikes,
    iv: expiries.map((expiry) => strikes.map((strike) => byKey.get(`${expiry}:${strike}`) ?? 0)),
  };
}

export function termdMarketsOverviewToUi(
  response: TermdMarketsOverviewResponse,
): TermdMarketsOverview | null {
  if (!Array.isArray(response.cells)) return null;

  const cells = response.cells
    .map((cell) => termdMarketOverviewCellToUi(cell))
    .filter((cell): cell is TermdMarketOverviewCell => cell !== null);
  const names = new Map(cells.map((cell) => [cell.symbol, cell.name]));
  const quotes = (response.quotes ?? [])
    .map((quote) => {
      const mapped = termdQuoteToUiQuote(quote);
      return mapped ? { ...mapped, name: names.get(mapped.ticker) ?? mapped.name } : null;
    })
    .filter((quote): quote is Quote => quote !== null);

  return {
    universe: asString(response.universe) ?? "unknown",
    asOf: asString(response.asOf),
    cells,
    quotes,
  };
}

function termdMarketOverviewCellToUi(cell: unknown): TermdMarketOverviewCell | null {
  const payload = cell as TermdMarketOverviewCellPayload;
  const symbol = asString(payload.symbol)?.toUpperCase();
  const name = asString(payload.name);
  const sector = asString(payload.sector)?.toUpperCase();
  const weight = asNumber(payload.weight);
  if (!symbol || !name || !sector || weight === null) return null;

  const quote = payload.quote ? termdQuoteToUiQuote(payload.quote) : null;
  const backendPct = asNumber(payload.pct);
  return {
    symbol,
    name,
    sector,
    weight,
    pct: backendPct ?? quote?.pct ?? 0,
    source: quote?.source ?? dataSourceStateFromAvailability(asString(payload.availability)),
  };
}

export function encodeTermdSubscribeFrame(channels: readonly string[]): Uint8Array {
  return encode({
    version: WIRE_VERSION,
    frameType: "sub",
    channel: "control",
    seq: Date.now(),
    payload: encode({
      channels,
      cursors: [],
    }),
  });
}

export function decodeTermdWireFrame(bytes: Uint8Array): TermdWireFrame {
  const frame = decode(bytes) as TermdWireFramePayload;
  const version = asNumber(frame.version);
  const frameType = asString(frame.frameType);
  const channel = asString(frame.channel);
  const seq = asNumber(frame.seq);
  const payload = frame.payload;
  if (version !== WIRE_VERSION) throw new Error(`unsupported termd wire version ${version ?? "unknown"}`);
  if (!frameType || !STREAM_FRAME_TYPES.has(frameType)) {
    throw new Error(`unsupported termd frame type ${frameType ?? "unknown"}`);
  }
  if (!channel || seq === null || !(payload instanceof Uint8Array)) {
    throw new Error("malformed termd wire frame");
  }
  return {
    version,
    frameType: frameType as TermdWireFrameType,
    channel,
    seq,
    payload,
  };
}

export function termdWebSocketUrl(baseUrl: string, path = "/api/v1/ws"): string {
  const fullPath = `${stripTrailingSlash(baseUrl)}${path}`;
  if (fullPath.startsWith("https://")) return `wss://${fullPath.slice("https://".length)}`;
  if (fullPath.startsWith("http://")) return `ws://${fullPath.slice("http://".length)}`;
  if (typeof window === "undefined") return fullPath;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${fullPath.startsWith("/") ? fullPath : `/${fullPath}`}`;
}

export function termdDetailChannels(
  symbol: string,
  assetClass: TermdAssetClass = "eq",
): [string, string, string] {
  const normalized = symbol.trim().toUpperCase();
  return [
    `bar.${assetClass}.${normalized}.m1`,
    `depth.${assetClass}.${normalized}`,
    `tick.${assetClass}.${normalized}`,
  ];
}

export function termdDerivativeChannels(
  symbol: string,
  assetClass: TermdAssetClass = "eq",
): [string, string] {
  const normalized = symbol.trim().toUpperCase();
  return [`options.${assetClass}.${normalized}`, `vol-surface.${assetClass}.${normalized}`];
}

export function termdNewsChannels(symbols: readonly string[] = []): string[] {
  const channels = ["news.global"];
  for (const symbol of normalizeSymbols(symbols)) channels.push(`news.symbol.${symbol}`);
  return channels;
}

export function termdMacroSeriesChannels(ids: readonly string[]): string[] {
  return Array.from(
    new Set(
      ids
        .map((id) => id.trim())
        .filter(Boolean)
        .map((id) => `macro.series.${id}`),
    ),
  );
}

export function termdPredictionChannels(
  markets: readonly Pick<TermdPredictionMarket, "venue" | "marketId">[],
): string[] {
  const channels: string[] = [];
  const seen = new Set<string>();
  for (const market of markets) {
    const venue = market.venue.trim().toLowerCase();
    const marketId = market.marketId.trim();
    if (!venue || !marketId) continue;
    const channel = `prediction.${venue}.${marketId}`;
    if (seen.has(channel)) continue;
    seen.add(channel);
    channels.push(channel);
  }
  return channels;
}

export function termdEventToNewsItem(event: unknown): NewsItem | null {
  const item = event as TermdNewsEvent;
  if (asString(item.kind) !== "news") return null;
  const id = asString(item.id);
  const headline = asString(item.headline);
  if (!id || !headline) return null;

  const categories = asStringArray(item.categories);
  const symbols = asStringArray(item.symbols).map((symbol) => symbol.toUpperCase());
  const body = cleanNewsBody(asString(item.body));
  const url = asString(item.url);
  const source = newsSourceLabel(asString(item.provenance?.source), categories, symbols);

  return {
    id,
    time: publishedTime(asString(item.published)),
    src: source,
    headline: headline.toUpperCase(),
    tone: toneFromSentiment(asString(item.sentiment)),
    cat: categoryFromBackend(categories),
    body: body
      ? [body]
      : [`No story summary was supplied by ${source}${url ? "; open the source link for the full article." : "."}`],
    symbols,
    ...(url ? { url } : {}),
  };
}

function cleanNewsBody(value: string | null): string | null {
  if (!value) return null;
  const text = value
    .replace(/<!\[CDATA\[/gi, "")
    .replace(/\]\]>/g, "")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/p>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 0 ? text : null;
}

function newsSourceLabel(
  source: string | null,
  categories: readonly string[],
  symbols: readonly string[],
): string {
  const normalizedSource = source?.toLowerCase() ?? "";
  const normalizedCategories = categories.map((category) => category.toLowerCase());
  const symbolCategory = normalizedCategories.find((category) => category.startsWith("symbol.yahoo."));
  if (normalizedSource === "yahoo-finance" || symbolCategory) {
    const symbol = symbols[0] ?? symbolCategory?.replace("symbol.yahoo.", "").toUpperCase();
    return symbol ? `YH ${symbol}` : "YAHOO";
  }
  if (normalizedSource === "federal-reserve") return "FED";
  if (normalizedSource === "ecb") return "ECB";
  if (normalizedSource === "gdelt") return "GDELT";

  const category = normalizedCategories[0] ?? "";
  if (category.includes("bbc-business")) return "BBC BUS";
  if (category.includes("bbc-world")) return "BBC WORLD";
  if (category.includes("bbc-technology")) return "BBC TECH";
  if (category.includes("npr-business")) return "NPR BUS";
  if (category.includes("marketwatch")) return "MW TOP";
  if (category.includes("ft-markets")) return "FT MKT";
  if (category.includes("wsj-markets")) return "WSJ MKT";
  if (category.includes("wsj-business")) return "WSJ BUS";
  if (category.includes("wsj-world")) return "WSJ WLD";
  if (category.includes("eia")) return "EIA";
  if (category.includes("coindesk")) return "COINDESK";
  if (category.includes("cointelegraph")) return "CT CRYP";
  if (category.includes("aljazeera")) return "ALJAZ";
  if (category.includes("fed-")) return "FED";
  if (category.includes("ecb-")) return "ECB";

  return source?.toUpperCase() ?? "TERMD";
}

export function termdRssFeedToUi(feed: unknown): TermdRssFeed | null {
  const item = feed as TermdRssFeedPayload;
  const id = asString(item.id);
  const userId = asString(item.userId);
  const name = asString(item.name);
  const url = asString(item.url);
  const pollSecs = asInteger(item.pollSecs);
  if (!id || !userId || !name || !url || pollSecs === null || pollSecs <= 0) return null;
  return {
    id,
    userId,
    name,
    url,
    categories: asStringArray(item.categories),
    pollSecs,
    symbolTagging: rssSymbolTagging(asString(item.symbolTagging)),
    manualSymbols: asStringArray(item.manualSymbols).map((symbol) => symbol.toUpperCase()),
  };
}

export function termdWatchlistToUi(watchlist: unknown): TermdWatchlist | null {
  const item = watchlist as TermdWatchlistPayload;
  const id = asString(item.id);
  const userId = asString(item.userId);
  const name = asString(item.name);
  if (!id || !userId || !name) return null;
  return {
    id,
    userId,
    name,
    symbols: asStringArray(item.symbols).map((symbol) => symbol.toUpperCase()),
  };
}

export function termdUserPositionToUi(position: unknown): TermdUserPosition | null {
  const item = position as TermdPositionPayload;
  const userId = asString(item.userId);
  const symbol = asString(item.symbol)?.toUpperCase();
  const qty = asNumber(item.qty);
  const avgPx = asNumber(item.avgPx);
  const marketPx = asNumber(item.marketPx);
  if (!userId || !symbol || qty === null || avgPx === null || marketPx === null) return null;
  return { userId, symbol, qty, avgPx, marketPx };
}

export function termdUserAlertToUi(alert: unknown): TermdUserAlert | null {
  const item = alert as TermdAlertPayload;
  const id = asString(item.id);
  const userId = asString(item.userId);
  const symbol = asString(item.symbol)?.toUpperCase();
  const condition = userAlertCondition(asString(item.condition));
  const threshold = asNumber(item.threshold);
  if (!id || !userId || !symbol || !condition || threshold === null || threshold <= 0) return null;
  return {
    id,
    userId,
    symbol,
    condition,
    threshold,
    active: item.active === true,
  };
}

export function termdEconomicEventsResponseToUi(
  response: TermdEventsResponse,
  recentPrintsResponse?: TermdEventsResponse | null,
): TermdEconomicCalendarSnapshot | null {
  const items = (response.events ?? [])
    .map((event) => termdEconomicEventToUi(event))
    .filter((item): item is EventItem => item !== null);
  const recentPrints = recentPrintsResponse
    ? (recentPrintsResponse.events ?? [])
        .map((event) => termdEconomicEventToUi(event))
        .filter((item): item is EventItem => item !== null)
        .filter(hasActual)
    : items.filter(hasActual);
  if (items.length === 0 && recentPrints.length === 0) return null;
  return {
    events: items.filter((item) => !hasActual(item)),
    recentPrints,
  };
}

export function termdEconomicEventToUi(event: unknown): EventItem | null {
  const item = event as TermdEconomicEvent;
  if (asString(item.kind) !== "econEvent") return null;
  const ccy = asString(item.ccy)?.toUpperCase();
  const label = asString(item.label);
  if (!ccy || !label) return null;
  const actual = dashString(item.actual);
  return {
    time: economicTimeLabel(asString(item.time), actual !== undefined),
    ccy,
    imp: importance(item.importance),
    label,
    fcst: dashString(item.forecast) ?? "-",
    prev: dashString(item.previous) ?? "-",
    actual,
    source: dataSourceFromPayload("live", item.provenance),
  };
}

export function termdCalendarEventToEarning(event: unknown): Earning | null {
  const item = event as TermdCalendarEventPayload;
  if (asString(item.kind) !== "earnings") return null;
  const symbol = asString(item.symbol)?.toUpperCase();
  const title = asString(item.title);
  if (!symbol || !title) return null;
  const forecast = parseForecastFields(asString(item.forecast));
  return {
    date: dateLabel(asString(item.time)),
    whenStr: earningsWhen(asString(item.previous)),
    symbol,
    name: earningsName(title, symbol),
    consensusEps: forecast.eps ?? 0,
    consensusRev: forecast.revenue ?? "N/A",
    prevEps: forecast.prevEps ?? 0,
    reported: asNumber(item.actual) ?? undefined,
    source: dataSourceFromPayload("live", item.provenance),
  };
}

export function termdFilingEventToUi(event: unknown): TermdFiling | null {
  const item = event as TermdFilingEventPayload;
  if (asString(item.kind) !== "filing") return null;
  const accession = asString(item.accession);
  const cik = asInteger(item.cik);
  const company = asString(item.company);
  const form = asString(item.form)?.toUpperCase();
  const filed = asString(item.filed);
  const primaryDocUrl = asString(item.primaryDocUrl);
  if (!accession || cik === null || !company || !form || !filed || !primaryDocUrl) return null;
  return {
    accession,
    cik,
    company,
    form,
    filed,
    period: asString(item.period),
    primaryDocUrl,
    symbols: asStringArray(item.symbols).map((symbol) => symbol.toUpperCase()),
    source: dataSourceFromPayload("live", item.provenance),
  };
}

export function termdFilingDetailResponseToUi(
  response: TermdFilingDetailResponse,
): TermdFilingDetail | null {
  const filing = termdFilingEventToUi(response.filing);
  if (!filing) return null;
  return {
    filing,
    facts: (response.facts ?? [])
      .map((fact) => termdXbrlFactToUi(fact))
      .filter((fact): fact is TermdXbrlFact => fact !== null),
  };
}

export function termdInsiderTradeEventToUi(event: unknown): TermdInsiderTrade | null {
  const item = event as TermdInsiderTradePayload;
  if (asString(item.kind) !== "insiderTrade") return null;
  const accession = asString(item.accession);
  const cik = asInteger(item.cik);
  const symbol = asString(item.symbol)?.toUpperCase();
  const person = asString(item.person);
  const relationship = asString(item.relationship);
  const side = insiderSide(asString(item.side));
  const shares = asNumber(item.shares);
  const traded = asString(item.traded);
  if (
    !accession ||
    cik === null ||
    !symbol ||
    !person ||
    !relationship ||
    shares === null ||
    !traded
  ) {
    return null;
  }
  return {
    accession,
    cik,
    symbol,
    person,
    relationship,
    side,
    shares,
    price: asNumber(item.price),
    traded,
    source: dataSourceFromPayload("live", item.provenance),
  };
}

export function termdInstitutionalHoldingToUi(
  holding: unknown,
): TermdInstitutionalHolding | null {
  const item = holding as TermdInstitutionalHoldingPayload;
  const accession = asString(item.accession);
  const cik = asInteger(item.cik);
  const quarter = asDateString(item.quarter);
  const issuer = asString(item.issuer);
  const classTitle = asString(item.classTitle);
  const cusip = asString(item.cusip)?.toUpperCase();
  const value = asNumber(item.value);
  const shares = asNumber(item.shares);
  const shareType = asString(item.shareType);
  if (
    !accession ||
    cik === null ||
    !quarter ||
    !issuer ||
    !classTitle ||
    !cusip ||
    value === null ||
    shares === null ||
    !shareType
  ) {
    return null;
  }
  return {
    accession,
    cik,
    quarter,
    issuer,
    classTitle,
    cusip,
    value,
    shares,
    shareType,
    putCall: asString(item.putCall),
    investmentDiscretion: asString(item.investmentDiscretion),
    source: dataSourceFromPayload("live", item.provenance),
  };
}

export function termdEventToPredictionMarket(event: unknown): TermdPredictionMarket | null {
  const item = event as TermdPredictionEvent;
  if (asString(item.kind) !== "predictionQuote") return null;
  const venue = asString(item.venue)?.toUpperCase();
  const marketId = asString(item.marketId);
  const question = asString(item.question);
  if (!venue || !marketId || !question) return null;
  if (isCompositePredictionMarket(venue, marketId, question)) return null;

  const bid = probabilityOrNull(item.bid);
  const ask = probabilityOrNull(item.ask);
  const last = probabilityOrNull(item.last);
  const mid = bid !== null && ask !== null ? roundPercent((bid + ask) / 2) : last;
  const spread = bid !== null && ask !== null ? roundPercent(Math.max(0, ask - bid)) : null;

  return {
    venue,
    marketId,
    question,
    outcome: asString(item.outcome)?.toUpperCase() ?? "-",
    bid,
    ask,
    last,
    mid,
    spread,
    volume: asNumber(item.volume),
    resolved: item.resolved === true,
    resolution: asString(item.resolution),
    source: asString(item.provenance?.source)?.toUpperCase() ?? venue,
    receivedAt: asString(item.provenance?.receivedAt) ?? "",
  };
}

function isCompositePredictionMarket(venue: string, marketId: string, question: string): boolean {
  if (venue === "KALSHI" && marketId.toUpperCase().startsWith("KXMVE")) return true;
  const legCount = question
    .split(",")
    .filter((part) => /^\s*(yes|no)\s+/i.test(part))
    .length;
  return legCount > 1;
}

export function termdSeriesResponseToUiSeries(response: TermdSeriesResponse): TermdMacroSeries | null {
  return termdSeriesPayloadToUiSeries(response);
}

function termdSeriesPayloadToUiSeries(
  response: unknown,
  fallbackId = "",
): TermdMacroSeries | null {
  const payload = response as TermdSeriesResponse;
  const id = asString(payload.id) ?? fallbackId;
  if (!id || !Array.isArray(payload.points)) return null;
  const points = payload.points
    .map((point) => termdSeriesPointToUiPoint(point, id))
    .filter((point): point is TermdMacroPoint => point !== null)
    .sort((left, right) => left.time.localeCompare(right.time));
  return points.length > 0 ? { id, points } : null;
}

export function termdRatesResponseToUi(response: TermdRatesResponse): TermdRatesSnapshot | null {
  const curve = (response.curve ?? [])
    .map((point) => termdRateCurvePointToUi(point))
    .filter((point): point is YieldCurvePoint => point !== null);
  const policyRates = (response.policyRates ?? [])
    .map((row) => termdPolicyRateToUi(row))
    .filter((row): row is CbRate => row !== null);
  if (curve.length === 0 && policyRates.length === 0) return null;
  return {
    currency: asString(response.currency)?.toUpperCase() ?? "USD",
    asOf: asString(response.asOf),
    curve,
    policyRates,
  };
}

export function termdFixedIncomeResponseToUi(
  response: TermdFixedIncomeResponse,
): TermdFixedIncomeSnapshot | null {
  const bonds = (response.bonds ?? [])
    .map((row) => termdBondToUi(row))
    .filter((row): row is BondRow => row !== null);
  const cds = (response.cds ?? [])
    .map((row) => termdCdsToUi(row))
    .filter((row): row is CdsRow => row !== null);
  const indices = (response.indices ?? [])
    .map((row) => termdCreditIndexToUi(row))
    .filter((row): row is CreditIndexRow => row !== null);
  if (bonds.length === 0 && cds.length === 0 && indices.length === 0) return null;
  return {
    asOf: asString(response.asOf),
    bonds,
    cds,
    indices,
  };
}

export function termdFxResponseToUi(response: TermdFxResponse): TermdFxSnapshot | null {
  const ccys = (response.ccys ?? [])
    .map((ccy) => asString(ccy)?.toUpperCase())
    .filter((ccy): ccy is string => ccy !== null);
  if (ccys.length === 0 || !Array.isArray(response.matrix)) return null;

  const matrix = response.matrix.map((row) =>
    Array.isArray(row)
      ? row.map((value) => {
          const parsed = asNumber(value);
          return parsed === null ? null : parsed;
        })
      : [],
  );
  const quotes = (response.quotes ?? [])
    .map((quote) => termdQuoteToUiQuote(quote))
    .filter((quote): quote is Quote => quote !== null);

  return {
    asOf: asString(response.asOf),
    ccys,
    matrix,
    quotes,
  };
}

export function termdCommoditiesResponseToUi(
  response: TermdCommoditiesResponse,
): TermdCommoditiesSnapshot | null {
  const frontMonths = termdQuotePayloadsToUi(response.frontMonths);
  const energy = termdQuotePayloadsToUi(response.energy);
  const metals = termdQuotePayloadsToUi(response.metals);
  const ags = termdQuotePayloadsToUi(response.ags);
  if (
    frontMonths.length === 0 &&
    energy.length === 0 &&
    metals.length === 0 &&
    ags.length === 0
  ) {
    return null;
  }
  return {
    asOf: asString(response.asOf),
    frontMonths,
    energy,
    metals,
    ags,
  };
}

export function termdScreenResponseToUi(response: TermdScreenResponse): TermdScreenSnapshot | null {
  const screen = asString(response.screen)?.toUpperCase();
  if (!screen) return null;
  const quotes = (response.quotes ?? [])
    .map((quote) => termdQuoteToUiQuote(quote))
    .filter((quote): quote is Quote => quote !== null);
  const news = (response.news?.events ?? [])
    .map((event) => termdEventToNewsItem(event))
    .filter((item): item is NewsItem => item !== null);
  const earnings = (response.earnings?.events ?? [])
    .map((event) => termdCalendarEventToEarning(event))
    .filter((event): event is Earning => event !== null);
  const datasets = (response.datasets ?? [])
    .map((dataset) => termdScreenDatasetMetaToUi(dataset))
    .filter((dataset): dataset is TermdScreenDatasetMeta => dataset !== null);

  return {
    screen,
    asOf: asString(response.asOf),
    datasets,
    quotes,
    marketsOverview: response.marketsOverview
      ? termdMarketsOverviewToUi(response.marketsOverview)
      : null,
    rates: response.rates ? termdRatesResponseToUi(response.rates) : null,
    fixedIncome: response.fixedIncome ? termdFixedIncomeResponseToUi(response.fixedIncome) : null,
    fx: response.fx ? termdFxResponseToUi(response.fx) : null,
    commodities: response.commodities
      ? termdCommoditiesResponseToUi(response.commodities)
      : null,
    news,
    economicCalendar: response.economicEvents || response.recentPrints
      ? termdEconomicEventsResponseToUi(
          response.economicEvents ?? { events: [] },
          response.recentPrints,
        )
      : null,
    earnings,
  };
}

function termdQuotePayloadsToUi(payloads: readonly TermdQuotePayload[] | undefined): Quote[] {
  return (payloads ?? [])
    .map((quote) => termdQuoteToUiQuote(quote))
    .filter((quote): quote is Quote => quote !== null);
}

function termdScreenDatasetMetaToUi(meta: unknown): TermdScreenDatasetMeta | null {
  const payload = meta as TermdScreenDatasetMetaPayload;
  const key = asString(payload.key);
  if (!key) return null;
  const staleAfterMs = asNumber(payload.staleAfterMs);
  const sourceLabel =
    asString(payload.source)?.toUpperCase() ??
    sourceLabelFromAvailability(asString(payload.availability));
  return {
    key,
    source: {
      kind: dataSourceKindFromAvailability(asString(payload.availability)),
      label: sourceLabel,
      ...(asString(payload.asOf) ? { receivedAt: asString(payload.asOf)! } : {}),
    },
    asOf: asString(payload.asOf),
    staleAfterMs: staleAfterMs ?? 0,
  };
}

function termdBondToUi(row: unknown): BondRow | null {
  const payload = row as TermdBondPayload;
  const issuer = asString(payload.issuer)?.toUpperCase();
  const desc = asString(payload.desc);
  const maturity = asString(payload.maturity);
  const rating = asString(payload.rating);
  if (!issuer || !desc || !maturity || !rating) return null;
  return {
    issuer,
    desc,
    cpn: asNumber(payload.cpn),
    maturity,
    px: asNumber(payload.px),
    ytm: asNumber(payload.ytm),
    oas: asInteger(payload.oas),
    rating,
    source: dataSourceFromPayload(payload.availability, payload.provenance),
  };
}

function termdCdsToUi(row: unknown): CdsRow | null {
  const payload = row as TermdCdsPayload;
  const name = asString(payload.name)?.toUpperCase();
  const region = asString(payload.region);
  const rating = asString(payload.rating);
  if (!name || !region || !rating) return null;
  return {
    name,
    region,
    rating,
    px: asNumber(payload.px),
    chg: asNumber(payload.chg),
    ytd: asNumber(payload.ytd),
    source: dataSourceFromPayload(payload.availability, payload.provenance),
  };
}

function termdCreditIndexToUi(row: unknown): CreditIndexRow | null {
  const payload = row as TermdCreditIndexPayload;
  const name = asString(payload.name)?.toUpperCase();
  const desc = asString(payload.desc);
  if (!name || !desc) return null;
  return {
    name,
    desc,
    last: asNumber(payload.last),
    chg: asNumber(payload.chg),
    ytd: asNumber(payload.ytd),
    source: dataSourceFromPayload(payload.availability, payload.provenance),
  };
}

function termdXbrlFactToUi(fact: unknown): TermdXbrlFact | null {
  const payload = fact as TermdXbrlFactPayload;
  const concept = asString(payload.concept);
  const value = asNumber(payload.value);
  const unit = asString(payload.unit);
  if (!concept || value === null || !unit) return null;
  return {
    concept,
    value,
    unit,
    periodStart: asString(payload.periodStart),
    periodEnd: asString(payload.periodEnd),
  };
}

function browserEnv(): Env {
  return ((import.meta as unknown as { env?: Env }).env ?? {}) as Env;
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function queryPath(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function parseList(
  value: string | undefined,
  fallback: readonly string[],
  uppercase: boolean,
): readonly string[] {
  const symbols = (value ?? "")
    .split(",")
    .map((symbol) => symbol.trim())
    .filter(Boolean);
  if (symbols.length === 0) return fallback;
  const normalized = symbols.map((symbol) => (uppercase ? symbol.toUpperCase() : symbol));
  return Array.from(new Set(normalized));
}

function normalizeSymbols(symbols: readonly string[]): string[] {
  return Array.from(
    new Set(
      symbols
        .map((symbol) => symbol.trim().toUpperCase())
        .filter(Boolean),
    ),
  );
}

function macroSeriesIdFromChannel(channel: string): string | null {
  return channel.startsWith("macro.series.") ? channel.slice("macro.series.".length) : null;
}

function numberFromString(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asDateString(value: unknown): string | null {
  const text = asString(value);
  if (text) return text;
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [yearValue, ordinalValue] = value;
  const year = asInteger(yearValue);
  const ordinal = asInteger(ordinalValue);
  if (year === null || ordinal === null || ordinal < 1 || ordinal > 366) return null;
  const date = new Date(Date.UTC(year, 0, ordinal));
  if (date.getUTCFullYear() !== year) return null;
  return `${year}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(
    date.getUTCDate(),
  ).padStart(2, "0")}`;
}

function asNumber(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function asInteger(value: unknown): number | null {
  const parsed = asNumber(value);
  return parsed === null ? null : Math.trunc(parsed);
}

function dataSourceKindFromBackend(source: string): DataSourceState["kind"] {
  return source.toLowerCase() === "mock" ? "mock" : "live";
}

function dataSourceFromPayload(
  availability: unknown,
  provenance: { source?: unknown; receivedAt?: unknown } | undefined,
): DataSourceState {
  const source = asString(provenance?.source);
  const receivedAt = asString(provenance?.receivedAt) ?? undefined;
  if (!source) return dataSourceStateFromAvailability(asString(availability));
  return {
    kind: dataSourceKindFromBackend(source),
    label: source.toUpperCase(),
    receivedAt,
  };
}

function detailSnapshot<T>(
  payload: {
    availability?: unknown;
    source?: unknown;
    asOf?: unknown;
    staleAfterMs?: unknown;
  },
  data: T,
): TermdDetailSnapshot<T> {
  const asOf = asString(payload.asOf);
  const staleAfterMs = asNumber(payload.staleAfterMs) ?? 0;
  return {
    data,
    source: dataSourceFromAvailabilitySource(payload.availability, payload.source, asOf),
    asOf,
    staleAfterMs,
  };
}

function eventDetailSnapshot<T>(
  provenance: { source?: unknown; receivedAt?: unknown } | undefined,
  data: T,
  staleAfterMs: number,
): TermdDetailSnapshot<T> {
  const asOf = asString(provenance?.receivedAt);
  return {
    data,
    source: dataSourceFromPayload("live", provenance),
    asOf,
    staleAfterMs,
  };
}

function dataSourceFromAvailabilitySource(
  availability: unknown,
  source: unknown,
  asOf: string | null,
): DataSourceState {
  const availabilityText = asString(availability);
  const sourceText = asString(source);
  const fallback = dataSourceStateFromAvailability(availabilityText);
  const label = sourceText?.toUpperCase() ?? fallback.label;
  const kind = availabilityText
    ? fallback.kind
    : sourceText
      ? dataSourceKindFromBackend(sourceText)
      : fallback.kind;
  return {
    kind,
    label,
    ...(asOf ? { receivedAt: asOf } : {}),
  };
}

function dataSourceStateFromAvailability(availability: string | null): DataSourceState {
  switch (availability) {
    case "mock":
      return { kind: "mock", label: "MOCK" };
    case "live":
      return { kind: "live", label: "TERMD" };
    case "stale":
      return { kind: "stale", label: "STALE" };
    default:
      return { kind: "unavailable", label: "N/A" };
  }
}

function dataSourceKindFromAvailability(availability: string | null): DataSourceState["kind"] {
  return dataSourceStateFromAvailability(availability).kind;
}

function sourceLabelFromAvailability(availability: string | null): string {
  return dataSourceStateFromAvailability(availability).label;
}

function probabilityOrNull(value: unknown): number | null {
  const parsed = asNumber(value);
  if (parsed === null || parsed < 0 || parsed > 1) return null;
  return roundPercent(parsed);
}

function termdSeriesPointToUiPoint(point: unknown, fallbackId: string): TermdMacroPoint | null {
  const payload = point as TermdSeriesPointPayload;
  const id = asString(payload.id) ?? fallbackId;
  const time = asString(payload.time);
  const value = asNumber(payload.value);
  if (!id || !time || value === null) return null;
  return {
    id,
    time,
    value,
    unit: asString(payload.unit) ?? "",
    source: asString(payload.provenance?.source)?.toUpperCase() ?? "TERMD",
  };
}

function termdRateCurvePointToUi(point: unknown): YieldCurvePoint | null {
  const payload = point as TermdRateCurvePointPayload;
  const tenor = asString(payload.tenor)?.toUpperCase();
  const yld = asNumber(payload.yld);
  if (!tenor) return null;
  return {
    tenor,
    yld: yld === null ? null : Number(yld.toFixed(3)),
    source: dataSourceFromPayload(payload.availability, payload.provenance),
  };
}

function termdPolicyRateToUi(row: unknown): CbRate | null {
  const payload = row as TermdPolicyRatePayload;
  const ccy = asString(payload.ccy)?.toUpperCase();
  const bank = asString(payload.bank);
  const rate = asNumber(payload.rate);
  if (!ccy || !bank) return null;
  const observedAt = asString(payload.observedAt);
  return {
    ccy,
    bank,
    rate: rate === null ? null : Number(rate.toFixed(3)),
    lastMove: observedAt ? observedAt.slice(0, 10) : "N/A",
    next: "N/A",
    bias: "HOLD",
    source: dataSourceFromPayload(payload.availability, payload.provenance),
  };
}

function depthLevelsToUi(value: unknown): DepthBookData["bids"] {
  if (!Array.isArray(value)) return [];
  return value
    .map((level) => {
      const payload = level as TermdDepthLevelPayload;
      const px = asNumber(payload.px);
      const qty = asNumber(payload.qty);
      return px !== null && qty !== null ? { px, qty } : null;
    })
    .filter((level): level is { px: number; qty: number } => level !== null);
}

function termdTickToUiTrade(value: unknown): Trade | null {
  const payload = value as TermdTickEvent;
  if (asString(payload.kind) !== "tick") return null;
  const px = asNumber(payload.px);
  const qty = asNumber(payload.qty);
  if (px === null || qty === null) return null;
  return {
    time: tradeTimeLabel(asString(payload.provenance?.receivedAt)),
    px,
    qty,
    side: tradeSide(asString(payload.side)),
  };
}

function tradeSide(value: string | null): Trade["side"] {
  return value === "sell" ? "S" : "B";
}

function insiderSide(value: string | null): TermdInsiderTrade["side"] {
  if (value === "buy" || value === "sell") return value;
  return "unknown";
}

function rssSymbolTagging(value: string | null): TermdRssFeed["symbolTagging"] {
  if (value === "off" || value === "manual") return value;
  return "auto";
}

function userAlertCondition(value: string | null): TermdUserAlert["condition"] | null {
  switch (value) {
    case ">=":
    case "above":
    case "price-above":
    case "gte":
      return ">=";
    case "<=":
    case "below":
    case "price-below":
    case "lte":
      return "<=";
    default:
      return null;
  }
}

function optionNumber(value: unknown): number {
  return roundPrice(asNumber(value) ?? 0);
}

function optionInteger(value: unknown): number {
  return Math.max(0, Math.round(asNumber(value) ?? 0));
}

function optionIv(value: unknown): number {
  const parsed = asNumber(value) ?? 0;
  return roundPercent(parsed * 100);
}

function formatExpiryLabel(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.toUpperCase();
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][date.getUTCMonth()];
  const year = String(date.getUTCFullYear()).slice(-2);
  return `${day}${month}${year}`;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => asString(entry))
    .filter((entry): entry is string => entry !== null);
}

function roundPrice(value: number): number {
  const abs = Math.abs(value);
  return Number(value.toFixed(abs >= 10 ? 2 : abs >= 1 ? 4 : 5));
}

function roundPercent(value: number): number {
  return Number(value.toFixed(2));
}

function formatSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "-";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(Math.round(value));
}

function publishedTime(value: string | null): string {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function economicTimeLabel(value: string | null, includeWeekday: boolean): string {
  if (!value) return includeWeekday ? "--:-- ---" : "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return includeWeekday ? "--:-- ---" : "--:--";
  const time = `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}`;
  if (!includeWeekday) return time;
  return `${time} ${["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][date.getUTCDay()]}`;
}

function tradeTimeLabel(value: string | null): string {
  if (!value) return "--:--:--.---";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--.---";
  return (
    `${String(date.getUTCHours()).padStart(2, "0")}:` +
    `${String(date.getUTCMinutes()).padStart(2, "0")}:` +
    `${String(date.getUTCSeconds()).padStart(2, "0")}.` +
    String(date.getUTCMilliseconds()).padStart(3, "0")
  );
}

function dateLabel(value: string | null): string {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}

function dashString(value: unknown): string | undefined {
  const text = asString(value);
  return text ?? undefined;
}

function hasActual(item: EventItem): boolean {
  return item.actual !== undefined && item.actual !== "-";
}

function importance(value: unknown): 1 | 2 | 3 {
  const parsed = asNumber(value);
  if (parsed === 1 || parsed === 2 || parsed === 3) return parsed;
  return 1;
}

function earningsWhen(value: string | null): string {
  const normalized = value?.toUpperCase();
  return normalized === "BMO" || normalized === "AMC" ? normalized : "-";
}

function earningsName(title: string, symbol: string): string {
  const marker = title.toLowerCase().indexOf(" earnings");
  const candidate = marker > 0 ? title.slice(0, marker) : title;
  return candidate.trim() || symbol;
}

function parseForecastFields(value: string | null): {
  eps: number | null;
  prevEps: number | null;
  revenue: string | null;
} {
  const fields = new Map<string, string>();
  for (const part of value?.split(";") ?? []) {
    const [rawKey, ...rawValue] = part.split("=");
    const key = rawKey?.trim().toLowerCase();
    const fieldValue = rawValue.join("=").trim();
    if (key && fieldValue) fields.set(key, fieldValue);
  }
  return {
    eps: asNumber(fields.get("eps")),
    prevEps: asNumber(fields.get("prev_eps") ?? fields.get("prevEps")),
    revenue: revenueLabel(asNumber(fields.get("revenue"))),
  };
}

function revenueLabel(value: number | null): string | null {
  if (value === null) return null;
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${value.toFixed(0)}`;
}

function toneFromSentiment(value: string | null): NewsItem["tone"] {
  switch (value) {
    case "positive":
      return "pos";
    case "negative":
      return "neg";
    case "alert":
      return "alert";
    default:
      return "neutral";
  }
}

function categoryFromBackend(categories: readonly string[]): NewsItem["cat"] | undefined {
  const normalized = categories.map((category) => category.toLowerCase());
  if (normalized.some((category) => category.includes("econ") || category.includes("macro"))) {
    return "ECON";
  }
  if (normalized.some((category) => category.includes("fx"))) return "FX";
  if (normalized.some((category) => category.includes("equity") || category.includes("company"))) {
    return "EQ";
  }
  if (normalized.some((category) => category.includes("fixed") || category.includes("rates"))) {
    return "FI";
  }
  if (normalized.some((category) => category.includes("commodity") || category.includes("energy"))) {
    return "CMDTY";
  }
  if (normalized.some((category) => category.includes("credit"))) return "CRED";
  return "TOP";
}

async function decodeWebSocketData(data: MessageEvent["data"]): Promise<Uint8Array> {
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (data instanceof Uint8Array) return data;
  if (data instanceof Blob) return new Uint8Array(await data.arrayBuffer());
  throw new Error("unsupported termd websocket payload");
}
