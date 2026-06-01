import { useEffect, useMemo, useState } from "react";
import { fmt, fmtSigned, useNow } from "./components";
import { COMMODITIES, FX, INDICES, WATCHLIST, type Quote } from "./data";
import { ChatProvider } from "./chat";
import { ForecastProviderRoot } from "./forecastProvider";
import {
  AlertsManager,
  CommandPalette,
  ModalRoot,
  ThemeSwitcher,
  DeskManagerModal,
  useModal,
} from "./modals";
import {
  DataProviderRoot,
  SECTOR_DISPLAY,
  useActiveFilter,
  useActiveSymbol,
  useAlerts,
  usePauseState,
  useProvider,
  useQuote,
  useScreenDatasets,
  useTheme,
  useTickFlash,
  type ActiveFilter,
  type ThemeName,
  type DeskSnapshot,
} from "./providers";
import { AlertToast } from "./secondaries";
import {
  SCREEN_BREADCRUMBS,
  SCREEN_LABELS,
  renderScreen,
  type FKey,
  type ScreenKey,
} from "./screens";
import type { Alert } from "./providers";

const F_KEYS: FKey[] = [
  "F1", "F2", "F3", "F4", "F5", "F6",
  "F7", "F8", "F9", "F10", "F11", "F12",
];
const SECONDARIES: ScreenKey[] = ["MSG", "MOST", "ERN", "CORR", "GIP", "SF"];
const ALL_SCREEN_KEYS: ScreenKey[] = [...F_KEYS, ...SECONDARIES];

