import { useEffect, useMemo, useRef, useState } from "react";
import {
  dataSourceDisplayLabel,
  type BondRow,
  type CbRate,
  type CdsRow,
  type CreditIndexRow,
  type DataSourceKind,
  type EventItem,
  type NewsItem,
  type Position,
  type Quote,
} from "./data";
import {
  useActiveFilter,
  useActiveSymbol,
  useChartData,
  useDetailSource,
  useDepth,
  useHeatmap,
  useOptionChain,
  usePositions,
  usePredictionMarkets,
  useQuote,
  useQuoteList,
  useResearch,
  useScreenDatasets,
  useTickFlash,
  useTimeSales,
  type DetailDataset,
  type HeatmapCell,
  type OptionRow,
  type QuoteCategory,
  type Trade,
} from "./providers";
import type { TermdPredictionMarket } from "./termdApi";

/* ─────────────────────────────────────────────────────────────────────────────
   helpers
   ──────────────────────────────────────────────────────────────────────────── */

export const fmt = (n: number, digits = 2) =>
  n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

export const fmtSigned = (n: number, digits = 2) =>
  (n >= 0 ? "+" : "") + fmt(n, digits);

const fmtMaybe = (n: number | null | undefined, digits = 2) =>
  n == null ? "N/A" : fmt(n, digits);

const fmtSignedMaybe = (n: number | null | undefined, digits = 2) =>
  n == null ? "N/A" : fmtSigned(n, digits);

const signedClass = (n: number | null | undefined) =>
  n == null ? "text-term-dim" : n >= 0 ? "text-term-red" : "text-term-green";

const sourceClass = (source: { kind: string } | undefined) => {
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

export function DatasetRight({
  datasetKey,
  fallback,
}: {
  datasetKey: string;
  fallback: string;
}) {
  const datasets = useScreenDatasets();
  const dataset = datasets.find((entry) => entry.key === datasetKey);
  if (!dataset) return <>{fallback}</>;
  const status =
    dataset.source.kind === "unavailable" ? "N/A" : dataset.source.kind.toUpperCase();
  const asOf = compactDatasetAsOf(dataset.asOf);
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <span className="truncate">{fallback}</span>
      <span>·</span>
      <span className={datasetStatusClass(dataset.source.kind)}>{status}</span>
      {asOf && (
        <>
          <span>·</span>
          <span>{asOf}</span>
        </>
      )}
    </span>
  );
}

export function DetailRight({
  kind,
  fallback,
  symbol,
}: {
  kind: DetailDataset;
  fallback: string;
  symbol?: string;
}) {
  const [active] = useActiveSymbol();
  const source = useDetailSource(kind, symbol ?? active);
  const status = source.kind === "unavailable" ? "N/A" : source.kind.toUpperCase();
  const asOf = compactDatasetAsOf(source.receivedAt ?? null);
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <span className="truncate">{fallback}</span>
      <span>·</span>
      <span className={dataSourceStatusClass(source.kind)}>{status}</span>
      {asOf && (
        <>
          <span>·</span>
          <span>{asOf}</span>
        </>
      )}
    </span>
  );
}

function datasetStatusClass(kind: ReturnType<typeof useScreenDatasets>[number]["source"]["kind"]) {
  return dataSourceStatusClass(kind);
}

