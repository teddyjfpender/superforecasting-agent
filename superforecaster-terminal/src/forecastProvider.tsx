// Superforecaster data provider for the web terminal.
//
// A self-contained SIBLING to the financial `DataProvider` (providers.tsx): it
// owns its own class instance, React context, poll loop, and subscription sets.
// It never reads or writes the finance plane's state, so the two data sources
// nest cleanly without coupling. The forecast bridge is read-only and local
// (see `forecasting/webbridge.py` + the `/forecast-api` Vite proxy), so this
// provider is a plain GET-poller — no websockets, no auth.
//
// Mirrors the established patterns:
//   - `DataProviderRoot` / `useProvider`            (ref + start/stop + context)
//   - `usePredictionMarkets`                        (useReducer + subscribe + getter)
//   - `BackendFirstDataProvider.start()/stop()`     (immediate refresh + interval)

import { createContext, useContext, useEffect, useReducer, useRef } from "react";
import type { ReactNode } from "react";
import {
  createForecastApiClient,
  readForecastApiConfig,
} from "./forecastApi";
import type {
  ForecastApiClient,
  ForecastApiConfig,
  ForecastDataSource,
  ForecastQuestionPacket,
  ForecastWorkspacePayload,
} from "./forecastApi";

const DISABLED_SOURCE: ForecastDataSource = { kind: "unavailable", label: "SF (DISABLED)" };
const OFFLINE_SOURCE: ForecastDataSource = { kind: "unavailable", label: "SF" };

const EMPTY_WORKSPACE: ForecastWorkspacePayload = {
  forecasts: [],
  theses: [],
  active_count: 0,
  closing_soon_count: 0,
  open_alert_count: 0,
  thesis_count: 0,
  generated_at: null,
  source: OFFLINE_SOURCE,
};

class ForecastProvider {
  private readonly config: ForecastApiConfig | null;
  private readonly client: ForecastApiClient | null;
  private workspace: ForecastWorkspacePayload = EMPTY_WORKSPACE;
  private source: ForecastDataSource;
  private readonly questions = new Map<string, ForecastQuestionPacket | null>();
  private readonly workspaceSubs = new Set<() => void>();
  private readonly questionSubs = new Map<string, Set<() => void>>();
  private readonly pending = new Set<string>();
  private handle: number | undefined;

  constructor() {
    this.config = readForecastApiConfig();
    this.client = createForecastApiClient(this.config);
    this.source = this.client ? OFFLINE_SOURCE : DISABLED_SOURCE;
  }

  isEnabled(): boolean {
    return this.client != null;
  }

  getWorkspace(): ForecastWorkspacePayload {
    return this.workspace;
  }

  getSource(): ForecastDataSource {
    return this.source;
  }

  getQuestion(id: string): ForecastQuestionPacket | null {
    return this.questions.get(id) ?? null;
  }

  subscribeWorkspace(cb: () => void): () => void {
    this.workspaceSubs.add(cb);
    return () => {
      this.workspaceSubs.delete(cb);
    };
  }

  subscribeQuestion(id: string, cb: () => void): () => void {
    let set = this.questionSubs.get(id);
    if (!set) {
      set = new Set();
      this.questionSubs.set(id, set);
    }
    set.add(cb);
    return () => {
      set!.delete(cb);
    };
  }

  start(): void {
    if (!this.client || this.handle != null) return;
    void this.refresh();
    this.handle = window.setInterval(
      () => void this.refresh(),
      this.config?.pollMs ?? 5_000,
    );
  }

  stop(): void {
    if (this.handle != null) {
      window.clearInterval(this.handle);
      this.handle = undefined;
    }
  }

  /** Lazily fetch one question packet (the P2 "tail"); idempotent + de-duped. */
  ensureQuestion(id: string): void {
    if (!this.client || !id || this.questions.has(id) || this.pending.has(id)) return;
    this.pending.add(id);
    void this.client
      .fetchQuestion(id)
      .then((res) => {
        this.questions.set(id, res.packet);
      })
      .catch(() => {
        this.questions.set(id, null);
      })
      .finally(() => {
        this.pending.delete(id);
        this.notifyQuestion(id);
      });
  }

  private async refresh(): Promise<void> {
    if (!this.client) return;
    try {
      const payload = await this.client.fetchWorkspace();
      this.workspace = payload;
      this.source = payload.source;
    } catch {
      // Keep the last good book; flag the source as unavailable so the strip
      // reflects the dropped poll without blanking the desk.
      this.source = OFFLINE_SOURCE;
    }
    this.notifyWorkspace();
  }

  private notifyWorkspace(): void {
    for (const cb of this.workspaceSubs) cb();
  }

  private notifyQuestion(id: string): void {
    const set = this.questionSubs.get(id);
    if (!set) return;
    for (const cb of set) cb();
  }
}

const ForecastContext = createContext<ForecastProvider | null>(null);

export function ForecastProviderRoot({ children }: { children: ReactNode }) {
  const ref = useRef<ForecastProvider | null>(null);
  if (!ref.current) ref.current = new ForecastProvider();
  useEffect(() => {
    ref.current!.start();
    return () => ref.current!.stop();
  }, []);
  return (
    <ForecastContext.Provider value={ref.current}>
      {children}
    </ForecastContext.Provider>
  );
}

export function useForecastProvider(): ForecastProvider {
  const provider = useContext(ForecastContext);
  if (!provider) {
    throw new Error("useForecastProvider must be used inside <ForecastProviderRoot>");
  }
  return provider;
}

export function useForecastWorkspace(): {
  payload: ForecastWorkspacePayload;
  source: ForecastDataSource;
  enabled: boolean;
} {
  const provider = useForecastProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const unsub = provider.subscribeWorkspace(() => force());
    return () => unsub();
  }, [provider]);
  return {
    payload: provider.getWorkspace(),
    source: provider.getSource(),
    enabled: provider.isEnabled(),
  };
}

export function useForecastQuestion(id: string | null): ForecastQuestionPacket | null {
  const provider = useForecastProvider();
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (!id) return;
    provider.ensureQuestion(id);
    const unsub = provider.subscribeQuestion(id, () => force());
    return () => unsub();
  }, [provider, id]);
  return id ? provider.getQuestion(id) : null;
}
