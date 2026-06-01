import { useEffect, useMemo, useRef, useState } from "react";
import { fmt, fmtSigned, useArrowNav } from "./components";
import { useModal, AddPositionModal, NewPortfolioModal } from "./modals";
import {
  sectorFor,
  symbolPassesFilter,
  useActiveFilter,
  useActiveSymbol,
  usePortfolios,
  usePositions,
  useProvider,
} from "./providers";
import { dataSourceDisplayLabel, type Position } from "./data";

const sourceClass = (source: Position["source"]) => {
  switch (source?.kind) {
    case "live":
      return "text-term-green";
    case "stale":
      return "text-term-yellow";
    case "unavailable":
      return "text-term-dim";
    default:
      return "text-term-yellow";
  }
};

/* ─────────────────────────────────────────────────────────────────────────────
   Deterministic helpers — every analytics tab pulls per-symbol metrics
   from these so the numbers are stable across renders. Not a substitute
   for real risk math; sized to feel right and to track per-symbol identity.
   ──────────────────────────────────────────────────────────────────────────── */

function hashStr(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 16807) + 1) >>> 0;
    return (s & 0x7fffffff) / 0x7fffffff;
  };
}

/** Annualised return & vol per symbol — deterministic, 8–45% vol band. */
function riskReturnFor(ticker: string): { vol: number; ret: number } {
  const r = rng(hashStr(ticker + ":riskret"));
  const vol = 8 + r() * 37;           // 8 – 45 %
  const ret = -8 + r() * 38;          // -8 – +30 %
  return { vol, ret };
}

const FACTORS = [
  "Value",
  "Growth",
  "Momentum",
  "Quality",
  "Size",
  "Low Vol",
] as const;
type Factor = (typeof FACTORS)[number];

/** Factor score per symbol per factor — in [-1, +1]. */
function factorScoreFor(ticker: string, factor: Factor): number {
  const r = rng(hashStr(ticker + ":" + factor));
  return +(r() * 2 - 1).toFixed(2);
}

/* Reusable sizing hook (mirrors components.tsx) — kept inline so the
   analytics charts don't need to import private helpers. */