function ActiveSymbolBadge() {
  const [active] = useActiveSymbol();
  const { quote, flash } = useQuote(active);
  if (!quote) return null;
  const unavailable = quote.source?.kind === "unavailable";
  const pos = quote.chg >= 0;
  const flashClass =
    flash === "up" ? "cell-flash-up" : flash === "down" ? "cell-flash-down" : "";
  return (
    <span className="ml-2 inline-flex items-baseline gap-2 border border-term-border-hi px-2 py-[1px]">
      <span className="text-term-dim">SEC</span>
      <span className="text-term-accent-hi">{quote.ticker}</span>
      <span className={`tabular-nums text-term-text ${flashClass}`}>
        {unavailable ? "N/A" : fmt(quote.last, 2)}
      </span>
      <span className={`tabular-nums ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : `${pos ? "▲" : "▼"} ${fmtSigned(quote.pct, 2)}%`}
      </span>
    </span>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   top bar
   ──────────────────────────────────────────────────────────────────────────── */

function TopBar({ now, activeKey }: { now: Date; activeKey: ScreenKey }) {
  const dateStr = now
    .toLocaleDateString("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
    })
    .toUpperCase();
  const timeStr =
    now.toLocaleTimeString("en-GB", { hour12: false }) +
    "." +
    String(now.getMilliseconds()).padStart(3, "0").slice(0, 2);

  const breadcrumb = SCREEN_BREADCRUMBS[activeKey];
  const [head, ...rest] = breadcrumb.split(" / ");
  const tail = rest.join(" / ");

  return (
    <div className="flex items-stretch border-b border-term-border-hi bg-term-bg-elev text-[11px] uppercase">
      <div className="flex items-center gap-2 border-r border-term-border-hi px-3 py-1 font-bold text-term-accent-hi">
        <span className="inline-block h-2 w-2 bg-term-accent pulse-dot" />
        BBRG&nbsp;TERMINAL <span className="text-term-dim">TX-02</span>
      </div>

      <div className="flex flex-1 items-center gap-3 px-3 py-1">
        <span className="text-term-dim">SCR:</span>
        <span className="text-term-accent">{activeKey} {SCREEN_LABELS[activeKey]}</span>
        <span className="text-term-dim">/</span>
        <span className="text-term-text">{head}</span>
        {tail && (
          <>
            <span className="text-term-dim">/</span>
            <span className="text-term-accent-hi">{tail}</span>
          </>
        )}
        <ActiveSymbolBadge />
        <span className="ml-auto text-term-dim">⌘K</span>
        <span className="border border-term-accent/60 px-1 text-term-accent">PALETTE</span>
        <span className="text-term-dim">·</span>
        <span className="text-term-dim">DATA</span>
        <span className="border border-term-accent/60 px-1 text-term-accent">READ ONLY</span>
      </div>

      <div className="flex items-center divide-x divide-term-border-hi border-l border-term-border-hi text-term-text">
        <div className="px-3 py-1">
          <span className="text-term-dim">USR </span>
          <span className="text-term-accent">OPERATOR</span>
        </div>
        <div className="px-3 py-1">
          <span className="text-term-dim">SES </span>
          <span className="text-term-green">SECURE</span>
        </div>
        <div className="px-3 py-1 tabular-nums">
          <span className="text-term-dim">LAT </span>
          <span className="text-term-green">11ms</span>
        </div>
        <div className="px-3 py-1 tabular-nums">{dateStr}</div>
        <div className="px-3 py-1 tabular-nums text-term-accent-hi">{timeStr} ET</div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   function-key bar
   ──────────────────────────────────────────────────────────────────────────── */

function FunctionBar({
  activeKey,
  onSelect,
}: {
  activeKey: ScreenKey;
  onSelect: (k: ScreenKey) => void;
}) {
  return (
    <div className="flex border-b border-term-border-hi bg-term-bg-elev text-[10.5px] uppercase">
      {F_KEYS.map((k) => {
        const isActive = k === activeKey;
        return (
          <button
            key={k}
            onClick={() => onSelect(k)}
            aria-pressed={isActive}
            className={`group flex flex-1 items-center justify-center gap-2 border-r border-term-border-hi px-2 py-1 transition-colors last:border-r-0 ${
              isActive
                ? "bg-term-accent text-term-on-accent"
                : "text-term-text hover:bg-term-accent/15 hover:text-term-accent-hi"
            }`}
          >
            <span className={isActive ? "text-term-on-accent" : "text-term-dim group-hover:text-term-accent"}>
              {k}
            </span>
            <span className="tracking-wider">{SCREEN_LABELS[k]}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   ticker
   ──────────────────────────────────────────────────────────────────────────── */

function TickerSymbol({ q }: { q: Quote }) {
  const { quote } = useQuote(q.ticker);
  const live = quote ?? q;
  const unavailable = live.source?.kind === "unavailable";
  const flash = useTickFlash(live.last);
  const pos = live.chg >= 0;
  const flashClass =
    flash === "up" ? "cell-flash-up" : flash === "down" ? "cell-flash-down" : "";
  return (
    <span className="inline-flex items-baseline gap-2 px-4">
      <span className="text-term-accent-hi">{live.ticker}</span>
      <span className={`tabular-nums text-term-text ${flashClass}`}>
        {unavailable ? "N/A" : fmt(live.last, 2)}
      </span>
      <span className={`tabular-nums ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : `${pos ? "▲" : "▼"} ${fmtSigned(live.pct, 2)}%`}
      </span>
      <span className="text-term-muted">│</span>
    </span>
  );
}

function FilterBanner() {
  const [filter, setFilter] = useActiveFilter();
  if (filter.kind === "none") return null;
  const label =
    filter.kind === "sector"
      ? `${filter.sector} · ${SECTOR_DISPLAY[filter.sector] ?? filter.sector}`
      : "filter";
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-term-border-hi bg-term-accent/10 px-2 py-1 text-[11px] uppercase">
      <span className="text-term-dim">LENS ▸</span>
      <span className="inline-flex items-baseline gap-2 border border-term-accent bg-term-accent/15 px-2 py-[1px]">
        <span className="text-term-cyan">SECTOR</span>
        <span className="text-term-accent-hi">{label}</span>
        <button
          onClick={() => setFilter({ kind: "none" })}
          className="ml-1 border-l border-term-accent/60 pl-2 text-term-dim hover:text-term-red"
          title="Clear filter (or ⌘K → CLEAR)"
        >
          × CLEAR
        </button>
      </span>
      <span className="ml-auto text-term-dim">
        ⌘K → /<span className="text-term-accent">sector</span> to change
      </span>
    </div>
  );
}

