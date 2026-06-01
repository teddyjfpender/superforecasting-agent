import { decode } from "@msgpack/msgpack";
import { decodeTermdWireFrame, encodeTermdSubscribeFrame } from "../src/termdApi.ts";

type JsonObject = Record<string, unknown>;

type SmokeCheck = {
  name: string;
  detail: string;
};

const env = process.env;
const baseUrl = stripTrailingSlash(
  env.TERMD_SMOKE_BASE_URL ??
    env.VITE_TERMD_API_BASE_URL ??
    "http://127.0.0.1:5174/termd-api",
);
const token = env.TERMD_SMOKE_TOKEN ?? env.TERMD_API_TOKEN ?? env.VITE_TERMD_API_TOKEN;
const symbol = (env.TERMD_SMOKE_SYMBOL ?? "NVDA").trim().toUpperCase();
const symbols = normalizeCsv(env.TERMD_SMOKE_SYMBOLS ?? `${symbol},AAPL`);
const assetClass = (env.TERMD_SMOKE_ASSET_CLASS ?? "eq").trim();
const macroSeries = (env.TERMD_SMOKE_POLICY_SERIES ?? "bis.US_POLICY_RATE").trim();
const timeoutMs = numberEnv(env.TERMD_SMOKE_TIMEOUT_MS) ?? 5_000;
const restRetries = Math.max(1, Math.trunc(numberEnv(env.TERMD_SMOKE_REST_RETRIES) ?? 5));

if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
  fail(`TERMD_SMOKE_BASE_URL must be absolute http(s), got ${baseUrl}`);
}
if (!symbol) fail("TERMD_SMOKE_SYMBOL cannot be empty");
if (symbols.length === 0) fail("TERMD_SMOKE_SYMBOLS cannot be empty");
if (!assetClass) fail("TERMD_SMOKE_ASSET_CLASS cannot be empty");
if (!macroSeries) fail("TERMD_SMOKE_POLICY_SERIES cannot be empty");

const checks: SmokeCheck[] = [];
const requiredScreenDatasets = [
  "quotes",
  "markets-overview",
  "rates",
  "fixed-income",
  "fx",
  "commodities",
  "news",
  "economic-events",
  "recent-prints",
  "earnings",
];

const readyz = await getJson("/readyz");
assertObject(readyz, "readyz response");
assert(readyz.ready === true, "readyz.ready must be true");
checks.push({ name: "readyz", detail: "edge reports ready=true" });

const screen = await getJson(
  `/api/v1/screen/terminal?symbols=${encodeURIComponent(symbols.join(","))}&newsLimit=2`,
);
assertObject(screen, "screen response");
const screenQuotes = arrayField(screen, "quotes");
assert(
  screenQuotes.some((quote) => {
    assertObject(quote, "screen quote");
    return quote.symbol === symbol;
  }),
  `screen snapshot must include ${symbol} quote`,
);
const datasets = arrayField(screen, "datasets");
assert(datasets.length > 0, "screen snapshot must include dataset metadata");
const datasetAvailability = screenDatasetAvailability(datasets);
assertScreenDatasetPayloads(screen, datasetAvailability);
checks.push({
  name: "screen",
  detail: `screen snapshot includes ${screenQuotes.length} quote(s) and all ${requiredScreenDatasets.length} required dataset markers`,
});

const quote = await getJson(`/api/v1/quote/${encodeURIComponent(symbol)}`);
assertObject(quote, "quote response");
assertObject(quote.quote, "quote response quote");
assert(quote.quote.symbol === symbol, `quote response symbol must be ${symbol}`);
checks.push({ name: "quote", detail: `${symbol} REST quote is available` });

const chart = await getJson(
  `/api/v1/chart/${encodeURIComponent(symbol)}?interval=1m&limit=2`,
);
assertObject(chart, "chart response");
assert(arrayField(chart, "bars").length > 0, "chart response must include bars");
checks.push({ name: "chart", detail: `${symbol} REST chart has bars` });

const depth = await getJson(`/api/v1/depth/${encodeURIComponent(symbol)}`);
assertObject(depth, "depth response");
const restDepthEvent = objectField(depth, "depth");
assert(arrayField(restDepthEvent, "bids").length > 0, "depth response must include bids");
assert(arrayField(restDepthEvent, "asks").length > 0, "depth response must include asks");
checks.push({ name: "depth", detail: `${symbol} REST depth has bid/ask levels` });

const trades = await getJson(`/api/v1/trades/${encodeURIComponent(symbol)}?limit=2`);
assertObject(trades, "trades response");
assert(arrayField(trades, "trades").length > 0, "trades response must include recent prints");
checks.push({ name: "trades", detail: `${symbol} REST time-and-sales has prints` });

