import { useMemo, useState } from "react";
import { dataSourceDisplayLabel } from "./data";
import {
  ActiveChart,
  Chart,
  DetailRight,
  Panel,
  fmt,
  fmtSigned,
  useArrowNav,
} from "./components";
import {
  symbolPassesFilter,
  useActiveFilter,
  useActiveSymbol,
  useChartData,
  useCorrelation,
  useDetailSource,
  useEarnings,
  useMovers,
  useOptionSurface,
  useProvider,
  useWatchlists,
} from "./providers";

const fmtMaybe = (n: number | null | undefined, digits = 2) =>
  n == null ? "N/A" : fmt(n, digits);

/* ─────────────────────────────────────────────────────────────────────────────
   MOST — Movers
   ──────────────────────────────────────────────────────────────────────────── */

type MoverRow = { ticker: string; name: string; last: number; chg: number; pct: number; vol: string };

function MoversSection({
  id,
  title,
  rows,
  cls,
}: {
  id: number;
  title: string;
  rows: readonly MoverRow[];
  cls: string;
}) {
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<MoverRow, HTMLTableElement>({
    items: rows,
    getKey: (r) => r.ticker,
    current: active,
    setCurrent: setActive,
  });
  return (
    <Panel id={id} title={title} right={`TOP ${rows.length}`}>
      <table
        ref={nav.ref}
        tabIndex={nav.tabIndex}
        onClick={nav.onClick}
        onKeyDown={nav.onKeyDown}
        className="w-full text-[11px] tabular-nums outline-none"
      >
        <thead className="sticky top-0 bg-term-panel text-term-dim">
          <tr>
            <th className="px-2 py-[3px] text-left font-normal uppercase">#</th>
            <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
            <th className="px-2 py-[3px] text-left font-normal uppercase">Security</th>
            <th className="px-2 py-[3px] text-right font-normal uppercase">Last</th>
            <th className="px-2 py-[3px] text-right font-normal uppercase">Chg</th>
            <th className="px-2 py-[3px] text-right font-normal uppercase">%</th>
          </tr>
          <tr><th colSpan={6} className="border-b border-term-border p-0" /></tr>
        </thead>
        <tbody>
          {rows.map((q, i) => (
            <tr
              key={q.ticker}
              data-nav-key={q.ticker}
              onClick={() => setActive(q.ticker)}
              className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                active === q.ticker ? "row-active" : ""
              }`}
            >
              <td className="px-2 py-[3px] text-term-dim">{String(i + 1).padStart(2, " ")}</td>
              <td className="px-2 py-[3px] text-term-accent-hi">{q.ticker}</td>
              <td className="px-2 py-[3px] text-term-text">{q.name}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{fmt(q.last, 2)}</td>
              <td className={`px-2 py-[3px] text-right ${cls}`}>{fmtSigned(q.chg, 2)}</td>
              <td className={`px-2 py-[3px] text-right ${cls}`}>{fmtSigned(q.pct, 2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function MoversScreen() {
  const { gainers: allG, losers: allL, actives: allA } = useMovers();
  const [filter] = useActiveFilter();
  const apply = <T extends { ticker: string }>(rows: readonly T[]) =>
    rows.filter((r) => symbolPassesFilter(r.ticker, filter));
  const gainers = apply(allG);
  const losers = apply(allL);
  const actives = apply(allA);
  return (
    <div className="col-span-12 grid min-h-0 grid-cols-3 gap-px bg-term-border">
      <MoversSection id={1} title="Top Gainers" rows={gainers} cls="text-term-green" />
      <MoversSection id={2} title="Top Losers"  rows={losers}  cls="text-term-red" />
      <MoversSection id={3} title="Most Active (|Δ%|)" rows={actives} cls="text-term-accent-hi" />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   ERN — Earnings calendar
   ──────────────────────────────────────────────────────────────────────────── */

export function EarningsScreen() {
  const earnings = useEarnings();
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<{ symbol: string }, HTMLTableElement>({
    items: earnings,
    getKey: (e) => e.symbol,
    current: active,
    setCurrent: setActive,
  });
  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div className="col-span-8 flex min-h-0">
        <Panel id={1} title="Earnings Calendar" right={`${earnings.length} REPORTS · NEXT 14D`}>
          <table
            ref={nav.ref}
            tabIndex={nav.tabIndex}
            onClick={nav.onClick}
            onKeyDown={nav.onKeyDown}
            className="w-full text-[11px] tabular-nums outline-none"
          >
            <thead className="sticky top-0 bg-term-panel text-term-dim">
              <tr>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Date</th>
                <th className="px-2 py-[3px] text-left font-normal uppercase">When</th>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Security</th>
                <th className="px-2 py-[3px] text-right font-normal uppercase">Cons EPS</th>
                <th className="px-2 py-[3px] text-right font-normal uppercase">Prev EPS</th>
                <th className="px-2 py-[3px] text-right font-normal uppercase">Cons Rev</th>
                <th className="px-2 py-[3px] text-right font-normal uppercase">Implied Move</th>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Src</th>
              </tr>
              <tr><th colSpan={9} className="border-b border-term-border p-0" /></tr>
            </thead>
            <tbody>
              {earnings.map((e, i) => {
                const unavailable = e.source?.kind === "unavailable";
                const move = unavailable ? "N/A" : `±${(((i * 131) % 8) + 2).toFixed(1)}%`;
                const source = dataSourceDisplayLabel(e.source);
                return (
                  <tr
                    key={i}
                    data-nav-key={e.symbol}
                    onClick={() => setActive(e.symbol)}
                    className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                      active === e.symbol ? "row-active" : ""
                    }`}
                  >
                    <td className="px-2 py-[3px] text-term-text">{e.date}</td>
                    <td className="px-2 py-[3px] text-term-accent">{e.whenStr}</td>
                    <td className="px-2 py-[3px] text-term-accent-hi">{e.symbol}</td>
                    <td className="px-2 py-[3px] text-term-text">{e.name}</td>
                    <td className="px-2 py-[3px] text-right text-term-text">{fmtMaybe(e.consensusEps, 2)}</td>
                    <td className="px-2 py-[3px] text-right text-term-dim">{fmtMaybe(e.prevEps, 2)}</td>
                    <td className="px-2 py-[3px] text-right text-term-text">{e.consensusRev}</td>
                    <td className="px-2 py-[3px] text-right text-term-yellow">{move}</td>
                    <td className="px-2 py-[3px] text-term-yellow">{source}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      </div>
      <div className="col-span-4 flex min-h-0">
        <Panel id={2} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY" />}>
          <ActiveChart />
        </Panel>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   CORR — Correlation matrix over the watchlist
   ──────────────────────────────────────────────────────────────────────────── */

function corrColor(rho: number) {
  // -1 .. +1 → red .. neutral .. green
  if (!Number.isFinite(rho)) {
    return { bg: "transparent", fg: "var(--color-term-dim)" };
  }
  if (rho > 0) {
    const a = Math.min(1, rho);
    return {
      bg: `color-mix(in srgb, var(--color-term-green) ${(8 + a * 55).toFixed(0)}%, transparent)`,
      fg: "var(--color-term-text)",
    };
  } else {
    const a = Math.min(1, -rho);
    return {
      bg: `color-mix(in srgb, var(--color-term-red) ${(8 + a * 55).toFixed(0)}%, transparent)`,
      fg: "var(--color-term-text)",
    };
  }
}

export function CorrelationScreen() {
  const [, setActive] = useActiveSymbol();
  const { activeSymbols } = useWatchlists();
  const [filter] = useActiveFilter();
  const symbols = useMemo(
    () =>
      activeSymbols
        .filter((s) => symbolPassesFilter(s, filter))
        .slice(0, 12)
        .map((s) => String(s)),
    [activeSymbols, filter],
  );
  const m = useCorrelation(symbols);
  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div className="col-span-9 flex min-h-0">
        <Panel id={1} title="Correlation — Watchlist (60D)" right="ρ · click row or column to set active">
          <div className="overflow-auto">
            <table className="w-full border-separate border-spacing-0 text-[11px] tabular-nums">
              <thead className="sticky top-0 bg-term-panel text-term-dim">
                <tr>
                  <th className="px-2 py-[3px] text-left font-normal uppercase"> </th>
                  {symbols.map((s) => (
                    <th
                      key={s}
                      onClick={() => setActive(s)}
                      className="cursor-pointer px-2 py-[3px] text-right font-normal text-term-accent-hi hover:bg-term-accent/15"
                    >
                      {s}
                    </th>
                  ))}
                </tr>
                <tr><th colSpan={symbols.length + 1} className="border-b border-term-border p-0" /></tr>
              </thead>
              <tbody>
                {m.map((row, i) => (
                  <tr key={i}>
                    <td
                      onClick={() => setActive(symbols[i])}
                      className="cursor-pointer border-b border-term-border/60 px-2 py-[3px] text-term-accent-hi hover:bg-term-accent/15"
                    >
                      {symbols[i]}
                    </td>
                    {row.map((v, j) => {
                      const { bg, fg } = corrColor(v);
                      return (
                        <td
                          key={j}
                          className="border-b border-term-border/60 px-2 py-[3px] text-right tabular-nums"
                          style={{ background: i === j ? "var(--color-term-panel)" : bg, color: fg }}
                        >
                          {i === j ? "1.00" : Number.isFinite(v) ? v.toFixed(2) : "N/A"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="col-span-3 flex min-h-0">
        <Panel id={2} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY" />}>
          <ActiveChart />
        </Panel>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   GIP — Multi-chart grid
   ──────────────────────────────────────────────────────────────────────────── */

const QUADRANT_DEFAULTS = ["NVDA", "AAPL", "TSLA", "MSFT"];

export function MultiChartScreen() {
  const [symbols, setSymbols] = useState<string[]>(QUADRANT_DEFAULTS);
  const [activeQuad, setActiveQuad] = useState(0);
  const [activeSym] = useActiveSymbol();
  const provider = useProvider();
  const { activeSymbols } = useWatchlists();
  const watchlistSymbols = activeSymbols
    .map((s) => provider.getQuote(s))
    .filter((q): q is NonNullable<typeof q> => !!q)
    .slice(0, 16);

  const setQuad = (i: number, sym: string) => {
    setSymbols((s) => {
      const next = [...s];
      next[i] = sym;
      return next;
    });
  };

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div
        className="col-span-9 grid min-h-0 gap-px bg-term-border"
        style={{
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gridTemplateRows: "repeat(2, minmax(0, 1fr))",
        }}
      >
        {symbols.map((sym, i) => (
          <button
            key={i}
            onClick={() => setActiveQuad(i)}
            className={`flex min-h-0 flex-col border bg-term-panel text-left ${
              i === activeQuad
                ? "border-term-accent"
                : "border-term-border hover:border-term-border-hi"
            }`}
          >
            <header className={`flex shrink-0 items-center justify-between border-b border-term-border px-2 py-[2px] text-[11px] uppercase ${
              i === activeQuad ? "bg-term-accent text-term-on-accent" : "bg-term-panel text-term-accent-hi"
            }`}>
              <span>
                <span className="mr-2">Q{i + 1})</span>
                {sym}
              </span>
              <span className="text-[10px] opacity-70">
                {i === activeQuad ? "ACTIVE · ⏎ TO BIND" : "CLICK TO FOCUS"}
              </span>
            </header>
            <div className="min-h-0 flex-1 overflow-hidden">
              <QuadChart symbol={sym} />
            </div>
          </button>
        ))}
      </div>
      <div className="col-span-3 flex min-h-0">
        <Panel id={1} title="Bind Quadrant" right={`Q${activeQuad + 1}`}>
          <div className="space-y-2 p-3 text-[12px] uppercase">
            <div className="text-term-dim">
              Click a watchlist row below to bind it to{" "}
              <span className="text-term-accent-hi">Q{activeQuad + 1}</span>.
            </div>
            <div className="rounded border border-term-border-hi p-2">
              <div className="mb-1 text-term-dim">CURRENT</div>
              <div className="text-term-accent-hi">{symbols[activeQuad]}</div>
            </div>
            <div className="rounded border border-term-border-hi p-2">
              <div className="mb-1 text-term-dim">USE ACTIVE</div>
              <button
                onClick={() => setQuad(activeQuad, activeSym)}
                className="border border-term-accent bg-term-accent/15 px-2 py-1 text-term-accent-hi hover:bg-term-accent/25"
              >
                Bind {activeSym} → Q{activeQuad + 1}
              </button>
            </div>
            <ul>
              {watchlistSymbols.map((q) => (
                <li key={q.ticker}>
                  <button
                    onClick={() => setQuad(activeQuad, q.ticker)}
                    className="flex w-full items-center justify-between border-b border-term-border/60 px-2 py-1 hover:bg-term-accent/10"
                  >
                    <span className="text-term-accent-hi">{q.ticker}</span>
                    <span className="text-term-text">{q.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function QuadChart({ symbol }: { symbol: string }) {
  const data = useChartData(symbol);
  const source = useDetailSource("chart", symbol);
  return <Chart title={symbol} subtitle="GP · INTRADAY" data={data} source={source} />;
}

/* ─────────────────────────────────────────────────────────────────────────────
   OVDV — Volatility surface (used as 4th tab in EQTY TabbedPanel)
   ──────────────────────────────────────────────────────────────────────────── */

function ivColor(iv: number, atm: number) {
  const x = (iv - atm) / Math.max(0.001, atm);  // -1..+1 ish
  const a = Math.min(1, Math.abs(x) * 2);
  if (x >= 0) {
    return {
      bg: `color-mix(in srgb, var(--color-term-red) ${(8 + a * 55).toFixed(0)}%, transparent)`,
      fg: "var(--color-term-text)",
    };
  } else {
    return {
      bg: `color-mix(in srgb, var(--color-term-green) ${(8 + a * 55).toFixed(0)}%, transparent)`,
      fg: "var(--color-term-text)",
    };
  }
}

export function VolatilitySurface({ symbol }: { symbol: string }) {
  const s = useOptionSurface(symbol);
  const source = useDetailSource("vol-surface", symbol);
  // ATM index = strike closest to spot, approximated as middle of the strikes
  const atmIdx = Math.floor(s.strikes.length / 2);
  const atm = s.iv[0]?.[atmIdx] ?? 25;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-baseline justify-between border-b border-term-border px-2 py-1 text-[11px] uppercase">
        <span className="text-term-accent-hi">{symbol} · Volatility Surface</span>
        <span className="text-term-dim">
          EXPIRY × STRIKE · IV % · {dataSourceDisplayLabel(source)}
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-[11px] tabular-nums">
          <thead className="sticky top-0 bg-term-panel text-term-dim">
            <tr>
              <th className="px-2 py-[3px] text-left font-normal uppercase">Expiry</th>
              {s.strikes.map((k) => (
                <th key={k} className="px-2 py-[3px] text-right font-normal text-term-accent">
                  {fmt(k, 2)}
                </th>
              ))}
            </tr>
            <tr><th colSpan={s.strikes.length + 1} className="border-b border-term-border p-0" /></tr>
          </thead>
          <tbody>
            {s.expiries.length === 0 && (
              <tr>
                <td
                  colSpan={Math.max(1, s.strikes.length + 1)}
                  className="px-2 py-3 text-center text-term-dim"
                >
                  {source.kind === "unavailable" ? "N/A" : "Awaiting data"}
                </td>
              </tr>
            )}
            {s.expiries.map((e, ei) => (
              <tr key={e}>
                <td className="border-b border-term-border/60 px-2 py-[3px] text-term-accent-hi">{e}</td>
                {s.iv[ei].map((v, ki) => {
                  const { bg, fg } = ivColor(v, atm);
                  return (
                    <td
                      key={ki}
                      className="border-b border-term-border/60 px-2 py-[3px] text-right"
                      style={{ background: bg, color: fg }}
                    >
                      {fmt(v, 1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Alert toast — small absolutely-positioned ribbon over the bottom-right
   ──────────────────────────────────────────────────────────────────────────── */

export function AlertToast({
  alert,
  onClose,
}: {
  alert: { symbol: string; level: number; condition: string; triggeredPx?: number };
  onClose: () => void;
}) {
  return (
    <div
      onClick={onClose}
      className="toast pointer-events-auto fixed bottom-9 right-3 z-[90] border border-term-accent bg-term-bg-elev px-3 py-2 text-[11px] uppercase"
      style={{ boxShadow: "0 0 0 1px #000, 0 4px 16px rgba(0,0,0,0.65)" }}
    >
      <div className="flex items-center gap-3">
        <span className="border border-term-yellow bg-term-yellow/15 px-1.5 py-[1px] text-term-yellow">
          ALERT
        </span>
        <span className="text-term-accent-hi">{alert.symbol}</span>
        <span className="text-term-text">
          {alert.condition} {fmt(alert.level, 2)}
        </span>
        {alert.triggeredPx != null && (
          <span className="text-term-green">@ {fmt(alert.triggeredPx, 2)}</span>
        )}
        <span className="text-term-dim">CLICK TO DISMISS</span>
      </div>
    </div>
  );
}
