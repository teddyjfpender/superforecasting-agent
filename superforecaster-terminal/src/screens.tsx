import { useMemo, useState } from "react";
import {
  ActiveChart,
  BondsTable,
  CbRatesTable,
  CdsTable,
  Chart,
  CreditIndexTable,
  CrossRateMatrix,
  DatasetRight,
  DetailRight,
  DepthBook,
  EventTable,
  Heatmap,
  MarketsTable,
  NewsFeed,
  OptionsChain,
  Panel,
  PREDICTION_TOPICS,
  PredictionMarketsTable,
  RecentPrintsTable,
  ResearchPanel,
  TabbedPanel,
  TimeSales,
  fmt,
  fmtSigned,
  inferPredictionTopic,
  pad,
  predictionTopicLabel,
  type PredictionTopic,
} from "./components";
import {
  useActiveSymbol,
  useBonds,
  useCBRates,
  useCDS,
  useCreditIndices,
  useCrossFX,
  useEvents,
  useNews,
  usePredictionMarkets,
  useRecentPrints,
  useYieldCurve,
} from "./providers";
import { ChatScreen } from "./chat";
import { NewsScreen } from "./news";
import {
  AccountSummary,
  Concentration,
  EditablePositionsTable,
  EfficientFrontier,
  FactorExposures,
  PLAttribution,
  PerformanceVsBenchmark,
  PortfolioBar,
  RiskMetricsTable,
  SectorAllocation,
} from "./portfolio";
import { EditableWatchlist, WatchlistBar } from "./watchlist";
import {
  CorrelationScreen,
  EarningsScreen,
  MoversScreen,
  MultiChartScreen,
  VolatilitySurface,
} from "./secondaries";

export type FKey =
  | "F1" | "F2" | "F3" | "F4" | "F5" | "F6"
  | "F7" | "F8" | "F9" | "F10" | "F11" | "F12";

export type SecondaryKey = "MOST" | "ERN" | "CORR" | "GIP" | "MSG";
export type ScreenKey = FKey | SecondaryKey;

/* ─────────────────────────────────────────────────────────────────────────────
   F1 · HELP
   ──────────────────────────────────────────────────────────────────────────── */