const options = await getJson(`/api/v1/options/${encodeURIComponent(symbol)}`);
assertObject(options, "options response");
assert(arrayField(options, "contracts").length > 0, "options response must include contracts");
checks.push({ name: "options", detail: `${symbol} REST option chain has contracts` });

const surface = await getJson(`/api/v1/vol-surface/${encodeURIComponent(symbol)}`);
assertObject(surface, "vol-surface response");
assert(arrayField(surface, "points").length > 0, "vol-surface response must include points");
checks.push({ name: "vol-surface", detail: `${symbol} REST vol surface has points` });

const rates = await getJson("/api/v1/rates");
assertObject(rates, "rates response");
assert(arrayField(rates, "curve").length > 0, "rates response must include curve points");
assert(
  arrayField(rates, "policyRates").some((row) => {
    assertObject(row, "policy rate row");
    return row.seriesId === macroSeries;
  }),
  `rates response must include policy series ${macroSeries}`,
);
checks.push({ name: "rates", detail: `rates response includes ${macroSeries}` });

const macro = await getJson(`/api/v1/macro/series/${encodeURIComponent(macroSeries)}`);
assertObject(macro, "macro series response");
assert(arrayField(macro, "points").length > 0, `macro series ${macroSeries} must include points`);
checks.push({ name: "macro", detail: `${macroSeries} REST series has points` });

const filings = await getJson(`/api/v1/filings?symbol=${encodeURIComponent(symbol)}`);
assertObject(filings, "filings response");
arrayField(filings, "events");
const insider = await getJson(`/api/v1/insider/${encodeURIComponent(symbol)}?limit=2`);
assertObject(insider, "insider response");
arrayField(insider, "events");
const holdings = await getJson(`/api/v1/holdings/13f?symbol=${encodeURIComponent(symbol)}&limit=2`);
assertObject(holdings, "13F holdings response");
arrayField(holdings, "holdings");
checks.push({ name: "edgar", detail: "filings, insider, and 13F routes expose read-only row arrays" });

const wsChannels = [
  `bar.${assetClass}.${symbol}.m1`,
  `depth.${assetClass}.${symbol}`,
  `tick.${assetClass}.${symbol}`,
  `options.${assetClass}.${symbol}`,
  `vol-surface.${assetClass}.${symbol}`,
];
const snapshots = await collectWebSocketSnapshots(wsChannels);
const barSnapshot = objectField(snapshots, wsChannels[0]);
assertObject(barSnapshot, "bar websocket snapshot");
assert(arrayField(barSnapshot, "bars").length > 0, "bar websocket snapshot must include bars");
const depthSnapshot = objectField(snapshots, wsChannels[1]);
assertObject(depthSnapshot, "depth websocket snapshot");
assert(arrayField(depthSnapshot, "bids").length > 0, "depth websocket snapshot must include bids");
assert(arrayField(depthSnapshot, "asks").length > 0, "depth websocket snapshot must include asks");
const tickSnapshot = objectField(snapshots, wsChannels[2]);
assertObject(tickSnapshot, "tick websocket snapshot");
assert(typeof tickSnapshot.px === "number", "tick websocket snapshot must include px");
const optionsSnapshot = objectField(snapshots, wsChannels[3]);
assertObject(optionsSnapshot, "options websocket snapshot");
assert(arrayField(optionsSnapshot, "contracts").length > 0, "options websocket snapshot must include contracts");
const surfaceSnapshot = objectField(snapshots, wsChannels[4]);
assertObject(surfaceSnapshot, "vol-surface websocket snapshot");
assert(arrayField(surfaceSnapshot, "points").length > 0, "vol-surface websocket snapshot must include points");
checks.push({ name: "websocket", detail: `received snapshots for ${wsChannels.join(", ")}` });

console.log(JSON.stringify({ ok: true, baseUrl, symbol, checks }, null, 2));

