import { expect, test } from "bun:test";
import {
  createForecastApiClient,
  forecastWorkspaceToUi,
  readForecastApiConfig,
} from "../src/forecastApi";

test("config is disabled by default and enabled by the flag", () => {
  expect(readForecastApiConfig({})).toBeNull();
  const cfg = readForecastApiConfig({ VITE_FORECAST_API_ENABLED: "1" });
  expect(cfg).not.toBeNull();
  expect(cfg!.baseUrl).toBe("/forecast-api");
  expect(cfg!.pollMs).toBe(5_000);
});

test("config respects an explicit base url (trailing slash stripped) + poll", () => {
  const cfg = readForecastApiConfig({
    VITE_FORECAST_API_BASE_URL: "http://127.0.0.1:8787/",
    VITE_FORECAST_API_POLL_MS: "2000",
  });
  expect(cfg!.baseUrl).toBe("http://127.0.0.1:8787");
  expect(cfg!.pollMs).toBe(2_000);
});

test("forecastWorkspaceToUi coerces a malformed payload without throwing", () => {
  const ui = forecastWorkspaceToUi({
    forecasts: "nope",
    active_count: "3",
    generated_at: 123,
  });
  expect(ui.forecasts).toEqual([]);
  expect(ui.active_count).toBe(3);
  expect(ui.generated_at).toBeNull();
  expect(ui.source.kind).toBe("unavailable");
});

test("forecastWorkspaceToUi marks the source live when generated_at is present", () => {
  const ui = forecastWorkspaceToUi({
    forecasts: [],
    generated_at: "2026-06-01T00:00:00Z",
    product: "sf",
  });
  expect(ui.source.kind).toBe("live");
  expect(ui.generated_at).toBe("2026-06-01T00:00:00Z");
});

test("fetchWorkspace maps a wire payload through the client", async () => {
  const client = createForecastApiClient({ baseUrl: "/forecast-api", pollMs: 5_000 })!;
  const original = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        forecasts: [{ id: "a" }],
        active_count: 1,
        generated_at: "2026-06-01T00:00:00Z",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    )) as typeof fetch;
  try {
    const ws = await client.fetchWorkspace(10);
    expect(ws.forecasts.length).toBe(1);
    expect(ws.active_count).toBe(1);
    expect(ws.source.kind).toBe("live");
  } finally {
    globalThis.fetch = original;
  }
});

test("fetchJson throws on a non-OK response", async () => {
  const client = createForecastApiClient({ baseUrl: "/forecast-api", pollMs: 5_000 })!;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response("err", { status: 500 })) as typeof fetch;
  try {
    await expect(client.fetchWorkspace()).rejects.toThrow(/forecast 500/);
  } finally {
    globalThis.fetch = original;
  }
});

test("fetchQuestion returns a null packet on 404 (optional404)", async () => {
  const client = createForecastApiClient({ baseUrl: "/forecast-api", pollMs: 5_000 })!;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response("nf", { status: 404 })) as typeof fetch;
  try {
    const res = await client.fetchQuestion("missing");
    expect(res.packet).toBeNull();
  } finally {
    globalThis.fetch = original;
  }
});
