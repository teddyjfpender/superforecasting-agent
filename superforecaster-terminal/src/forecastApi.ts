// Forecast API client for the web terminal.
//
// Mirrors the structure and coercion style of `termdApi.ts` (see
// `readTermdApiConfig`, the private `fetchJson<T>`, `createTermdApiClient`, and
// the `asString`/`asNumber` wire->UI mapper helpers). The forecast bridge is a
// local, token-less HTTP surface that re-publishes the forecasting desk's
// workspace, question packets, and dashboard summary as structured JSON.
//
// Defensive contract: every wire field is typed `?: unknown` and coerced so a
// malformed payload degrades to `null`/empty values. The mapping layer never
// throws; only the transport layer (`fetchJson`) raises on a non-OK response.

import type {
  ForecastWorkspaceItem,
  ForecastAnalystNote,
  ForecastRelatedView,
} from "./forecastFormat";

// ---------------------------------------------------------------------------
// Environment + configuration
// ---------------------------------------------------------------------------

type Env = {
  VITE_FORECAST_API_BASE_URL?: string;
  VITE_FORECAST_API_ENABLED?: string;
  VITE_FORECAST_API_POLL_MS?: string;
};

export type ForecastApiConfig = {
  baseUrl: string;
  pollMs: number;
};

const DEFAULT_POLL_MS = 5_000;

export function readForecastApiConfig(env: Env = browserEnv()): ForecastApiConfig | null {
  const enabled =
    env.VITE_FORECAST_API_ENABLED === "1" || Boolean(env.VITE_FORECAST_API_BASE_URL);
  if (!enabled) return null;

  const pollMs = numberFromString(env.VITE_FORECAST_API_POLL_MS);
  return {
    // No token: the forecast bridge is a local same-origin/loopback surface.
    baseUrl: stripTrailingSlash(env.VITE_FORECAST_API_BASE_URL || "/forecast-api"),
    pollMs: pollMs && pollMs >= 1_000 ? pollMs : DEFAULT_POLL_MS,
  };
}

// ---------------------------------------------------------------------------
// Payload types (wire shapes are intentionally permissive: every field optional)
// ---------------------------------------------------------------------------

/** Provenance for a forecast payload, mirroring termd's `DataSourceState`. */
export type ForecastDataSource = {
  kind: "live" | "stale" | "mock" | "unavailable";
  label: string;
  generatedAt?: string;
};

/** Response of `GET /forecast/workspace`. */
export type ForecastWorkspacePayload = {
  forecasts: ForecastWorkspaceItem[];
  active_count: number;
  closing_soon_count: number;
  open_alert_count: number;
  generated_at: string | null;
  product?: string;
  output?: string;
  source: ForecastDataSource;
};

/** Wire shape of the workspace response before coercion. */
type ForecastWorkspaceWire = {
  forecasts?: unknown;
  active_count?: unknown;
  closing_soon_count?: unknown;
  open_alert_count?: unknown;
  generated_at?: unknown;
  product?: unknown;
  output?: unknown;
};

/** Response of `GET /forecast/question/<id>` — the desk emits `{ packet }`. */
export type ForecastQuestionResponse = {
  packet: ForecastQuestionPacket | null;
};

/** A question packet is deeply nested; consumers narrow it as needed. */
export type ForecastQuestionPacket = {
  question?: Record<string, unknown> | null;
  analyst_note?: ForecastAnalystNote | null;
  analyst_notes?: ForecastAnalystNote[];
  related_forecasts?: ForecastRelatedView[];
  evidence?: unknown[];
  forecast_history?: unknown[];
  retrospective?: ForecastAnalystNote | null;
  [key: string]: unknown;
};

/** Wire shape of the question response before coercion. */
type ForecastQuestionWire = {
  packet?: unknown;
};

/** Response of `GET /forecast/dashboard` — `{ summary, output }`. */
export type ForecastDashboardResponse = {
  summary: Record<string, unknown> | null;
  output: string | null;
};