function Ticker() {
  const all = useMemo(
    () => [...INDICES, ...COMMODITIES, ...FX, ...WATCHLIST.slice(0, 10)],
    [],
  );
  return (
    <div className="overflow-hidden border-b border-term-border-hi bg-term-bg text-[11px]">
      <div className="ticker-track inline-flex whitespace-nowrap py-1">
        <span className="inline-flex">{all.map((q, i) => <TickerSymbol key={`a${i}`} q={q} />)}</span>
        <span className="inline-flex">{all.map((q, i) => <TickerSymbol key={`b${i}`} q={q} />)}</span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   status bar
   ──────────────────────────────────────────────────────────────────────────── */

function StatusBar({
  now,
  activeKey,
  onSelect,
}: {
  now: Date;
  activeKey: ScreenKey;
  onSelect: (k: ScreenKey) => void;
}) {
  const [cmd, setCmd] = useState("");
  const [paused, setPaused] = usePauseState();
  const { alerts } = useAlerts();
  const datasets = useScreenDatasets();
  const activeAlerts = alerts.filter((a) => a.status === "ACTIVE").length;

  const onSubmit = (raw: string) => {
    const trimmed = raw.trim().toUpperCase();
    const m = trimmed.match(/^F(\d{1,2})$/);
    if (m) {
      const n = +m[1];
      if (n >= 1 && n <= 12) onSelect(`F${n}` as FKey);
    } else if (trimmed) {
      const byLabel = ALL_SCREEN_KEYS.find((k) => SCREEN_LABELS[k] === trimmed);
      if (byLabel) onSelect(byLabel);
    }
    setCmd("");
  };

  return (
    <div className="flex items-center gap-3 border-t border-term-border-hi bg-term-bg-elev px-2 py-1 text-[11px] uppercase">
      <button
        onClick={() => setPaused(!paused)}
        className={`flex items-center gap-1 border px-2 py-[1px] ${
          paused
            ? "border-term-yellow text-term-yellow hover:bg-term-yellow/15"
            : "border-term-green text-term-green hover:bg-term-green/15"
        }`}
        title="Space to toggle"
      >
        <span className={`inline-block h-2 w-2 align-middle ${paused ? "bg-term-yellow" : "bg-term-green pulse-dot"}`} />
        {paused ? "PAUSED" : "LIVE"}
      </button>
      <span className="text-term-dim">│</span>
      <span className="text-term-dim">NYSE</span>
      <span className="text-term-green">●</span>
      <span className="text-term-dim">NASDAQ</span>
      <span className="text-term-green">●</span>
      <span className="text-term-dim">LSE</span>
      <span className="text-term-red">●</span>
      <span className="text-term-dim">TSE</span>
      <span className="text-term-yellow">●</span>

      <span className="text-term-dim">│</span>

      <span className="text-term-dim">SCR</span>
      <span className="text-term-accent-hi">{activeKey}</span>

      <span className="text-term-dim">│</span>

      <DataPlaneStrip datasets={datasets} />

      <span className="text-term-dim">│</span>

      <span className="text-term-dim">ALRT</span>
      <span className={activeAlerts > 0 ? "text-term-yellow" : "text-term-dim"}>
        {activeAlerts}
      </span>

      <span className="text-term-dim">│</span>

      <span className="text-term-accent">CMD</span>
      <span className="text-term-text">&gt;</span>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(cmd);
        }}
        className="flex min-w-0 flex-1 items-center"
      >
        <input
          value={cmd}
          onChange={(e) => setCmd(e.target.value.toUpperCase())}
          placeholder="TYPE A SCREEN (F5 / FX / MOST / GIP) OR ⌘K FOR PALETTE"
          className="min-w-0 flex-1 bg-transparent text-term-accent-hi placeholder-term-muted outline-none"
          spellCheck={false}
        />
      </form>
      <span className="blink text-term-accent-hi">▋</span>

      <span className="text-term-dim">│</span>
      <span className="tabular-nums text-term-accent-hi">
        {now.toISOString().replace("T", " ").slice(0, 19)}Z
      </span>
    </div>
  );
}

function DataPlaneStrip({
  datasets,
}: {
  datasets: ReturnType<typeof useScreenDatasets>;
}) {
  const counts = datasetStatusCounts(datasets);
  const title = datasets
    .map((dataset) => `${dataset.key}: ${datasetStatusLabel(dataset)}`)
    .join(" · ");

  return (
    <span className="flex shrink-0 items-center gap-1 overflow-hidden" title={title}>
      <span className="text-term-dim">DATA</span>
      {counts.map((status) => (
        <span
          key={status.label}
          className={`inline-flex shrink-0 items-center gap-1 border border-term-border-hi px-1 tabular-nums ${datasetStatusClass(status.kind)}`}
        >
          <span>{status.label}</span>
          <span className="text-term-accent-hi">{status.count}</span>
        </span>
      ))}
    </span>
  );
}