function useBox<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      const w = Math.floor(r.width);
      const h = Math.floor(r.height);
      if (w > 1 && h > 1) {
        setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  return [ref, size] as const;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Portfolio bar — selector pills + create + rename + delete
   ──────────────────────────────────────────────────────────────────────────── */

export function PortfolioBar() {
  const { portfolios, activeId, setActive, rename, remove } = usePortfolios();
  const modal = useModal();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const startRename = (id: string, current: string) => {
    setEditingId(id);
    setDraft(current);
  };
  const commitRename = () => {
    if (editingId && draft.trim()) rename(editingId, draft.trim());
    setEditingId(null);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 items-center gap-1 overflow-x-auto px-2 py-1 text-[11px] uppercase">
      <span className="shrink-0 text-term-dim">PORTFOLIO ▸</span>
      {portfolios.map((p) => {
        const isActive = p.id === activeId;
        const isEditing = editingId === p.id;
        if (isEditing) {
          return (
            <input
              key={p.id}
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitRename();
                if (e.key === "Escape") {
                  setEditingId(null);
                  setDraft("");
                }
              }}
              className="w-40 border border-term-accent bg-term-bg px-2 py-[2px] text-term-accent-hi outline-none"
              maxLength={40}
              spellCheck={false}
            />
          );
        }
        return (
          <button
            key={p.id}
            onClick={() => setActive(p.id)}
            onDoubleClick={() => startRename(p.id, p.name)}
            className={`shrink-0 border px-2 py-[2px] uppercase ${
              isActive
                ? "border-term-accent bg-term-accent text-term-on-accent"
                : "border-term-border-hi text-term-text hover:border-term-accent hover:bg-term-accent/10"
            }`}
            title="Double-click to rename"
          >
            {p.name}
          </button>
        );
      })}
      <button
        onClick={() =>
          modal.open((c) => <NewPortfolioModal close={c} />)
        }
        className="shrink-0 border border-term-border-hi px-2 py-[2px] text-term-accent hover:border-term-accent hover:bg-term-accent/10"
      >
        + NEW
      </button>
      {portfolios.length > 1 && (
        <button
          onClick={() => {
            const active = portfolios.find((p) => p.id === activeId);
            if (!active) return;
            // eslint-disable-next-line no-alert
            const ok = window.confirm(
              `Delete portfolio "${active.name}"? Positions are removed; cash is forfeit. Cannot be undone.`,
            );
            if (ok) remove(active.id);
          }}
          className="shrink-0 border border-term-border-hi px-2 py-[2px] text-term-red hover:border-term-red hover:bg-term-red/10"
          title="Delete active portfolio"
        >
          DELETE
        </button>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Account summary — live KPIs across the active portfolio
   ──────────────────────────────────────────────────────────────────────────── */

export function AccountSummary() {
  const positions = usePositions();
  const provider = useProvider();
  const { portfolios, activeId } = usePortfolios();
  const active = portfolios.find((p) => p.id === activeId);
  const cash = active?.cash ?? 0;

  const netLiq = positions.reduce((s, p) => s + p.mv, 0) + cash;
  const grossExposure = positions.reduce((s, p) => s + Math.abs(p.mv), 0);
  const longExposure = positions
    .filter((p) => p.qty > 0)
    .reduce((s, p) => s + p.mv, 0);
  const shortExposure = positions
    .filter((p) => p.qty < 0)
    .reduce((s, p) => s + p.mv, 0);

  // Day P/L: chg * qty per position
  const dayPL = positions.reduce((s, p) => {
    const q = provider.getQuote(p.ticker);
    return s + (q?.chg ?? 0) * p.qty;
  }, 0);

  const Cell = ({
    k,
    v,
    cls = "text-term-accent-hi",
  }: {
    k: string;
    v: string;
    cls?: string;
  }) => (
    <div className="flex min-w-0 flex-1 flex-col items-start justify-center border-l border-term-border first:border-l-0 px-3 py-1">
      <span className="text-[10px] uppercase text-term-dim">{k}</span>
      <span className={`truncate tabular-nums ${cls}`}>{v}</span>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 items-stretch text-[12px]">
      <Cell k="Net Liq" v={fmt(netLiq, 2)} />
      <Cell
        k="Day P/L"
        v={fmtSigned(dayPL, 2)}
        cls={dayPL >= 0 ? "text-term-green" : "text-term-red"}
      />
      <Cell k="Cash" v={fmt(cash, 2)} cls="text-term-text" />
      <Cell k="Gross Exp." v={fmt(grossExposure, 2)} cls="text-term-text" />
      <Cell
        k="Long Exp."
        v={fmt(longExposure, 2)}
        cls="text-term-green"
      />
      <Cell
        k="Short Exp."
        v={fmt(Math.abs(shortExposure), 2)}
        cls={shortExposure === 0 ? "text-term-dim" : "text-term-red"}
      />
      <Cell
        k="Positions"
        v={String(positions.length)}
        cls="text-term-text"
      />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Sector allocation — horizontal bars
   ──────────────────────────────────────────────────────────────────────────── */

export function SectorAllocation() {
  const positions = usePositions();
  const buckets = useMemo(() => {
    const m = new Map<string, { mv: number; pl: number; n: number }>();
    let total = 0;
    for (const p of positions) {
      const sector = sectorFor(p.ticker);
      const cur = m.get(sector) ?? { mv: 0, pl: 0, n: 0 };
      cur.mv += Math.abs(p.mv);
      cur.pl += p.pl;
      cur.n += 1;
      m.set(sector, cur);
      total += Math.abs(p.mv);
    }
    return Array.from(m.entries())
      .map(([sector, v]) => ({
        sector,
        mv: v.mv,
        pl: v.pl,
        n: v.n,
        pct: total > 0 ? (v.mv / total) * 100 : 0,
      }))
      .sort((a, b) => b.pct - a.pct);
  }, [positions]);

  if (buckets.length === 0) {
    return (
      <div className="p-4 text-center text-[12px] uppercase text-term-dim">
        No positions yet. Use{" "}
        <span className="text-term-accent">+ ADD POSITION</span> to create a
        manual mark/risk book.
      </div>
    );
  }
  const max = buckets[0].pct;
  return (
    <div className="space-y-1 px-3 py-2 text-[11px]">
      {buckets.map((b) => (
        <div key={b.sector} className="grid grid-cols-[88px_1fr_72px_72px] items-center gap-2">
          <span className="uppercase text-term-accent-hi">{b.sector}</span>
          <div className="relative h-3 bg-term-border/40">
            <div
              className="absolute inset-y-0 left-0 bg-term-accent"
              style={{ width: `${(b.pct / max) * 100}%` }}
            />
          </div>
          <span className="text-right tabular-nums text-term-text">
            {fmt(b.pct, 1)}%
          </span>
          <span
            className={`text-right tabular-nums ${
              b.pl >= 0 ? "text-term-green" : "text-term-red"
            }`}
          >
            {fmtSigned(b.pl, 0)}
          </span>
        </div>
      ))}
      <div className="mt-2 grid grid-cols-[88px_1fr_72px_72px] items-center gap-2 border-t border-term-border pt-2 text-[10px] uppercase text-term-dim">
        <span>SECTOR</span>
        <span>SHARE OF GROSS</span>
        <span className="text-right">%</span>
        <span className="text-right">P/L $</span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   P/L attribution — today, sorted by absolute contribution
   ──────────────────────────────────────────────────────────────────────────── */

export function PLAttribution() {
  const positions = usePositions();
  const provider = useProvider();
  const [active, setActive] = useActiveSymbol();
  const rows = useMemo(() => {
    const enriched = positions.map((p) => {
      const q = provider.getQuote(p.ticker);
      const chg = q?.chg ?? 0;
      const pct = q?.pct ?? 0;
      const dayPL = chg * p.qty;
      return { ...p, chg, pct, dayPL };
    });
    const total = enriched.reduce((s, r) => s + r.dayPL, 0);
    enriched.sort((a, b) => Math.abs(b.dayPL) - Math.abs(a.dayPL));
    return { enriched, total };
  }, [positions, provider]);

  if (rows.enriched.length === 0) {
    return (
      <div className="p-4 text-center text-[12px] uppercase text-term-dim">
        Nothing to attribute — empty portfolio.
      </div>
    );
  }
  const maxAbs = Math.max(
    ...rows.enriched.map((r) => Math.abs(r.dayPL)),
    1,
  );
  return (
    <PLAttributionTable
      enriched={rows.enriched}
      total={rows.total}
      maxAbs={maxAbs}
      active={active}
      setActive={setActive}
    />
  );
}

function PLAttributionTable({
  enriched,
  total,
  maxAbs,
  active,
  setActive,
}: {
  enriched: readonly (Position & { chg: number; pct: number; dayPL: number })[];
  total: number;
  maxAbs: number;
  active: string;
  setActive: (s: string) => void;
}) {
  const nav = useArrowNav<Position & { dayPL: number }, HTMLTableElement>({
    items: enriched,
    getKey: (r) => r.ticker,
    current: active,
    setCurrent: setActive,
  });
  return (
    <table
      ref={nav.ref}
      tabIndex={nav.tabIndex}
      onClick={nav.onClick}
      onKeyDown={nav.onKeyDown}
      className="w-full text-[11px] tabular-nums outline-none"
    >
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">%Chg</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Qty</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Day P/L</th>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Contribution</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">% of Day</th>
        </tr>
        <tr><th colSpan={6} className="border-b border-term-border p-0" /></tr>
      </thead>
      <tbody>
        {enriched.map((r) => {
          const pos = r.dayPL >= 0;
          const pctOfDay =
            total !== 0 ? (r.dayPL / total) * 100 : 0;
          const barPct = (Math.abs(r.dayPL) / maxAbs) * 100;
          return (
            <tr
              key={r.ticker}
              data-nav-key={r.ticker}
              onClick={() => setActive(r.ticker)}
              className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                active === r.ticker ? "row-active" : ""
              }`}
            >
              <td className="px-2 py-[3px] text-term-accent-hi">{r.ticker}</td>
              <td className={`px-2 py-[3px] text-right ${r.pct >= 0 ? "text-term-green" : "text-term-red"}`}>
                {fmtSigned(r.pct, 2)}%
              </td>
              <td className="px-2 py-[3px] text-right text-term-text">{r.qty.toLocaleString()}</td>
              <td className={`px-2 py-[3px] text-right ${pos ? "text-term-green" : "text-term-red"}`}>
                {fmtSigned(r.dayPL, 2)}
              </td>
              <td className="px-2 py-[3px]">
                <div className="relative h-2 bg-term-border/30">
                  <div
                    className={`absolute inset-y-0 ${pos ? "left-1/2 bg-term-green" : "right-1/2 bg-term-red"}`}
                    style={{ width: `${barPct / 2}%` }}
                  />
                  <div className="absolute inset-y-0 left-1/2 w-px bg-term-border-hi" />
                </div>
              </td>
              <td className={`px-2 py-[3px] text-right ${pos ? "text-term-green" : "text-term-red"}`}>
                {fmtSigned(pctOfDay, 1)}%
              </td>
            </tr>
          );
        })}
        <tr className="border-t border-term-border bg-term-accent/10 font-semibold">
          <td className="px-2 py-[3px] text-term-accent-hi">TOTAL</td>
          <td />
          <td />
          <td className={`px-2 py-[3px] text-right ${total >= 0 ? "text-term-green" : "text-term-red"}`}>
            {fmtSigned(total, 2)}
          </td>
          <td />
          <td className="px-2 py-[3px] text-right text-term-text">100.0%</td>
        </tr>
      </tbody>
    </table>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Positions table with delete button + inline + ADD POSITION row
   ──────────────────────────────────────────────────────────────────────────── */

export function EditablePositionsTable() {
  const allPositions = usePositions();
  const [filter] = useActiveFilter();
  const positions = allPositions.filter((p) =>
    symbolPassesFilter(p.ticker, filter),
  );
  const filteredOut = allPositions.length - positions.length;
  const { activeId, portfolios, removePosition } = usePortfolios();
  const active = portfolios.find((p) => p.id === activeId);
  const modal = useModal();
  const [activeSymbol, setActiveSymbol] = useActiveSymbol();
  const nav = useArrowNav<Position, HTMLTableElement>({
    items: positions,
    getKey: (p) => p.ticker,
    current: activeSymbol,
    setCurrent: setActiveSymbol,
  });

  if (!active) return null;

  const handleRemove = (ticker: string) => {
    // eslint-disable-next-line no-alert
    const ok = window.confirm(`Remove ${ticker} from ${active.name}?`);
    if (ok) removePosition(active.id, ticker);
  };

  return (
    <table
      ref={nav.ref}
      tabIndex={nav.tabIndex}
      onClick={nav.onClick}
      onKeyDown={nav.onKeyDown}
      className="w-full text-[11px] tabular-nums outline-none"
    >
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Security</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Qty</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Avg Cost</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Mark</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Market Val</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">P/L</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">P/L %</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Wgt</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Src</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase"> </th>
        </tr>
        <tr><th colSpan={11} className="border-b border-term-border p-0" /></tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <PositionRow
            key={p.ticker}
            p={p}
            onClickRow={() => setActiveSymbol(p.ticker)}
            onRemove={() => handleRemove(p.ticker)}
          />
        ))}
        {positions.length === 0 && (
          <tr>
            <td colSpan={11} className="px-3 py-6 text-center text-[12px] uppercase text-term-dim">
              {filteredOut > 0
                ? `Lens hides every position in ${active.name} (${filteredOut} hidden). Clear the filter to see them.`
                : <>No positions in {active.name}. Click{" "}<span className="text-term-accent">+ ADD POSITION</span> below to start.</>
              }
            </td>
          </tr>
        )}
        {positions.length > 0 && filteredOut > 0 && (
          <tr>
            <td colSpan={11} className="border-b border-term-border/60 bg-term-accent/5 px-2 py-1 text-[10px] uppercase text-term-dim">
              ▸ Lens hides <span className="text-term-cyan">{filteredOut}</span> position{filteredOut === 1 ? "" : "s"} not in the active sector.
            </td>
          </tr>
        )}
        <tr>
          <td colSpan={11} className="px-2 py-2">
            <button
              onClick={() =>
                modal.open((c) => (
                  <AddPositionModal
                    portfolioId={active.id}
                    portfolioName={active.name}
                    close={c}
                  />
                ))
              }
              className="border border-term-accent bg-term-accent/10 px-3 py-1 text-[11px] uppercase text-term-accent-hi hover:bg-term-accent/20"
            >
              + ADD POSITION
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

function PositionRow({
  p,
  onClickRow,
  onRemove,
}: {
  p: Position;
  onClickRow: () => void;
  onRemove: () => void;
}) {
  const unavailable = p.source?.kind === "unavailable";
  return (
    <tr data-nav-key={p.ticker} className="cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10">
      <td onClick={onClickRow} className="px-2 py-[3px] text-term-accent-hi">{p.ticker}</td>
      <td onClick={onClickRow} className="px-2 py-[3px] text-term-text">{p.name}</td>
      <td onClick={onClickRow} className={`px-2 py-[3px] text-right ${p.qty >= 0 ? "text-term-text" : "text-term-red"}`}>
        {p.qty.toLocaleString()}
      </td>
      <td onClick={onClickRow} className="px-2 py-[3px] text-right text-term-text">{fmt(p.avg, 2)}</td>
      <td onClick={onClickRow} className="px-2 py-[3px] text-right text-term-accent-hi">
        {unavailable ? "N/A" : fmt(p.mark, 2)}
      </td>
      <td onClick={onClickRow} className="px-2 py-[3px] text-right text-term-text">
        {unavailable ? "N/A" : fmt(p.mv, 2)}
      </td>
      <td onClick={onClickRow} className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : p.pl >= 0 ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : fmtSigned(p.pl, 2)}
      </td>
      <td onClick={onClickRow} className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : p.plPct >= 0 ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : `${fmtSigned(p.plPct, 2)}%`}
      </td>
      <td onClick={onClickRow} className="px-2 py-[3px] text-right text-term-text">
        {unavailable ? "-" : `${fmt(p.wgt, 1)}%`}
      </td>
      <td onClick={onClickRow} className={`px-2 py-[3px] text-right uppercase ${sourceClass(p.source)}`}>
        {dataSourceDisplayLabel(p.source)}
      </td>
      <td className="px-2 py-[3px] text-right">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="border border-term-border-hi px-1.5 py-[1px] text-[10px] text-term-dim hover:border-term-red hover:bg-term-red/10 hover:text-term-red"
          title="Remove position"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Performance vs Benchmark — cumulative return overlay (portfolio vs SPX),
   over the last 60 trading days. Two lines, one chart.
   ──────────────────────────────────────────────────────────────────────────── */

function generateCumReturn(seed: number, points: number, vol = 1.2, drift = 0.05) {
  const r = rng(seed);
  const out: number[] = [];
  let cum = 0;
  for (let i = 0; i < points; i++) {
    cum += drift + (r() - 0.5) * vol;
    out.push(cum);
  }
  return out;
}

export function PerformanceVsBenchmark() {
  const positions = usePositions();
  const N = 60;
  const { portfolio, spx } = useMemo(() => {
    const seed = hashStr(
      positions
        .map((p) => p.ticker)
        .sort()
        .join("|") || "empty",
    );
    return {
      portfolio: generateCumReturn(seed, N, 1.4, 0.06),
      spx: generateCumReturn(0xc0ffee, N, 1.1, 0.04),
    };
  }, [positions]);

  const [ref, size] = useBox<HTMLDivElement>();
  const W = size.w;
  const H = size.h;
  const padL = 56;
  const padR = 70;
  const padT = 10;
  const padB = 22;
  const innerW = Math.max(0, W - padL - padR);
  const innerH = Math.max(0, H - padT - padB);

  const all = [...portfolio, ...spx];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;

  const lineFor = (data: number[]) =>
    data
      .map((v, i) => {
        const x = padL + (i / (N - 1)) * innerW;
        const y = padT + (1 - (v - min) / range) * innerH;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  const portfolioEnd = portfolio[N - 1];
  const spxEnd = spx[N - 1];
  const alpha = portfolioEnd - spxEnd;
  const lastY = (v: number) =>
    padT + (1 - (v - min) / range) * innerH;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-x-4 border-b border-term-border px-2 py-1 text-[11px] uppercase">
        <div className="flex items-baseline gap-3">
          <span className="text-term-accent-hi">Portfolio vs SPX</span>
          <span className="text-term-dim">CUMULATIVE RETURN · 60D</span>
        </div>
        <div className="flex items-baseline gap-3 tabular-nums">
          <span className="text-term-dim">PORT</span>
          <span
            className={portfolioEnd >= 0 ? "text-term-green" : "text-term-red"}
          >
            {fmtSigned(portfolioEnd, 2)}%
          </span>
          <span className="text-term-dim">SPX</span>
          <span className={spxEnd >= 0 ? "text-term-green" : "text-term-red"}>
            {fmtSigned(spxEnd, 2)}%
          </span>
          <span className="text-term-dim">α</span>
          <span className={alpha >= 0 ? "text-term-green" : "text-term-red"}>
            {fmtSigned(alpha, 2)}%
          </span>
        </div>
      </div>
      <div ref={ref} className="relative min-h-0 flex-1 overflow-hidden">
        {W > 100 && H > 60 && (
          <svg
            className="block h-full w-full"
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
          >
            <rect
              x={padL}
              y={padT}
              width={innerW}
              height={innerH}
              fill="none"
              stroke="var(--color-term-border)"
              shapeRendering="crispEdges"
            />
            {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
              const v = max - f * range;
              const y = padT + f * innerH;
              return (
                <g key={i}>
                  <line
                    x1={padL}
                    x2={padL + innerW}
                    y1={y + 0.5}
                    y2={y + 0.5}
                    stroke="var(--color-term-grid)"
                    shapeRendering="crispEdges"
                  />
                  <text
                    x={padL - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize="10"
                    fill="var(--color-term-dim)"
                    fontFamily="var(--font-mono)"
                  >
                    {fmtSigned(v, 1)}%
                  </text>
                </g>
              );
            })}
            {/* Zero line */}
            <line
              x1={padL}
              x2={padL + innerW}
              y1={Math.round(lastY(0)) + 0.5}
              y2={Math.round(lastY(0)) + 0.5}
              stroke="var(--color-term-border-hi)"
              strokeDasharray="3 3"
              shapeRendering="crispEdges"
            />
            {/* SPX (benchmark) */}
            <path
              d={lineFor(spx)}
              fill="none"
              stroke="var(--color-term-cyan)"
              strokeWidth="1.3"
              strokeOpacity="0.85"
              vectorEffect="non-scaling-stroke"
            />
            {/* Portfolio (cream/accent) */}
            <path
              d={lineFor(portfolio)}
              fill="none"
              stroke="var(--color-term-accent-hi)"
              strokeWidth="1.6"
              vectorEffect="non-scaling-stroke"
            />
            {/* End labels */}
            <rect
              x={padL + innerW + 2}
              y={lastY(portfolioEnd) - 8}
              width={padR - 4}
              height={16}
              fill="var(--color-term-accent-hi)"
            />
            <text
              x={padL + innerW + (padR - 4) / 2 + 2}
              y={lastY(portfolioEnd) + 4}
              textAnchor="middle"
              fontSize="10.5"
              fill="#000"
              fontFamily="var(--font-mono)"
              fontWeight="700"
            >
              {fmtSigned(portfolioEnd, 2)}%
            </text>
            <text
              x={padL + innerW + 4}
              y={lastY(spxEnd) + 4}
              fontSize="10"
              fill="var(--color-term-cyan)"
              fontFamily="var(--font-mono)"
            >
              SPX {fmtSigned(spxEnd, 1)}%
            </text>
          </svg>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Efficient Frontier — risk/return scatter of holdings + a theoretical
   frontier curve. Bubble size = position weight.
   ──────────────────────────────────────────────────────────────────────────── */

export function EfficientFrontier() {
  const positions = usePositions();
  const [activeSym, setActive] = useActiveSymbol();
  const [ref, size] = useBox<HTMLDivElement>();

  const points = useMemo(
    () =>
      positions.map((p) => {
        const { vol, ret } = riskReturnFor(p.ticker);
        return { ticker: p.ticker, vol, ret, wgt: p.wgt };
      }),
    [positions],
  );

  const portfolio = useMemo(() => {
    if (points.length === 0) return null;
    const totalW = points.reduce((s, p) => s + p.wgt, 0) || 1;
    const ret = points.reduce((s, p) => s + (p.ret * p.wgt) / totalW, 0);
    // Diversification: portfolio vol ≈ weighted avg × 0.65 (deterministic mock).
    const wgtAvgVol = points.reduce(
      (s, p) => s + (p.vol * p.wgt) / totalW,
      0,
    );
    return { vol: wgtAvgVol * 0.65, ret };
  }, [points]);

  const W = size.w;
  const H = size.h;
  const padL = 50;
  const padR = 16;
  const padT = 14;
  const padB = 30;
  const innerW = Math.max(0, W - padL - padR);
  const innerH = Math.max(0, H - padT - padB);

  const xMin = 0;
  const xMax = 50;     // vol axis 0..50%
  const yMin = -15;
  const yMax = 35;     // return axis -15..+35%
  const xScale = (v: number) =>
    padL + ((v - xMin) / (xMax - xMin)) * innerW;
  const yScale = (v: number) =>
    padT + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  // Theoretical frontier curve — sqrt of vol scaled (purely illustrative).
  const frontier = Array.from({ length: 40 }).map((_, i) => {
    const vol = (i / 39) * xMax;
    const ret = -2 + Math.sqrt(vol) * 6.5;
    return { vol, ret };
  });
  const frontierPath = frontier
    .map((p, i) => {
      const x = xScale(p.vol);
      const y = yScale(p.ret);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-x-4 border-b border-term-border px-2 py-1 text-[11px] uppercase">
        <div className="flex items-baseline gap-3">
          <span className="text-term-accent-hi">Efficient Frontier</span>
          <span className="text-term-dim">RISK / RETURN · ANN.</span>
        </div>
        <div className="flex items-baseline gap-3 tabular-nums">
          {portfolio && (
            <>
              <span className="text-term-dim">PORT VOL</span>
              <span className="text-term-accent-hi">
                {fmt(portfolio.vol, 1)}%
              </span>
              <span className="text-term-dim">PORT RET</span>
              <span
                className={
                  portfolio.ret >= 0 ? "text-term-green" : "text-term-red"
                }
              >
                {fmtSigned(portfolio.ret, 1)}%
              </span>
              <span className="text-term-dim">SHARPE</span>
              <span className="text-term-accent-hi">
                {fmt(portfolio.ret / Math.max(0.5, portfolio.vol), 2)}
              </span>
            </>
          )}
        </div>
      </div>
      <div ref={ref} className="relative min-h-0 flex-1 overflow-hidden">
        {W > 100 && H > 80 && (
          <svg
            className="block h-full w-full"
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
          >
            <rect
              x={padL}
              y={padT}
              width={innerW}
              height={innerH}
              fill="none"
              stroke="var(--color-term-border)"
              shapeRendering="crispEdges"
            />
            {/* Grid lines + axis labels */}
            {[0, 0.2, 0.4, 0.6, 0.8, 1].map((f, i) => {
              const x = padL + f * innerW;
              const y = padT + f * innerH;
              return (
                <g key={i}>
                  <line
                    x1={x + 0.5}
                    x2={x + 0.5}
                    y1={padT}
                    y2={padT + innerH}
                    stroke="var(--color-term-grid)"
                    shapeRendering="crispEdges"
                  />
                  <line
                    x1={padL}
                    x2={padL + innerW}
                    y1={y + 0.5}
                    y2={y + 0.5}
                    stroke="var(--color-term-grid)"
                    shapeRendering="crispEdges"
                  />
                  <text
                    x={x}
                    y={padT + innerH + 14}
                    textAnchor="middle"
                    fontSize="10"
                    fill="var(--color-term-dim)"
                    fontFamily="var(--font-mono)"
                  >
                    {fmt(xMin + f * (xMax - xMin), 0)}%
                  </text>
                  <text
                    x={padL - 4}
                    y={y + 3}
                    textAnchor="end"
                    fontSize="10"
                    fill="var(--color-term-dim)"
                    fontFamily="var(--font-mono)"
                  >
                    {fmtSigned(yMax - f * (yMax - yMin), 0)}%
                  </text>
                </g>
              );
            })}
            <text
              x={padL + innerW / 2}
              y={H - 4}
              textAnchor="middle"
              fontSize="9"
              fill="var(--color-term-dim)"
              fontFamily="var(--font-mono)"
            >
              VOL (ANNUALISED %)
            </text>
            <text
              x={6}
              y={padT + innerH / 2}
              transform={`rotate(-90 6,${padT + innerH / 2})`}
              textAnchor="middle"
              fontSize="9"
              fill="var(--color-term-dim)"
              fontFamily="var(--font-mono)"
            >
              RETURN (ANN. %)
            </text>
            {/* Zero return line */}
            <line
              x1={padL}
              x2={padL + innerW}
              y1={Math.round(yScale(0)) + 0.5}
              y2={Math.round(yScale(0)) + 0.5}
              stroke="var(--color-term-border-hi)"
              strokeDasharray="3 3"
              shapeRendering="crispEdges"
            />
            {/* Frontier curve */}
            <path
              d={frontierPath}
              fill="none"
              stroke="var(--color-term-cyan)"
              strokeWidth="1.2"
              strokeOpacity="0.7"
              strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke"
            />
            {/* Position bubbles */}
            {points.map((p) => {
              const x = xScale(p.vol);
              const y = yScale(p.ret);
              const r = 3 + Math.sqrt(p.wgt) * 1.6;
              const isActive = p.ticker === activeSym;
              const color = p.ret >= 0 ? "var(--color-term-green)" : "var(--color-term-red)";
              return (
                <g key={p.ticker} style={{ cursor: "pointer" }} onClick={() => setActive(p.ticker)}>
                  <circle
                    cx={x}
                    cy={y}
                    r={r}
                    fill={color}
                    fillOpacity={0.35}
                    stroke={color}
                    strokeWidth={isActive ? 2 : 1}
                  />
                  {isActive && (
                    <circle
                      cx={x}
                      cy={y}
                      r={r + 4}
                      fill="none"
                      stroke="var(--color-term-accent-hi)"
                      strokeWidth="1.2"
                    />
                  )}
                  <text
                    x={x + r + 3}
                    y={y + 3}
                    fontSize="9"
                    fill={
                      isActive
                        ? "var(--color-term-accent-hi)"
                        : "var(--color-term-text)"
                    }
                    fontFamily="var(--font-mono)"
                  >
                    {p.ticker}
                  </text>
                </g>
              );
            })}
            {/* Portfolio aggregate */}
            {portfolio && (
              <g>
                <line
                  x1={xScale(portfolio.vol) - 8}
                  x2={xScale(portfolio.vol) + 8}
                  y1={yScale(portfolio.ret)}
                  y2={yScale(portfolio.ret)}
                  stroke="var(--color-term-accent-hi)"
                  strokeWidth="2"
                />
                <line
                  x1={xScale(portfolio.vol)}
                  x2={xScale(portfolio.vol)}
                  y1={yScale(portfolio.ret) - 8}
                  y2={yScale(portfolio.ret) + 8}
                  stroke="var(--color-term-accent-hi)"
                  strokeWidth="2"
                />
                <text
                  x={xScale(portfolio.vol) + 12}
                  y={yScale(portfolio.ret) + 4}
                  fontSize="10"
                  fill="var(--color-term-accent-hi)"
                  fontWeight="700"
                  fontFamily="var(--font-mono)"
                >
                  PORTFOLIO
                </text>
              </g>
            )}
          </svg>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Factor Exposures — weighted-average tilt per style factor, rendered as
   centered horizontal bars (negative = left/red, positive = right/green).
   ──────────────────────────────────────────────────────────────────────────── */

export function FactorExposures() {
  const positions = usePositions();
  const scores = useMemo(() => {
    const totalW = positions.reduce((s, p) => s + p.wgt, 0) || 1;
    return FACTORS.map((f) => {
      const v = positions.reduce(
        (s, p) => s + (factorScoreFor(p.ticker, f) * p.wgt) / totalW,
        0,
      );
      return { factor: f, value: +v.toFixed(2) };
    });
  }, [positions]);
  if (positions.length === 0) {
    return (
      <div className="p-4 text-center text-[12px] uppercase text-term-dim">
        Nothing to factor — empty portfolio.
      </div>
    );
  }
  return (
    <div className="space-y-2 px-3 py-3 text-[11px]">
      <div className="grid grid-cols-[100px_1fr_60px] items-center gap-2 text-[10px] uppercase text-term-dim">
        <span>FACTOR</span>
        <span>EXPOSURE (vs benchmark · −1 to +1)</span>
        <span className="text-right">SCORE</span>
      </div>
      {scores.map((s) => {
        const pct = Math.abs(s.value) * 50;       // 0..50 (half of bar)
        const isPos = s.value >= 0;
        return (
          <div
            key={s.factor}
            className="grid grid-cols-[100px_1fr_60px] items-center gap-2"
          >
            <span className="text-term-accent-hi uppercase">{s.factor}</span>
            <div className="relative h-3 bg-term-border/40">
              <div className="absolute inset-y-0 left-1/2 w-px bg-term-border-hi" />
              <div
                className={`absolute inset-y-0 ${isPos ? "left-1/2 bg-term-green" : "right-1/2 bg-term-red"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span
              className={`text-right tabular-nums ${
                isPos ? "text-term-green" : "text-term-red"
              }`}
            >
              {fmtSigned(s.value, 2)}
            </span>
          </div>
        );
      })}
      <div className="border-t border-term-border pt-2 text-[10px] uppercase text-term-dim">
        ▸ Portfolio tilts vs. a neutral benchmark. Long bars = strong
        directional exposure; short bars = roughly balanced.
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Concentration — top-N share, HHI, single-position max share.
   ──────────────────────────────────────────────────────────────────────────── */

export function Concentration() {
  const positions = usePositions();
  const rows = useMemo(
    () => [...positions].sort((a, b) => b.wgt - a.wgt),
    [positions],
  );
  if (rows.length === 0) {
    return (
      <div className="p-4 text-center text-[12px] uppercase text-term-dim">
        No positions — nothing to concentrate.
      </div>
    );
  }
  const totalW = rows.reduce((s, r) => s + r.wgt, 0);
  const top1 = rows[0]?.wgt ?? 0;
  const top5 = rows.slice(0, 5).reduce((s, r) => s + r.wgt, 0);
  const top10 = rows.slice(0, 10).reduce((s, r) => s + r.wgt, 0);
  const hhi = rows.reduce((s, r) => s + (r.wgt / 100) ** 2, 0) * 10_000;

  const Kpi = ({
    k,
    v,
    cls = "text-term-accent-hi",
  }: {
    k: string;
    v: string;
    cls?: string;
  }) => (
    <div className="flex flex-col px-3 py-1">
      <span className="text-[10px] uppercase text-term-dim">{k}</span>
      <span className={`tabular-nums ${cls}`}>{v}</span>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-stretch divide-x divide-term-border border-b border-term-border text-[12px]">
        <Kpi k="Positions" v={String(rows.length)} cls="text-term-text" />
        <Kpi k="Top 1 %" v={`${fmt(top1, 1)}%`} />
        <Kpi k="Top 5 %" v={`${fmt(top5, 1)}%`} />
        <Kpi k="Top 10 %" v={`${fmt(top10, 1)}%`} />
        <Kpi
          k="HHI"
          v={fmt(hhi, 0)}
          cls={
            hhi > 2500
              ? "text-term-red"
              : hhi > 1500
                ? "text-term-yellow"
                : "text-term-green"
          }
        />
        <Kpi k="Total Wgt" v={`${fmt(totalW, 1)}%`} cls="text-term-text" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-[11px] tabular-nums">
          <thead className="sticky top-0 bg-term-panel text-term-dim">
            <tr>
              <th className="px-2 py-[3px] text-left font-normal uppercase">#</th>
              <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
              <th className="px-2 py-[3px] text-left font-normal uppercase">Security</th>
              <th className="px-2 py-[3px] text-right font-normal uppercase">Mark</th>
              <th className="px-2 py-[3px] text-right font-normal uppercase">MV</th>
              <th className="px-2 py-[3px] text-left font-normal uppercase">Wgt</th>
              <th className="px-2 py-[3px] text-right font-normal uppercase">%</th>
            </tr>
            <tr><th colSpan={7} className="border-b border-term-border p-0" /></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={r.ticker}
                className="cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10"
              >
                <td className="px-2 py-[3px] text-term-dim">
                  {String(i + 1).padStart(2, " ")}
                </td>
                <td className="px-2 py-[3px] text-term-accent-hi">{r.ticker}</td>
                <td className="px-2 py-[3px] text-term-text">{r.name}</td>
                <td className="px-2 py-[3px] text-right text-term-text">
                  {fmt(r.mark, 2)}
                </td>
                <td className="px-2 py-[3px] text-right text-term-text">
                  {fmt(r.mv, 2)}
                </td>
                <td className="px-2 py-[3px]">
                  <div className="relative h-2 bg-term-border/40">
                    <div
                      className="absolute inset-y-0 left-0 bg-term-accent"
                      style={{ width: `${Math.min(100, (r.wgt / Math.max(1, top1)) * 100)}%` }}
                    />
                  </div>
                </td>
                <td className="px-2 py-[3px] text-right text-term-accent-hi">
                  {fmt(r.wgt, 1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Risk metrics — extracted for reuse in the new layout.
   ──────────────────────────────────────────────────────────────────────────── */

export function RiskMetricsTable() {
  return (
    <table className="w-full text-[12px] tabular-nums">
      <tbody>
        {[
          ["Portfolio Beta", "1.18"],
          ["Sharpe (1Y)", "1.42"],
          ["Sortino (1Y)", "1.84"],
          ["VaR 95% (1D)", "−42,184.20"],
          ["Max DD (1Y)", "−8.4%"],
          ["Tracking Error", "412 bps"],
          ["Information R.", "0.84"],
        ].map(([k, v]) => (
          <tr key={k} className="border-b border-term-border/60">
            <td className="px-3 py-1 uppercase text-term-dim">{k}</td>
            <td className="px-3 py-1 text-right text-term-accent-hi">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