async function getJson(path: string): Promise<unknown> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= restRetries; attempt += 1) {
    try {
      const response = await fetch(apiUrl(path), {
        headers: token
          ? { accept: "application/json", authorization: `Bearer ${token}` }
          : { accept: "application/json" },
      });
      if (!response.ok) {
        const body = await response.text().catch(() => "");
        throw new Error(`${path} returned ${response.status}: ${body.slice(0, 500)}`);
      }
      return response.json();
    } catch (error) {
      lastError = error;
      if (attempt < restRetries) await sleep(250 * attempt);
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function collectWebSocketSnapshots(channels: readonly string[]): Promise<JsonObject> {
  return new Promise((resolve, reject) => {
    const seen: JsonObject = {};
    const socket = openWebSocket();
    const timer = setTimeout(() => {
      socket.close(1000, "smoke timeout");
      reject(new Error(`timed out waiting for snapshots: ${channels.filter((channel) => !(channel in seen)).join(",")}`));
    }, timeoutMs);

    socket.onopen = () => {
      socket.send(encodeTermdSubscribeFrame(channels));
    };
    socket.onerror = (event) => {
      clearTimeout(timer);
      reject(new Error(`websocket error: ${JSON.stringify(event)}`));
    };
    socket.onmessage = (event) => {
      try {
        const frame = decodeTermdWireFrame(webSocketPayloadBytes(event.data));
        if (frame.frameType !== "snapshot" || !channels.includes(frame.channel)) return;
        seen[frame.channel] = decode(frame.payload);
        if (channels.every((channel) => channel in seen)) {
          clearTimeout(timer);
          socket.close(1000, "smoke complete");
          resolve(seen);
        }
      } catch (error) {
        clearTimeout(timer);
        socket.close(1000, "smoke error");
        reject(error);
      }
    };
  });
}

function openWebSocket(): WebSocket {
  const url = webSocketUrl("/api/v1/ws");
  if (!token) return new WebSocket(url, "bbrg.v1");
  return new (WebSocket as unknown as {
    new (
      url: string,
      options: { headers?: Record<string, string>; protocols?: string[] },
    ): WebSocket;
  })(url, { headers: { Authorization: `Bearer ${token}` }, protocols: ["bbrg.v1"] });
}

function webSocketPayloadBytes(data: unknown): Uint8Array {
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (typeof Buffer !== "undefined" && Buffer.isBuffer(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  if (data instanceof Blob) {
    throw new Error("unexpected Blob websocket payload in synchronous smoke decoder");
  }
  throw new Error(`unsupported websocket payload ${Object.prototype.toString.call(data)}`);
}

function apiUrl(path: string): string {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function webSocketUrl(path: string): string {
  const url = new URL(apiUrl(path));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function normalizeCsv(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean),
    ),
  );
}

function numberEnv(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function arrayField(value: JsonObject, key: string): unknown[] {
  const field = value[key];
  assert(Array.isArray(field), `${key} must be an array`);
  return field;
}

function objectField(value: unknown, key: string): JsonObject {
  assertObject(value, `${key} parent`);
  const field = value[key];
  assertObject(field, key);
  return field;
}

function assertObject(value: unknown, label: string): asserts value is JsonObject {
  assert(value !== null && typeof value === "object" && !Array.isArray(value), `${label} must be an object`);
}

function screenDatasetAvailability(datasets: unknown[]): Map<string, string> {
  const availability = new Map<string, string>();
  for (const dataset of datasets) {
    assertObject(dataset, "screen dataset marker");
    const key = dataset.key;
    const value = dataset.availability;
    if (typeof key === "string" && typeof value === "string") availability.set(key, value);
  }
  for (const key of requiredScreenDatasets) {
    assert(availability.has(key), `screen dataset marker ${key} is missing`);
  }
  return availability;
}

function assertScreenDatasetPayloads(
  screen: JsonObject,
  availability: Map<string, string>,
): void {
  assertDatasetAllNonemptyWhenAvailable(screen, availability, "rates", "rates", ["curve", "policyRates"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "fixed-income", "fixedIncome", ["bonds", "cds", "indices"]);
  assertDatasetAllNonemptyWhenAvailable(screen, availability, "fx", "fx", ["ccys", "matrix"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "commodities", "commodities", ["frontMonths", "energy", "metals", "ags"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "news", "news", ["events"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "economic-events", "economicEvents", ["events"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "recent-prints", "recentPrints", ["events"]);
  assertDatasetAnyNonemptyWhenAvailable(screen, availability, "earnings", "earnings", ["events"]);
}

function assertDatasetAnyNonemptyWhenAvailable(
  screen: JsonObject,
  availability: Map<string, string>,
  datasetKey: string,
  payloadField: string,
  arrayFields: string[],
): void {
  const payload = objectField(screen, payloadField);
  if (availability.get(datasetKey) === "unavailable") return;
  assert(
    arrayFields.some((field) => Array.isArray(payload[field]) && (payload[field] as unknown[]).length > 0),
    `${payloadField} must include at least one populated backend array`,
  );
}

function assertDatasetAllNonemptyWhenAvailable(
  screen: JsonObject,
  availability: Map<string, string>,
  datasetKey: string,
  payloadField: string,
  arrayFields: string[],
): void {
  const payload = objectField(screen, payloadField);
  if (availability.get(datasetKey) === "unavailable") return;
  for (const field of arrayFields) {
    assert(arrayField(payload, field).length > 0, `${payloadField}.${field} must not be empty`);
  }
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) fail(message);
}

function fail(message: string): never {
  throw new Error(`data-plane smoke failed: ${message}`);
}