function datasetStatusCounts(datasets: ReturnType<typeof useScreenDatasets>) {
  const order = ["live", "stale", "mock", "unavailable"] as const;
  return order
    .map((kind) => ({
      kind,
      label: kind === "unavailable" ? "N/A" : kind.toUpperCase(),
      count: datasets.filter((dataset) => dataset.source.kind === kind).length,
    }))
    .filter((status) => status.count > 0);
}

function datasetStatusLabel(dataset: ReturnType<typeof useScreenDatasets>[number]): string {
  if (dataset.source.kind === "unavailable") return "N/A";
  if (dataset.source.kind === "stale") return "STALE";
  return dataset.source.kind.toUpperCase();
}

function datasetStatusClass(kind: ReturnType<typeof useScreenDatasets>[number]["source"]["kind"]): string {
  switch (kind) {
    case "live":
      return "text-term-green";
    case "stale":
      return "text-term-yellow";
    case "mock":
      return "text-term-yellow";
    case "unavailable":
      return "text-term-dim";
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   keyboard shortcuts + alert toast
   ──────────────────────────────────────────────────────────────────────────── */

function GlobalShortcuts({
  activeKey,
  setActiveKey,
}: {
  activeKey: ScreenKey;
  setActiveKey: (k: ScreenKey) => void;
}) {
  const modal = useModal();
  const [paused, setPaused] = usePauseState();
  const [activeSymbol, setActiveSymbol] = useActiveSymbol();
  const provider = useProvider();
  const { theme, setTheme } = useTheme();

  const [filter, setFilter] = useActiveFilter();
  const currentSnapshot = (): DeskSnapshot => ({
    activeKey,
    activeSymbol,
    activeWatchlistId: provider.getActiveWatchlistId(),
    activePortfolioId: provider.getActivePortfolioId(),
    theme,
    filter,
  });
  const applySnapshot = (s: DeskSnapshot) => {
    setActiveKey(s.activeKey as ScreenKey);
    setActiveSymbol(s.activeSymbol);
    provider.setActiveWatchlistId(s.activeWatchlistId);
    provider.setActivePortfolioId(s.activePortfolioId);
    setTheme(s.theme as ThemeName);
    setFilter((s.filter as ActiveFilter) ?? { kind: "none" });
  };

  useEffect(() => {
    const DIGIT_MAP: Record<string, FKey> = {
      "1": "F1", "2": "F2", "3": "F3", "4": "F4", "5": "F5",
      "6": "F6", "7": "F7", "8": "F8", "9": "F9", "0": "F10",
      "-": "F11", "=": "F12",
    };

    const inInput = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return (
        !!el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          (el as HTMLElement).isContentEditable)
      );
    };

    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      // Cmd/Ctrl+K — palette (works even when typing)
      if (mod && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        modal.open((close) => (
          <CommandPalette
            close={close}
            onScreen={(k) => setActiveKey(k as ScreenKey)}
            onAction={(id) => {
              setTimeout(() => {
                if (id === "alrt")
                  modal.open((c) => <AlertsManager close={c} />);
                else if (id === "thm")
                  modal.open((c) => <ThemeSwitcher close={c} />);
                else if (id === "desk")
                  modal.open((c) => (
                    <DeskManagerModal
                      currentSnapshot={currentSnapshot()}
                      applySnapshot={applySnapshot}
                      close={c}
                    />
                  ));
                else if (id === "pause") setPaused(!paused);
              }, 0);
            }}
          />
        ));
        return;
      }

      // Other Cmd/Ctrl shortcuts
      if (mod && !e.shiftKey) {
        const k = e.key.toLowerCase();
        if (k === "/" || e.key === "/") {
          e.preventDefault();
          setActiveKey("MSG");
          return;
        }
        if (k === "e") {
          e.preventDefault();
          modal.open((c) => <AlertsManager close={c} />);
          return;
        }
        // ⌘+, for theme. ⌘+T / ⌘+Shift+T are browser-reserved
        // (New Tab / Reopen Closed Tab) and never reach the page; ⌘+,
        // is the macOS "Preferences" convention and a natural fit.
        if (e.key === ",") {
          e.preventDefault();
          modal.open((c) => <ThemeSwitcher close={c} />);
          return;
        }
        // ⌘+\ clears the active sector lens. Most natural "back to
        // unfiltered" gesture; \ is free in every major browser on
        // macOS and Windows/Linux.
        if (e.key === "\\") {
          e.preventDefault();
          setFilter({ kind: "none" });
          return;
        }
        // ⌘+[ for desks — saved snapshots of the whole view
        // (screen + symbol + watchlist + portfolio + theme). Bracket
        // keys are free in every major browser.
        if (e.key === "[") {
          e.preventDefault();
          modal.open((c) => (
            <DeskManagerModal
              currentSnapshot={currentSnapshot()}
              applySnapshot={applySnapshot}
              close={c}
            />
          ));
          return;
        }
      }

      // F-key direct. Accept any modifier — ⌘+F11 is a common workaround
      // for macOS Mission Control swallowing bare F11, and Ctrl+F-key has
      // no useful default in any major browser. preventDefault ensures the
      // browser doesn't also act on the chord.
      const fm = e.key.match(/^F(\d{1,2})$/);
      if (fm) {
        const n = +fm[1];
        if (n >= 1 && n <= 12) {
          e.preventDefault();
          setActiveKey(`F${n}` as FKey);
        }
        return;
      }

      // Plain digit-row fallback for F-keys (only when not focused on input)
      if (!mod && !inInput(e.target)) {
        // Space toggles pause
        if (e.key === " ") {
          e.preventDefault();
          setPaused(!paused);
          return;
        }
        const mapped = DIGIT_MAP[e.key];
        if (mapped) {
          e.preventDefault();
          setActiveKey(mapped);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modal, setActiveKey, paused, setPaused, activeKey, activeSymbol, theme]);

  return null;
}

function AlertToastSlot() {
  const { lastTrigger } = useAlerts();
  const [shown, setShown] = useState<Alert | null>(null);
  useEffect(() => {
    if (lastTrigger) {
      setShown(lastTrigger);
      const t = setTimeout(() => setShown(null), 4800);
      return () => clearTimeout(t);
    }
  }, [lastTrigger]);
  if (!shown) return null;
  return (
    <AlertToast
      alert={{
        symbol: shown.symbol,
        level: shown.level,
        condition: shown.condition,
        triggeredPx: shown.triggeredPx,
      }}
      onClose={() => setShown(null)}
    />
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   app
   ──────────────────────────────────────────────────────────────────────────── */

export function App() {
  return (
    <DataProviderRoot>
      <ForecastProviderRoot>
        <ModalRoot>
          <AppShell />
        </ModalRoot>
      </ForecastProviderRoot>
    </DataProviderRoot>
  );
}

function AppShell() {
  const now = useNow();
  const [activeKey, setActiveKey] = useState<ScreenKey>("F3");

  return (
    <ChatProvider
      activeKey={activeKey}
      setActiveKey={(k) => setActiveKey(k as ScreenKey)}
    >
      <AppShellBody
        now={now}
        activeKey={activeKey}
        setActiveKey={setActiveKey}
      />
    </ChatProvider>
  );
}

function AppShellBody({
  now,
  activeKey,
  setActiveKey,
}: {
  now: Date;
  activeKey: ScreenKey;
  setActiveKey: (k: ScreenKey) => void;
}) {

  // The router calls renderScreen which expects an onJump callback. For
  // secondary screens, we still accept the broader ScreenKey.
  const jump = (k: ScreenKey) => setActiveKey(k);

  return (
    <div className="flex h-screen flex-col bg-term-bg text-term-text">
      <GlobalShortcuts activeKey={activeKey} setActiveKey={setActiveKey} />
      <TopBar now={now} activeKey={activeKey} />
      <FunctionBar activeKey={activeKey} onSelect={setActiveKey} />
      <FilterBanner />
      <Ticker />

      <main className="grid min-h-0 flex-1 grid-cols-12 gap-px bg-term-border">
        {renderScreen(activeKey, jump)}
      </main>

      <StatusBar now={now} activeKey={activeKey} onSelect={setActiveKey} />
      <AlertToastSlot />
    </div>
  );
}