function dataSourceStatusClass(kind: DataSourceKind) {
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

function compactDatasetAsOf(asOf: string | null): string | null {
  if (!asOf) return null;
  const parsed = new Date(asOf);
  if (Number.isNaN(parsed.getTime())) return asOf.slice(0, 16).toUpperCase();
  return parsed.toISOString().slice(11, 16) + "Z";
}

export const pad = (s: string | number, w: number, right = false) => {
  const str = String(s);
  if (str.length >= w) return str;
  const fill = " ".repeat(w - str.length);
  return right ? fill + str : str + fill;
};

export const useNow = () => {
  const [t, setT] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setT(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return t;
};

const flashCls = (f: "up" | "down" | null) =>
  f === "up" ? "cell-flash-up" : f === "down" ? "cell-flash-down" : "";

/* ─────────────────────────────────────────────────────────────────────────────
   arrow-key navigation

   useArrowNav makes any container (a table, list, button group) keyboard-
   navigable: click any row → the container takes focus → ↑/↓ (or ←/→) move
   "current" through the item list, calling setCurrent at each step. The
   container ends up in the tab order while it has focus, then drops out
   when blurred — so the user never has to think about it.

   Usage:

     const nav = useArrowNav({
       items: rows,
       getKey: (q) => q.ticker,
       current: active,
       setCurrent: setActive,
     });
     return <table {...nav.containerProps} className="… outline-none">…</table>;

   For horizontal nav (tabs), pass `orientation: "horizontal"`.
   ──────────────────────────────────────────────────────────────────────────── */

export function useArrowNav<T, E extends HTMLElement = HTMLElement>(opts: {
  items: readonly T[];
  getKey: (item: T) => string;
  current: string | null | undefined;
  setCurrent: (key: string) => void;
  orientation?: "vertical" | "horizontal";
  wrap?: boolean;
}) {
  const { items, getKey, current, setCurrent, orientation = "vertical", wrap = false } = opts;
  const ref = useRef<E | null>(null);

  // After keyboard nav moves the selection, scroll the new row into view —
  // but only when we own focus, so plain click selections (which scroll the
  // user's chosen click target on their own terms) aren't yanked around.
  useEffect(() => {
    if (!current) return;
    const host = ref.current;
    if (!host) return;
    if (!host.contains(document.activeElement) && document.activeElement !== host) return;
    const safe = (window.CSS && (CSS as { escape?: (s: string) => string }).escape)
      ? CSS.escape(current)
      : current.replace(/"/g, '\\"');
    const target = host.querySelector(`[data-nav-key="${safe}"]`) as HTMLElement | null;
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);

  const prevKey = orientation === "vertical" ? "ArrowUp" : "ArrowLeft";
  const nextKey = orientation === "vertical" ? "ArrowDown" : "ArrowRight";

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (items.length === 0) return;
    if (e.key !== prevKey && e.key !== nextKey && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const idx = current == null ? -1 : items.findIndex((it) => getKey(it) === current);
    let next: number;
    if (e.key === "Home") {
      next = 0;
    } else if (e.key === "End") {
      next = items.length - 1;
    } else if (e.key === nextKey) {
      if (idx < 0) next = 0;
      else if (idx >= items.length - 1) next = wrap ? 0 : items.length - 1;
      else next = idx + 1;
    } else {
      if (idx < 0) next = items.length - 1;
      else if (idx <= 0) next = wrap ? items.length - 1 : 0;
      else next = idx - 1;
    }
    setCurrent(getKey(items[next]));
  };

  return {
    ref,
    tabIndex: 0,
    onKeyDown,
    onClick: () => ref.current?.focus({ preventScroll: true }),
  };
}

/* ─────────────────────────────────────────────────────────────────────────────
   primitives
   ──────────────────────────────────────────────────────────────────────────── */

export function Panel(props: {
  id: string | number;
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
      <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-2 py-[2px] text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
        <span>
          <span className="mr-2 inline-block min-w-[1.25rem] text-right">
            {props.id})
          </span>
          {props.title}
        </span>
        <span className="text-[10px]">{props.right}</span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{props.children}</div>
    </section>
  );
}

const Th = ({
  children,
  right,
  className = "",
}: {
  children: React.ReactNode;
  right?: boolean;
  className?: string;
}) => (
  <th
    className={`px-2 py-[3px] font-normal uppercase ${right ? "text-right" : "text-left"} ${className}`}
  >
    {children}
  </th>
);

const ThRule = ({ span }: { span: number }) => (
  <tr>
    <th colSpan={span} className="border-b border-term-border p-0" />
  </tr>
);

/* ─────────────────────────────────────────────────────────────────────────────
   live tables
   ──────────────────────────────────────────────────────────────────────────── */

function MarketsRow({ q }: { q: Quote }) {
  const [active, setActive] = useActiveSymbol();
  const isActive = active === q.ticker;
  const flash = useTickFlash(q.last);
  const unavailable = q.source?.kind === "unavailable";
  const pos = q.chg >= 0;
  return (
    <tr
      data-nav-key={q.ticker}
      onClick={() => setActive(q.ticker)}
      className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
        isActive ? "row-active" : ""
      }`}
    >
      <td className="px-2 py-[3px]">
        <span className="text-term-accent-hi">{q.ticker}</span>
        <span className="ml-2 text-term-dim">{q.name}</span>
      </td>
      <td className={`px-2 py-[3px] text-right text-term-text ${flashCls(flash)}`}>
        {unavailable ? "N/A" : fmt(q.last, 2)}
      </td>
      <td
        className={`px-2 py-[3px] text-right ${
          unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"
        }`}
      >
        {unavailable ? "-" : fmtSigned(q.chg, 2)}
      </td>
      <td
        className={`px-2 py-[3px] text-right ${
          unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"
        }`}
      >
        {unavailable ? "-" : `${pos ? "▲" : "▼"} ${fmtSigned(q.pct, 2)}%`}
      </td>
      <td className="px-2 py-[3px] text-right">
        <SourceBadge source={q.source} />
      </td>
    </tr>
  );
}

function SourceBadge({ source }: { source: Quote["source"] }) {
  const label = dataSourceDisplayLabel(source);
  return (
    <span
      className={`inline-flex min-w-10 justify-center whitespace-nowrap border border-term-border-hi px-1 ${sourceClass(source)}`}
      title={[label, source?.label, source?.receivedAt].filter(Boolean).join(" ")}
    >
      {label}
    </span>
  );
}

function EmptyDataRow({ colSpan, source }: { colSpan: number; source: Quote["source"] }) {
  const label = source?.kind === "unavailable" ? "N/A" : "Awaiting data";
  return (
    <tr>
      <td colSpan={colSpan} className="px-2 py-3 text-center text-term-dim">
        <span>{label}</span>
        {source && (
          <span className="ml-2">
            <SourceBadge source={source} />
          </span>
        )}
      </td>
    </tr>
  );
}

export function MarketsTable({ category }: { category: QuoteCategory }) {
  const rows = useQuoteList(category);
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<Quote, HTMLTableElement>({
    items: rows,
    getKey: (q) => q.ticker,
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
          <Th>Ticker</Th>
          <Th right>Last</Th>
          <Th right>Chg</Th>
          <Th right>%</Th>
          <Th right>Src</Th>
        </tr>
        <ThRule span={5} />
      </thead>
      <tbody>
        {rows.map((q) => (
          <MarketsRow key={q.ticker} q={q} />
        ))}
      </tbody>
    </table>
  );
}

/** Coarse topic buckets we expose in the PRED tab filter strip. */
export const PREDICTION_TOPICS = [
  "ALL",
  "POLITICS",
  "MACRO",
  "GEOPOL",
  "CRYPTO",
  "TECH",
  "SPORTS",
  "CLIMATE",
  "ENT",
  "OTHER",
] as const;
export type PredictionTopic = (typeof PREDICTION_TOPICS)[number];

const PREDICTION_TOPIC_LABELS: Record<PredictionTopic, string> = {
  ALL: "All Topics",
  POLITICS: "Politics",
  MACRO: "Macro / Rates",
  GEOPOL: "Geopolitics",
  CRYPTO: "Crypto",
  TECH: "Tech / AI",
  SPORTS: "Sports",
  CLIMATE: "Climate",
  ENT: "Culture",
  OTHER: "Other",
};

export function predictionTopicLabel(topic: PredictionTopic): string {
  return PREDICTION_TOPIC_LABELS[topic];
}

// Order matters — first matching bucket wins. Keep specific keywords
// (e.g. politicians) before broad ones (e.g. "vote") to avoid mis-bucketing.
const PREDICTION_TOPIC_KEYWORDS: ReadonlyArray<[Exclude<PredictionTopic, "ALL" | "OTHER">, readonly string[]]> = [
  ["GEOPOL", ["ukraine", "russia", "putin", "china", "taiwan", "xi jinping", "israel", "gaza", "hamas", "iran", "north korea", "kim jong", "nato", "ceasefire", "hezbollah", "houthi", "syria", "venezuela"]],
  ["POLITICS", ["trump", "biden", "harris", "vance", "desantis", "newsom", "obama", "rfk", "election", "president", "presidential", "senate", "congress", "house seat", "governor", "ballot", "primary", "caucus", "republican", "democrat", "gop", "dnc", "rnc", "impeach", "nominee", "supreme court", "scotus", "prime minister", "parliament", "merz", "starmer", "macron", "meloni"]],
  ["CRYPTO", ["bitcoin", "btc", "ethereum", "eth ", " eth", "crypto", "solana", "sol ", "doge", "ripple", "xrp", "binance", "coinbase", "stablecoin", "tether", "usdc", "hashrate", "halving", "memecoin", "altcoin", "defi", "nft"]],
  ["MACRO", ["fed ", "fomc", "powell", "rate cut", "rate hike", "interest rate", "cpi", "ppi", "inflation", "gdp", "recession", "unemployment", "nonfarm", "payroll", "jobless", "treasury yield", "ecb", "boe", "boj"]],
  ["TECH", ["openai", "anthropic", "claude", "chatgpt", "gpt-", "gpt5", "gpt 5", "gemini", "llm", "agi", "artificial intelligence", "ai model", "tesla", "spacex", "starship", "musk", "apple ", "google", "alphabet", "meta", "nvidia", "microsoft"]],
  ["SPORTS", ["nfl", "nba", "nhl", "mlb", "super bowl", "world series", "stanley cup", "world cup", "champions league", "premier league", "uefa", "fifa", "olympic", "f1 ", "formula 1", "tennis", "ufc", "boxing", "ncaa", "march madness"]],
  ["CLIMATE", ["hurricane", "tornado", "typhoon", "wildfire", "heatwave", "drought", "earthquake", "tsunami", "climate", "temperature record", "snowfall", "rainfall", "storm"]],
  ["ENT", ["oscar", "academy award", "emmy", "grammy", "tony award", "billboard", "taylor swift", "beyonce", "netflix", "box office", "album", "movie", "tv show", "celebrity", "kanye", "drake"]],
];

export function inferPredictionTopic(question: string): PredictionTopic {
  const q = ` ${question.toLowerCase()} `;
  for (const [topic, keywords] of PREDICTION_TOPIC_KEYWORDS) {
    for (const kw of keywords) {
      if (q.includes(kw)) return topic;
    }
  }
  return "OTHER";
}

function formatProbability(value: number | null): string {
  return value === null ? "-" : `${fmt(value * 100, 1)}`;
}

function formatProbabilitySpread(value: number | null): string {
  return value === null ? "-" : fmt(value * 100, 1);
}

function formatPredictionVolume(value: number | null): string {
  if (value === null || value <= 0) return "-";
  if (value >= 1_000_000) return `${fmt(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${fmt(value / 1_000, 1)}K`;
  return fmt(value, 0);
}

function formatPredictionTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}:${String(date.getUTCSeconds()).padStart(2, "0")}`;
}

function PredictionMarketsRow({
  market,
  index,
}: {
  market: TermdPredictionMarket;
  index: number;
}) {
  const live = !market.resolved;
  return (
    <tr className="border-b border-term-border/60 hover:bg-term-accent/10">
      <td className="px-2 py-[3px] text-right text-term-dim">{pad(index + 1, 2, true)}</td>
      <td className="px-2 py-[3px] text-term-accent">{market.venue}</td>
      <td className="px-2 py-[3px] text-term-dim">{market.source || market.venue}</td>
      <td
        className="max-w-0 truncate px-2 py-[3px] text-term-text"
        title={market.question}
      >
        {market.question}
      </td>
      <td className="px-2 py-[3px] text-term-dim">{market.outcome}</td>
      <td className="px-2 py-[3px] text-right text-term-green">
        {formatProbability(market.bid)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-red">
        {formatProbability(market.ask)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-accent-hi">
        {formatProbability(market.mid)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-yellow">
        {formatProbabilitySpread(market.spread)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-text">
        {formatPredictionVolume(market.volume)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-dim">
        {formatPredictionTime(market.receivedAt)}
      </td>
      <td className={`px-2 py-[3px] text-right ${live ? "text-term-green" : "text-term-dim"}`}>
        {live ? "LIVE" : "DONE"}
      </td>
    </tr>
  );
}

const predictionRowKey = (m: TermdPredictionMarket) =>
  `${m.venue}:${m.marketId}:${m.outcome}`;

export function PredictionMarketsTable({
  limit = 32,
  venue,
  topic,
  emptyHint,
}: {
  limit?: number;
  /** Filter to a single venue (case-insensitive). Omit to show all venues. */
  venue?: string;
  /** Filter to a single topic bucket. "ALL" (or omitted) shows everything. */
  topic?: PredictionTopic;
  /** Override the empty-state copy. Useful for "coming soon" tabs. */
  emptyHint?: string;
}) {
  const rows = usePredictionMarkets();

  // Stable ranking: only re-sort when the set of visible markets actually
  // changes (entries added / removed) or when the filter changes. Within the
  // same set, preserve the previous row order even as volumes tick — keeps
  // rows from jumping under the user while they're reading.
  const orderRef = useRef<{
    filterKey: string;
    order: Map<string, number>;
  }>({ filterKey: "", order: new Map() });

  const ranked = useMemo(() => {
    const venueKey = venue?.toUpperCase();
    const topicKey = topic && topic !== "ALL" ? topic : null;
    const filterKey = `${venueKey ?? ""}|${topicKey ?? ""}`;

    const filtered = rows.filter((row) => {
      if (venueKey && row.venue.toUpperCase() !== venueKey) return false;
      if (topicKey && inferPredictionTopic(row.question) !== topicKey) return false;
      return true;
    });

    const visibleKeys = new Set(filtered.map(predictionRowKey));
    const prev = orderRef.current;

    let sameSet =
      prev.filterKey === filterKey && prev.order.size === visibleKeys.size;
    if (sameSet) {
      for (const k of visibleKeys) {
        if (!prev.order.has(k)) {
          sameSet = false;
          break;
        }
      }
    }

    if (!sameSet) {
      const sorted = [...filtered].sort((left, right) => {
        if (left.resolved !== right.resolved) return left.resolved ? 1 : -1;
        return (right.volume ?? 0) - (left.volume ?? 0);
      });
      const order = new Map<string, number>();
      sorted.forEach((m, i) => order.set(predictionRowKey(m), i));
      orderRef.current = { filterKey, order };
      return sorted.slice(0, limit);
    }

    return [...filtered]
      .sort(
        (a, b) =>
          (prev.order.get(predictionRowKey(a)) ?? 0) -
          (prev.order.get(predictionRowKey(b)) ?? 0),
      )
      .slice(0, limit);
  }, [rows, limit, venue, topic]);
  if (ranked.length === 0) {
    const topicSuffix = topic && topic !== "ALL"
      ? ` matching topic "${predictionTopicLabel(topic).toUpperCase()}"`
      : "";
    return (
      <div className="flex h-full items-center justify-center px-3 text-center text-[11px] uppercase text-term-dim">
        {emptyHint ?? (venue
          ? `No ${venue.toUpperCase()} markets${topicSuffix} in the live feed.`
          : topicSuffix
            ? `No markets${topicSuffix} in the live feed.`
            : "Awaiting deployed prediction-market feed.")}
      </div>
    );
  }
  return (
    <table className="w-full table-fixed text-[11px] tabular-nums">
      <colgroup>
        <col className="w-8" />
        <col className="w-[72px]" />
        <col className="w-[70px]" />
        <col />
        <col className="w-[62px]" />
        <col className="w-[58px]" />
        <col className="w-[58px]" />
        <col className="w-[58px]" />
        <col className="w-[58px]" />
        <col className="w-[70px]" />
        <col className="w-[72px]" />
        <col className="w-[58px]" />
      </colgroup>
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th right>#</Th>
          <Th>Venue</Th>
          <Th>Src</Th>
          <Th>Market</Th>
          <Th>Side</Th>
          <Th right>Bid %</Th>
          <Th right>Ask %</Th>
          <Th right>Mid %</Th>
          <Th right>Sprd</Th>
          <Th right>Vol</Th>
          <Th right>Recv UTC</Th>
          <Th right>State</Th>
        </tr>
        <ThRule span={12} />
      </thead>
      <tbody>
        {ranked.map((market, index) => (
          <PredictionMarketsRow
            key={`${market.venue}:${market.marketId}:${market.outcome}`}
            market={market}
            index={index}
          />
        ))}
      </tbody>
    </table>
  );
}

export function ResearchPanel({ symbol }: { symbol: string }) {
  const research = useResearch(symbol);

  const EmptyRow = ({ colSpan, source }: { colSpan: number; source: Quote["source"] }) => (
    <tr className="border-b border-term-border/60">
      <td colSpan={colSpan} className="px-2 py-3 text-center uppercase text-term-dim">
        N/A <span className="ml-2"><SourceBadge source={source} /></span>
      </td>
    </tr>
  );

  return (
    <div className="grid h-full min-h-0 grid-cols-3 gap-px bg-term-border text-[11px] tabular-nums">
      <section className="min-h-0 overflow-auto bg-term-panel">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-term-border bg-term-panel px-2 py-[3px] uppercase">
          <span className="text-term-accent-hi">Filings</span>
          <SourceBadge source={research.filingsSource} />
        </header>
        <table className="w-full table-fixed">
          <colgroup>
            <col className="w-[62px]" />
            <col className="w-[50px]" />
            <col />
            <col className="w-[58px]" />
          </colgroup>
          <thead className="sticky top-[23px] bg-term-panel text-term-dim">
            <tr>
              <Th>Filed</Th>
              <Th>Form</Th>
              <Th>Company</Th>
              <Th>Period</Th>
            </tr>
            <ThRule span={4} />
          </thead>
          <tbody>
            {research.filings.length === 0 && <EmptyRow colSpan={4} source={research.filingsSource} />}
            {research.filings.map((filing) => (
              <tr key={filing.accession} className="border-b border-term-border/60 hover:bg-term-accent/10">
                <td className="px-2 py-[3px] text-term-dim">{compactDate(filing.filed)}</td>
                <td className="px-2 py-[3px] text-term-accent">{filing.form}</td>
                <td className="truncate px-2 py-[3px] text-term-text" title={filing.company}>
                  {filing.company}
                </td>
                <td className="px-2 py-[3px] text-term-dim">{compactDate(filing.period)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="min-h-0 overflow-auto bg-term-panel">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-term-border bg-term-panel px-2 py-[3px] uppercase">
          <span className="text-term-accent-hi">Insider</span>
          <span className="inline-flex items-center gap-1 text-term-dim">
            <span>{symbol}</span>
            <SourceBadge source={research.insiderSource} />
          </span>
        </header>
        <table className="w-full table-fixed">
          <colgroup>
            <col className="w-[62px]" />
            <col className="w-[42px]" />
            <col />
            <col className="w-[62px]" />
            <col className="w-[54px]" />
          </colgroup>
          <thead className="sticky top-[23px] bg-term-panel text-term-dim">
            <tr>
              <Th>Trade</Th>
              <Th>Side</Th>
              <Th>Person</Th>
              <Th right>Shares</Th>
              <Th right>Px</Th>
            </tr>
            <ThRule span={5} />
          </thead>
          <tbody>
            {research.insiderTrades.length === 0 && <EmptyRow colSpan={5} source={research.insiderSource} />}
            {research.insiderTrades.map((trade) => (
              <tr key={trade.accession} className="border-b border-term-border/60 hover:bg-term-accent/10">
                <td className="px-2 py-[3px] text-term-dim">{compactDate(trade.traded)}</td>
                <td className={trade.side === "buy" ? "px-2 py-[3px] text-term-green" : trade.side === "sell" ? "px-2 py-[3px] text-term-red" : "px-2 py-[3px] text-term-dim"}>
                  {trade.side.toUpperCase()}
                </td>
                <td className="truncate px-2 py-[3px] text-term-text" title={`${trade.person} - ${trade.relationship}`}>
                  {trade.person}
                </td>
                <td className="px-2 py-[3px] text-right text-term-text">{compactNumber(trade.shares)}</td>
                <td className="px-2 py-[3px] text-right text-term-text">{trade.price === null ? "N/A" : fmt(trade.price, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="min-h-0 overflow-auto bg-term-panel">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-term-border bg-term-panel px-2 py-[3px] uppercase">
          <span className="text-term-accent-hi">13F Holdings</span>
          <SourceBadge source={research.holdingsSource} />
        </header>
        <table className="w-full table-fixed">
          <colgroup>
            <col className="w-[70px]" />
            <col />
            <col className="w-[58px]" />
            <col className="w-[62px]" />
          </colgroup>
          <thead className="sticky top-[23px] bg-term-panel text-term-dim">
            <tr>
              <Th>Quarter</Th>
              <Th>Issuer</Th>
              <Th right>Value</Th>
              <Th right>Shares</Th>
            </tr>
            <ThRule span={4} />
          </thead>
          <tbody>
            {research.institutionalHoldings.length === 0 && (
              <EmptyRow colSpan={4} source={research.holdingsSource} />
            )}
            {research.institutionalHoldings.map((holding) => (
              <tr key={`${holding.accession}-${holding.cusip}`} className="border-b border-term-border/60 hover:bg-term-accent/10">
                <td className="px-2 py-[3px] text-term-dim">{compactDate(holding.quarter)}</td>
                <td className="truncate px-2 py-[3px] text-term-text" title={holding.issuer}>
                  {holding.issuer}
                </td>
                <td className="px-2 py-[3px] text-right text-term-accent-hi">{compactCurrency(holding.value)}</td>
                <td className="px-2 py-[3px] text-right text-term-text">{compactNumber(holding.shares)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function compactDate(value: string | null): string {
  if (!value || value === "N/A") return "N/A";
  return value.slice(0, 10);
}

function compactNumber(value: number): string {
  if (value >= 1_000_000) return `${fmt(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${fmt(value / 1_000, 1)}K`;
  return fmt(value, 0);
}

function compactCurrency(value: number): string {
  if (value >= 1_000_000_000) return `${fmt(value / 1_000_000_000, 1)}B`;
  if (value >= 1_000_000) return `${fmt(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${fmt(value / 1_000, 1)}K`;
  return fmt(value, 0);
}

function WatchlistRow({ q, idx }: { q: Quote; idx: number }) {
  const [active, setActive] = useActiveSymbol();
  const isActive = active === q.ticker;
  const unavailable = q.source?.kind === "unavailable";
  const flash = useTickFlash(q.last);
  const pos = q.chg >= 0;
  return (
    <tr
      data-nav-key={q.ticker}
      onClick={() => setActive(q.ticker)}
      className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
        isActive ? "row-active" : ""
      }`}
    >
      <td className="px-2 py-[3px] text-term-dim">{pad(idx + 1, 2, true)}</td>
      <td className="px-2 py-[3px] text-term-accent-hi">{q.ticker}</td>
      <td className="px-2 py-[3px] text-term-text">{q.name}</td>
      <td className="px-2 py-[3px] text-right text-term-text">{unavailable ? "N/A" : fmt(q.bid, 2)}</td>
      <td className="px-2 py-[3px] text-right text-term-text">{unavailable ? "N/A" : fmt(q.ask, 2)}</td>
      <td
        className={`px-2 py-[3px] text-right text-term-accent-hi ${flashCls(flash)}`}
      >
        {unavailable ? "N/A" : fmt(q.last, 2)}
      </td>
      <td
        className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}
      >
        {unavailable ? "-" : fmtSigned(q.chg, 2)}
      </td>
      <td
        className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}
      >
        {unavailable ? "-" : `${pos ? "▲" : "▼"} ${fmtSigned(q.pct, 2)}%`}
      </td>
      <td className="px-2 py-[3px] text-right text-term-text">{unavailable ? "N/A" : q.vol}</td>
    </tr>
  );
}

export function Watchlist({
  category = "watchlist",
}: {
  category?: QuoteCategory;
}) {
  const rows = useQuoteList(category);
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<Quote, HTMLTableElement>({
    items: rows,
    getKey: (q) => q.ticker,
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
          <Th>#</Th>
          <Th>Ticker</Th>
          <Th>Security</Th>
          <Th right>Bid</Th>
          <Th right>Ask</Th>
          <Th right>Last</Th>
          <Th right>Chg</Th>
          <Th right>%Chg</Th>
          <Th right>Vol</Th>
        </tr>
        <ThRule span={9} />
      </thead>
      <tbody>
        {rows.map((q, i) => (
          <WatchlistRow key={q.ticker} q={q} idx={i} />
        ))}
      </tbody>
    </table>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   news / events / bonds / CDS / cb rates / positions / cross fx
   (no live-tick mutation; rows still clickable where a symbol is present)
   ──────────────────────────────────────────────────────────────────────────── */

export function NewsFeed({
  items,
  dense = false,
  selectedId,
  onSelect,
}: {
  items: readonly NewsItem[];
  dense?: boolean;
  selectedId?: string | null;
  onSelect?: (item: NewsItem) => void;
}) {
  const nav = useArrowNav<NewsItem, HTMLUListElement>({
    items,
    getKey: (n) => n.id,
    current: selectedId ?? null,
    setCurrent: (id) => {
      const n = items.find((it) => it.id === id);
      if (n) onSelect?.(n);
    },
  });
  return (
    <ul
      ref={onSelect ? nav.ref : null}
      tabIndex={onSelect ? nav.tabIndex : undefined}
      onClick={onSelect ? nav.onClick : undefined}
      onKeyDown={onSelect ? nav.onKeyDown : undefined}
      className={`outline-none ${dense ? "text-[11px]" : "text-[12px]"}`}
    >
      {items.map((n) => {
        const tone = n.tone === "alert" ? "text-term-yellow" : "text-term-text";
        const isSelected = selectedId === n.id;
        return (
          <li
            key={n.id}
            data-nav-key={n.id}
            onClick={() => onSelect?.(n)}
            className={`flex gap-2 border-b border-term-border/60 px-2 py-1 ${
              onSelect ? "cursor-pointer" : ""
            } ${
              isSelected ? "row-active" : "hover:bg-term-accent/10"
            }`}
          >
            <span className="shrink-0 tabular-nums text-term-dim">{n.time}</span>
            <span className="w-16 shrink-0 text-term-accent">{n.src}</span>
            {!dense && n.cat && (
              <span className="w-12 shrink-0 text-term-dim">{n.cat}</span>
            )}
            <span className="min-w-0 flex-1">
              <span className={`block leading-snug uppercase ${tone}`}>
                {n.tone === "alert" && (
                  <span className="mr-1 inline-block border border-term-yellow px-1 font-semibold text-term-yellow">
                    !
                  </span>
                )}
                {n.headline}
              </span>
              {!dense && n.body[0] && (
                <span className="mt-0.5 block truncate text-[10px] normal-case leading-snug text-term-dim">
                  {n.body[0]}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function EventTable({ items }: { items: readonly EventItem[] }) {
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th>Time</Th>
          <Th>Ccy</Th>
          <Th>Imp</Th>
          <Th>Event</Th>
          <Th right>Fcst</Th>
          <Th right>Prev</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={7} />
      </thead>
      <tbody>
        {items.map((e, i) => (
          <tr key={i} className="border-b border-term-border/60 hover:bg-term-accent/10">
            <td className="px-2 py-[3px] text-term-text">{e.time}</td>
            <td className="px-2 py-[3px] text-term-accent-hi">{e.ccy}</td>
            <td className="px-2 py-[3px] text-term-yellow">
              {"★".repeat(e.imp)}
              <span className="text-term-muted">{"★".repeat(3 - e.imp)}</span>
            </td>
            <td className="px-2 py-[3px] uppercase text-term-text">{e.label}</td>
            <td className="px-2 py-[3px] text-right text-term-text">{e.fcst}</td>
            <td className="px-2 py-[3px] text-right text-term-dim">{e.prev}</td>
            <td className={`px-2 py-[3px] uppercase ${sourceClass(e.source)}`}>
              {dataSourceDisplayLabel(e.source)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RecentPrintsTable({ items }: { items: readonly EventItem[] }) {
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th>Time</Th>
          <Th>Ccy</Th>
          <Th>Event</Th>
          <Th right>Fcst</Th>
          <Th right>Actual</Th>
          <Th right>Prev</Th>
          <Th right>Surp</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={8} />
      </thead>
      <tbody>
        {items.map((e, i) => {
          const f = parseFloat(e.fcst.replace(/[^-0-9.]/g, "")) || 0;
          const a = parseFloat((e.actual ?? "0").replace(/[^-0-9.]/g, "")) || 0;
          const surprise = a - f;
          const has = e.actual && e.actual !== "—";
          return (
            <tr key={i} className="border-b border-term-border/60 hover:bg-term-accent/10">
              <td className="px-2 py-[3px] text-term-text">{e.time}</td>
              <td className="px-2 py-[3px] text-term-accent-hi">{e.ccy}</td>
              <td className="px-2 py-[3px] uppercase text-term-text">{e.label}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{e.fcst}</td>
              <td className="px-2 py-[3px] text-right text-term-accent-hi">
                {e.actual ?? "—"}
              </td>
              <td className="px-2 py-[3px] text-right text-term-dim">{e.prev}</td>
              <td
                className={`px-2 py-[3px] text-right ${
                  !has ? "text-term-dim" : surprise >= 0 ? "text-term-green" : "text-term-red"
                }`}
              >
                {has ? (surprise >= 0 ? "▲" : "▼") + " " + fmtSigned(surprise, 2) : "—"}
              </td>
              <td className={`px-2 py-[3px] uppercase ${sourceClass(e.source)}`}>
                {dataSourceDisplayLabel(e.source)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function BondsTable({ rows }: { rows: readonly BondRow[] }) {
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<BondRow, HTMLTableElement>({
    items: rows,
    getKey: (b) => b.issuer,
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
          <Th>Issuer</Th>
          <Th>Description</Th>
          <Th right>Cpn</Th>
          <Th right>Px</Th>
          <Th right>YTM</Th>
          <Th right>OAS</Th>
          <Th>Rtg</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={8} />
      </thead>
      <tbody>
        {rows.map((b, i) => {
          const isActive = active === b.issuer;
          return (
            <tr
              key={i}
              data-nav-key={b.issuer}
              onClick={() => setActive(b.issuer)}
              className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                isActive ? "row-active" : ""
              }`}
            >
              <td className="px-2 py-[3px] text-term-accent-hi">{b.issuer}</td>
              <td className="px-2 py-[3px] text-term-text">{b.desc}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{fmtMaybe(b.cpn, 2)}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{fmtMaybe(b.px, 2)}</td>
              <td className="px-2 py-[3px] text-right text-term-accent-hi">{fmtMaybe(b.ytm, 2)}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{b.oas ?? "N/A"}</td>
              <td className="px-2 py-[3px] text-term-yellow">{b.rating}</td>
              <td className={`px-2 py-[3px] uppercase ${sourceClass(b.source)}`}>{dataSourceDisplayLabel(b.source)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function CdsTable({ rows }: { rows: readonly CdsRow[] }) {
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<CdsRow, HTMLTableElement>({
    items: rows,
    getKey: (r) => r.name,
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
          <Th>Reference</Th>
          <Th>Region/Sector</Th>
          <Th>Rtg</Th>
          <Th right>5Y CDS</Th>
          <Th right>1D Δ</Th>
          <Th right>YTD Δ</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={7} />
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const isActive = active === r.name;
          return (
            <tr
              key={i}
              data-nav-key={r.name}
              onClick={() => setActive(r.name)}
              className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                isActive ? "row-active" : ""
              }`}
            >
              <td className="px-2 py-[3px] text-term-accent-hi">{r.name}</td>
              <td className="px-2 py-[3px] text-term-text">{r.region}</td>
              <td className="px-2 py-[3px] text-term-yellow">{r.rating}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{r.px ?? "N/A"}</td>
              <td className={`px-2 py-[3px] text-right ${signedClass(r.chg)}`}>
                {fmtSignedMaybe(r.chg, 1)}
              </td>
              <td className={`px-2 py-[3px] text-right ${signedClass(r.ytd)}`}>
                {fmtSignedMaybe(r.ytd, 0)}
              </td>
              <td className={`px-2 py-[3px] uppercase ${sourceClass(r.source)}`}>{dataSourceDisplayLabel(r.source)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function CreditIndexTable({ rows }: { rows: readonly CreditIndexRow[] }) {
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th>Index</Th>
          <Th>Description</Th>
          <Th right>Last</Th>
          <Th right>1D Δ</Th>
          <Th right>YTD Δ</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={6} />
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name} className="border-b border-term-border/60 hover:bg-term-accent/10">
            <td className="px-2 py-[3px] text-term-accent-hi">{row.name}</td>
            <td className="px-2 py-[3px] text-term-text">{row.desc}</td>
            <td className="px-2 py-[3px] text-right text-term-text">{row.last ?? "N/A"}</td>
            <td className={`px-2 py-[3px] text-right ${signedClass(row.chg)}`}>
              {fmtSignedMaybe(row.chg, 1)}
            </td>
            <td className={`px-2 py-[3px] text-right ${signedClass(row.ytd)}`}>
              {fmtSignedMaybe(row.ytd, 0)}
            </td>
            <td className={`px-2 py-[3px] uppercase ${sourceClass(row.source)}`}>
              {dataSourceDisplayLabel(row.source)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Map a CB policy currency to the most natural symbol to focus on
 *  when a user clicks the row. USD → DXY; everything else routes to
 *  the conventional pair with USD as the counterpart. */
const CCY_TO_FX_SYMBOL: Record<string, string> = {
  USD: "DXY",
  EUR: "EURUSD",
  GBP: "GBPUSD",
  JPY: "USDJPY",
  CHF: "USDCHF",
  CAD: "USDCAD",
  AUD: "AUDUSD",
  NZD: "NZDUSD",
  CNY: "USDCNH",
  MXN: "USDMXN",
};

export function CbRatesTable({ rows }: { rows: readonly CbRate[] }) {
  const [active, setActive] = useActiveSymbol();
  const navItems = useMemo(
    () => rows.map((r) => ({ row: r, target: CCY_TO_FX_SYMBOL[r.ccy] ?? r.ccy })),
    [rows],
  );
  const nav = useArrowNav<{ row: CbRate; target: string }, HTMLTableElement>({
    items: navItems,
    getKey: (it) => it.target,
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
          <Th>Ccy</Th>
          <Th>Bank</Th>
          <Th right>Rate</Th>
          <Th>Last Move</Th>
          <Th>Next</Th>
          <Th>Bias</Th>
          <Th>Src</Th>
        </tr>
        <ThRule span={7} />
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr className="border-b border-term-border/60">
            <td className="px-2 py-[3px] text-term-dim">N/A</td>
            <td className="px-2 py-[3px] text-term-dim">CENTRAL BANK RATES UNAVAILABLE</td>
            <td className="px-2 py-[3px] text-right text-term-dim">N/A</td>
            <td className="px-2 py-[3px] text-term-dim">N/A</td>
            <td className="px-2 py-[3px] text-term-dim">N/A</td>
            <td className="px-2 py-[3px] text-term-dim">N/A</td>
            <td className="px-2 py-[3px] text-term-dim">N/A</td>
          </tr>
        ) : null}
        {rows.map((r, i) => {
          const target = CCY_TO_FX_SYMBOL[r.ccy] ?? r.ccy;
          const isActive = active === target;
          return (
            <tr
              key={i}
              data-nav-key={target}
              onClick={() => setActive(target)}
              className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
                isActive ? "row-active" : ""
              }`}
              title={`Focus ${target}`}
            >
              <td className="px-2 py-[3px] text-term-accent-hi">{r.ccy}</td>
              <td className="px-2 py-[3px] text-term-text">{r.bank}</td>
              <td className={`px-2 py-[3px] text-right ${r.rate === null ? "text-term-dim" : "text-term-accent-hi"}`}>
                {r.rate === null ? "N/A" : `${fmt(r.rate, 2)}%`}
              </td>
              <td className="px-2 py-[3px] text-term-dim">{r.lastMove}</td>
              <td className="px-2 py-[3px] text-term-text">{r.next}</td>
              <td
                className={`px-2 py-[3px] ${
                  r.bias === "HIKE"
                    ? "text-term-red"
                    : r.bias === "CUT"
                      ? "text-term-green"
                      : "text-term-yellow"
                }`}
              >
                {r.bias}
              </td>
              <td className={`px-2 py-[3px] uppercase ${sourceClass(r.source)}`}>
                {dataSourceDisplayLabel(r.source)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function PositionsTable() {
  const rows = usePositions();
  const [active, setActive] = useActiveSymbol();
  const nav = useArrowNav<Position, HTMLTableElement>({
    items: rows,
    getKey: (p) => p.ticker,
    current: active,
    setCurrent: setActive,
  });
  const totals = rows.reduce(
    (s, p) => ({ mv: s.mv + p.mv, pl: s.pl + p.pl }),
    { mv: 0, pl: 0 },
  );
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
          <Th>Ticker</Th>
          <Th>Security</Th>
          <Th right>Qty</Th>
          <Th right>Avg Cost</Th>
          <Th right>Mark</Th>
          <Th right>Market Val</Th>
          <Th right>P/L</Th>
          <Th right>P/L %</Th>
          <Th right>Wgt</Th>
          <Th right>Src</Th>
        </tr>
        <ThRule span={10} />
      </thead>
      <tbody>
        {rows.map((p) => (
          <PositionsRow key={p.ticker} p={p} />
        ))}
        <tr className="border-b border-term-border bg-term-accent/10 font-semibold">
          <td className="px-2 py-[3px] text-term-accent-hi">TOTAL</td>
          <td className="px-2 py-[3px] text-term-dim">{rows.length} POSITIONS</td>
          <td /><td /><td />
          <td className="px-2 py-[3px] text-right text-term-accent-hi">{fmt(totals.mv, 2)}</td>
          <td className={`px-2 py-[3px] text-right ${totals.pl >= 0 ? "text-term-green" : "text-term-red"}`}>
            {fmtSigned(totals.pl, 2)}
          </td>
          <td />
          <td className="px-2 py-[3px] text-right text-term-text">100.0%</td>
          <td />
        </tr>
      </tbody>
    </table>
  );
}

function PositionsRow({ p }: { p: Position }) {
  const [active, setActive] = useActiveSymbol();
  const isActive = active === p.ticker;
  const unavailable = p.source?.kind === "unavailable";
  const flash = useTickFlash(unavailable ? p.avg : p.mark);
  return (
    <tr
      data-nav-key={p.ticker}
      onClick={() => setActive(p.ticker)}
      className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
        isActive ? "row-active" : ""
      }`}
    >
      <td className="px-2 py-[3px] text-term-accent-hi">{p.ticker}</td>
      <td className="px-2 py-[3px] text-term-text">{p.name}</td>
      <td className={`px-2 py-[3px] text-right ${p.qty >= 0 ? "text-term-text" : "text-term-red"}`}>
        {p.qty.toLocaleString()}
      </td>
      <td className="px-2 py-[3px] text-right text-term-text">{fmt(p.avg, 2)}</td>
      <td className={`px-2 py-[3px] text-right text-term-accent-hi ${flashCls(flash)}`}>
        {unavailable ? "N/A" : fmt(p.mark, 2)}
      </td>
      <td className="px-2 py-[3px] text-right text-term-text">{unavailable ? "N/A" : fmt(p.mv, 2)}</td>
      <td className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : p.pl >= 0 ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : fmtSigned(p.pl, 2)}
      </td>
      <td className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : p.plPct >= 0 ? "text-term-green" : "text-term-red"}`}>
        {unavailable ? "-" : `${fmtSigned(p.plPct, 2)}%`}
      </td>
      <td className="px-2 py-[3px] text-right text-term-text">{unavailable ? "-" : `${fmt(p.wgt, 1)}%`}</td>
      <td className="px-2 py-[3px] text-right">
        <SourceBadge source={p.source} />
      </td>
    </tr>
  );
}

export function CrossRateMatrix({
  ccys,
  matrix,
}: {
  ccys: readonly string[];
  matrix: readonly (readonly (number | null)[])[];
}) {
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th> </Th>
          {ccys.map((c) => (
            <Th right key={c}>{c}</Th>
          ))}
        </tr>
        <ThRule span={ccys.length + 1} />
      </thead>
      <tbody>
        {matrix.map((row, i) => (
          <tr key={i} className="border-b border-term-border/60 hover:bg-term-accent/10">
            <td className="px-2 py-[3px] text-term-accent-hi">{ccys[i]}</td>
            {row.map((v, j) => (
              <td
                key={j}
                className={`px-2 py-[3px] text-right ${
                  i === j ? "text-term-dim" : "text-term-text"
                }`}
              >
                {i === j
                  ? "—"
                  : v == null
                    ? "N/A"
                    : fmt(v, v >= 100 ? 2 : v >= 1 ? 4 : 5)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   options chain
   ──────────────────────────────────────────────────────────────────────────── */

export function OptionsChain({ symbol }: { symbol: string }) {
  const chain = useOptionChain(symbol);
  const source = useDetailSource("options", symbol);
  const spot = chain.spot;
  // ATM strike — closest to spot
  let atmIdx = 0;
  let bestD = Infinity;
  for (let i = 0; i < chain.rows.length; i++) {
    const d = Math.abs(chain.rows[i].strike - spot);
    if (d < bestD) {
      bestD = d;
      atmIdx = i;
    }
  }
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <th colSpan={6} className="border-r border-term-border bg-term-panel px-2 py-[3px] text-center font-semibold text-term-green">
            CALLS
          </th>
          <th className="bg-term-accent/10 px-2 py-[3px] text-center font-semibold text-term-accent-hi">
            STRIKE
          </th>
          <th colSpan={6} className="border-l border-term-border bg-term-panel px-2 py-[3px] text-center font-semibold text-term-red">
            PUTS
          </th>
        </tr>
        <tr>
          <Th right>OI</Th><Th right>Δ</Th><Th right>IV</Th>
          <Th right>Bid</Th><Th right>Ask</Th><Th right>Last</Th>
          <th className="bg-term-accent/10 px-2 py-[3px] text-center font-normal uppercase">K</th>
          <Th>Bid</Th><Th>Ask</Th><Th>Last</Th>
          <Th>IV</Th><Th>Δ</Th><Th>OI</Th>
        </tr>
        <ThRule span={13} />
      </thead>
      <tbody>
        {chain.rows.length === 0 && <EmptyDataRow colSpan={13} source={source} />}
        {chain.rows.map((r, i) => (
          <OptionsRowView key={r.strike} row={r} isAtm={i === atmIdx} spot={spot} />
        ))}
      </tbody>
    </table>
  );
}

function OptionsRowView({
  row: r,
  isAtm,
  spot,
}: {
  row: OptionRow;
  isAtm: boolean;
  spot: number;
}) {
  const callITM = r.strike < spot;
  const putITM = r.strike > spot;
  const callCls = callITM ? "bg-term-green/[0.06]" : "";
  const putCls = putITM ? "bg-term-red/[0.06]" : "";
  return (
    <tr
      className={`border-b border-term-border/60 hover:bg-term-accent/10 ${
        isAtm ? "outline outline-1 -outline-offset-1 outline-term-accent/40" : ""
      }`}
    >
      <td className={`px-2 py-[3px] text-right text-term-dim ${callCls}`}>{r.callOI.toLocaleString()}</td>
      <td className={`px-2 py-[3px] text-right text-term-text ${callCls}`}>{fmt(r.callDelta, 2)}</td>
      <td className={`px-2 py-[3px] text-right text-term-dim ${callCls}`}>{fmt(r.callIV, 1)}</td>
      <td className={`px-2 py-[3px] text-right text-term-text ${callCls}`}>{fmt(r.callBid, 2)}</td>
      <td className={`px-2 py-[3px] text-right text-term-text ${callCls}`}>{fmt(r.callAsk, 2)}</td>
      <td className={`px-2 py-[3px] text-right text-term-green ${callCls}`}>{fmt(r.callLast, 2)}</td>
      <td
        className={`bg-term-accent/10 px-2 py-[3px] text-center ${
          isAtm ? "font-bold text-term-accent-hi" : "text-term-accent"
        }`}
      >
        {fmt(r.strike, 2)}
      </td>
      <td className={`px-2 py-[3px] text-term-text ${putCls}`}>{fmt(r.putBid, 2)}</td>
      <td className={`px-2 py-[3px] text-term-text ${putCls}`}>{fmt(r.putAsk, 2)}</td>
      <td className={`px-2 py-[3px] text-term-red ${putCls}`}>{fmt(r.putLast, 2)}</td>
      <td className={`px-2 py-[3px] text-term-dim ${putCls}`}>{fmt(r.putIV, 1)}</td>
      <td className={`px-2 py-[3px] text-term-text ${putCls}`}>{fmt(r.putDelta, 2)}</td>
      <td className={`px-2 py-[3px] text-term-dim ${putCls}`}>{r.putOI.toLocaleString()}</td>
    </tr>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   time and sales
   ──────────────────────────────────────────────────────────────────────────── */

export function TimeSales({ symbol }: { symbol: string }) {
  const trades = useTimeSales(symbol, 80);
  const source = useDetailSource("trades", symbol);
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th>Time</Th>
          <Th right>Price</Th>
          <Th right>Qty</Th>
          <Th>Side</Th>
        </tr>
        <ThRule span={4} />
      </thead>
      <tbody>
        {trades.length === 0 && (
          <EmptyDataRow colSpan={4} source={source} />
        )}
        {trades.map((t, i) => (
          <TradeRow key={i} t={t} />
        ))}
      </tbody>
    </table>
  );
}

function TradeRow({ t }: { t: Trade }) {
  const flash = useTickFlash(t.px);
  const sideClr = t.side === "B" ? "text-term-green" : "text-term-red";
  return (
    <tr className="border-b border-term-border/60">
      <td className="px-2 py-[2px] text-term-dim">{t.time.slice(0, 12)}</td>
      <td className={`px-2 py-[2px] text-right ${sideClr} ${flashCls(flash)}`}>
        {fmt(t.px, 2)}
      </td>
      <td className="px-2 py-[2px] text-right text-term-text">{t.qty.toLocaleString()}</td>
      <td className={`px-2 py-[2px] ${sideClr}`}>{t.side === "B" ? "BID" : "ASK"}</td>
    </tr>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   tabbed panel — switch between Depth / Options / T&S in the same body
   ──────────────────────────────────────────────────────────────────────────── */

export function TabbedPanel({
  id,
  tabs,
  initial = 0,
}: {
  id: string | number;
  tabs: { key: string; label: React.ReactNode; right?: React.ReactNode; render: () => React.ReactNode }[];
  initial?: number;
}) {
  const [idx, setIdx] = useState(initial);
  const active = tabs[idx];

  const onTabsKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
    if (tabs.length === 0) return;
    e.preventDefault();
    const next =
      e.key === "Home" ? 0 :
      e.key === "End"  ? tabs.length - 1 :
      e.key === "ArrowRight" ? (idx + 1) % tabs.length :
      (idx - 1 + tabs.length) % tabs.length;
    setIdx(next);
    // Move focus to the newly-selected tab so subsequent presses keep cycling
    const host = e.currentTarget as HTMLElement;
    const buttons = host.querySelectorAll<HTMLButtonElement>("button[data-tab-idx]");
    buttons[next]?.focus();
  };

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
      <header className="flex shrink-0 items-stretch border-b border-term-border bg-term-accent text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
        <span className="flex items-center px-2 py-[2px]">
          <span className="mr-2 inline-block min-w-[1.25rem] text-right">{id})</span>
          <span className="opacity-70">VIEW:</span>
        </span>
        <div className="flex" role="tablist" onKeyDown={onTabsKeyDown}>
          {tabs.map((t, i) => (
            <button
              key={t.key}
              data-tab-idx={i}
              role="tab"
              aria-selected={i === idx}
              tabIndex={i === idx ? 0 : -1}
              onClick={() => setIdx(i)}
              className={`border-l border-term-on-accent/30 px-3 py-[2px] uppercase outline-none ${
                i === idx
                  ? "bg-term-inv-bg text-term-inv-fg"
                  : "hover:bg-term-on-accent/15"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <span className="ml-auto flex items-center px-2 py-[2px] text-[10px]">
          {active.right}
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{active.render()}</div>
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   heatmap — sectors × constituents, color by % change
   ──────────────────────────────────────────────────────────────────────────── */

function heatColor(pct: number): { bg: string; fg: string } {
  // Clamp to ±3% for visual saturation
  const x = Math.max(-3, Math.min(3, pct)) / 3;
  if (x >= 0) {
    const a = Math.abs(x);
    return {
      bg: `color-mix(in srgb, var(--color-term-green) ${(15 + a * 55).toFixed(0)}%, #050505)`,
      fg: a > 0.65 ? "#000" : "var(--color-term-text)",
    };
  } else {
    const a = Math.abs(x);
    return {
      bg: `color-mix(in srgb, var(--color-term-red) ${(15 + a * 55).toFixed(0)}%, #050505)`,
      fg: a > 0.65 ? "#000" : "var(--color-term-text)",
    };
  }
}

export function Heatmap() {
  const cells = useHeatmap();
  const [, setActive] = useActiveSymbol();
  const [filter] = useActiveFilter();
  const filterSector = filter.kind === "sector" ? filter.sector : null;
  const bySector = useMemo(() => {
    const m = new Map<string, HeatmapCell[]>();
    for (const c of cells) {
      let arr = m.get(c.sector);
      if (!arr) {
        arr = [];
        m.set(c.sector, arr);
      }
      arr.push(c);
    }
    // Sort each sector's cells by weight desc so big names lead
    for (const arr of m.values()) arr.sort((a, b) => b.weight - a.weight);
    return Array.from(m.entries());
  }, [cells]);

  return (
    <div className="flex h-full flex-col gap-px bg-term-border p-px text-[10px]">
      {bySector.map(([sector, list]) => {
        const totalWeight = list.reduce((s, c) => s + c.weight, 0);
        const sectorAvg =
          list.reduce((s, c) => s + c.pct * c.weight, 0) / Math.max(0.001, totalWeight);
        const isFiltered = filterSector !== null && filterSector !== sector;
        return (
          <div
            key={sector}
            className={`flex min-h-0 flex-1 items-stretch gap-px ${
              isFiltered ? "opacity-30" : ""
            }`}
          >
            <div
              className={`flex w-[80px] shrink-0 flex-col justify-center px-2 py-1 ${
                filterSector === sector
                  ? "bg-term-accent/15"
                  : "bg-term-panel"
              }`}
            >
              <div className="text-[11px] font-semibold uppercase text-term-accent-hi">
                {sector}
              </div>
              <div
                className={`tabular-nums ${
                  sectorAvg >= 0 ? "text-term-green" : "text-term-red"
                }`}
              >
                {sectorAvg >= 0 ? "▲" : "▼"} {fmtSigned(sectorAvg, 2)}%
              </div>
            </div>
            <div className="flex min-w-0 flex-1 gap-px">
              {list.map((c) => {
                const { bg, fg } = heatColor(c.pct);
                const flex = Math.max(0.4, c.weight);
                return (
                  <button
                    key={c.symbol}
                    onClick={() => setActive(c.symbol)}
                    title={`${c.symbol} · ${c.name}  ${fmtSigned(c.pct, 2)}%`}
                    className="flex min-w-0 flex-col items-start justify-between overflow-hidden px-1.5 py-1 text-left hover:outline hover:outline-1 hover:outline-term-accent"
                    style={{
                      flex: `${flex} ${flex} 0%`,
                      background: bg,
                      color: fg,
                    }}
                  >
                    <span className="truncate text-[11px] font-bold uppercase">
                      {c.symbol}
                    </span>
                    <span className="truncate text-[10px] tabular-nums opacity-90">
                      {fmtSigned(c.pct, 2)}%
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   chart — measured at exact container pixel size, Catmull-Rom smoothed
   ──────────────────────────────────────────────────────────────────────────── */

function useContainerSize<T extends HTMLElement>() {
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

    // Belt-and-suspenders: re-measure on viewport changes that ResizeObserver
    // sometimes fails to deliver synchronously to nested elements — most
    // notably Chrome's extension side panel opening, devtools docking, and
    // fullscreen toggles. Both events are cheap; React de-dupes equal sizes.
    window.addEventListener("resize", measure);
    document.addEventListener("visibilitychange", measure);

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
      document.removeEventListener("visibilitychange", measure);
    };
  }, []);
  return [ref, size] as const;
}

function smoothPath(pts: [number, number][]): string {
  if (pts.length === 0) return "";
  if (pts.length === 1)
    return `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d +=
      ` C${c1x.toFixed(2)},${c1y.toFixed(2)}` +
      ` ${c2x.toFixed(2)},${c2y.toFixed(2)}` +
      ` ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

export function Chart({
  title,
  subtitle,
  data,
  xLabels,
  formatY = (v) => fmt(v, 2),
  yLabel,
  source,
}: {
  title: string;
  subtitle?: string;
  data: number[];
  xLabels?: string[];
  formatY?: (v: number) => string;
  yLabel?: string;
  source?: Quote["source"];
}) {
  const [ref, size] = useContainerSize<HTMLDivElement>();
  const N = data.length;
  const min = N ? Math.min(...data) : 0;
  const max = N ? Math.max(...data) : 0;
  const last = N ? data[N - 1] : 0;
  const first = N ? data[0] : 0;
  const chg = last - first;
  const pct = first ? (chg / first) * 100 : 0;
  const pos = chg >= 0;
  const stroke = pos ? "var(--color-term-green)" : "var(--color-term-red)";

  const W = size.w;
  const H = size.h;
  const padL = W < 480 ? 44 : 56;
  const padR = W < 480 ? 44 : 56;
  const padT = 10;
  const padB = 22;
  const innerW = Math.max(0, W - padL - padR);
  const innerH = Math.max(0, H - padT - padB);

  const snap = (n: number) => Math.round(n) + 0.5;

  const x = (i: number) => padL + (i / Math.max(1, N - 1)) * innerW;
  const y = (v: number) =>
    padT + (1 - (v - min) / (max - min || 1)) * innerH;

  const points: [number, number][] = data.map((v, i) => [x(i), y(v)]);
  const path = smoothPath(points);

  const targetYTicks = Math.max(3, Math.min(6, Math.floor(innerH / 40)));

  // X-axis labels: when not overridden, place ticks at clean intraday times
  // (09:30 → 16:00, NYSE-style) snapped to a step appropriate for the width.
  // Each entry carries an explicit time-fraction so positioning is exact and
  // never produces duplicate labels at wide widths.
  type LabelEntry = { text: string; frac: number };
  let labelEntries: LabelEntry[];
  if (xLabels && xLabels.length > 0) {
    labelEntries = xLabels.map((text, i, arr) => ({
      text,
      frac: arr.length > 1 ? i / (arr.length - 1) : 0,
    }));
  } else {
    const dayStartMin = 9 * 60 + 30;     // 09:30
    const dayEndMin = 16 * 60;           // 16:00
    const rangeMin = dayEndMin - dayStartMin; // 390
    const idealCount = Math.max(3, Math.min(14, Math.floor(innerW / 80)));
    const stepCandidates = [15, 30, 60, 90, 120, 180];
    const step = stepCandidates.reduce((best, c) =>
      Math.abs(rangeMin / c - idealCount) < Math.abs(rangeMin / best - idealCount) ? c : best,
    );
    const times: number[] = [];
    let m = dayStartMin;
    while (m < dayEndMin) {
      times.push(m);
      m += step;
    }
    if (times[times.length - 1] !== dayEndMin) times.push(dayEndMin);
    labelEntries = times.map((tm) => ({
      text:
        String(Math.floor(tm / 60)).padStart(2, "0") +
        ":" +
        String(tm % 60).padStart(2, "0"),
      frac: (tm - dayStartMin) / rangeMin,
    }));
  }
  const lastY = y(last);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-x-4 border-b border-term-border px-2 py-1 text-[11px] uppercase">
        <div className="flex items-baseline gap-3">
          <span className="text-term-accent-hi">{title}</span>
          {subtitle && <span className="text-term-dim">{subtitle}</span>}
          {source && <SourceBadge source={source} />}
        </div>
        <div className="flex items-baseline gap-3 tabular-nums">
          <span className="text-term-dim">O</span><span>{N ? formatY(first) : "N/A"}</span>
          <span className="text-term-dim">H</span><span>{N ? formatY(max) : "N/A"}</span>
          <span className="text-term-dim">L</span><span>{N ? formatY(min) : "N/A"}</span>
          <span className="text-term-dim">C</span>
          <span className="text-term-accent-hi">{N ? formatY(last) : "N/A"}</span>
          <span className={N ? (pos ? "text-term-green" : "text-term-red") : "text-term-dim"}>
            {N ? `${pos ? "▲" : "▼"} ${fmtSigned(chg, 2)} (${fmtSigned(pct, 2)}%)` : "-"}
          </span>
        </div>
      </div>

      <div ref={ref} className="relative min-h-0 flex-1 overflow-hidden">
        {yLabel && (
          <span className="pointer-events-none absolute left-1 top-1 z-10 text-[10px] uppercase text-term-dim">
            {yLabel}
          </span>
        )}
        {N === 0 && source?.kind === "unavailable" && (
          <div className="absolute inset-0 flex items-center justify-center text-[11px] uppercase text-term-dim">
            <span>N/A</span>
            <span className="ml-2">
              <SourceBadge source={source} />
            </span>
          </div>
        )}
        {W > 100 && H > 60 && (
          <svg
            className="block h-full w-full"
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
          >
            <rect
              x={snap(padL)}
              y={snap(padT)}
              width={innerW}
              height={innerH}
              fill="none"
              stroke="var(--color-term-border)"
              shapeRendering="crispEdges"
            />
            {Array.from({ length: targetYTicks + 1 }).map((_, i) => {
              const v = max - (i / targetYTicks) * (max - min);
              const yy = padT + (i / targetYTicks) * innerH;
              return (
                <g key={`y${i}`}>
                  <line x1={padL} x2={padL + innerW} y1={snap(yy)} y2={snap(yy)} stroke="var(--color-term-grid)" shapeRendering="crispEdges" />
                  <line x1={padL - 4} x2={padL} y1={snap(yy)} y2={snap(yy)} stroke="var(--color-term-border-hi)" shapeRendering="crispEdges" />
                  <text x={padL - 6} y={Math.round(yy) + 3} textAnchor="end" fontSize="10" fill="var(--color-term-dim)" fontFamily="var(--font-mono)" textRendering="geometricPrecision">
                    {formatY(v)}
                  </text>
                </g>
              );
            })}
            {labelEntries.map((l, i) => {
              const xx = padL + l.frac * innerW;
              return (
                <g key={`x${i}`}>
                  <line x1={snap(xx)} x2={snap(xx)} y1={padT} y2={padT + innerH} stroke="var(--color-term-grid)" shapeRendering="crispEdges" />
                  <line x1={snap(xx)} x2={snap(xx)} y1={padT + innerH} y2={padT + innerH + 4} stroke="var(--color-term-border-hi)" shapeRendering="crispEdges" />
                  <text x={Math.round(xx)} y={padT + innerH + 14} textAnchor="middle" fontSize="10" fill="var(--color-term-dim)" fontFamily="var(--font-mono)" textRendering="geometricPrecision">
                    {l.text}
                  </text>
                </g>
              );
            })}
            <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" shapeRendering="geometricPrecision" vectorEffect="non-scaling-stroke" />
            <line x1={padL} x2={padL + innerW} y1={snap(lastY)} y2={snap(lastY)} stroke={stroke} strokeDasharray="2 3" strokeOpacity="0.65" shapeRendering="crispEdges" />
            <rect x={Math.round(padL + innerW) + 1} y={Math.round(lastY) - 8} width={padR - 4} height={16} fill={stroke} shapeRendering="crispEdges" />
            <text x={Math.round(padL + innerW + (padR - 4) / 2 + 2)} y={Math.round(lastY) + 4} textAnchor="middle" fontSize="10.5" fill="#000" fontFamily="var(--font-mono)" fontWeight="700" textRendering="geometricPrecision">
              {formatY(last)}
            </text>
          </svg>
        )}
      </div>
    </div>
  );
}

/** Live chart for the current active symbol. */
export function ActiveChart() {
  const [active] = useActiveSymbol();
  const data = useChartData(active);
  const source = useDetailSource("chart", active);
  const { quote } = useQuote(active);
  const title = quote?.name ? `${active} · ${quote.name}` : active;
  return (
    <Chart
      title={title}
      subtitle="GP · INTRADAY · 1D · 1MIN"
      data={data}
      source={source}
    />
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   live depth book — driven by active symbol
   ──────────────────────────────────────────────────────────────────────────── */

export function DepthBook({ symbol }: { symbol?: string }) {
  const [active] = useActiveSymbol();
  const sym = symbol ?? active;
  const depth = useDepth(sym);
  const source = useDetailSource("depth", sym);
  let cumBid = 0;
  let cumAsk = 0;
  const LEVELS = Math.min(depth.bids.length, depth.asks.length);
  return (
    <table className="w-full text-[11px] tabular-nums">
      <thead className="sticky top-0 bg-term-panel text-term-dim">
        <tr>
          <Th>Lvl</Th>
          <Th right>Bid Cum</Th>
          <Th right>Bid Qty</Th>
          <Th right>Bid</Th>
          <th className="border-x border-term-border px-2 py-[3px] text-center font-normal uppercase">⇄</th>
          <Th>Ask</Th>
          <Th>Ask Qty</Th>
          <Th>Ask Cum</Th>
          <Th right>Lvl</Th>
        </tr>
        <ThRule span={9} />
      </thead>
      <tbody>
        {LEVELS === 0 && <EmptyDataRow colSpan={9} source={source} />}
        {Array.from({ length: LEVELS }).map((_, i) => {
          const b = depth.bids[i];
          const a = depth.asks[i];
          cumBid += b.qty;
          cumAsk += a.qty;
          return (
            <tr key={i} className="border-b border-term-border/60">
              <td className="px-2 py-[3px] text-term-dim">{pad(i + 1, 2, true)}</td>
              <td className="px-2 py-[3px] text-right text-term-dim">{cumBid.toLocaleString()}</td>
              <td className="px-2 py-[3px] text-right text-term-text">{b.qty.toLocaleString()}</td>
              <td className="px-2 py-[3px] text-right text-term-green">{fmt(b.px, 2)}</td>
              <td className="border-x border-term-border px-2 py-[3px] text-center text-term-dim">·</td>
              <td className="px-2 py-[3px] text-term-red">{fmt(a.px, 2)}</td>
              <td className="px-2 py-[3px] text-term-text">{a.qty.toLocaleString()}</td>
              <td className="px-2 py-[3px] text-term-dim">{cumAsk.toLocaleString()}</td>
              <td className="px-2 py-[3px] text-right text-term-dim">{pad(i + 1, 2, true)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