/** Wire shape of the dashboard response before coercion. */
type ForecastDashboardWire = {
  summary?: unknown;
  output?: unknown;
};

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class ForecastApiClient {
  constructor(private readonly config: ForecastApiConfig) {}

  /**
   * Fetch the standing forecast book. Mirrors `{ forecasts, active_count,
   * closing_soon_count, open_alert_count, generated_at, ... }`.
   */
  async fetchWorkspace(limit = 75): Promise<ForecastWorkspacePayload> {
    const response = await this.fetchJson<ForecastWorkspaceWire>(
      `/forecast/workspace?limit=${encodeURIComponent(String(limit))}`,
    );
    return forecastWorkspaceToUi(response ?? {});
  }

  /** Fetch one question packet by id; returns `{ packet }`. */
  async fetchQuestion(id: string): Promise<ForecastQuestionResponse> {
    const response = await this.fetchJson<ForecastQuestionWire>(
      `/forecast/question/${encodeURIComponent(id)}`,
      true,
    );
    return { packet: asPacket(response?.packet) };
  }

  /** Fetch the dashboard summary; returns `{ summary, output }`. */
  async fetchDashboard(limit = 20): Promise<ForecastDashboardResponse> {
    const response = await this.fetchJson<ForecastDashboardWire>(
      `/forecast/dashboard?limit=${encodeURIComponent(String(limit))}`,
    );
    return {
      summary: asRecord(response?.summary),
      output: asString(response?.output),
    };
  }

  private async fetchJson<T>(path: string, optional404 = false): Promise<T | null> {
    const headers: HeadersInit = { accept: "application/json" };
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      cache: "no-store",
      headers,
    });
    if (optional404 && response.status === 404) return null;
    if (!response.ok) throw new Error(`forecast ${response.status} for ${path}`);
    return (await response.json()) as T;
  }
}

export function createForecastApiClient(
  config: ForecastApiConfig | null = readForecastApiConfig(),
): ForecastApiClient | null {
  return config ? new ForecastApiClient(config) : null;
}

// ---------------------------------------------------------------------------
// Wire -> UI mappers (defensive: never throw; coerce to null/empty)
// ---------------------------------------------------------------------------

export function forecastWorkspaceToUi(
  payload: ForecastWorkspaceWire,
): ForecastWorkspacePayload {
  const generatedAt = asString(payload.generated_at);
  const source: ForecastDataSource = {
    kind: generatedAt ? "live" : "unavailable",
    label: asString(payload.product)?.toUpperCase() ?? "FORECAST",
    ...(generatedAt ? { generatedAt } : {}),
  };

  return {
    // `forecasts` items are passed through as the sibling-module type. They are
    // already permissive (every field optional), so a malformed entry surfaces
    // as a sparse object rather than throwing here.
    forecasts: asArray<ForecastWorkspaceItem>(payload.forecasts),
    active_count: asCount(payload.active_count),
    closing_soon_count: asCount(payload.closing_soon_count),
    open_alert_count: asCount(payload.open_alert_count),
    generated_at: generatedAt,
    ...(asString(payload.product) ? { product: asString(payload.product)! } : {}),
    ...(asString(payload.output) ? { output: asString(payload.output)! } : {}),
    source,
  };
}

function asPacket(value: unknown): ForecastQuestionPacket | null {
  const record = asRecord(value);
  return record as ForecastQuestionPacket | null;
}

// ---------------------------------------------------------------------------
// Coercers + env helpers (mirrored from termdApi.ts)
// ---------------------------------------------------------------------------

function browserEnv(): Env {
  return ((import.meta as unknown as { env?: Env }).env ?? {}) as Env;
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function numberFromString(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asNumber(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

/** Non-negative integer count; malformed input -> 0. */
function asCount(value: unknown): number {
  const parsed = asNumber(value);
  if (parsed === null) return 0;
  const truncated = Math.trunc(parsed);
  return truncated > 0 ? truncated : 0;
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
