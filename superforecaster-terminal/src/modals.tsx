import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { fmt, fmtSigned, useArrowNav } from "./components";
import {
  SECTORS_LIST,
  SECTOR_DISPLAY,
  useActiveFilter,
  useActiveSymbol,
  useAlerts,
  useProvider,
  useQuote,
  useTheme,
  useWatchlists,
  useDesks,
  type AlertCondition,
  type ThemeName,
  type DeskSnapshot,
} from "./providers";
import { SCREEN_LABELS, type FKey } from "./screens";

/* ─────────────────────────────────────────────────────────────────────────────
   Modal context
   ──────────────────────────────────────────────────────────────────────────── */

type ModalRender = (close: () => void) => ReactNode;

const ModalCtx = createContext<{
  open: (render: ModalRender) => void;
  close: () => void;
} | null>(null);

export function ModalRoot({ children }: { children: ReactNode }) {
  // Each call to open() bumps `gen` and stores it alongside the render
  // function. We key the modal frame by `gen` so every open() remounts the
  // inner subtree instead of reusing stale local form state.
  const [modal, setModal] = useState<{ render: ModalRender; gen: number } | null>(null);
  const genRef = useRef(0);
  const open = (render: ModalRender) => {
    genRef.current += 1;
    setModal({ render, gen: genRef.current });
  };
  const close = () => setModal(null);

  useEffect(() => {
    if (!modal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal]);

  return (
    <ModalCtx.Provider value={{ open, close }}>
      {children}
      {modal && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) close();
          }}
        >
          <div className="modal-frame" key={modal.gen}>
            {modal.render(close)}
          </div>
        </div>
      )}
    </ModalCtx.Provider>
  );
}

export function useModal() {
  const ctx = useContext(ModalCtx);
  if (!ctx) throw new Error("useModal must be inside <ModalRoot>");
  return ctx;
}

