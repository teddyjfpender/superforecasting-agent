import { expect, test } from "bun:test";
import { createBackendFirstDataProviderForTest } from "../src/providers";
import { dataSourceDisplayLabel } from "../src/data";
import type { TermdApiConfig } from "../src/termdApi";

const backendConfig: TermdApiConfig = {
  baseUrl: "/termd-api",
  macroSeries: [],
  predictionVenues: [],
  symbols: ["NVDA"],
  pollMs: 5_000,
};

test("backend provider hydrates authenticated custom RSS feeds as read-only data", async () => {
  const originalFetch = globalThis.fetch;
  const originalWebSocket = globalThis.WebSocket;
  const calls: { url: string; authorization?: string }[] = [];
  globalThis.WebSocket = undefined as unknown as typeof WebSocket;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = init?.headers as Record<string, string> | undefined;
    calls.push({ url, authorization: headers?.authorization });
    if (url.includes("/api/v1/screen/terminal")) {
      return new Response(
        JSON.stringify({
          screen: "terminal",
          asOf: "2026-05-20T12:00:00Z",
          datasets: [
            {
              key: "news",
              availability: "live",
              source: "termd",
              asOf: "2026-05-20T12:00:00Z",
              staleAfterMs: 5000,
            },
          ],
          quotes: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/users/me/rss")) {
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
              manualSymbols: ["NVDA"],
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/watchlists")) {
      return new Response(
        JSON.stringify({
          watchlists: [
            {
              id: "watchlist.default",
              userId: "user-1",
              name: "Default",
              symbols: ["NVDA"],
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/positions")) {
      return new Response(
        JSON.stringify({
          positions: [
            {
              userId: "user-1",
              symbol: "NVDA",
              qty: 25,
              avgPx: 180,
              marketPx: 182,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/v1/alerts")) {
      return new Response(
        JSON.stringify({
          alerts: [
            {
              id: "alert.user-1.1",
              userId: "user-1",
              symbol: "NVDA",
              condition: "price-above",
              threshold: 205,
              active: true,
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response("not found", { status: 404 });
  }) as typeof fetch;

  try {
    const provider = createBackendFirstDataProviderForTest(
      { ...backendConfig, token: "rss-token" },
      { remoteBootstrapPending: false },
    );
    const updated = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("RSS feed update timed out")), 500);
      const unsubscribe = provider.subscribeRssFeeds(() => {
        clearTimeout(timeout);
        unsubscribe();
        resolve();
      });
    });

    await (provider as unknown as { refreshRemote(): Promise<void> }).refreshRemote();
    await updated;

    expect(calls).toEqual([
      {
        url: "/termd-api/api/v1/screen/terminal?symbols=NVDA&newsLimit=25",
        authorization: "Bearer rss-token",
      },
      {
        url: "/termd-api/api/v1/users/me/rss",
        authorization: "Bearer rss-token",
      },
      {
        url: "/termd-api/api/v1/watchlists",
        authorization: "Bearer rss-token",
      },
      {
        url: "/termd-api/api/v1/positions",
        authorization: "Bearer rss-token",
      },
      {
        url: "/termd-api/api/v1/alerts",
        authorization: "Bearer rss-token",
      },
    ]);
    expect(provider.getRssFeeds()).toEqual([
      {
        id: "feed-1",
        userId: "user-1",
        name: "SEC Headlines",
        url: "https://sec.example.com/rss.xml",
        categories: ["filings"],
        pollSecs: 600,
        symbolTagging: "auto",
        manualSymbols: ["NVDA"],
      },
    ]);
    expect(provider.listWatchlists()).toEqual([
      {
        id: "watchlist.default",
        name: "Default",
        createdAt: 0,
      },
    ]);
    expect(provider.getActiveWatchlistId()).toBe("watchlist.default");
    expect(provider.getWatchlistSymbols("watchlist.default")).toEqual(["NVDA"]);
    expect(provider.watchlistsAreReadOnly()).toBe(true);
    expect(provider.getPositions()).toMatchObject([
      {
        ticker: "NVDA",
        qty: 25,
        avg: 180,
        mark: 182,
        mv: 4550,
        pl: 50,
        source: { kind: "live", label: "TERMD" },
      },
    ]);
    expect(provider.getAlerts()).toEqual([
      {
        id: "alert.user-1.1",
        symbol: "NVDA",
        level: 205,
        condition: ">=",
        status: "ACTIVE",
        createdAt: 0,
        source: { kind: "live", label: "TERMD" },
      },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.WebSocket = originalWebSocket;
  }
});

test("backend provider renders unavailable datasets instead of local seeded fallbacks", async () => {
  const originalFetch = globalThis.fetch;
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = undefined as unknown as typeof WebSocket;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/screen/terminal")) {
      return new Response(
        JSON.stringify({
          screen: "terminal",
          asOf: null,
          datasets: [
            { key: "quotes", availability: "unavailable", source: "termd", asOf: null, staleAfterMs: 0 },
            { key: "fixed-income", availability: "unavailable", source: "termd", asOf: null, staleAfterMs: 0 },
            { key: "economic-events", availability: "unavailable", source: "termd", asOf: null, staleAfterMs: 0 },
          ],
          quotes: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response("not found", { status: 404 });
  }) as typeof fetch;

  try {
    const provider = createBackendFirstDataProviderForTest(backendConfig, {
      remoteBootstrapPending: false,
    });

    await (provider as unknown as { refreshRemote(): Promise<void> }).refreshRemote();

    const quote = provider.getQuote("NVDA");
    expect(quote?.last).toBe(0);
    expect(quote?.vol).toBe("N/A");
    expect(quote?.source?.kind).toBe("unavailable");
    expect(dataSourceDisplayLabel(quote?.source)).toBe("N/A");

    expect(provider.getBonds()[0]).toMatchObject({
      issuer: "N/A",
      source: { kind: "unavailable" },
    });
    expect(provider.getEvents()[0]).toMatchObject({
      label: "ECONOMIC CALENDAR UNAVAILABLE",
      source: { kind: "unavailable" },
    });
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.WebSocket = originalWebSocket;
  }
});

test("symbol research hydrates 13F only through the symbol-qualified backend route", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/api/v1/filings?")) {
      return new Response(
        JSON.stringify({
          events: [
            {
              kind: "filing",
              accession: "0001045810-26-000123",
              cik: 1045810,
              company: "NVIDIA CORP",
              form: "10-Q",
              filed: "2026-05-14T00:00:00Z",
              period: "2026-04-30T00:00:00Z",
              primaryDocUrl:
                "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000123/nvda-10q.htm",
              symbols: ["NVDA"],
              provenance: { source: "sec-edgar", receivedAt: "2026-05-14T12:00:00Z" },
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
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
      if (!url.includes("symbol=NVDA")) {
        return new Response("13F route must be symbol-qualified for research", { status: 500 });
      }
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
    const provider = createBackendFirstDataProviderForTest(backendConfig, {
      remoteBootstrapPending: false,
    });
    const updated = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("research update timed out")), 500);
      const unsubscribe = provider.subscribeResearch("nvda", () => {
        clearTimeout(timeout);
        unsubscribe();
        resolve();
      });
      provider.getResearch("nvda");
    });

    await updated;
    const research = provider.getResearch("nvda");

    expect(calls).toEqual([
      "/termd-api/api/v1/filings?symbol=NVDA",
      "/termd-api/api/v1/insider/NVDA?limit=8",
      "/termd-api/api/v1/holdings/13f?symbol=NVDA&limit=8",
    ]);
    expect(research.filings).toHaveLength(1);
    expect(research.insiderTrades).toHaveLength(1);
    expect(research.institutionalHoldings).toHaveLength(1);
    expect(research.institutionalHoldings[0]?.cusip).toBe("67066G104");
    expect(research.institutionalHoldings[0]?.quarter).toBe("2026-03-31");
    expect(research.holdingsSource).toEqual({
      kind: "live",
      label: "SEC-EDGAR",
      receivedAt: "2026-05-14T12:00:00Z",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
