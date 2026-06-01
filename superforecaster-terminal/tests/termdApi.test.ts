import { expect, test } from "bun:test";
import { decode, encode } from "@msgpack/msgpack";
import {
  decodeTermdWireFrame,
  encodeTermdSubscribeFrame,
  readTermdApiConfig,
  TermdApiClient,
  termdBarsResponseToChartData,
  termdCalendarEventToEarning,
  termdDerivativeChannels,
  termdDetailChannels,
  termdDepthResponseToUi,
  termdEconomicEventsResponseToUi,
  termdEventToChartSnapshot,
  termdEventToDepth,
  termdFilingDetailResponseToUi,
  termdFilingEventToUi,
  termdEventToNewsItem,
  termdEventToPredictionMarket,
  termdEventToQuote,
  termdEventToTrade,
  termdCommoditiesResponseToUi,
  termdFixedIncomeResponseToUi,
  termdFxResponseToUi,
  termdInsiderTradeEventToUi,
  termdInstitutionalHoldingToUi,
  termdMacroSeriesChannels,
  termdMarketsOverviewToUi,
  termdNewsChannels,
  termdOptionsResponseToUi,
  termdPredictionChannels,
  termdQuoteToUiQuote,
  termdRatesResponseToUi,
  termdRssFeedToUi,
  termdSeriesResponseToUiSeries,
  termdTradesResponseToUi,
  termdWatchlistToUi,
  termdUserAlertToUi,
  termdUserPositionToUi,
  termdVolSurfaceResponseToUi,
  termdWebSocketUrl,
} from "../src/termdApi";
import { dataSourceDisplayLabel, type Quote } from "../src/data";

const previousQuote: Quote = {
  ticker: "NVDA",
  name: "NVIDIA CORP",
  last: 180,
  chg: 0,
  pct: 0,
  vol: "-",
  bid: 179.99,
  ask: 180.01,
};

test("renders source states with explicit terminal labels", () => {
  expect(dataSourceDisplayLabel(undefined)).toBe("LOCAL");
  expect(dataSourceDisplayLabel({ kind: "live", label: "TERMD" })).toBe("LIVE · TERMD");
  expect(dataSourceDisplayLabel({ kind: "live", label: "" })).toBe("LIVE");
  expect(dataSourceDisplayLabel({ kind: "stale", label: "termd-feed" })).toBe("STALE");
  expect(dataSourceDisplayLabel({ kind: "mock", label: "termd.fixed-income.fixture" })).toBe("MOCK");
  expect(dataSourceDisplayLabel({ kind: "unavailable", label: "TERMD unavailable" })).toBe("N/A");
});

test("maps backend quote snapshots into terminal quotes", () => {
  const quote = termdQuoteToUiQuote(
    { symbol: "nvda", bid: 182.1, bidSz: 200, ask: 182.14, askSz: 150 },
    previousQuote,
  );

  expect(quote).toEqual({
    ticker: "NVDA",
    name: "NVIDIA CORP",
    last: 182.12,
    chg: 2.12,
    pct: 1.18,
    vol: "350",
    bid: 182.1,
    ask: 182.14,
    source: {
      kind: "live",
      label: "TERMD",
    },
  });
});

test("rejects malformed backend quote snapshots", () => {
  expect(termdQuoteToUiQuote({ symbol: "NVDA", bid: 0, ask: 182 })).toBeNull();
  expect(termdQuoteToUiQuote({ symbol: "", bid: 181, ask: 182 })).toBeNull();
});

test("marks backend mock provenance as mock data", () => {
  expect(
    termdQuoteToUiQuote({
      symbol: "NVDA",
      bid: 182.1,
      ask: 182.14,
      provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
    })?.source,
  ).toEqual({
    kind: "mock",
    label: "MOCK",
    receivedAt: "2026-05-14T00:00:00Z",
  });
});

test("maps backend quote events from stream payloads into terminal quotes", () => {
  const quote = termdEventToQuote(
    { kind: "quote", symbol: "NVDA", bid: 181.5, bidSz: 100, ask: 181.7, askSz: 50 },
    previousQuote,
  );

  expect(quote).toEqual({
    ticker: "NVDA",
    name: "NVIDIA CORP",
    last: 181.6,
    chg: 1.6,
    pct: 0.89,
    vol: "150",
    bid: 181.5,
    ask: 181.7,
    source: {
      kind: "live",
      label: "TERMD",
    },
  });
});

test("maps backend RSS feed snapshots into terminal feed rows", () => {
  expect(
    termdRssFeedToUi({
      id: "feed-1",
      userId: "user-1",
      name: "Reuters Macro",
      url: "https://feeds.example.com/reuters.xml",
      categories: ["macro", "rates"],
      pollSecs: 300,
      symbolTagging: "manual",
      manualSymbols: ["spy", "us10y"],
    }),
  ).toEqual({
    id: "feed-1",
    userId: "user-1",
    name: "Reuters Macro",
    url: "https://feeds.example.com/reuters.xml",
    categories: ["macro", "rates"],
    pollSecs: 300,
    symbolTagging: "manual",
    manualSymbols: ["SPY", "US10Y"],
  });
  expect(termdRssFeedToUi({ id: "bad-feed", name: "Missing URL" })).toBeNull();
});

test("maps backend watchlist snapshots into terminal watchlist rows", () => {
  expect(
    termdWatchlistToUi({
      id: "watchlist.default",
      userId: "user-1",
      name: "Default",
      symbols: ["nvda", "spy"],
    }),
  ).toEqual({
    id: "watchlist.default",
    userId: "user-1",
    name: "Default",
    symbols: ["NVDA", "SPY"],
  });
  expect(termdWatchlistToUi({ id: "bad-watchlist", symbols: ["NVDA"] })).toBeNull();
});

test("maps backend read-only user-state snapshots into terminal rows", () => {
  expect(
    termdUserPositionToUi({
      userId: "user-1",
      symbol: "nvda",
      qty: 25,
      avgPx: 180,
      marketPx: 182,
    }),
  ).toEqual({
    userId: "user-1",
    symbol: "NVDA",
    qty: 25,
    avgPx: 180,
    marketPx: 182,
  });
  expect(
    termdUserAlertToUi({
      id: "alert.user-1.1",
      userId: "user-1",
      symbol: "nvda",
      condition: "price-below",
      threshold: 160,
      active: false,
    }),
  ).toEqual({
    id: "alert.user-1.1",
    userId: "user-1",
    symbol: "NVDA",
    condition: "<=",
    threshold: 160,
    active: false,
  });
  expect(termdUserPositionToUi({ symbol: "NVDA" })).toBeNull();
  expect(termdUserAlertToUi({ id: "bad-alert", condition: "unknown" })).toBeNull();
});