function ModalHeader({
  title,
  right,
  onClose,
}: {
  title: string;
  right?: ReactNode;
  onClose: () => void;
}) {
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-3 py-1 text-[12px] font-semibold uppercase tracking-wider text-term-on-accent">
      <span>{title}</span>
      <div className="flex items-center gap-3">
        {right}
        <button
          onClick={onClose}
          className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
        >
          ESC
        </button>
      </div>
    </header>
  );
}

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <span className="w-28 text-term-dim">{label}</span>
      {children}
    </div>
  );
}
function Toggle<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { v: T; label: string; cls?: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex border border-term-border-hi">
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
          onClick={() => onChange(o.v)}
          className={`px-3 py-1 text-[11px] uppercase ${
            value === o.v
              ? `bg-term-accent text-term-on-accent ${o.cls ?? ""}`
              : `text-term-text hover:bg-term-accent/15 ${o.cls ?? ""}`
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Alerts Manager
   ──────────────────────────────────────────────────────────────────────────── */

export function AlertsManager({ close }: { close: () => void }) {
  const [active] = useActiveSymbol();
  const provider = useProvider();
  const { alerts } = useAlerts();
  const [symbol, setSymbol] = useState(active);
  const [condition, setCondition] = useState<AlertCondition>(">=");
  const [level, setLevel] = useState("");
  const { quote } = useQuote(symbol);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const lv = parseFloat(level);
    if (!isFinite(lv) || lv <= 0 || !symbol) return;
    provider.addAlert({ symbol: symbol.toUpperCase(), level: lv, condition });
    setLevel("");
  };

  return (
    <>
      <ModalHeader title="Alerts" right={<span className="text-[10px] text-term-on-accent/70">{alerts.filter(a => a.status === "ACTIVE").length} ACTIVE</span>} onClose={close} />
      <div className="min-h-0 flex-1 overflow-auto">
        <form onSubmit={submit} className="space-y-2 border-b border-term-border p-3 text-[12px] uppercase">
          <div className="grid grid-cols-[auto_auto_auto_auto] items-center gap-2">
            <span className="text-term-dim">Symbol</span>
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="w-28 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
            />
            <Toggle
              value={condition}
              options={[
                { v: ">=", label: "≥ (HIT UP)" },
                { v: "<=", label: "≤ (HIT DOWN)" },
              ]}
              onChange={(v) => setCondition(v as AlertCondition)}
            />
            <input
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              placeholder={quote ? fmt(quote.last, 2) : "level"}
              className="w-28 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none tabular-nums focus:border-term-accent"
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-term-dim">
              {quote ? `CURRENT ${quote.ticker} · ${fmt(quote.last, 2)}` : ""}
            </span>
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              ADD ALERT &lt;GO&gt;
            </button>
          </div>
        </form>
        {alerts.length === 0 ? (
          <div className="p-6 text-center text-[12px] uppercase text-term-dim">
            No alerts. Create one above; the status bar pill blinks on trigger.
          </div>
        ) : (
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-term-panel text-term-dim">
              <tr>
                <th className="px-2 py-1 text-left font-normal uppercase">Created</th>
                <th className="px-2 py-1 text-left font-normal uppercase">Symbol</th>
                <th className="px-2 py-1 text-left font-normal uppercase">Cond</th>
                <th className="px-2 py-1 text-right font-normal uppercase">Level</th>
                <th className="px-2 py-1 text-left font-normal uppercase">Status</th>
                <th className="px-2 py-1 text-right font-normal uppercase">Triggered</th>
                <th className="px-2 py-1 text-right font-normal uppercase">Action</th>
              </tr>
              <tr><th colSpan={7} className="border-b border-term-border p-0" /></tr>
            </thead>
            <tbody>
              {alerts.map((a) => {
                const status =
                  a.status === "ACTIVE" ? "text-term-yellow" :
                  a.status === "TRIGGERED" ? "text-term-green" :
                  "text-term-dim";
                return (
                  <tr key={a.id} className="border-b border-term-border/60 hover:bg-term-accent/10">
                    <td className="px-2 py-[3px] text-term-dim">
                      {a.createdAt > 0
                        ? new Date(a.createdAt).toLocaleTimeString("en-GB", { hour12: false })
                        : "REMOTE"}
                    </td>
                    <td className="px-2 py-[3px] text-term-accent-hi">{a.symbol}</td>
                    <td className="px-2 py-[3px] text-term-text">{a.condition}</td>
                    <td className="px-2 py-[3px] text-right text-term-text">{fmt(a.level, 2)}</td>
                    <td className={`px-2 py-[3px] ${status}`}>{a.status}</td>
                    <td className="px-2 py-[3px] text-right text-term-text">
                      {a.triggeredPx != null ? fmt(a.triggeredPx, 2) : "—"}
                    </td>
                    <td className="px-2 py-[3px] text-right">
                      {a.status === "ACTIVE" && !a.source ? (
                        <button
                          onClick={() => provider.cancelAlert(a.id)}
                          className="border border-term-red px-1.5 py-[1px] text-[10px] text-term-red hover:bg-term-red/15"
                        >
                          CXL
                        </button>
                      ) : (
                        <span className="text-term-dim">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Command Palette — Cmd/Ctrl+K
   ──────────────────────────────────────────────────────────────────────────── */

export type PaletteAction =
  | { kind: "symbol"; symbol: string; label: string }
  | { kind: "screen"; key: string; label: string }
  | { kind: "action"; id: string; label: string }
  | { kind: "sector"; sector: string; label: string };

export function CommandPalette({
  close,
  onScreen,
  onAction,
}: {
  close: () => void;
  onScreen: (key: string) => void;
  onAction: (id: string) => void;
}) {
  const provider = useProvider();
  const [, setActive] = useActiveSymbol();
  const [, setFilter] = useActiveFilter();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeItemRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const items: PaletteAction[] = useMemo(() => {
    const out: PaletteAction[] = [];
    // Sectors — appear first so a bare "tech" goes to filter, not ticker.
    for (const s of SECTORS_LIST) {
      out.push({
        kind: "sector",
        sector: s,
        label: `${s} · ${SECTOR_DISPLAY[s]} · filter every screen to this sector`,
      });
    }
    out.push({
      kind: "sector",
      sector: "CLEAR",
      label: "CLEAR · remove active sector filter",
    });
    // Screens
    const fkeys: FKey[] = ["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12"];
    for (const k of fkeys) {
      out.push({ kind: "screen", key: k, label: `${k} · ${SCREEN_LABELS[k]}` });
    }
    const secondaries: { key: string; label: string }[] = [
      { key: "SF",   label: "SF · Superforecaster desk (distributions · calibration)" },
      { key: "MSG",  label: "MSG · AI co-pilot chat  [⌘/]" },
      { key: "MOST", label: "MOST · Movers (gainers / losers / actives)" },
      { key: "ERN",  label: "ERN · Earnings calendar" },
      { key: "CORR", label: "CORR · Correlation matrix" },
      { key: "GIP",  label: "GIP · Multi-chart grid" },
    ];
    for (const s of secondaries) out.push({ kind: "screen", key: s.key, label: s.label });
    // Actions
    out.push({ kind: "action", id: "alrt",  label: "ALRT · alerts manager  [⌘E]" });
    out.push({ kind: "action", id: "thm",   label: "THM · theme switcher  [⌘,]" });
    out.push({ kind: "action", id: "desk",  label: "DESK · switch / save desks (curated cockpits)  [⌘[]" });
    out.push({ kind: "action", id: "pause", label: "PAUSE · pause / resume tick stream  [SPACE]" });
    // Symbols (from all subscribed)
    for (const s of provider.allSymbols()) {
      const qq = provider.getQuote(s);
      out.push({ kind: "symbol", symbol: s, label: `${s}${qq ? `  ${fmt(qq.last, 2)}  ${fmtSigned(qq.pct, 2)}%` : ""}${qq?.name ? `  · ${qq.name}` : ""}` });
    }
    return out;
  }, [provider]);

  // `/` prefix scopes results to sector entries only — power-user mode.
  const filtered = useMemo(() => {
    const raw = q.trim();
    const isSectorMode = raw.startsWith("/");
    const needle = (isSectorMode ? raw.slice(1) : raw).toLowerCase();
    const pool = isSectorMode
      ? items.filter((it) => it.kind === "sector")
      : items;
    if (!needle) return (isSectorMode ? pool : pool.slice(0, 30));
    return pool
      .map((it) => ({ it, score: scoreMatch(needle, it.label.toLowerCase()) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 60)
      .map((x) => x.it);
  }, [items, q]);

  useEffect(() => { setIdx(0); }, [q]);

  const select = (it: PaletteAction) => {
    if (it.kind === "symbol") setActive(it.symbol);
    else if (it.kind === "screen") onScreen(it.key);
    else if (it.kind === "action") onAction(it.id);
    else if (it.kind === "sector") {
      setFilter(
        it.sector === "CLEAR"
          ? { kind: "none" }
          : { kind: "sector", sector: it.sector },
      );
    }
    close();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIdx((i) => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[idx]) select(filtered[idx]);
    }
  };

  return (
    <>
      <header className="flex shrink-0 items-center gap-2 border-b border-term-border bg-term-panel px-3 py-2 text-[12px] uppercase">
        <span className="text-term-accent">▸</span>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Type a symbol, screen, command, or sector (try / for sector-only)…"
          className="min-w-0 flex-1 bg-transparent text-term-accent-hi placeholder-term-muted outline-none"
          spellCheck={false}
        />
        <span className="text-[10px] text-term-dim">↑↓ navigate · ↵ select · ESC close</span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="p-6 text-center text-[12px] uppercase text-term-dim">
            No matches.
          </div>
        ) : (
          <ul className="text-[12px]">
            {filtered.map((it, i) => (
              <li
                key={`${it.kind}:${
                  "symbol" in it
                    ? it.symbol
                    : "key" in it
                      ? it.key
                      : "sector" in it
                        ? it.sector
                        : it.id
                }`}
                ref={i === idx ? activeItemRef : null}
                onMouseEnter={() => setIdx(i)}
                onClick={() => select(it)}
                className={`flex cursor-pointer items-center gap-3 border-b border-term-border/40 px-3 py-1.5 ${
                  i === idx ? "bg-term-accent/15" : "hover:bg-term-accent/10"
                }`}
              >
                <span
                  className={`w-14 shrink-0 text-[10px] uppercase ${
                    it.kind === "symbol"
                      ? "text-term-green"
                      : it.kind === "screen"
                        ? "text-term-accent"
                        : it.kind === "sector"
                          ? "text-term-cyan"
                          : "text-term-yellow"
                  }`}
                >
                  {it.kind}
                </span>
                <span className="truncate text-term-text">{it.label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function scoreMatch(needle: string, hay: string): number {
  if (!needle) return 1;
  if (hay.startsWith(needle)) return 1000 - hay.length;
  if (hay.includes(needle)) return 500 - hay.indexOf(needle);
  // Fuzzy subseq
  let hi = 0;
  for (let i = 0; i < needle.length; i++) {
    const idx = hay.indexOf(needle[i], hi);
    if (idx < 0) return 0;
    hi = idx + 1;
  }
  return 100 - (hi - needle.length);
}

/* ─────────────────────────────────────────────────────────────────────────────
   New Portfolio modal
   ──────────────────────────────────────────────────────────────────────────── */

export function NewPortfolioModal({ close }: { close: () => void }) {
  const provider = useProvider();
  const [name, setName] = useState("");
  const [cash, setCash] = useState("100000");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    const c = Math.max(0, parseFloat(cash) || 0);
    const meta = provider.createPortfolio(trimmed, c);
    provider.setActivePortfolioId(meta.id);
    close();
  };
  return (
    <>
      <ModalHeader title="New Portfolio" right={<span className="text-[10px] text-term-on-accent/70">CREATE + ACTIVATE</span>} onClose={close} />
      <div className="min-h-0 flex-1 overflow-auto p-4 text-[12px] uppercase">
        <form onSubmit={submit} className="space-y-3">
          <FieldRow label="Name">
            <input
              ref={inputRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. PRIMARY PA2"
              maxLength={40}
              className="w-72 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
              spellCheck={false}
            />
          </FieldRow>
          <FieldRow label="Starting Cash">
            <input
              value={cash}
              onChange={(e) => setCash(e.target.value.replace(/[^0-9.]/g, ""))}
              className="w-40 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none tabular-nums focus:border-term-accent"
            />
            <span className="ml-2 text-term-dim">USD</span>
          </FieldRow>
          <div className="flex justify-end gap-2 pt-3">
            <button
              type="button"
              onClick={close}
              className="border border-term-border-hi px-3 py-1 text-term-text hover:bg-term-accent/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              Create &lt;GO&gt;
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Add Position modal — for manual portfolio entry (not a trade)
   ──────────────────────────────────────────────────────────────────────────── */

export function AddPositionModal({
  portfolioId,
  portfolioName,
  close,
}: {
  portfolioId: string;
  portfolioName: string;
  close: () => void;
}) {
  const provider = useProvider();
  const [active] = useActiveSymbol();
  const [ticker, setTicker] = useState(active);
  const [qty, setQty] = useState("100");
  const [avg, setAvg] = useState("");
  const [side, setSide] = useState<"LONG" | "SHORT">("LONG");
  const [error, setError] = useState<string | null>(null);
  const tickerRef = useRef<HTMLInputElement>(null);
  useEffect(() => { tickerRef.current?.focus(); tickerRef.current?.select(); }, []);
  const { quote } = useQuote(ticker);
  const suggestedAvg = quote?.last ?? 0;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const t = ticker.toUpperCase().trim();
    const q = parseInt(qty, 10);
    const a = parseFloat(avg || String(suggestedAvg));
    if (!t) return setError("Ticker required");
    if (!q || q <= 0) return setError("Qty must be > 0");
    if (!isFinite(a) || a <= 0) return setError("Avg cost must be > 0");
    const ok = provider.addManualPosition(portfolioId, {
      ticker: t,
      qty: side === "SHORT" ? -q : q,
      avg: a,
    });
    if (!ok) return setError("Failed to add position");
    close();
  };
  return (
    <>
      <ModalHeader
        title={`Add Position — ${portfolioName}`}
        right={<span className="text-[10px] text-term-on-accent/70">MANUAL ENTRY</span>}
        onClose={close}
      />
      <div className="min-h-0 flex-1 overflow-auto p-4 text-[12px] uppercase">
        <form onSubmit={submit} className="space-y-3">
          <FieldRow label="Ticker">
            <input
              ref={tickerRef}
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              className="w-32 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
              spellCheck={false}
            />
            <span className="ml-2 text-term-dim">
              {quote ? `LIVE LAST ${fmt(quote.last, 2)}` : "no live quote"}
            </span>
          </FieldRow>
          <FieldRow label="Side">
            <Toggle
              value={side}
              options={[
                { v: "LONG",  label: "LONG",  cls: "text-term-green" },
                { v: "SHORT", label: "SHORT", cls: "text-term-red" },
              ]}
              onChange={(v) => setSide(v as "LONG" | "SHORT")}
            />
          </FieldRow>
          <FieldRow label="Qty">
            <input
              value={qty}
              onChange={(e) => setQty(e.target.value.replace(/[^0-9]/g, ""))}
              className="w-32 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none tabular-nums focus:border-term-accent"
            />
          </FieldRow>
          <FieldRow label="Avg Cost">
            <input
              value={avg}
              onChange={(e) => setAvg(e.target.value)}
              placeholder={suggestedAvg ? fmt(suggestedAvg, 2) : "0.00"}
              className="w-32 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none tabular-nums focus:border-term-accent"
            />
            <button
              type="button"
              onClick={() => setAvg(String(suggestedAvg))}
              className="ml-2 border border-term-border-hi px-2 py-0.5 text-[10px] text-term-dim hover:bg-term-accent/10"
            >
              USE LAST
            </button>
          </FieldRow>
          {error && (
            <div className="border border-term-red bg-term-red/15 px-3 py-2 text-term-red">
              ▸ {error}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-3">
            <button
              type="button"
              onClick={close}
              className="border border-term-border-hi px-3 py-1 text-term-text hover:bg-term-accent/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              Add &lt;GO&gt;
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   New Watchlist modal
   ──────────────────────────────────────────────────────────────────────────── */

export function NewWatchlistModal({ close }: { close: () => void }) {
  const { create, setActive } = useWatchlists();
  const [name, setName] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    const meta = create(name.trim(), []);
    setActive(meta.id);
    close();
  };
  return (
    <>
      <ModalHeader
        title="New Watchlist"
        right={<span className="text-[10px] text-term-on-accent/70">CREATE + ACTIVATE</span>}
        onClose={close}
      />
      <div className="min-h-0 flex-1 overflow-auto p-4 text-[12px] uppercase">
        <form onSubmit={submit} className="space-y-3">
          <FieldRow label="Name">
            <input
              ref={ref}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. AI Semis"
              maxLength={40}
              className="w-72 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
              spellCheck={false}
            />
          </FieldRow>
          <div className="text-term-dim">
            Starts empty — add symbols inline with{" "}
            <span className="text-term-accent">+ ADD SYMBOL</span> on the watchlist
            footer.
          </div>
          <div className="flex justify-end gap-2 pt-3">
            <button
              type="button"
              onClick={close}
              className="border border-term-border-hi px-3 py-1 text-term-text hover:bg-term-accent/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              Create &lt;GO&gt;
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Add Symbol to watchlist
   ──────────────────────────────────────────────────────────────────────────── */

export function AddSymbolModal({
  watchlistId,
  watchlistName,
  close,
}: {
  watchlistId: string;
  watchlistName: string;
  close: () => void;
}) {
  const { addSymbol } = useWatchlists();
  const provider = useProvider();
  const [active] = useActiveSymbol();
  const [ticker, setTicker] = useState(active);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  const { quote } = useQuote(ticker);
  const knownSymbols = useMemo(() => provider.allSymbols(), [provider]);
  const suggestions = useMemo(() => {
    const q = ticker.trim().toUpperCase();
    if (!q) return [] as string[];
    return knownSymbols
      .filter((s) => s.startsWith(q) && s !== q)
      .slice(0, 6);
  }, [ticker, knownSymbols]);

  const submit = (e?: React.FormEvent, sym?: string) => {
    e?.preventDefault();
    setError(null);
    const t = (sym ?? ticker).toUpperCase().trim();
    if (!t) return setError("Ticker required");
    if (!provider.getQuote(t)) return setError(`Unknown symbol: ${t}`);
    const ok = addSymbol(watchlistId, t);
    if (!ok) return setError(`Already in ${watchlistName}`);
    close();
  };
  return (
    <>
      <ModalHeader
        title={`Add Symbol — ${watchlistName}`}
        right={<span className="text-[10px] text-term-on-accent/70">{quote ? `LAST ${fmt(quote.last, 2)}` : "no quote"}</span>}
        onClose={close}
      />
      <div className="min-h-0 flex-1 overflow-auto p-4 text-[12px] uppercase">
        <form onSubmit={(e) => submit(e)} className="space-y-3">
          <FieldRow label="Ticker">
            <input
              ref={ref}
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              className="w-40 border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
              spellCheck={false}
            />
          </FieldRow>
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <span className="text-term-dim">Matches:</span>
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(undefined, s)}
                  className="border border-term-border-hi px-2 py-[1px] text-[11px] text-term-accent-hi hover:border-term-accent hover:bg-term-accent/10"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {error && (
            <div className="border border-term-red bg-term-red/15 px-3 py-2 text-term-red">
              ▸ {error}
            </div>
          )}
          <div className="flex justify-end gap-2 pt-3">
            <button
              type="button"
              onClick={close}
              className="border border-term-border-hi px-3 py-1 text-term-text hover:bg-term-accent/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              Add &lt;GO&gt;
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Desks — save / load / rename / delete a snapshot of the view
   ──────────────────────────────────────────────────────────────────────────── */

export function DeskManagerModal({
  currentSnapshot,
  applySnapshot,
  close,
}: {
  currentSnapshot: DeskSnapshot;
  applySnapshot: (s: DeskSnapshot) => void;
  close: () => void;
}) {
  const { desks, save, update, rename, remove } = useDesks();
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const submitNew = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    save(name.trim(), currentSnapshot);
    setName("");
  };
  return (
    <>
      <ModalHeader
        title="Desks"
        right={<span className="text-[10px] text-term-on-accent/70">{desks.length} SAVED</span>}
        onClose={close}
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <form onSubmit={submitNew} className="space-y-2 border-b border-term-border p-3 text-[12px] uppercase">
          <div className="text-term-dim">
            Save the current view (screen + symbol + watchlist + portfolio + theme) as a named
            desk. Click any saved desk to apply it.
          </div>
          <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2">
            <span className="text-term-dim">Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. AI Semis Cockpit"
              maxLength={40}
              className="border border-term-border-hi bg-term-bg px-2 py-1 text-term-accent-hi outline-none focus:border-term-accent"
              spellCheck={false}
            />
            <button
              type="submit"
              className="border border-term-accent bg-term-accent/15 px-3 py-1 text-term-accent-hi hover:bg-term-accent/25"
            >
              SAVE CURRENT
            </button>
          </div>
          <div className="text-[10px] text-term-dim">
            Current: <span className="text-term-accent">{currentSnapshot.activeKey}</span>{" "}
            · <span className="text-term-accent-hi">{currentSnapshot.activeSymbol}</span>{" "}
            · theme <span className="text-term-accent">{currentSnapshot.theme}</span>
          </div>
        </form>
        {desks.length === 0 ? (
          <div className="p-6 text-center text-[12px] uppercase text-term-dim">
            No desks yet. Create one above.
          </div>
        ) : (
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-term-panel text-term-dim">
              <tr>
                <th className="px-3 py-1 text-left font-normal uppercase">Name</th>
                <th className="px-3 py-1 text-left font-normal uppercase">Screen</th>
                <th className="px-3 py-1 text-left font-normal uppercase">Symbol</th>
                <th className="px-3 py-1 text-left font-normal uppercase">Theme</th>
                <th className="px-3 py-1 text-right font-normal uppercase">Actions</th>
              </tr>
              <tr><th colSpan={5} className="border-b border-term-border p-0" /></tr>
            </thead>
            <tbody>
              {desks.map((ws) => {
                const isEditing = editingId === ws.id;
                return (
                  <tr key={ws.id} className="border-b border-term-border/60 hover:bg-term-accent/10">
                    <td className="px-3 py-1">
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          onBlur={() => {
                            if (editDraft.trim()) rename(ws.id, editDraft.trim());
                            setEditingId(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              if (editDraft.trim()) rename(ws.id, editDraft.trim());
                              setEditingId(null);
                            }
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          className="border border-term-accent bg-term-bg px-1 py-0 text-term-accent-hi outline-none"
                        />
                      ) : (
                        <button
                          onClick={() => {
                            applySnapshot(ws.snapshot);
                            close();
                          }}
                          className="text-left text-term-accent-hi underline-offset-2 hover:underline"
                        >
                          {ws.name}
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-1 text-term-accent">{ws.snapshot.activeKey}</td>
                    <td className="px-3 py-1 text-term-accent-hi">{ws.snapshot.activeSymbol}</td>
                    <td className="px-3 py-1 text-term-text">{ws.snapshot.theme}</td>
                    <td className="px-3 py-1 text-right">
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => {
                            applySnapshot(ws.snapshot);
                            close();
                          }}
                          className="border border-term-border-hi px-2 py-[1px] text-[10px] text-term-text hover:border-term-accent hover:bg-term-accent/10"
                        >
                          LOAD
                        </button>
                        <button
                          onClick={() => update(ws.id, currentSnapshot)}
                          className="border border-term-border-hi px-2 py-[1px] text-[10px] text-term-dim hover:border-term-accent hover:bg-term-accent/10"
                          title="Overwrite with current view"
                        >
                          UPDATE
                        </button>
                        <button
                          onClick={() => {
                            setEditingId(ws.id);
                            setEditDraft(ws.name);
                          }}
                          className="border border-term-border-hi px-2 py-[1px] text-[10px] text-term-dim hover:border-term-accent hover:bg-term-accent/10"
                        >
                          RENAME
                        </button>
                        <button
                          onClick={() => {
                            // eslint-disable-next-line no-alert
                            if (window.confirm(`Delete desk "${ws.name}"?`)) remove(ws.id);
                          }}
                          className="border border-term-border-hi px-2 py-[1px] text-[10px] text-term-red hover:border-term-red hover:bg-term-red/10"
                        >
                          DEL
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Theme switcher
   ──────────────────────────────────────────────────────────────────────────── */

export function ThemeSwitcher({ close }: { close: () => void }) {
  const { theme, setTheme } = useTheme();
  const choices: { v: ThemeName; label: string; desc: string }[] = [
    { v: "cream",    label: "Cream",          desc: "Warm cream on pure black (default)" },
    { v: "amber",    label: "Bloomberg Amber", desc: "Classic Bloomberg amber on black" },
    { v: "phosphor", label: "Phosphor Green",  desc: "Green-screen terminal aesthetic" },
    { v: "paper",    label: "Paper",           desc: "Light theme — black ink on warm paper" },
  ];
  const nav = useArrowNav<typeof choices[number], HTMLUListElement>({
    items: choices,
    getKey: (c) => c.v,
    current: theme,
    setCurrent: (v) => setTheme(v as ThemeName),
  });
  return (
    <>
      <ModalHeader title="Theme" right={<span className="text-[10px] text-term-on-accent/70">PRESS 1–4 OR ↑↓</span>} onClose={close} />
      <div className="min-h-0 flex-1 overflow-auto p-4 text-[12px] uppercase">
        <ul
          ref={nav.ref}
          tabIndex={nav.tabIndex}
          onClick={nav.onClick}
          onKeyDown={nav.onKeyDown}
          className="space-y-2 outline-none"
        >
          {choices.map((c, i) => (
            <li key={c.v} data-nav-key={c.v}>
              <button
                onClick={() => { setTheme(c.v); }}
                className={`flex w-full items-center gap-4 border px-3 py-2 text-left ${
                  c.v === theme
                    ? "border-term-accent bg-term-accent/15"
                    : "border-term-border-hi hover:bg-term-accent/10"
                }`}
              >
                <span className="border border-term-accent-hi px-1.5 py-[1px] text-[11px] text-term-accent-hi">
                  {i + 1}
                </span>
                <span className="w-40 text-term-accent">{c.label}</span>
                <span className="text-term-text">{c.desc}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