function HelpScreen({ onJump }: { onJump: (k: ScreenKey) => void }) {
  type ShortcutRow = [string, string, string, string]; // [Key, Alt, Function, Description]
  const FUNCTION_KEYS: ShortcutRow[] = [
    ["F1",  "1",  "HELP",  "This screen — keyboard shortcuts, commands, and main menu"],
    ["F2",  "2",  "MKTS",  "Markets monitor — sector heatmap, global indices, FX, rates"],
    ["F3",  "3",  "EQTY",  "Equity dashboard — watchlist, chart, depth, options, T&S"],
    ["F4",  "4",  "PRED",  "Prediction markets — Polymarket & Kalshi (distribution markets soon)"],
    ["F5",  "5",  "RATES", "Government bond yields & central bank policy"],
    ["F6",  "6",  "FX",    "Foreign exchange — G10 spot, cross rates, EM"],
    ["F7",  "7",  "CMDTY", "Commodities — energy, metals, ags front month"],
    ["F8",  "8",  "FI",    "Fixed income — corporate bonds, IG/HY"],
    ["F9",  "9",  "CRED",  "Credit — 5Y CDS spreads, IG/HY indices"],
    ["F10", "0",  "ECON",  "Economic calendar — releases, prints, central bank policy"],
    ["F11", "-",  "NEWS",  "News wire — top stories, filtered by category"],
    ["F12", "=",  "PORT",  "Portfolio — positions, P/L, live marks"],
  ];

  type ChordRow = [string, string, string]; // [Chord, Function, Description]
  const GLOBAL_CHORDS: ChordRow[] = [
    ["⌘K",     "PALETTE", "Open the command palette — fuzzy search all symbols, screens, and actions"],
    ["⌘/",     "MSG",     "Jump to the AI co-pilot chat for data lookup, alerts, and navigation"],
    ["⌘E",     "ALRT",    "Open Alerts Manager — create ≥/≤ price alerts on any symbol"],
    ["⌘,",     "THM",     "Theme switcher — cream / amber / phosphor / paper"],
    ["⌘[",     "DESK",    "Desks — save / load named view snapshots (Bloomberg-style cockpits)"],
    ["⌘K + /", "LENS",    "Sector filter — type / then a sector (TECH, FIN, …) to scope every screen"],
    ["⌘\\",    "CLEAR",   "Clear the active sector lens"],
    ["SPACE",  "PAUSE",   "Pause or resume the live tick stream (also click LIVE/PAUSED pill)"],
    ["ESC",    "CLOSE",   "Close any open modal (Alerts, Palette, Theme, Desks, …)"],
    ["↑ / ↓",  "NAV",     "Inside the Command Palette: move selection"],
    ["↵",      "SELECT",  "Inside the Command Palette: jump to the highlighted result"],
  ];

  type ScreenRow = [string, string, string]; // [Mnemonic, How to reach, Description]
  const SECONDARY_SCREENS: ScreenRow[] = [
    ["MSG",  "⌘/ or ⌘K → MSG",          "AI co-pilot — Claude with read-only data tools + navigation"],
    ["MOST", "⌘K → MOST or CMD > MOST", "Movers — top gainers, top losers, most active by |Δ%|"],
    ["GIP",  "⌘K → GIP  or CMD > GIP",  "Multi-chart grid — 2×2 quadrants, click to focus & bind"],
    ["CORR", "⌘K → CORR or CMD > CORR", "Correlation matrix — watchlist ρ heatmap (red↔green)"],
    ["ERN",  "⌘K → ERN  or CMD > ERN",  "Earnings calendar — next 14d with consensus & implied move"],
    ["OMON", "F3 → Options tab",         "Options chain — calls/puts at ATM ± 9 strikes"],
    ["OVDV", "F3 → Vol Surface tab",     "Implied vol surface — expiry × strike heatmap"],
    ["TAS",  "F3 → Time & Sales tab",    "Tick-by-tick trade tape with bid/ask flags"],
    ["DEPTH","F3 → Depth tab",           "Level II order book — 10 levels each side"],
  ];

  type CommandRow = [string, string, string]; // [Mnemonic, Where, What]
  const COMMAND_LINE: CommandRow[] = [
    ["<ticker>",   "any row click",     "Set the active security; chart / depth / options / T&S all rebind"],
    ["F<n>",       "CMD > or palette",  "Jump to screen by F-key number (F1–F12)"],
    ["<LABEL>",    "CMD >",             "Jump to screen by label, e.g. EQTY, RATES, MOST, GIP"],
    ["1–9 0 - =",  "anywhere (no input)", "Digit-row fallback for F1–F12 when the OS eats the F-key"],
    ["heatmap",    "F2 cell click",     "Click any sector heatmap cell to set the active symbol"],
    ["bind",       "F3 GIP quadrant",    "Click a quadrant then a watchlist row to bind"],
    ["CXL",        "alerts",            "Cancel an active alert from its row"],
  ];

  type CurateRow = [string, string, string]; // [Action, Where, Effect]
  const CURATE_VIEW: CurateRow[] = [
    // Watchlists (worksheets) — F3 EQTY
    ["WATCHLIST",     "F3 → top pills",            "Click a pill to switch active watchlist; double-click to rename inline"],
    ["+ NEW",         "F3 watchlist bar",          "Create an empty watchlist (name only). Activates immediately."],
    ["+ ADD SYMBOL",  "F3 watchlist footer",       "Add a ticker to the active watchlist (prefix-match suggestions, rejects unknown)"],
    ["✕",             "F3 watchlist row",          "Remove that symbol from the active watchlist"],
    ["DELETE",        "F3 watchlist bar",          "Delete the active watchlist (refuses to remove the last)"],
    // Portfolios — F12 PORT
    ["PORTFOLIO",     "F12 → top pills",           "Click a pill to switch active portfolio; double-click to rename inline"],
    ["+ NEW",         "F12 portfolio bar",         "Create a portfolio with a name + starting cash. Activates immediately."],
    ["+ ADD POSITION","F12 positions footer",      "Manually add a LONG/SHORT position with avg cost (no order routing)"],
    ["✕",             "F12 position row",          "Remove that position from the active portfolio"],
    ["DELETE",        "F12 portfolio bar",         "Delete the active portfolio (refuses to remove the last)"],
    // Desks — global
    ["SAVE DESK",     "⌘[ → name + SAVE CURRENT",  "Snapshot the entire view (screen + symbol + watchlist + portfolio + theme) as a named desk"],
    ["LOAD DESK",     "⌘[ → click name or LOAD",   "Snap back to a saved desk in one click — all five sub-states restore together"],
    ["UPDATE DESK",   "⌘[ → row → UPDATE",         "Overwrite a saved desk with the current view"],
    ["RENAME DESK",   "⌘[ → row → RENAME",         "Inline rename a desk; ↵ commits, ESC cancels"],
    ["DELETE DESK",   "⌘[ → row → DEL",            "Permanently delete a desk (confirmed)"],
    // Lens — sector filter, the third leg of curation
    ["SECTOR LENS",   "⌘K → /<sector>",            "Filter every screen (watchlist, positions, heatmap, movers, correlation) to one sector"],
    ["CLEAR LENS",    "⌘\\ or ⌘K → CLEAR or × on banner", "Remove the active sector lens"],
  ];

  type ActionRow = [string, string, string]; // [Action, How, Result]
  const DATA_ACTIONS: ActionRow[] = [
    ["SELECT SEC",   "row click / palette",       "Rebind chart, depth, options, T&S, news, and context panels"],
    ["ALERT ≥",      "⌘E → ≥ → level → ↵",         "Fires locally the first time price crosses up through the level"],
    ["ALERT ≤",      "⌘E → ≤ → level → ↵",         "Fires locally the first time price crosses down through the level"],
    ["ADD POSITION", "F12 → + ADD POSITION",       "Manually add a holding for mark/risk views; no order routing"],
    ["DATA STATUS",  "status bar DATA strip",      "Inspect LIVE, STALE, MOCK, and N/A dataset counts"],
    ["SAVE DESK",    "⌘[ → name + SAVE CURRENT",   "Persist the current data workspace locally"],
  ];

  type SystemRow = [string, string, string];
  const SYSTEM_TOGGLES: SystemRow[] = [
    ["LIVE / PAUSE", "Status bar pill or SPACE",  "Halt or resume the entire tick stream"],
    ["THEME",        "⌘,",                        "Cream (default), Bloomberg Amber, Phosphor Green, Paper"],
    ["WORKSPACES",   "⌘[",                        "Save / load / rename / delete view snapshots — persisted to localStorage"],
    ["WATCHLISTS",   "F3 top pills · localStorage", "Multiple named lists; click pill to switch, double-click to rename"],
    ["PORTFOLIOS",   "F12 top pills · localStorage", "Multiple named books for manual marks and risk views"],
    ["DATA SOURCE",  "providers.ts",              "BackendFirstDataProvider consumes termd snapshots with local demo fallback"],
  ];

  const Section = ({
    title,
    cols,
    rows,
  }: {
    title: string;
    cols: [string, string, string, string?];
    rows: (ShortcutRow | ChordRow | ScreenRow | CommandRow | CurateRow | ActionRow | SystemRow)[];
  }) => (
    <section>
      <header className="sticky top-0 z-10 border-b border-term-border bg-term-panel px-3 py-1 text-[11px] uppercase tracking-wider text-term-accent-hi">
        ▸ {title}
      </header>
      <table className="w-full text-[12px] tabular-nums">
        <thead className="bg-term-panel text-term-dim">
          <tr>
            <th className="px-3 py-1 text-left font-normal uppercase">{cols[0]}</th>
            <th className="px-3 py-1 text-left font-normal uppercase">{cols[1]}</th>
            <th className="px-3 py-1 text-left font-normal uppercase">{cols[2]}</th>
            {cols[3] && <th className="px-3 py-1 text-left font-normal uppercase">{cols[3]}</th>}
          </tr>
          <tr><th colSpan={cols[3] ? 4 : 3} className="border-b border-term-border p-0" /></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-term-border/60 hover:bg-term-accent/10">
              {r.map((cell, ci) => {
                if (ci === 0) {
                  return (
                    <td key={ci} className="px-3 py-1">
                      <span className="inline-block border border-term-accent-hi px-1.5 py-[1px] text-term-accent-hi">
                        {cell}
                      </span>
                    </td>
                  );
                }
                if (cols[3] && ci === 1) {
                  return (
                    <td key={ci} className="px-3 py-1">
                      <span className="inline-block border border-term-dim px-1.5 py-[1px] text-term-dim">
                        {cell}
                      </span>
                    </td>
                  );
                }
                const isFunction = cols[3] ? ci === 2 : ci === 1;
                return (
                  <td
                    key={ci}
                    className={`px-3 py-1 ${isFunction ? "text-term-accent" : "text-term-text"}`}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );

  type MenuItem = { k: ScreenKey; label: string; desc: string };
  type MenuGroup = { title: string; items: MenuItem[] };
  const MENU_GROUPS: MenuGroup[] = [
    {
      title: "Markets",
      items: [
        { k: "F2",  label: "MKTS",  desc: "Sector heatmap & global markets" },
        { k: "F3",  label: "EQTY",  desc: "Equity dashboard · depth · options · T&S · vol" },
        { k: "F4",  label: "PRED",  desc: "Prediction markets · Polymarket & Kalshi" },
        { k: "F5",  label: "RATES", desc: "Government yields & curve" },
        { k: "F6",  label: "FX",    desc: "Foreign exchange & EM" },
        { k: "F7",  label: "CMDTY", desc: "Commodities front month" },
      ],
    },
    {
      title: "AI & Discovery",
      items: [
        { k: "MSG",  label: "MSG",  desc: "AI co-pilot · Claude · tool use enabled" },
        { k: "MOST", label: "MOST", desc: "Movers — gainers / losers / actives" },
        { k: "GIP",  label: "GIP",  desc: "Multi-chart grid (2×2 quadrants)" },
        { k: "CORR", label: "CORR", desc: "Correlation matrix · watchlist" },
        { k: "ERN",  label: "ERN",  desc: "Earnings calendar · next 14d" },
      ],
    },
    {
      title: "Credit, Research, News",
      items: [
        { k: "F8",  label: "FI",    desc: "Corporate bonds — IG/HY" },
        { k: "F9",  label: "CRED",  desc: "CDS spreads & indices" },
        { k: "F10", label: "ECON",  desc: "Economic calendar — releases & prints" },
        { k: "F11", label: "NEWS",  desc: "News wire — filtered" },
      ],
    },
    {
      title: "Portfolio",
      items: [
        { k: "F12", label: "PORT",  desc: "Portfolio & risk · live marks" },
      ],
    },
  ];

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div className="col-span-7 flex min-h-0">
        <Panel id={1} title="Commands & Shortcuts" right="EVERYTHING YOU CAN DO">
          <div className="divide-y divide-term-border/40">
            <Section
              title="Function Keys — Primary Screens"
              cols={["Key", "Alt", "Function", "Description"]}
              rows={FUNCTION_KEYS}
            />
            <Section
              title="Global Keyboard Chords"
              cols={["Chord", "Function", "Description"]}
              rows={GLOBAL_CHORDS}
            />
            <Section
              title="Secondary Screens & Panel Tabs"
              cols={["Mnemonic", "Reached via", "Description"]}
              rows={SECONDARY_SCREENS}
            />
            <Section
              title="Command Line & Click Bindings"
              cols={["Token", "Where", "Effect"]}
              rows={COMMAND_LINE}
            />
            <Section
              title="Curate Your View — Watchlists · Portfolios · Desks"
              cols={["Action", "Where", "Effect"]}
              rows={CURATE_VIEW}
            />
            <Section
              title="Read-Only Data Actions"
              cols={["Action", "How", "Result"]}
              rows={DATA_ACTIONS}
            />
            <Section
              title="System Toggles"
              cols={["Toggle", "Where", "Notes"]}
              rows={SYSTEM_TOGGLES}
            />
            <div className="bg-term-panel px-3 py-2 text-[11px] text-term-dim">
              NOTE: ON macOS, <span className="text-term-accent">F11/F12</span> may be intercepted
              by Mission Control. Use the <span className="text-term-accent">Alt</span> column
              (unmodified <span className="text-term-accent">-</span> /{" "}
              <span className="text-term-accent">=</span>), click the tile, type{" "}
              <span className="text-term-accent">F12</span> /{" "}
              <span className="text-term-accent">PORT</span> in the command line, or open the
              palette with <span className="text-term-accent">⌘K</span>.
            </div>
          </div>
        </Panel>
      </div>

      <div
        className="col-span-5 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.5fr) minmax(0, 1fr)" }}
      >
        <Panel id={2} title="Main Menu" right="CLICK A TILE TO JUMP">
          <div
            className="grid h-full min-h-full gap-px bg-term-border"
            style={{
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gridTemplateRows: "repeat(2, minmax(0, 1fr))",
            }}
          >
            {MENU_GROUPS.map((g, gi) => (
              <section key={gi} className="flex min-h-0 flex-col bg-term-panel">
                <header className="shrink-0 border-b border-term-border bg-term-accent/15 px-3 py-1 text-[11px] uppercase tracking-wider text-term-accent-hi">
                  {pad(gi + 1, 2, true)}) {g.title}
                </header>
                <ul className="min-h-0 flex-1 overflow-auto">
                  {g.items.map((it) => (
                    <li key={it.k}>
                      <button
                        onClick={() => onJump(it.k)}
                        className="flex w-full items-center gap-3 border-b border-term-border/60 px-3 py-[6px] text-left hover:bg-term-accent/10"
                      >
                        <span className="border border-term-accent-hi px-1.5 py-[1px] text-[11px] text-term-accent-hi">
                          {it.k}
                        </span>
                        <span className="w-14 text-[11px] uppercase text-term-accent">{it.label}</span>
                        <span className="truncate text-[11px] uppercase text-term-text">{it.desc}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </Panel>

        <div className="grid min-h-0 grid-cols-2 gap-px bg-term-border">
          <Panel id={3} title="Quick-Start Flow" right="3-STEP">
            <ol className="space-y-3 px-3 py-3 text-[12px] uppercase">
              <li className="border-l-2 border-term-accent pl-3">
                <div className="text-term-accent-hi">1) Pick a security</div>
                <div className="mt-1 text-term-text normal-case">
                  Click any row in the watchlist, markets monitor, or sector
                  heatmap — chart, depth, options, vol surface, T&amp;S rebind.
                </div>
              </li>
              <li className="border-l-2 border-term-accent pl-3">
                <div className="text-term-accent-hi">2) Inspect or alert</div>
                <div className="mt-1 text-term-text normal-case">
                  Use <span className="text-term-accent">F12 PORT</span> for
                  manual marks and risk views.{" "}
                  <span className="text-term-accent">⌘E</span> arms a local
                  price alert.
                </div>
              </li>
              <li className="border-l-2 border-term-accent pl-3">
                <div className="text-term-accent-hi">3) Explore</div>
                <div className="mt-1 text-term-text normal-case">
                  <span className="text-term-accent">⌘K</span> palette — fuzzy
                  across symbols, screens, actions. Or type a label in the
                  <span className="text-term-accent"> CMD &gt;</span> line.
                </div>
              </li>
            </ol>
          </Panel>
          <Panel id={4} title="About · System">
            <div className="space-y-1 px-3 py-2 text-[11px] uppercase">
              <Row k="Terminal"      v="BBRG · TX-02" />
              <Row k="Version"       v="0.3.0 (build 6abdf2b)" />
              <Row k="User"          v="OPERATOR" valueClass="text-term-accent-hi" />
              <Row k="Profile"       v="EQUITY TRADING · US LARGE CAP" />
              <Row k="Session"       v="SECURE · TLS 1.3" valueClass="text-term-green" />
              <Row k="Latency"       v="11ms · NY4 → IAD" valueClass="text-term-green" />
              <Row k="Data Provider" v="TERMD BACKEND-FIRST · DEMO FALLBACK" valueClass="text-term-accent" />
              <Row k="Market Data"   v="DELAYED 0s · OPRA · TOTALVIEW" />
              <Row k="Subscription"  v="PROFESSIONAL · TERMINAL ANYWHERE" />
              <Row k="Support"       v="HDS <HELP> · 24/7" />
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v, valueClass = "text-term-text" }: { k: string; v: string; valueClass?: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-term-dim">{k}</span>
      <span className={valueClass}>{v}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F2 · MARKETS — heatmap on top, three split rails below
   ──────────────────────────────────────────────────────────────────────────── */

function MarketsScreen() {
  return (
    <div
      className="col-span-12 grid min-h-0 gap-px bg-term-border"
      style={{ gridTemplateRows: "minmax(0, 1.4fr) minmax(0, 1fr)" }}
    >
      <Panel
        id={1}
        title="Sector Heatmap — S&P Constituents"
        right={<DatasetRight datasetKey="markets-overview" fallback="WEIGHTED · CLICK TO SELECT" />}
      >
        <Heatmap />
      </Panel>
      <div className="grid min-h-0 grid-cols-3 gap-px bg-term-border">
        <Panel id={2} title="World Indices" right={<DatasetRight datasetKey="quotes" fallback="WORLD · LOCAL CCY" />}>
          <MarketsTable category="world-indices" />
        </Panel>
        <Panel id={3} title="Sovereign Yields" right={<DatasetRight datasetKey="rates" fallback="G10 · % YTM" />}>
          <MarketsTable category="rates" />
        </Panel>
        <Panel id={4} title="FX Spot" right={<DatasetRight datasetKey="fx" fallback="G10 · BID/ASK" />}>
          <MarketsTable category="fx" />
        </Panel>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F3 · EQUITY — active-symbol driven dashboard
   ──────────────────────────────────────────────────────────────────────────── */

function EquityScreen() {
  const [active] = useActiveSymbol();
  const symbolNews = useNews({ symbol: active });
  const topNews = useNews();
  const events = useEvents();
  const panelNews = symbolNews.length > 0 ? symbolNews : topNews;
  return (
    <>
      <div
        className="col-span-3 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "repeat(4, minmax(0, 1fr))" }}
      >
        <Panel id={1} title="Markets Monitor" right={<DatasetRight datasetKey="quotes" fallback="WLD" />}>
          <MarketsTable category="indices" />
        </Panel>
        <Panel id={2} title="FX Spot" right={<DatasetRight datasetKey="fx" fallback="G10 · BID/ASK" />}>
          <MarketsTable category="fx" />
        </Panel>
        <Panel id={3} title="Sov. Yields" right={<DatasetRight datasetKey="rates" fallback="GBM · BPS" />}>
          <MarketsTable category="rates" />
        </Panel>
        <Panel id={4} title="Sector Heat — SPDR" right={<DatasetRight datasetKey="markets-overview" fallback="GICS L1" />}>
          <MarketsTable category="sectors" />
        </Panel>
      </div>

      <div
        className="col-span-6 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 36px) minmax(0, 1.35fr) minmax(0, 1.55fr) minmax(0, 1.25fr)" }}
      >
        <Panel id={5} title="Watchlists" right="READ MODEL · LOCAL UI">
          <WatchlistBar />
        </Panel>
        <Panel id={6} title="Watchlist · Quotes" right={<DatasetRight datasetKey="quotes" fallback="CLICK ROW TO FOCUS" />}>
          <EditableWatchlist />
        </Panel>
        <Panel id={7} title="Chart — GP" right={<DetailRight kind="chart" fallback={`${active} · STUDY: VOL/MA20`} />}>
          <ActiveChart />
        </Panel>
        <TabbedPanel
          id={8}
          initial={0}
          tabs={[
            {
              key: "depth",
              label: "Depth",
              right: `${active} · LEVEL II`,
              render: () => <DepthBook />,
            },
            {
              key: "opts",
              label: "Options",
              right: `${active} · 20JUN26 · ATM ± 9`,
              render: () => <OptionsChain symbol={active} />,
            },
            {
              key: "vol",
              label: "Vol Surface",
              right: `${active} · IV % · 6 EXPIRIES × 15 STRIKES`,
              render: () => <VolatilitySurface symbol={active} />,
            },
            {
              key: "tas",
              label: "Time & Sales",
              right: `${active} · LAST 80 PRINTS`,
              render: () => <TimeSales symbol={active} />,
            },
            {
              key: "research",
              label: "Research",
              right: `${active} · SEC · INSIDER · 13F`,
              render: () => <ResearchPanel symbol={active} />,
            },
          ]}
        />
      </div>

      <div
        className="col-span-3 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "repeat(4, minmax(0, 1fr))" }}
      >
        <Panel id={9} title="News Wire" right={<DatasetRight datasetKey="news" fallback="TOP · ALL SRCES" />}>
          <NewsFeed items={panelNews} dense />
        </Panel>
        <Panel id={10} title="Economic Calendar" right={<DatasetRight datasetKey="economic-events" fallback="TODAY" />}>
          <EventTable items={events} />
        </Panel>
        <Panel id={11} title="Commodities" right={<DatasetRight datasetKey="commodities" fallback="FRONT MONTH" />}>
          <MarketsTable category="commodities" />
        </Panel>
        <Panel id={12} title="Crypto" right={<DatasetRight datasetKey="quotes" fallback="USD · SPOT" />}>
          <MarketsTable category="crypto" />
        </Panel>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F4 · PRED — Prediction markets (Polymarket + Kalshi, distribution soon)
   ──────────────────────────────────────────────────────────────────────────── */

function PredictionScreen() {
  const markets = usePredictionMarkets();
  const [topic, setTopic] = useState<PredictionTopic>("ALL");

  const stats = useMemo(() => {
    let polymarket = 0;
    let kalshi = 0;
    let other = 0;
    let live = 0;
    let resolved = 0;
    let totalVolume = 0;
    let topVolume = 0;
    let topQuestion = "";
    let latestReceivedAt = "";
    const sources = new Set<string>();
    const emptyTopicCounts = (): Record<PredictionTopic, number> => ({
      ALL: 0,
      POLITICS: 0,
      MACRO: 0,
      GEOPOL: 0,
      CRYPTO: 0,
      TECH: 0,
      SPORTS: 0,
      CLIMATE: 0,
      ENT: 0,
      OTHER: 0,
    });
    const topicCounts = emptyTopicCounts();
    // Per-venue topic counts so the venue tab labels match the rows visible
    // under the current topic filter.
    const topicByVenue: Record<"POLYMARKET" | "KALSHI" | "OTHER", Record<PredictionTopic, number>> = {
      POLYMARKET: emptyTopicCounts(),
      KALSHI: emptyTopicCounts(),
      OTHER: emptyTopicCounts(),
    };
    for (const m of markets) {
      const venue = m.venue.toUpperCase();
      const venueBucket: "POLYMARKET" | "KALSHI" | "OTHER" =
        venue === "POLYMARKET" ? "POLYMARKET" : venue === "KALSHI" ? "KALSHI" : "OTHER";
      if (venueBucket === "POLYMARKET") polymarket++;
      else if (venueBucket === "KALSHI") kalshi++;
      else other++;
      if (m.source) sources.add(m.source.toUpperCase());
      if (m.receivedAt && (!latestReceivedAt || m.receivedAt > latestReceivedAt)) {
        latestReceivedAt = m.receivedAt;
      }
      if (m.resolved) resolved++;
      else live++;
      const vol = m.volume ?? 0;
      totalVolume += vol;
      if (vol > topVolume) {
        topVolume = vol;
        topQuestion = m.question;
      }
      const inferred = inferPredictionTopic(m.question);
      topicCounts[inferred]++;
      topicCounts.ALL++;
      topicByVenue[venueBucket][inferred]++;
      topicByVenue[venueBucket].ALL++;
    }
    return {
      total: markets.length,
      polymarket,
      kalshi,
      other,
      live,
      resolved,
      totalVolume,
      topVolume,
      topQuestion,
      latestReceivedAt,
      sources: Array.from(sources).sort(),
      topicCounts,
      topicByVenue,
    };
  }, [markets]);

  const sourceRight = stats.total === 0
    ? "AWAITING TERMD FEED"
    : `${stats.sources.slice(0, 2).join("/") || "TERMD"} · ${formatReceivedUtc(stats.latestReceivedAt)} UTC`;

  const formatVolume = (v: number) => {
    if (v <= 0) return "-";
    if (v >= 1_000_000) return `${fmt(v / 1_000_000, 1)}M`;
    if (v >= 1_000) return `${fmt(v / 1_000, 1)}K`;
    return fmt(v, 0);
  };

  // Fixed-width count slot. Tabular-nums + reserved character width keeps
  // tab/chip widths stable as digit counts tick under live updates.
  const Count = ({ n }: { n: number }) => (
    <span className="ml-1 inline-block min-w-[2.25ch] text-right tabular-nums text-term-dim">
      {n}
    </span>
  );

  const TabLabel = ({ text, n }: { text: string; n: number }) => (
    <span className="inline-flex items-baseline">
      <span>{text}</span>
      <Count n={n} />
    </span>
  );

  // Render Kpi panels with a fixed slot for every value so a swing from 9→10
  // doesn't shift siblings, and so panels that drop to 0 don't disappear.
  const Kpi = ({
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
    <div
      className="col-span-12 grid min-h-0 gap-px bg-term-border"
      style={{ gridTemplateRows: "minmax(0, 64px) minmax(0, 1fr)" }}
    >
      <Panel id={1} title="Prediction Snapshot" right={sourceRight}>
        <div className="flex h-full min-h-0 items-stretch text-[12px]">
          <Kpi k="Markets" v={String(stats.total)} cls="text-term-text" />
          <Kpi
            k="Polymarket"
            v={String(stats.polymarket)}
            cls={stats.polymarket > 0 ? "text-term-accent-hi" : "text-term-dim"}
          />
          <Kpi
            k="Kalshi"
            v={String(stats.kalshi)}
            cls={stats.kalshi > 0 ? "text-term-accent-hi" : "text-term-dim"}
          />
          <Kpi
            k="Other Venues"
            v={String(stats.other)}
            cls={stats.other > 0 ? "text-term-text" : "text-term-dim"}
          />
          <Kpi
            k="Live"
            v={String(stats.live)}
            cls={stats.live > 0 ? "text-term-green" : "text-term-dim"}
          />
          <Kpi
            k="Resolved"
            v={String(stats.resolved)}
            cls="text-term-dim"
          />
          <Kpi k="Notional ($)" v={formatVolume(stats.totalVolume)} cls="text-term-text" />
          <div className="flex min-w-0 flex-[2] flex-col items-start justify-center border-l border-term-border px-3 py-1">
            <span className="text-[10px] uppercase text-term-dim">Top by Volume</span>
            <span
              className="truncate text-term-accent-hi"
              title={stats.topQuestion}
            >
              {stats.topQuestion || "—"}
              {stats.topVolume > 0 && (
                <span className="ml-2 text-term-dim">
                  {formatVolume(stats.topVolume)}
                </span>
              )}
            </span>
          </div>
        </div>
      </Panel>

      <div className="flex min-h-0 flex-col gap-px bg-term-border">
        <PredictionTopicFilter
          topic={topic}
          setTopic={setTopic}
          counts={stats.topicCounts}
        />
        <div className="flex min-h-0 flex-1">
          <TabbedPanel
            id={2}
            initial={0}
            tabs={[
              {
                key: "all",
                label: <TabLabel text="All" n={stats.topicCounts[topic]} />,
                right: topic === "ALL"
                  ? "ALL VENUES · RANKED BY VOLUME"
                  : `ALL VENUES · TOPIC: ${predictionTopicLabel(topic).toUpperCase()}`,
                render: () => <PredictionMarketsTable limit={64} topic={topic} />,
              },
              {
                key: "polymarket",
                label: (
                  <TabLabel text="Polymarket" n={stats.topicByVenue.POLYMARKET[topic]} />
                ),
                right: topic === "ALL"
                  ? "POLYMARKET CLOB · YES/NO BINARY"
                  : `POLYMARKET · TOPIC: ${predictionTopicLabel(topic).toUpperCase()}`,
                render: () => (
                  <PredictionMarketsTable venue="polymarket" limit={64} topic={topic} />
                ),
              },
              {
                key: "kalshi",
                label: <TabLabel text="Kalshi" n={stats.topicByVenue.KALSHI[topic]} />,
                right: topic === "ALL"
                  ? "KALSHI EXCHANGE · CFTC-REGULATED"
                  : `KALSHI · TOPIC: ${predictionTopicLabel(topic).toUpperCase()}`,
                render: () => (
                  <PredictionMarketsTable
                    venue="kalshi"
                    limit={64}
                    topic={topic}
                    emptyHint="No Kalshi markets yet — enable the Kalshi venue in the backend feed (set VITE_TERMD_PREDICTION_VENUE=polymarket,kalshi)."
                  />
                ),
              },
              {
                key: "distribution",
                label: "Distribution",
                right: "COMING SOON · PARI-MUTUEL · OPTION-STYLE PAYOFFS",
                render: () => (
                  <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-[11px] uppercase">
                    <span className="text-term-accent-hi">DISTRIBUTION MARKETS</span>
                    <span className="text-term-dim normal-case max-w-md">
                      Continuous-outcome and pari-mutuel markets (price ranges,
                      numeric strike payoffs) will surface here once the backend
                      exposes distribution-style quotes. For now this tab is a
                      placeholder while the Polymarket/Kalshi mix above stays the
                      primary view.
                    </span>
                  </div>
                ),
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function PredictionTopicFilter({
  topic,
  setTopic,
  counts,
}: {
  topic: PredictionTopic;
  setTopic: (t: PredictionTopic) => void;
  counts: Record<PredictionTopic, number>;
}) {
  return (
    <div className="flex shrink-0 items-stretch gap-px overflow-x-auto border border-term-border bg-term-panel text-[11px] uppercase">
      <span className="flex items-center bg-term-accent px-2 py-[2px] font-semibold tracking-wider text-term-on-accent">
        Topic
      </span>
      {PREDICTION_TOPICS.map((t) => {
        const active = topic === t;
        const n = counts[t] ?? 0;
        return (
          <button
            key={t}
            type="button"
            onClick={() => setTopic(t)}
            aria-pressed={active}
            className={`flex items-baseline gap-1 border-l border-term-border px-2 py-[2px] outline-none transition-colors ${
              active
                ? "bg-term-inv-bg text-term-inv-fg"
                : "text-term-text hover:bg-term-accent/15"
            }`}
            title={`${predictionTopicLabel(t)} (${n})`}
          >
            <span>{predictionTopicLabel(t)}</span>
            <span
              className={`inline-block min-w-[2.25ch] text-right tabular-nums ${
                active ? "text-term-inv-fg/70" : "text-term-dim"
              }`}
            >
              {n}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function formatReceivedUtc(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return `${String(date.getUTCHours()).padStart(2, "0")}:${String(date.getUTCMinutes()).padStart(2, "0")}:${String(date.getUTCSeconds()).padStart(2, "0")}`;
}

/* ─────────────────────────────────────────────────────────────────────────────
   F5 · RATES
   ──────────────────────────────────────────────────────────────────────────── */

function RatesScreen() {
  const cbRates = useCBRates();
  const usCurve = useYieldCurve();
  const chartCurve = usCurve.filter((p): p is typeof p & { yld: number } => p.yld !== null);
  const curveData = chartCurve.map((p) => p.yld);
  const tenors = chartCurve.map((p) => p.tenor);
  const twoYearYield = usCurve.find((p) => p.tenor === "2Y")?.yld ?? 4.18;
  return (
    <>
      <div className="col-span-3 flex min-h-0">
        <Panel id={1} title="Sov. Yields — G10" right={<DatasetRight datasetKey="rates" fallback="% YTM · 1D Δ BPS" />}>
          <MarketsTable category="rates" />
        </Panel>
      </div>

      <div
        className="col-span-6 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.6fr) minmax(0, 1fr)" }}
      >
        <Panel id={2} title="US Treasury Yield Curve" right={<DatasetRight datasetKey="rates" fallback="ON-THE-RUN · % YTM" />}>
          <Chart
            title="USYC — US TREASURY CURVE"
            subtitle="ON-THE-RUN · END OF DAY"
            data={curveData}
            xLabels={tenors}
            formatY={(v) => fmt(v, 2) + "%"}
            yLabel="YTM (%)"
          />
        </Panel>
        <Panel id={3} title="Yield Curve Table" right={<DatasetRight datasetKey="rates" fallback="POINT-BY-POINT · BPS" />}>
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-term-panel text-term-dim">
              <tr>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Tenor</th>
                {usCurve.map((p) => (
                  <th key={p.tenor} className="px-2 py-[3px] text-right font-normal">{p.tenor}</th>
                ))}
              </tr>
              <tr>
                <th colSpan={usCurve.length + 1} className="border-b border-term-border p-0" />
              </tr>
            </thead>
            <tbody>
              {usCurve.length === 0 ? (
                <tr className="border-b border-term-border/60">
                  <td className="px-2 py-[3px] text-term-dim">YIELD CURVE DATA UNAVAILABLE</td>
                </tr>
              ) : (
                [
                  ["% YTM",  usCurve.map((p) => p.yld), "text-term-accent-hi"],
                  ["Δ 1D",   usCurve.map((p) => p.yld === null ? null : -0.011 + (p.yld - 4.2) * 0.04), "signed"],
                  ["Δ 1M",   usCurve.map((p) => p.yld === null ? null : -0.18 + (p.yld - 4.2) * 0.2), "signed"],
                  ["Δ YTD",  usCurve.map((p) => p.yld === null ? null : -0.32 + (p.yld - 4.2) * 0.3), "signed"],
                  ["vs 2Y",  usCurve.map((p) => p.yld === null ? null : p.yld - twoYearYield), "signed-bps"],
                ].map(([label, values, mode]) => (
                  <tr key={label as string} className="border-b border-term-border/60 hover:bg-term-accent/10">
                    <td className="px-2 py-[3px] text-term-accent">{label as string}</td>
                    {(values as (number | null)[]).map((v, i) => {
                      if (v === null) {
                        return (
                          <td key={i} className="px-2 py-[3px] text-right text-term-dim">
                            N/A
                          </td>
                        );
                      }
                      const pos = v >= 0;
                      const tone =
                        mode === "text-term-accent-hi"
                          ? "text-term-accent-hi"
                          : pos ? "text-term-green" : "text-term-red";
                      const display =
                        mode === "text-term-accent-hi"
                          ? fmt(v, 2)
                          : mode === "signed-bps"
                            ? fmtSigned(v * 100, 0)
                            : fmtSigned(v * 100, 1);
                      return (
                        <td key={i} className={`px-2 py-[3px] text-right ${tone}`}>
                          {display}
                        </td>
                      );
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="col-span-3 flex min-h-0">
        <Panel id={4} title="Central Bank Rates" right={<DatasetRight datasetKey="rates" fallback="GLOBAL · POLICY" />}>
          <CbRatesTable rows={cbRates} />
        </Panel>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F6 · FX
   ──────────────────────────────────────────────────────────────────────────── */

function FxScreen() {
  const crossFx = useCrossFX();

  return (
    <>
      <div className="col-span-3 flex min-h-0">
        <Panel id={1} title="G10 FX Spot" right={<DatasetRight datasetKey="fx" fallback="BID/ASK" />}>
          <MarketsTable category="fx" />
        </Panel>
      </div>

      <div
        className="col-span-6 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1fr) minmax(0, 1.2fr)" }}
      >
        <Panel id={2} title="Cross-Rate Matrix" right={<DatasetRight datasetKey="fx" fallback="ROW / COLUMN · MID" />}>
          <CrossRateMatrix ccys={crossFx.ccys} matrix={crossFx.matrix} />
        </Panel>
        <Panel id={3} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY · 1D · 1MIN" />}>
          <ActiveChart />
        </Panel>
      </div>

      <div className="col-span-3 flex min-h-0">
        <Panel id={4} title="EM FX" right={<DatasetRight datasetKey="fx" fallback="USD CROSSES" />}>
          <MarketsTable category="em-fx" />
        </Panel>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F7 · COMMODITIES
   ──────────────────────────────────────────────────────────────────────────── */

function CommoditiesScreen() {
  return (
    <>
      <div
        className="col-span-3 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "repeat(2, minmax(0, 1fr))" }}
      >
        <Panel id={1} title="Energy" right={<DatasetRight datasetKey="commodities" fallback="WTI · BRENT · NG" />}>
          <MarketsTable category="energy" />
        </Panel>
        <Panel id={2} title="Metals" right={<DatasetRight datasetKey="commodities" fallback="PRECIOUS · BASE" />}>
          <MarketsTable category="metals" />
        </Panel>
      </div>

      <div
        className="col-span-6 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.5fr) minmax(0, 1fr)" }}
      >
        <Panel id={3} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY · 1MIN" />}>
          <ActiveChart />
        </Panel>
        <Panel id={4} title="Forward Curve — WTI" right={<DatasetRight datasetKey="commodities" fallback="USD/BBL · M1-M12" />}>
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-term-panel text-term-dim">
              <tr>
                <th className="px-2 py-[3px] text-left font-normal uppercase">Month</th>
                {Array.from({ length: 12 }).map((_, i) => (
                  <th key={i} className="px-2 py-[3px] text-right font-normal">M{i + 1}</th>
                ))}
              </tr>
              <tr><th colSpan={13} className="border-b border-term-border p-0" /></tr>
            </thead>
            <tbody>
              {[
                ["PX",     Array.from({ length: 12 }, (_, i) => 76.84 - i * 0.38 + Math.sin(i * 0.6) * 0.4)],
                ["Δ M1",   Array.from({ length: 12 }, (_, i) => -i * 0.38 + Math.sin(i * 0.6) * 0.4)],
                ["Vol",    Array.from({ length: 12 }, (_, i) => Math.max(20, 412 - i * 38))],
                ["OI",     Array.from({ length: 12 }, (_, i) => Math.max(50, 1840 - i * 142))],
                ["Vega",   Array.from({ length: 12 }, (_, i) => 0.184 + i * 0.012)],
              ].map(([label, vals]) => (
                <tr key={label as string} className="border-b border-term-border/60 hover:bg-term-accent/10">
                  <td className="px-2 py-[3px] text-term-accent">{label as string}</td>
                  {(vals as number[]).map((v, i) => {
                    const isPx = label === "PX";
                    const isDM = label === "Δ M1";
                    const cls =
                      isPx ? "text-term-accent-hi"
                           : isDM ? (v >= 0 ? "text-term-green" : "text-term-red")
                                  : "text-term-text";
                    return (
                      <td key={i} className={`px-2 py-[3px] text-right ${cls}`}>
                        {isDM ? fmtSigned(v, 2) : isPx ? fmt(v, 2) : fmt(v, 0)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div
        className="col-span-3 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "repeat(2, minmax(0, 1fr))" }}
      >
        <Panel id={5} title="Agricultures" right={<DatasetRight datasetKey="commodities" fallback="GRAINS · SOFTS" />}>
          <MarketsTable category="ags" />
        </Panel>
        <Panel id={6} title="Crypto" right={<DatasetRight datasetKey="quotes" fallback="USD · SPOT" />}>
          <MarketsTable category="crypto" />
        </Panel>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F8 · FIXED INCOME
   ──────────────────────────────────────────────────────────────────────────── */

function FixedIncomeScreen() {
  const cbRates = useCBRates();
  const bonds = useBonds();
  return (
    <div
      className="col-span-12 grid min-h-0 gap-px bg-term-border"
      style={{ gridTemplateRows: "minmax(0, 1.7fr) minmax(0, 1fr)" }}
    >
      {/* Top row — chart is the main focus, flanked by sov yields & CB rates */}
      <div className="grid min-h-0 grid-cols-12 gap-px bg-term-border">
        <div className="col-span-3 flex min-h-0">
          <Panel id={1} title="Sov. Curves" right={<DatasetRight datasetKey="rates" fallback="CLICK ROW TO FOCUS" />}>
            <MarketsTable category="rates" />
          </Panel>
        </div>
        <div className="col-span-6 flex min-h-0">
          <Panel id={2} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY" />}>
            <ActiveChart />
          </Panel>
        </div>
        <div className="col-span-3 flex min-h-0">
          <Panel id={3} title="Central Bank Rates" right={<DatasetRight datasetKey="rates" fallback="CLICK FOR FX" />}>
            <CbRatesTable rows={cbRates} />
          </Panel>
        </div>
      </div>
      {/* Bottom row — wide bonds table; col-span-12 means it gets a much
          richer column layout than the cramped half-width version. */}
      <div className="flex min-h-0">
        <Panel id={4} title="Corporate Bonds — USD" right={<DatasetRight datasetKey="fixed-income" fallback="READ ONLY · SOURCE" />}>
          <BondsTable rows={bonds} />
        </Panel>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F9 · CREDIT
   ──────────────────────────────────────────────────────────────────────────── */

function CreditScreen() {
  const cds = useCDS();
  const indices = useCreditIndices();
  return (
    <>
      <div className="col-span-6 flex min-h-0">
        <Panel id={1} title="5Y CDS — Single Names" right={<DatasetRight datasetKey="fixed-income" fallback="BID · BPS · SOURCE" />}>
          <CdsTable rows={cds} />
        </Panel>
      </div>
      <div
        className="col-span-6 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.3fr) minmax(0, 1fr)" }}
      >
        <Panel id={2} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY" />}>
          <ActiveChart />
        </Panel>
        <Panel id={3} title="Index Snapshot" right={<DatasetRight datasetKey="fixed-income" fallback="LAST · 1D · YTD" />}>
          <CreditIndexTable rows={indices} />
        </Panel>
      </div>
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F10 · ECONOMICS
   ──────────────────────────────────────────────────────────────────────────── */

function EconScreen() {
  const cbRates = useCBRates();
  const events = useEvents();
  const recentPrints = useRecentPrints();
  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div className="col-span-4 flex min-h-0">
        <Panel id={1} title="Economic Calendar — Today" right={<DatasetRight datasetKey="economic-events" fallback="ALL G10" />}>
          <EventTable items={events} />
        </Panel>
      </div>
      <div className="col-span-5 flex min-h-0">
        <Panel id={2} title="Recent Prints — This Week" right={<DatasetRight datasetKey="recent-prints" fallback="ALL G10 · A/F/S" />}>
          <RecentPrintsTable items={recentPrints} />
        </Panel>
      </div>
      <div className="col-span-3 flex min-h-0">
        <Panel id={3} title="Central Bank Policy" right={<DatasetRight datasetKey="rates" fallback="GLOBAL" />}>
          <CbRatesTable rows={cbRates} />
        </Panel>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   F11 · NEWS  →  see ./news.tsx for the implementation.
   ──────────────────────────────────────────────────────────────────────────── */

/* ─────────────────────────────────────────────────────────────────────────────
   F12 · PORTFOLIO
   ──────────────────────────────────────────────────────────────────────────── */

function PortfolioScreen() {
  return (
    <div
      className="col-span-12 grid min-h-0 gap-px bg-term-border"
      style={{
        gridTemplateRows:
          "minmax(0, 36px) minmax(0, 64px) minmax(0, 1.35fr) minmax(0, 1fr)",
      }}
    >
      {/* Row 1 — Portfolios bar (full width, just a strip of pills). */}
      <Panel id={1} title="Portfolios" right="READ MODEL · LOCAL UI">
        <PortfolioBar />
      </Panel>

      {/* Row 2 — Account KPIs (full width). Seven KPI cells fit on
          col-span-12 comfortably with room to spare. */}
      <Panel id={2} title="Account" right={<DatasetRight datasetKey="quotes" fallback="USD · MTD" />}>
        <AccountSummary />
      </Panel>

      {/* Row 3 — Positions (col-7) + Chart (col-5). Coequal focuses. */}
      <div className="grid min-h-0 grid-cols-12 gap-px bg-term-border">
        <div className="col-span-7 flex min-h-0">
          <Panel id={3} title="Positions" right={<DatasetRight datasetKey="quotes" fallback="CLICK ROW · REMOVE" />}>
            <EditablePositionsTable />
          </Panel>
        </div>
        <div className="col-span-5 flex min-h-0">
          <Panel id={4} title="Chart — Active Security" right={<DetailRight kind="chart" fallback="INTRADAY" />}>
            <ActiveChart />
          </Panel>
        </div>
      </div>

      {/* Row 4 — Tabbed Analytics (col-8) + Risk Metrics (col-4). */}
      <div className="grid min-h-0 grid-cols-12 gap-px bg-term-border">
        <div className="col-span-8 flex min-h-0">
          <TabbedPanel
            id={5}
            initial={0}
            tabs={[
              {
                key: "sector",
                label: "Sector",
                right: "% of gross by GICS L1",
                render: () => <SectorAllocation />,
              },
              {
                key: "attr",
                label: "Attribution",
                right: "today · by contribution",
                render: () => <PLAttribution />,
              },
              {
                key: "perf",
                label: "Performance",
                right: "portfolio vs SPX · 60d",
                render: () => <PerformanceVsBenchmark />,
              },
              {
                key: "frontier",
                label: "Frontier",
                right: "risk / return · annualised",
                render: () => <EfficientFrontier />,
              },
              {
                key: "factors",
                label: "Factors",
                right: "style tilts · weighted",
                render: () => <FactorExposures />,
              },
              {
                key: "conc",
                label: "Concentration",
                right: "top-N · HHI",
                render: () => <Concentration />,
              },
            ]}
          />
        </div>
        <div className="col-span-4 flex min-h-0">
          <Panel id={6} title="Risk Metrics" right="EX-ANTE · WHOLE PORTFOLIO">
            <RiskMetricsTable />
          </Panel>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   registry
   ──────────────────────────────────────────────────────────────────────────── */

export const SCREEN_LABELS: Record<ScreenKey, string> = {
  F1:  "HELP",
  F2:  "MKTS",
  F3:  "EQTY",
  F4:  "PRED",
  F5:  "RATES",
  F6:  "FX",
  F7:  "CMDTY",
  F8:  "FI",
  F9:  "CRED",
  F10: "ECON",
  F11: "NEWS",
  F12: "PORT",
  MOST: "MOST",
  ERN:  "ERN",
  CORR: "CORR",
  GIP:  "GIP",
  MSG:  "MSG",
};

export const SCREEN_BREADCRUMBS: Record<ScreenKey, string> = {
  F1:  "HELP / KEYBOARD · COMMANDS · MAIN MENU",
  F2:  "MARKETS / HEATMAP · GLOBAL",
  F3:  "EQUITY US / WATCHLIST · CHART · DEPTH · OMON · OVDV · T&S",
  F4:  "PREDICTION / POLYMARKET · KALSHI · DISTRIBUTION (SOON)",
  F5:  "RATES / GOVT YIELDS · USYC",
  F6:  "FX / G10 SPOT · CROSS RATES",
  F7:  "COMMODITY / FRONT MONTH · ALL",
  F8:  "FIXED INCOME / CORP BONDS · USD",
  F9:  "CREDIT / 5Y CDS · ALL ISSUERS",
  F10: "ECONOMICS / CALENDAR · ALL G10",
  F11: "NEWS / TOP STORIES · ALL SRC",
  F12: "PORTFOLIO / PRIMARY PA1 · READ ONLY",
  MOST: "MOVERS / GAINERS · LOSERS · ACTIVES",
  ERN:  "EARNINGS / NEXT 14D · CONSENSUS",
  CORR: "CORRELATION / WATCHLIST · 60D ρ",
  GIP:  "MULTI-CHART / GIP · 2×2 QUADRANTS",
  MSG:  "AI CO-PILOT / CLAUDE · TOOL USE ENABLED",
};

export function isSecondary(key: string): key is SecondaryKey {
  return (
    key === "MOST" ||
    key === "ERN" ||
    key === "CORR" ||
    key === "GIP" ||
    key === "MSG"
  );
}

export function renderScreen(key: ScreenKey, onJump: (k: ScreenKey) => void) {
  switch (key) {
    case "F1":  return <HelpScreen onJump={onJump} />;
    case "F2":  return <MarketsScreen />;
    case "F3":  return <EquityScreen />;
    case "F4":  return <PredictionScreen />;
    case "F5":  return <RatesScreen />;
    case "F6":  return <FxScreen />;
    case "F7":  return <CommoditiesScreen />;
    case "F8":  return <FixedIncomeScreen />;
    case "F9":  return <CreditScreen />;
    case "F10": return <EconScreen />;
    case "F11": return <NewsScreen />;
    case "F12": return <PortfolioScreen />;
    case "MOST": return <MoversScreen />;
    case "ERN":  return <EarningsScreen />;
    case "CORR": return <CorrelationScreen />;
    case "GIP":  return <MultiChartScreen />;
    case "MSG":  return <ChatScreen />;
  }
}