test("fetches authenticated backend RSS feeds from the user read model", async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; authorization?: string }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = init?.headers as Record<string, string> | undefined;
    calls.push({
      url: String(input),
      authorization: headers?.authorization,
    });
    return new Response(
      JSON.stringify({
        feeds: [
          {
            id: "feed-1",
            userId: "user-1",
            name: "SEC Headlines",
            url: "https://sec.example.com/rss.xml",
            categories: ["filings"],
            pollSecs: 600,
            symbolTagging: "auto",
            manualSymbols: [],
          },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;

  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      token: "test-token",
      macroSeries: [],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });

    const feeds = await client.fetchRssFeeds();

    expect(calls).toEqual([
      {
        url: "/termd-api/api/v1/users/me/rss",
        authorization: "Bearer test-token",
      },
    ]);
    expect(feeds).toEqual([
      {
        id: "feed-1",
        userId: "user-1",
        name: "SEC Headlines",
        url: "https://sec.example.com/rss.xml",
        categories: ["filings"],
        pollSecs: 600,
        symbolTagging: "auto",
        manualSymbols: [],
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("encodes backend websocket subscription frames as messagepack", () => {
  const frame = decode(encodeTermdSubscribeFrame(["quote.NVDA", "quote.MSFT"])) as {
    version: number;
    frameType: string;
    channel: string;
    seq: number;
    payload: Uint8Array;
  };

  expect(frame.version).toBe(1);
  expect(frame.frameType).toBe("sub");
  expect(frame.channel).toBe("control");
  expect(frame.seq).toBeGreaterThan(0);
  expect(decode(frame.payload)).toEqual({
    channels: ["quote.NVDA", "quote.MSFT"],
    cursors: [],
  });
});

test("decodes backend websocket quote snapshot frames", () => {
  const wireBytes = encode({
    version: 1,
    frameType: "snapshot",
    channel: "quote.NVDA",
    seq: 7,
    payload: encode({
      kind: "quote",
      symbol: "NVDA",
      bid: 182.1,
      bidSz: 200,
      ask: 182.14,
      askSz: 150,
    }),
  });

  const frame = decodeTermdWireFrame(wireBytes);
  expect(frame.channel).toBe("quote.NVDA");
  expect(frame.frameType).toBe("snapshot");
  expect(frame.seq).toBe(7);
  expect(termdEventToQuote(decode(frame.payload), previousQuote)).toMatchObject({
    ticker: "NVDA",
    last: 182.12,
  });
});

test("maps backend websocket depth and tick frames into sourced detail snapshots", () => {
  const chartFrame = decodeTermdWireFrame(encode({
    version: 1,
    frameType: "delta",
    channel: "bar.eq.NVDA.m1",
    seq: 3,
    payload: encode({
      kind: "bar",
      symbol: "NVDA",
      interval: "M1",
      close: 182.2,
      openTime: "2026-05-15T09:30:00Z",
      provenance: { source: "finnhub", receivedAt: "2026-05-15T09:31:00Z" },
    }),
  }));
  const depthFrame = decodeTermdWireFrame(encode({
    version: 1,
    frameType: "snapshot",
    channel: "depth.eq.NVDA",
    seq: 4,
    payload: encode({
      kind: "depthUpdate",
      symbol: "NVDA",
      bids: [{ px: 182.1, qty: 200 }],
      asks: [{ px: 182.14, qty: 150 }],
      provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
    }),
  }));
  const tradeFrame = decodeTermdWireFrame(encode({
    version: 1,
    frameType: "delta",
    channel: "tick.eq.NVDA",
    seq: 5,
    payload: encode({
      kind: "tick",
      symbol: "NVDA",
      px: 182.12,
      qty: 50,
      side: "sell",
      provenance: { source: "finnhub", receivedAt: "2026-05-15T09:30:01.250Z" },
    }),
  }));

  expect(termdEventToChartSnapshot(decode(chartFrame.payload))).toEqual({
    data: [182.2],
    source: {
      kind: "live",
      label: "FINNHUB",
      receivedAt: "2026-05-15T09:31:00Z",
    },
    asOf: "2026-05-15T09:31:00Z",
    staleAfterMs: 60000,
  });
  expect(termdEventToDepth(decode(depthFrame.payload), "NVDA")).toEqual({
    data: {
      symbol: "NVDA",
      bids: [{ px: 182.1, qty: 200 }],
      asks: [{ px: 182.14, qty: 150 }],
    },
    source: {
      kind: "mock",
      label: "MOCK",
      receivedAt: "2026-05-14T00:00:00Z",
    },
    asOf: "2026-05-14T00:00:00Z",
    staleAfterMs: 5000,
  });
  expect(termdEventToTrade(decode(tradeFrame.payload))).toEqual({
    data: { time: "09:30:01.250", px: 182.12, qty: 50, side: "S" },
    source: {
      kind: "live",
      label: "FINNHUB",
      receivedAt: "2026-05-15T09:30:01.250Z",
    },
    asOf: "2026-05-15T09:30:01.250Z",
    staleAfterMs: 5000,
  });
});

test("builds websocket URLs from backend base URLs", () => {
  expect(termdWebSocketUrl("https://edge.example.com")).toBe("wss://edge.example.com/api/v1/ws");
  expect(termdWebSocketUrl("http://127.0.0.1:8080/")).toBe("ws://127.0.0.1:8080/api/v1/ws");
});

test("builds asset-qualified detail websocket channels", () => {
  expect(termdDetailChannels("nvda")).toEqual(["bar.eq.NVDA.m1", "depth.eq.NVDA", "tick.eq.NVDA"]);
  expect(termdDetailChannels("eurusd", "fx")).toEqual(["bar.fx.EURUSD.m1", "depth.fx.EURUSD", "tick.fx.EURUSD"]);
  expect(termdDetailChannels("btc-usd", "cx")).toEqual(["bar.cx.BTC-USD.m1", "depth.cx.BTC-USD", "tick.cx.BTC-USD"]);
  expect(termdDetailChannels("cl1", "cmdty")).toEqual(["bar.cmdty.CL1.m1", "depth.cmdty.CL1", "tick.cmdty.CL1"]);
  expect(termdDetailChannels("us10y", "rates")).toEqual(["bar.rates.US10Y.m1", "depth.rates.US10Y", "tick.rates.US10Y"]);
});

test("builds and consumes detail chart websocket channels", async () => {
  const originalWebSocket = globalThis.WebSocket;
  const sockets: FakeTermdDetailWebSocket[] = [];
  class FakeTermdDetailWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    binaryType: BinaryType = "blob";
    readyState = FakeTermdDetailWebSocket.OPEN;
    sent: unknown[] = [];
    private readonly listeners = new Map<string, Set<(event: unknown) => void>>();

    constructor(
      readonly url: string,
      readonly protocol?: string | string[],
    ) {
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: unknown) => void): void {
      const listeners = this.listeners.get(type) ?? new Set<(event: unknown) => void>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    send(data: unknown): void {
      this.sent.push(data);
    }

    close(): void {
      this.readyState = FakeTermdDetailWebSocket.CLOSED;
      this.dispatch("close", {});
    }

    dispatch(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
  }

  globalThis.WebSocket = FakeTermdDetailWebSocket as unknown as typeof WebSocket;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });
    const charts: unknown[] = [];
    const stream = client.streamDetails("nvda", {
      onChart: (snapshot) => charts.push(snapshot),
    });

    expect(stream).not.toBeNull();
    const socket = sockets[0];
    socket.dispatch("open", {});
    const subscribeFrame = decode(socket.sent[0] as Uint8Array) as { payload: Uint8Array };
    expect(decode(subscribeFrame.payload)).toEqual({
      channels: ["bar.eq.NVDA.m1", "depth.eq.NVDA", "tick.eq.NVDA"],
      cursors: [],
    });

    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "snapshot",
        channel: "bar.eq.NVDA.m1",
        seq: 6,
        payload: encode({
          symbol: "NVDA",
          interval: "M1",
          availability: "live",
          source: "finnhub",
          asOf: "2026-05-15T09:31:00Z",
          staleAfterMs: 60000,
          bars: [
            { kind: "bar", close: 181.1, openTime: "2026-05-15T09:29:00Z" },
            { kind: "bar", close: 182.2, openTime: "2026-05-15T09:30:00Z" },
          ],
        }),
      }),
    });
    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "bar.eq.NVDA.m1",
        seq: 7,
        payload: encode({
          kind: "bar",
          symbol: "NVDA",
          interval: "M1",
          close: 183.3,
          openTime: "2026-05-15T09:31:00Z",
          provenance: { source: "finnhub", receivedAt: "2026-05-15T09:32:00Z" },
        }),
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(charts[0]).toMatchObject({
      data: [181.1, 182.2],
      source: { kind: "live", label: "FINNHUB", receivedAt: "2026-05-15T09:31:00Z" },
      staleAfterMs: 60000,
    });
    expect(charts[1]).toMatchObject({
      data: [183.3],
      source: { kind: "live", label: "FINNHUB", receivedAt: "2026-05-15T09:32:00Z" },
    });
    stream?.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("builds and consumes derivative websocket channels", async () => {
  expect(termdDerivativeChannels("nvda")).toEqual(["options.eq.NVDA", "vol-surface.eq.NVDA"]);
  expect(termdDerivativeChannels("btc-usd", "cx")).toEqual([
    "options.cx.BTC-USD",
    "vol-surface.cx.BTC-USD",
  ]);

  const originalWebSocket = globalThis.WebSocket;
  const sockets: FakeTermdDerivativeWebSocket[] = [];
  class FakeTermdDerivativeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    binaryType: BinaryType = "blob";
    readyState = FakeTermdDerivativeWebSocket.OPEN;
    sent: unknown[] = [];
    private readonly listeners = new Map<string, Set<(event: unknown) => void>>();

    constructor(
      readonly url: string,
      readonly protocol?: string | string[],
    ) {
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: unknown) => void): void {
      const listeners = this.listeners.get(type) ?? new Set<(event: unknown) => void>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    send(data: unknown): void {
      this.sent.push(data);
    }

    close(): void {
      this.readyState = FakeTermdDerivativeWebSocket.CLOSED;
      this.dispatch("close", {});
    }

    dispatch(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
  }

  globalThis.WebSocket = FakeTermdDerivativeWebSocket as unknown as typeof WebSocket;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });
    const optionsRows: unknown[] = [];
    const surfaces: unknown[] = [];
    const stream = client.streamDerivatives("nvda", {
      onOptions: (snapshot) => optionsRows.push(snapshot),
      onVolSurface: (snapshot) => surfaces.push(snapshot),
    });

    expect(stream).not.toBeNull();
    const socket = sockets[0];
    socket.dispatch("open", {});
    const subscribeFrame = decode(socket.sent[0] as Uint8Array) as { payload: Uint8Array };
    expect(decode(subscribeFrame.payload)).toEqual({
      channels: ["options.eq.NVDA", "vol-surface.eq.NVDA"],
      cursors: [],
    });

    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "options.eq.NVDA",
        seq: 7,
        payload: encode({
          symbol: "NVDA",
          availability: "mock",
          source: "mock",
          asOf: "2026-05-14T00:00:00Z",
          staleAfterMs: 300000,
          contracts: [
            {
              symbol: "NVDA260620C00185000",
              underlying: "NVDA",
              expiry: "2026-06-20T00:00:00Z",
              strike: 185,
              right: "call",
              bid: 4.1,
              ask: 4.3,
              mark: 4.2,
              impliedVol: 0.42,
              openInterest: 10000,
              volume: 2500,
              provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
            },
          ],
        }),
      }),
    });
    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "vol-surface.eq.NVDA",
        seq: 8,
        payload: encode({
          symbol: "NVDA",
          availability: "mock",
          source: "mock",
          asOf: "2026-05-14T00:00:00Z",
          staleAfterMs: 300000,
          points: [
            {
              underlying: "NVDA",
              expiry: "2026-06-20T00:00:00Z",
              strike: 185,
              callIv: 0.42,
              putIv: 0.44,
              provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
            },
          ],
        }),
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(optionsRows[0]).toMatchObject({
      data: {
        symbol: "NVDA",
        expiry: "20JUN26",
        rows: [{ strike: 185, callIV: 42 }],
      },
      source: { kind: "mock", label: "MOCK", receivedAt: "2026-05-14T00:00:00Z" },
    });
    expect(surfaces[0]).toMatchObject({
      data: { expiries: ["20JUN26"], strikes: [185], iv: [[43]] },
      staleAfterMs: 300000,
    });
    stream?.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("builds and consumes macro series websocket channels", async () => {
  expect(termdMacroSeriesChannels(["fred.DGS10", "fred.DGS10", " bis.US_POLICY_RATE "])).toEqual([
    "macro.series.fred.DGS10",
    "macro.series.bis.US_POLICY_RATE",
  ]);

  const originalWebSocket = globalThis.WebSocket;
  const sockets: FakeTermdMacroWebSocket[] = [];
  class FakeTermdMacroWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    binaryType: BinaryType = "blob";
    readyState = FakeTermdMacroWebSocket.OPEN;
    sent: unknown[] = [];
    private readonly listeners = new Map<string, Set<(event: unknown) => void>>();

    constructor(
      readonly url: string,
      readonly protocol?: string | string[],
    ) {
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: unknown) => void): void {
      const listeners = this.listeners.get(type) ?? new Set<(event: unknown) => void>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    send(data: unknown): void {
      this.sent.push(data);
    }

    close(): void {
      this.readyState = FakeTermdMacroWebSocket.CLOSED;
      this.dispatch("close", {});
    }

    dispatch(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
  }

  globalThis.WebSocket = FakeTermdMacroWebSocket as unknown as typeof WebSocket;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: ["fred.DGS10"],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });
    const seriesRows: unknown[] = [];
    const points: unknown[] = [];
    const stream = client.streamMacroSeries(["fred.DGS10"], {
      onSeries: (series) => seriesRows.push(series),
      onPoint: (point) => points.push(point),
    });

    expect(stream).not.toBeNull();
    const socket = sockets[0];
    socket.dispatch("open", {});
    const subscribeFrame = decode(socket.sent[0] as Uint8Array) as { payload: Uint8Array };
    expect(decode(subscribeFrame.payload)).toEqual({
      channels: ["macro.series.fred.DGS10"],
      cursors: [],
    });

    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "snapshot",
        channel: "macro.series.fred.DGS10",
        seq: 3,
        payload: encode({
          id: "fred.DGS10",
          points: [
            {
              id: "fred.DGS10",
              time: "2026-05-19T00:00:00Z",
              value: 4.11,
              unit: "percent",
              provenance: { source: "fred" },
            },
          ],
        }),
      }),
    });
    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "macro.series.fred.DGS10",
        seq: 4,
        payload: encode({
          kind: "series",
          id: "fred.DGS10",
          time: "2026-05-20T00:00:00Z",
          value: 4.14,
          unit: "percent",
          provenance: { source: "fred" },
        }),
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(seriesRows[0]).toEqual({
      id: "fred.DGS10",
      points: [{ id: "fred.DGS10", time: "2026-05-19T00:00:00Z", value: 4.11, unit: "percent", source: "FRED" }],
    });
    expect(points[0]).toEqual({
      id: "fred.DGS10",
      time: "2026-05-20T00:00:00Z",
      value: 4.14,
      unit: "percent",
      source: "FRED",
    });
    stream?.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("builds and consumes news websocket channels", async () => {
  expect(termdNewsChannels(["nvda", "NVDA", "msft"])).toEqual([
    "news.global",
    "news.symbol.NVDA",
    "news.symbol.MSFT",
  ]);

  const originalWebSocket = globalThis.WebSocket;
  const sockets: FakeTermdNewsWebSocket[] = [];
  class FakeTermdNewsWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    binaryType: BinaryType = "blob";
    readyState = FakeTermdNewsWebSocket.OPEN;
    sent: unknown[] = [];
    private readonly listeners = new Map<string, Set<(event: unknown) => void>>();

    constructor(
      readonly url: string,
      readonly protocol?: string | string[],
    ) {
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: unknown) => void): void {
      const listeners = this.listeners.get(type) ?? new Set<(event: unknown) => void>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    send(data: unknown): void {
      this.sent.push(data);
    }

    close(): void {
      this.readyState = FakeTermdNewsWebSocket.CLOSED;
      this.dispatch("close", {});
    }

    dispatch(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
  }

  globalThis.WebSocket = FakeTermdNewsWebSocket as unknown as typeof WebSocket;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: [],
      symbols: ["NVDA"],
      pollMs: 5_000,
    });
    const received: unknown[] = [];
    const stream = client.streamNews({ onNews: (item) => received.push(item) }, ["nvda"]);

    expect(stream).not.toBeNull();
    const socket = sockets[0];
    socket.dispatch("open", {});
    const subscribeFrame = decode(socket.sent[0] as Uint8Array) as { payload: Uint8Array };
    expect(decode(subscribeFrame.payload)).toEqual({
      channels: ["news.global", "news.symbol.NVDA"],
      cursors: [],
    });

    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "news.global",
        seq: 9,
        payload: encode({
          kind: "news",
          id: "news.nvda.stream",
          headline: "Nvidia raises data-center forecast",
          body: "Guidance moves higher.",
          symbols: ["NVDA"],
          categories: ["company"],
          sentiment: "positive",
          published: "2026-05-20T14:45:00Z",
          provenance: { source: "finnhub", receivedAt: "2026-05-20T14:45:03Z" },
        }),
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(received[0]).toMatchObject({
      id: "news.nvda.stream",
      src: "FINNHUB",
      headline: "NVIDIA RAISES DATA-CENTER FORECAST",
      symbols: ["NVDA"],
    });
    stream?.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("builds and consumes prediction-market websocket channels", async () => {
  expect(
    termdPredictionChannels([
      { venue: "POLYMARKET", marketId: "poly.mock.fomc-june-2026" },
      { venue: "polymarket", marketId: "poly.mock.fomc-june-2026" },
      { venue: "KALSHI", marketId: "kalshi.mock.cpi" },
      { venue: "", marketId: "ignored" },
    ]),
  ).toEqual([
    "prediction.polymarket.poly.mock.fomc-june-2026",
    "prediction.kalshi.kalshi.mock.cpi",
  ]);

  const originalWebSocket = globalThis.WebSocket;
  const sockets: FakeTermdWebSocket[] = [];
  class FakeTermdWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;

    binaryType: BinaryType = "blob";
    readyState = FakeTermdWebSocket.OPEN;
    sent: unknown[] = [];
    private readonly listeners = new Map<string, Set<(event: unknown) => void>>();

    constructor(
      readonly url: string,
      readonly protocol?: string | string[],
    ) {
      sockets.push(this);
    }

    addEventListener(type: string, listener: (event: unknown) => void): void {
      const listeners = this.listeners.get(type) ?? new Set<(event: unknown) => void>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    }

    send(data: unknown): void {
      this.sent.push(data);
    }

    close(): void {
      this.readyState = FakeTermdWebSocket.CLOSED;
      this.dispatch("close", {});
    }

    dispatch(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event);
    }
  }

  globalThis.WebSocket = FakeTermdWebSocket as unknown as typeof WebSocket;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: ["polymarket"],
      symbols: [],
      pollMs: 5_000,
    });
    const received: unknown[] = [];
    const stream = client.streamPredictionMarkets(
      [{ venue: "POLYMARKET", marketId: "poly.mock.fomc-june-2026" }],
      { onMarket: (market) => received.push(market) },
    );

    expect(stream).not.toBeNull();
    const socket = sockets[0];
    socket.dispatch("open", {});
    const subscribeFrame = decode(socket.sent[0] as Uint8Array) as { payload: Uint8Array };
    expect(decode(subscribeFrame.payload)).toEqual({
      channels: ["prediction.polymarket.poly.mock.fomc-june-2026"],
      cursors: [],
    });

    socket.dispatch("message", {
      data: encode({
        version: 1,
        frameType: "delta",
        channel: "prediction.polymarket.poly.mock.fomc-june-2026",
        seq: 12,
        payload: encode({
          kind: "predictionQuote",
          venue: "polymarket",
          marketId: "poly.mock.fomc-june-2026",
          question: "Will the FOMC cut rates in June 2026?",
          outcome: "yes",
          bid: 0.51,
          ask: 0.55,
          last: 0.53,
          volume: 440000,
          resolved: false,
          provenance: { source: "polymarket", receivedAt: "2026-05-20T15:00:00Z" },
        }),
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(received[0]).toMatchObject({
      venue: "POLYMARKET",
      marketId: "poly.mock.fomc-june-2026",
      question: "Will the FOMC cut rates in June 2026?",
      mid: 0.53,
    });
    stream?.close();
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});

test("maps backend news events into terminal news rows", () => {
  const item = termdEventToNewsItem({
    kind: "news",
    id: "news.nvda.1",
    headline: "Nvidia expands data-center platform",
    body: "Platform demand remains strong.",
    symbols: ["nvda"],
    categories: ["company"],
    sentiment: "positive",
    published: "2026-05-15T09:42:00Z",
    provenance: { source: "finnhub" },
  });

  expect(item).toMatchObject({
    id: "news.nvda.1",
    src: "FINNHUB",
    headline: "NVIDIA EXPANDS DATA-CENTER PLATFORM",
    tone: "pos",
    cat: "EQ",
    body: ["Platform demand remains strong."],
    symbols: ["NVDA"],
  });
  expect(item?.time).toMatch(/^\d{2}:\d{2}$/);
});

test("reads explicit backend configuration without exposing private proxy token", () => {
  const config = readTermdApiConfig({
    VITE_TERMD_API_ENABLED: "1",
    VITE_TERMD_MACRO_SERIES: "fred.DGS10, bis.US_POLICY_RATE, fred.DGS10",
    VITE_TERMD_SYMBOLS: "nvda, brk/b, aapl, nvda",
    VITE_TERMD_API_POLL_MS: "2500",
  });

  expect(config).toEqual({
    baseUrl: "/termd-api",
    macroSeries: ["fred.DGS10", "bis.US_POLICY_RATE"],
    predictionVenues: ["polymarket", "kalshi"],
    symbols: ["NVDA", "BRK/B", "AAPL"],
    pollMs: 2500,
  });
});

test("uses the deployed keyless equity universe by default", () => {
  const config = readTermdApiConfig({ VITE_TERMD_API_ENABLED: "1" });

  expect(config?.symbols).toEqual(["AAPL", "MSFT", "NVDA", "QQQ", "SPY"]);
});

test("fetches quotes through the backend batch endpoint", async () => {
  const calls: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(
      JSON.stringify({
        quotes: [
          {
            symbol: "NVDA",
            bid: 182.1,
            bidSz: 200,
            ask: 182.14,
            askSz: 150,
            provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
          },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: ["polymarket"],
      symbols: [],
      pollMs: 5_000,
    });

    const quotes = await client.fetchQuotes(["nvda", "NVDA", "brk/b"]);

    expect(calls).toEqual(["/termd-api/api/v1/quotes?symbols=NVDA%2CBRK%2FB"]);
    expect(quotes).toEqual([
      {
        ticker: "NVDA",
        name: "NVDA",
        last: 182.12,
        chg: 0,
        pct: 0,
        vol: "350",
        bid: 182.1,
        ask: 182.14,
        source: {
          kind: "live",
          label: "YAHOO-FINANCE",
          receivedAt: "2026-05-15T17:21:55Z",
        },
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetches terminal screen snapshot through the backend batch endpoint", async () => {
  const calls: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(
      JSON.stringify({
        screen: "TERMINAL",
        asOf: "2026-05-15T17:21:55Z",
        datasets: [
          {
            key: "quotes",
            availability: "live",
            source: "yahoo-finance",
            asOf: "2026-05-15T17:21:55Z",
            staleAfterMs: 5000,
          },
          {
            key: "fixed-income",
            availability: "mock",
            source: "mock",
            asOf: "2026-05-14T00:00:00Z",
            staleAfterMs: 86400000,
          },
          {
            key: "commodities",
            availability: "live",
            source: "yahoo-finance",
            asOf: "2026-05-15T17:21:55Z",
            staleAfterMs: 60000,
          },
          {
            key: "recent-prints",
            availability: "live",
            source: "mock",
            asOf: "2026-05-15T13:30:00Z",
            staleAfterMs: 1800000,
          },
        ],
        quotes: [
          {
            symbol: "NVDA",
            bid: 182.1,
            bidSz: 200,
            ask: 182.14,
            askSz: 150,
            provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
          },
        ],
        fx: {
          asOf: "2026-05-15T17:21:55Z",
          ccys: ["USD", "EUR"],
          quotes: [
            {
              symbol: "EURUSD",
              bid: 1.1,
              ask: 1.1002,
              provenance: { source: "twelve-data", receivedAt: "2026-05-15T17:21:55Z" },
            },
          ],
          matrix: [
            [1, 0.909],
            [1.1, 1],
          ],
        },
        commodities: {
          asOf: "2026-05-15T17:21:55Z",
          frontMonths: [
            {
              symbol: "CL1",
              bid: 76.83,
              ask: 76.85,
              provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
            },
          ],
          energy: [
            {
              symbol: "CL1",
              bid: 76.83,
              ask: 76.85,
              provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
            },
          ],
          metals: [],
          ags: [],
        },
        news: {
          events: [
            {
              kind: "news",
              id: "n1",
              headline: "Nvidia shares rise",
              body: "Chip demand improved.",
              symbols: ["NVDA"],
              categories: ["equity"],
              sentiment: "positive",
              published: "2026-05-15T17:20:00Z",
              provenance: { source: "rss" },
            },
          ],
        },
        economicEvents: {
          events: [
            {
              kind: "econEvent",
              time: "2026-05-15T08:30:00Z",
              ccy: "usd",
              label: "US CPI YoY",
              importance: 3,
              forecast: "3.4",
              previous: "3.5",
              actual: null,
              provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
            },
          ],
        },
        recentPrints: {
          events: [
            {
              kind: "econEvent",
              time: "2026-05-15T13:30:00Z",
              ccy: "usd",
              label: "US Retail Sales",
              importance: 2,
              forecast: "0.2",
              previous: "0.1",
              actual: "0.4",
              provenance: { source: "mock", receivedAt: "2026-05-15T13:30:00Z" },
            },
          ],
        },
        earnings: {
          events: [
            {
              kind: "earnings",
              time: "2026-05-20T00:00:00Z",
              symbol: "nvda",
              title: "NVDA earnings",
              forecast: "eps=1.11; revenue=24860000000",
              previous: "amc",
              provenance: { source: "earnings-whispers", receivedAt: "2026-05-14T00:00:00Z" },
            },
          ],
        },
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: ["polymarket"],
      symbols: [],
      pollMs: 5_000,
    });

    const screen = await client.fetchScreen("terminal", ["nvda", "NVDA", "spy"], {
      from: "2026-05-15",
      to: "2026-05-20",
    });

    expect(calls).toEqual([
      "/termd-api/api/v1/screen/terminal?symbols=NVDA%2CSPY&newsLimit=25&from=2026-05-15&to=2026-05-20",
    ]);
    expect(screen?.screen).toBe("TERMINAL");
    expect(screen?.datasets).toEqual([
      {
        key: "quotes",
        source: {
          kind: "live",
          label: "YAHOO-FINANCE",
          receivedAt: "2026-05-15T17:21:55Z",
        },
        asOf: "2026-05-15T17:21:55Z",
        staleAfterMs: 5000,
      },
      {
        key: "fixed-income",
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
        asOf: "2026-05-14T00:00:00Z",
        staleAfterMs: 86400000,
      },
      {
        key: "commodities",
        source: {
          kind: "live",
          label: "YAHOO-FINANCE",
          receivedAt: "2026-05-15T17:21:55Z",
        },
        asOf: "2026-05-15T17:21:55Z",
        staleAfterMs: 60000,
      },
      {
        key: "recent-prints",
        source: {
          kind: "live",
          label: "MOCK",
          receivedAt: "2026-05-15T13:30:00Z",
        },
        asOf: "2026-05-15T13:30:00Z",
        staleAfterMs: 1800000,
      },
    ]);
    expect(screen?.quotes.map((quote) => quote.ticker)).toEqual(["NVDA"]);
    expect(screen?.fx?.ccys).toEqual(["USD", "EUR"]);
    expect(screen?.fx?.matrix[0][1]).toBe(0.909);
    expect(screen?.fx?.quotes[0]?.ticker).toBe("EURUSD");
    expect(screen?.commodities?.frontMonths[0]?.ticker).toBe("CL1");
    expect(screen?.news[0]?.headline).toBe("NVIDIA SHARES RISE");
    expect(screen?.economicCalendar?.events[0]?.label).toBe("US CPI YoY");
    expect(screen?.economicCalendar?.recentPrints[0]?.label).toBe("US Retail Sales");
    expect(screen?.earnings[0]?.symbol).toBe("NVDA");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maps backend FX response into cross-rate matrix and quote rows", () => {
  expect(
    termdFxResponseToUi({
      asOf: "2026-05-15T17:21:55Z",
      ccys: ["usd", "eur", "jpy"],
      quotes: [
        {
          symbol: "EURUSD",
          bid: 1.1,
          ask: 1.1002,
          provenance: { source: "twelve-data", receivedAt: "2026-05-15T17:21:55Z" },
        },
      ],
      matrix: [
        [1, 0.909, null],
        [1.1, 1, null],
        [null, null, 1],
      ],
    }),
  ).toEqual({
    asOf: "2026-05-15T17:21:55Z",
    ccys: ["USD", "EUR", "JPY"],
    matrix: [
      [1, 0.909, null],
      [1.1, 1, null],
      [null, null, 1],
    ],
    quotes: [
      {
        ticker: "EURUSD",
        name: "EURUSD",
        last: 1.1001,
        chg: 0,
        pct: 0,
        vol: "-",
        bid: 1.1,
        ask: 1.1002,
        source: {
          kind: "live",
          label: "TWELVE-DATA",
          receivedAt: "2026-05-15T17:21:55Z",
        },
      },
    ],
  });
});

test("maps backend commodities response into read-only quote groups", () => {
  expect(
    termdCommoditiesResponseToUi({
      asOf: "2026-05-15T17:21:55Z",
      frontMonths: [
        {
          symbol: "cl1",
          bid: 76.83,
          bidSz: 0,
          ask: 76.85,
          askSz: 0,
          provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
        },
      ],
      energy: [],
      metals: [
        {
          symbol: "xau",
          bid: 2614,
          ask: 2614.4,
          provenance: { source: "yahoo-finance", receivedAt: "2026-05-15T17:21:55Z" },
        },
      ],
      ags: [],
    }),
  ).toEqual({
    asOf: "2026-05-15T17:21:55Z",
    frontMonths: [
      {
        ticker: "CL1",
        name: "CL1",
        last: 76.84,
        chg: 0,
        pct: 0,
        vol: "-",
        bid: 76.83,
        ask: 76.85,
        source: {
          kind: "live",
          label: "YAHOO-FINANCE",
          receivedAt: "2026-05-15T17:21:55Z",
        },
      },
    ],
    energy: [],
    metals: [
      {
        ticker: "XAU",
        name: "XAU",
        last: 2614.2,
        chg: 0,
        pct: 0,
        vol: "-",
        bid: 2614,
        ask: 2614.4,
        source: {
          kind: "live",
          label: "YAHOO-FINANCE",
          receivedAt: "2026-05-15T17:21:55Z",
        },
      },
    ],
    ags: [],
  });
});

test("maps backend markets overview into heatmap cells and quotes", async () => {
  const overview = termdMarketsOverviewToUi({
    universe: "sp500-core",
    asOf: "2026-05-14T00:00:00Z",
    cells: [
      {
        symbol: "nvda",
        name: "Nvidia",
        sector: "tech",
        weight: 8.2,
        pct: null,
        availability: "mock",
        quote: {
          symbol: "NVDA",
          bid: 182.1,
          bidSz: 200,
          ask: 182.14,
          askSz: 150,
          provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
        },
      },
      {
        symbol: "AAPL",
        name: "Apple",
        sector: "TECH",
        weight: 7.4,
        availability: "unavailable",
        quote: null,
      },
    ],
    quotes: [
      {
        symbol: "NVDA",
        bid: 182.1,
        bidSz: 200,
        ask: 182.14,
        askSz: 150,
        provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
      },
    ],
  });

  expect(overview).toEqual({
    universe: "sp500-core",
    asOf: "2026-05-14T00:00:00Z",
    cells: [
      {
        symbol: "NVDA",
        name: "Nvidia",
        sector: "TECH",
        weight: 8.2,
        pct: 0,
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
      {
        symbol: "AAPL",
        name: "Apple",
        sector: "TECH",
        weight: 7.4,
        pct: 0,
        source: { kind: "unavailable", label: "N/A" },
      },
    ],
    quotes: [
      {
        ticker: "NVDA",
        name: "Nvidia",
        last: 182.12,
        chg: 0,
        pct: 0,
        vol: "350",
        bid: 182.1,
        ask: 182.14,
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
    ],
  });
});

test("maps backend rates response into sourced curve and policy rows", () => {
  expect(
    termdRatesResponseToUi({
      currency: "usd",
      asOf: "2026-05-13T00:00:00Z",
      curve: [
        {
          tenor: "10y",
          seriesId: "fred.DGS10",
          yld: 4.1234,
          observedAt: "2026-05-13T00:00:00Z",
          availability: "mock",
          provenance: { source: "mock" },
        },
        {
          tenor: "2Y",
          seriesId: "fred.DGS2",
          yld: null,
          availability: "unavailable",
        },
      ],
      policyRates: [
        {
          ccy: "usd",
          bank: "FED - FOMC",
          seriesId: "bis.US_POLICY_RATE",
          rate: 4.5,
          observedAt: "2026-05-01T00:00:00Z",
          availability: "live",
          provenance: { source: "bis" },
        },
        {
          ccy: "EUR",
          bank: "ECB",
          seriesId: "ecb.policy",
          rate: null,
          availability: "unavailable",
        },
      ],
    }),
  ).toEqual({
    currency: "USD",
    asOf: "2026-05-13T00:00:00Z",
    curve: [
      { tenor: "10Y", yld: 4.123, source: { kind: "mock", label: "MOCK" } },
      { tenor: "2Y", yld: null, source: { kind: "unavailable", label: "N/A" } },
    ],
    policyRates: [
      {
        ccy: "USD",
        bank: "FED - FOMC",
        rate: 4.5,
        lastMove: "2026-05-01",
        next: "N/A",
        bias: "HOLD",
        source: { kind: "live", label: "BIS" },
      },
      {
        ccy: "EUR",
        bank: "ECB",
        rate: null,
        lastMove: "N/A",
        next: "N/A",
        bias: "HOLD",
        source: { kind: "unavailable", label: "N/A" },
      },
    ],
  });
});

test("maps backend economic and earnings calendar rows into terminal rows", () => {
  expect(
    termdEconomicEventsResponseToUi({
      events: [
        {
          kind: "econEvent",
          time: "2026-05-15T08:30:00Z",
          ccy: "usd",
          label: "US CPI YoY",
          importance: 3,
          forecast: "3.4",
          previous: "3.5",
          actual: null,
          provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
        },
        {
          kind: "econEvent",
          time: "2026-05-16T10:00:00Z",
          ccy: "eur",
          label: "EZ Trade Balance",
          importance: 2,
          forecast: "22.0B",
          previous: "24.0B",
          actual: "19.1B",
          provenance: { source: "fred", receivedAt: "2026-05-16T10:01:00Z" },
        },
      ],
    }),
  ).toEqual({
    events: [
      {
        time: "08:30",
        ccy: "USD",
        imp: 3,
        label: "US CPI YoY",
        fcst: "3.4",
        prev: "3.5",
        actual: undefined,
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
    ],
    recentPrints: [
      {
        time: "10:00 SAT",
        ccy: "EUR",
        imp: 2,
        label: "EZ Trade Balance",
        fcst: "22.0B",
        prev: "24.0B",
        actual: "19.1B",
        source: {
          kind: "live",
          label: "FRED",
          receivedAt: "2026-05-16T10:01:00Z",
        },
      },
    ],
  });

  expect(
    termdCalendarEventToEarning({
      kind: "earnings",
      time: "2026-05-20T00:00:00Z",
      symbol: "nvda",
      title: "NVDA earnings 2026Q1",
      forecast: "eps=1.11; revenue=24860000000",
      previous: "amc",
      provenance: { source: "earnings-whispers", receivedAt: "2026-05-14T00:00:00Z" },
    }),
  ).toEqual({
    date: "2026-05-20",
    whenStr: "AMC",
    symbol: "NVDA",
    name: "NVDA",
    consensusEps: 1.11,
    consensusRev: "$24.9B",
    prevEps: 0,
    reported: undefined,
    source: {
      kind: "live",
      label: "EARNINGS-WHISPERS",
      receivedAt: "2026-05-14T00:00:00Z",
    },
  });
});

test("fetches backend economic calendar with scheduled and actualized filters", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const actualized = url.includes("actual=true");
    return new Response(
      JSON.stringify({
        events: actualized
          ? [
              {
                kind: "econEvent",
                time: "2026-05-15T13:30:00Z",
                ccy: "usd",
                label: "US Retail Sales",
                importance: 2,
                forecast: "0.2",
                previous: "0.1",
                actual: "0.4",
                provenance: { source: "mock", receivedAt: "2026-05-15T13:30:00Z" },
              },
            ]
          : [
              {
                kind: "econEvent",
                time: "2026-05-15T08:30:00Z",
                ccy: "usd",
                label: "US CPI YoY",
                importance: 3,
                forecast: "3.4",
                previous: "3.5",
                actual: null,
                provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
              },
            ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });
    const calendar = await client.fetchEconomicCalendar();

    expect(calls).toEqual([
      "/termd-api/api/v1/events/economic?actual=false",
      "/termd-api/api/v1/events/economic?actual=true",
    ]);
    expect(calendar?.events[0]?.label).toBe("US CPI YoY");
    expect(calendar?.recentPrints[0]?.label).toBe("US Retail Sales");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maps backend EDGAR research payloads into read-only rows", () => {
  const filingPayload = {
    kind: "filing",
    accession: "0001045810-26-000123",
    cik: 1045810,
    company: "NVIDIA CORP",
    form: "10-q",
    filed: "2026-05-14T00:00:00Z",
    period: "2026-04-30T00:00:00Z",
    primaryDocUrl: "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-10q.htm",
    symbols: ["nvda"],
    provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
  };

  expect(termdFilingEventToUi(filingPayload)).toEqual({
    accession: "0001045810-26-000123",
    cik: 1045810,
    company: "NVIDIA CORP",
    form: "10-Q",
    filed: "2026-05-14T00:00:00Z",
    period: "2026-04-30T00:00:00Z",
    primaryDocUrl: "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-10q.htm",
    symbols: ["NVDA"],
    source: {
      kind: "live",
      label: "SEC-EDGAR",
      receivedAt: "2026-05-14T12:00:00Z",
    },
  });

  expect(
    termdFilingDetailResponseToUi({
      filing: filingPayload,
      facts: [
        {
          concept: "us-gaap:Revenues",
          value: 26_044_000_000,
          unit: "USD",
          periodStart: "2026-02-01T00:00:00Z",
          periodEnd: "2026-04-30T00:00:00Z",
        },
      ],
    }),
  ).toMatchObject({
    filing: { accession: "0001045810-26-000123", form: "10-Q" },
    facts: [
      {
        concept: "us-gaap:Revenues",
        value: 26_044_000_000,
        unit: "USD",
        periodStart: "2026-02-01T00:00:00Z",
        periodEnd: "2026-04-30T00:00:00Z",
      },
    ],
  });

  expect(
    termdInsiderTradeEventToUi({
      kind: "insiderTrade",
      accession: "0001045810-26-000124",
      cik: 1045810,
      symbol: "nvda",
      person: "Jane Director",
      relationship: "director",
      side: "sell",
      shares: 1500,
      price: 182.14,
      traded: "2026-05-13T00:00:00Z",
      provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
    }),
  ).toEqual({
    accession: "0001045810-26-000124",
    cik: 1045810,
    symbol: "NVDA",
    person: "Jane Director",
    relationship: "director",
    side: "sell",
    shares: 1500,
    price: 182.14,
    traded: "2026-05-13T00:00:00Z",
    source: {
      kind: "live",
      label: "SEC-EDGAR",
      receivedAt: "2026-05-14T12:00:00Z",
    },
  });

  expect(
    termdInstitutionalHoldingToUi({
      accession: "0001166559-26-000001",
      cik: 1166559,
      quarter: "2026-03-31",
      issuer: "NVIDIA CORP",
      classTitle: "COM",
      cusip: "67066g104",
      value: 125000,
      shares: 1000,
      shareType: "SH",
      putCall: null,
      investmentDiscretion: "SOLE",
      provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
    }),
  ).toEqual({
    accession: "0001166559-26-000001",
    cik: 1166559,
    quarter: "2026-03-31",
    issuer: "NVIDIA CORP",
    classTitle: "COM",
    cusip: "67066G104",
    value: 125000,
    shares: 1000,
    shareType: "SH",
    putCall: null,
    investmentDiscretion: "SOLE",
    source: {
      kind: "live",
      label: "SEC-EDGAR",
      receivedAt: "2026-05-14T12:00:00Z",
    },
  });
});

test("fetches backend EDGAR research routes through read-only adapters", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  const filingPayload = {
    kind: "filing",
    accession: "0001045810-26-000123",
    cik: 1045810,
    company: "NVIDIA CORP",
    form: "10-Q",
    filed: "2026-05-14T00:00:00Z",
    period: null,
    primaryDocUrl: "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-10q.htm",
    symbols: ["NVDA"],
    provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
  };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/api/v1/filings/0001045810-26-000123")) {
      return new Response(
        JSON.stringify({
          filing: filingPayload,
          facts: [{ concept: "us-gaap:Revenues", value: 26_044_000_000, unit: "USD" }],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/filings?")) {
      return new Response(JSON.stringify({ events: [filingPayload] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/api/v1/insider/")) {
      return new Response(
        JSON.stringify({
          events: [
            {
              kind: "insiderTrade",
              accession: "0001045810-26-000124",
              cik: 1045810,
              symbol: "NVDA",
              person: "Jane Director",
              relationship: "director",
              side: "sell",
              shares: 1500,
              price: 182.14,
              traded: "2026-05-13T00:00:00Z",
              provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/holdings/13f")) {
      return new Response(
        JSON.stringify({
          holdings: [
            {
              accession: "0001166559-26-000001",
              cik: 1166559,
              quarter: [2026, 90],
              issuer: "NVIDIA CORP",
              classTitle: "COM",
              cusip: "67066G104",
              value: 125000,
              shares: 1000,
              shareType: "SH",
              putCall: null,
              investmentDiscretion: "SOLE",
              provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response("not found", { status: 404 });
  }) as typeof fetch;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: [],
      symbols: [],
      pollMs: 5_000,
    });

    const filings = await client.fetchFilings({
      cik: 1045810,
      symbol: "nvda",
      form: "10-Q",
      from: "2026-05-14",
      to: "2026-05-14",
    });
    const detail = await client.fetchFilingDetail("0001045810-26-000123");
    const insider = await client.fetchInsiderTrades("nvda", {
      from: "2026-05-13",
      to: "2026-05-13",
      limit: 1,
    });
    const holdings = await client.fetchInstitutionalHoldings({
      symbol: "nvda",
      cik: 1166559,
      quarter: "2026-03-31",
      cusip: "67066g104",
      limit: 1,
    });

    expect(calls).toEqual([
      "/termd-api/api/v1/filings?cik=1045810&symbol=NVDA&form=10-Q&from=2026-05-14&to=2026-05-14",
      "/termd-api/api/v1/filings/0001045810-26-000123",
      "/termd-api/api/v1/insider/NVDA?from=2026-05-13&to=2026-05-13&limit=1",
      "/termd-api/api/v1/holdings/13f?symbol=NVDA&cik=1166559&quarter=2026-03-31&cusip=67066g104&limit=1",
    ]);
    expect(filings[0]?.accession).toBe("0001045810-26-000123");
    expect(detail?.facts[0]?.concept).toBe("us-gaap:Revenues");
    expect(insider[0]?.person).toBe("Jane Director");
    expect(holdings[0]?.cusip).toBe("67066G104");
    expect(holdings[0]?.quarter).toBe("2026-03-31");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maps backend fixed-income response into source-tagged read-only rows", () => {
  expect(
    termdFixedIncomeResponseToUi({
      asOf: "2026-05-14T00:00:00Z",
      bonds: [
        {
          issuer: "aapl",
          desc: "5.000 15-Aug-2031",
          cpn: 5,
          maturity: "2031-08-15",
          px: 102.14,
          ytm: 4.72,
          oas: 32,
          rating: "AA+",
          availability: "mock",
          provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
        },
      ],
      cds: [
        {
          name: "jpm",
          region: "US / FIN",
          rating: "A-",
          px: 42,
          chg: -1.2,
          ytd: -4,
          availability: "mock",
          provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
        },
      ],
      indices: [
        {
          name: "cdx ig",
          desc: "5Y CDS IG / OTR",
          last: 62,
          chg: 0.4,
          ytd: 4,
          availability: "mock",
          provenance: { source: "mock", receivedAt: "2026-05-14T00:00:00Z" },
        },
      ],
    }),
  ).toEqual({
    asOf: "2026-05-14T00:00:00Z",
    bonds: [
      {
        issuer: "AAPL",
        desc: "5.000 15-Aug-2031",
        cpn: 5,
        maturity: "2031-08-15",
        px: 102.14,
        ytm: 4.72,
        oas: 32,
        rating: "AA+",
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
    ],
    cds: [
      {
        name: "JPM",
        region: "US / FIN",
        rating: "A-",
        px: 42,
        chg: -1.2,
        ytd: -4,
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
    ],
    indices: [
      {
        name: "CDX IG",
        desc: "5Y CDS IG / OTR",
        last: 62,
        chg: 0.4,
        ytd: 4,
        source: {
          kind: "mock",
          label: "MOCK",
          receivedAt: "2026-05-14T00:00:00Z",
        },
      },
    ],
  });
});

test("maps backend detail snapshots into chart depth trades options and surface data", () => {
  expect(
    termdBarsResponseToChartData({
      symbol: "NVDA",
      interval: "m1",
      bars: [
        { kind: "bar", close: 182.2, openTime: "2026-05-15T09:31:00Z" },
        { kind: "bar", close: 181.9, openTime: "2026-05-15T09:30:00Z" },
      ],
    }),
  ).toEqual([181.9, 182.2]);

  expect(
    termdDepthResponseToUi(
      {
        depth: {
          kind: "depthUpdate",
          symbol: "nvda",
          bids: [{ px: 182.1, qty: 200 }],
          asks: [{ px: 182.14, qty: 150 }],
        },
      },
      "NVDA",
    ),
  ).toEqual({
    symbol: "NVDA",
    bids: [{ px: 182.1, qty: 200 }],
    asks: [{ px: 182.14, qty: 150 }],
  });

  expect(
    termdTradesResponseToUi({
      symbol: "NVDA",
      trades: [
        {
          kind: "tick",
          px: 182.12,
          qty: 50,
          side: "sell",
          provenance: { receivedAt: "2026-05-15T09:30:01.250Z" },
        },
      ],
    }),
  ).toEqual([{ time: "09:30:01.250", px: 182.12, qty: 50, side: "S" }]);

  expect(
    termdOptionsResponseToUi({
      symbol: "NVDA",
      contracts: [
        {
          underlying: "NVDA",
          expiry: "2026-06-20T00:00:00Z",
          strike: 185,
          right: "call",
          bid: 4.1,
          ask: 4.3,
          mark: 4.2,
          impliedVol: 0.42,
          openInterest: 1200,
        },
        {
          underlying: "NVDA",
          expiry: "2026-06-20T00:00:00Z",
          strike: 185,
          right: "put",
          bid: 3.1,
          ask: 3.4,
          mark: 3.25,
          impliedVol: 0.44,
          openInterest: 800,
        },
      ],
    }),
  ).toEqual({
    symbol: "NVDA",
    expiry: "20JUN26",
    spot: 0,
    rows: [
      {
        strike: 185,
        callBid: 4.1,
        callAsk: 4.3,
        callLast: 4.2,
        callIV: 42,
        callDelta: 0,
        callOI: 1200,
        putBid: 3.1,
        putAsk: 3.4,
        putLast: 3.25,
        putIV: 44,
        putDelta: 0,
        putOI: 800,
      },
    ],
  });

  expect(
    termdVolSurfaceResponseToUi({
      symbol: "NVDA",
      points: [
        {
          expiry: "2026-06-20T00:00:00Z",
          strike: 185,
          callIv: 0.42,
          putIv: 0.44,
        },
      ],
    }),
  ).toEqual({
    expiries: ["20JUN26"],
    strikes: [185],
    iv: [[43]],
  });
});

test("fetches backend detail snapshots with explicit source metadata", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    const base = {
      availability: "mock",
      source: "mock",
      asOf: "2026-05-14T00:00:00Z",
      staleAfterMs: 60000,
    };
    if (url.includes("/api/v1/chart/")) {
      return new Response(
        JSON.stringify({
          ...base,
          symbol: "NVDA",
          interval: "m1",
          bars: [{ kind: "bar", close: 182.2, openTime: "2026-05-15T09:31:00Z" }],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/depth/")) {
      return new Response(
        JSON.stringify({
          ...base,
          staleAfterMs: 5000,
          depth: {
            kind: "depthUpdate",
            symbol: "NVDA",
            bids: [{ px: 182.1, qty: 200 }],
            asks: [{ px: 182.14, qty: 150 }],
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/trades/")) {
      return new Response(
        JSON.stringify({
          ...base,
          staleAfterMs: 5000,
          symbol: "NVDA",
          trades: [
            {
              kind: "tick",
              px: 182.12,
              qty: 50,
              side: "sell",
              provenance: { receivedAt: "2026-05-15T09:30:01.250Z" },
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/options/")) {
      return new Response(
        JSON.stringify({
          ...base,
          staleAfterMs: 300000,
          symbol: "NVDA",
          contracts: [
            {
              underlying: "NVDA",
              expiry: "2026-06-20T00:00:00Z",
              strike: 185,
              right: "call",
              bid: 4.1,
              ask: 4.3,
              mark: 4.2,
              impliedVol: 0.42,
              openInterest: 1200,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response(
      JSON.stringify({
        ...base,
        staleAfterMs: 300000,
        symbol: "NVDA",
        points: [
          {
            expiry: "2026-06-20T00:00:00Z",
            strike: 185,
            callIv: 0.42,
            putIv: 0.44,
          },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    const client = new TermdApiClient({
      baseUrl: "/termd-api",
      macroSeries: [],
      predictionVenues: ["polymarket"],
      symbols: [],
      pollMs: 5_000,
    });

    const chart = await client.fetchChart("nvda", 1);
    const depth = await client.fetchDepth("nvda");
    const trades = await client.fetchTrades("nvda", 1);
    const options = await client.fetchOptionChain("nvda");
    const surface = await client.fetchOptionSurface("nvda");

    expect(chart).toMatchObject({
      data: [182.2],
      source: { kind: "mock", label: "MOCK", receivedAt: "2026-05-14T00:00:00Z" },
      asOf: "2026-05-14T00:00:00Z",
      staleAfterMs: 60000,
    });
    expect(depth?.source).toEqual({
      kind: "mock",
      label: "MOCK",
      receivedAt: "2026-05-14T00:00:00Z",
    });
    expect(depth?.data.bids).toEqual([{ px: 182.1, qty: 200 }]);
    expect(trades?.data).toEqual([{ time: "09:30:01.250", px: 182.12, qty: 50, side: "S" }]);
    expect(options?.data.rows[0]?.callIV).toBe(42);
    expect(options?.source.kind).toBe("mock");
    expect(surface?.data.iv).toEqual([[43]]);
    expect(surface?.staleAfterMs).toBe(300000);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maps backend prediction market rows into terminal probability rows", () => {
  const market = termdEventToPredictionMarket({
    kind: "predictionQuote",
    venue: "polymarket",
    marketId: "0xabc",
    question: "Fed cuts in June?",
    outcome: "yes",
    bid: 0.421,
    ask: 0.447,
    last: 0.43,
    volume: 1250000,
    resolved: false,
    provenance: {
      source: "polymarket",
      receivedAt: "2026-05-15T15:36:00Z",
    },
  });

  expect(market).toEqual({
    venue: "POLYMARKET",
    marketId: "0xabc",
    question: "Fed cuts in June?",
    outcome: "YES",
    bid: 0.42,
    ask: 0.45,
    last: 0.43,
    mid: 0.43,
    spread: 0.03,
    volume: 1250000,
    resolved: false,
    resolution: null,
    source: "POLYMARKET",
    receivedAt: "2026-05-15T15:36:00Z",
  });
});

test("filters composite prediction markets from terminal rows", () => {
  const market = termdEventToPredictionMarket({
    kind: "predictionQuote",
    venue: "kalshi",
    marketId: "KXMVESPORTSMULTIGAMEEXTENDED-S2026",
    question: "yes Seattle,yes Atlanta,yes Cleveland",
    outcome: "yes",
    bid: 0,
    ask: 0.1,
    last: 0.05,
    resolved: false,
  });

  expect(market).toBeNull();
});

test("maps backend macro series into chronological datapoints", () => {
  const series = termdSeriesResponseToUiSeries({
    id: "fred.DGS10",
    points: [
      {
        id: "fred.DGS10",
        time: "2026-05-13T00:00:00Z",
        value: 4.12,
        unit: "percent",
        provenance: { source: "fred" },
      },
      {
        id: "fred.DGS10",
        time: "2026-05-12T00:00:00Z",
        value: "4.08",
        unit: "percent",
        provenance: { source: "fred" },
      },
      { id: "fred.DGS10", time: "bad" },
    ],
  });

  expect(series).toEqual({
    id: "fred.DGS10",
    points: [
      {
        id: "fred.DGS10",
        time: "2026-05-12T00:00:00Z",
        value: 4.08,
        unit: "percent",
        source: "FRED",
      },
      {
        id: "fred.DGS10",
        time: "2026-05-13T00:00:00Z",
        value: 4.12,
        unit: "percent",
        source: "FRED",
      },
    ],
  });
});
