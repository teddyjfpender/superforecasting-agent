import Anthropic from "@anthropic-ai/sdk";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { fmt, fmtSigned, Panel } from "./components";
import {
  useActiveSymbol,
  useAlerts,
  usePositions,
  useProvider,
  useQuote,
  type AlertCondition,
  type DataProvider,
} from "./providers";

/* ─────────────────────────────────────────────────────────────────────────────
   Config — API key + model
   ──────────────────────────────────────────────────────────────────────────── */

const LS_KEY = "term-anthropic-api-key";
const MODEL = "claude-sonnet-4-6";

function readEnvKey(): string | null {
  try {
    const v = (import.meta as unknown as { env?: { VITE_ANTHROPIC_API_KEY?: string } }).env
      ?.VITE_ANTHROPIC_API_KEY;
    return v && v.length > 0 ? v : null;
  } catch {
    return null;
  }
}

function readStoredKey(): string | null {
  try {
    return localStorage.getItem(LS_KEY);
  } catch {
    return null;
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Tool definitions — what Claude can do
   ──────────────────────────────────────────────────────────────────────────── */

type ToolDef = Anthropic.Messages.Tool;

const TOOLS: ToolDef[] = [
  {
    name: "get_quote",
    description:
      "Read the live quote for a single symbol (ticker, last, chg, %, bid, ask, vol).",
    input_schema: {
      type: "object",
      properties: { symbol: { type: "string" } },
      required: ["symbol"],
    },
  },
  {
    name: "get_news",
    description:
      "Fetch recent news headlines. Filter by symbol (substring match) and/or category (TOP/ECON/FX/EQ/FI/CMDTY/CRED).",
    input_schema: {
      type: "object",
      properties: {
        symbol: { type: "string" },
        category: {
          type: "string",
          enum: ["TOP", "ECON", "FX", "EQ", "FI", "CMDTY", "CRED"],
        },
        limit: { type: "integer", default: 8 },
      },
    },
  },
  {
    name: "get_position",
    description:
      "Read the current portfolio position for a symbol — qty, avg cost, mark, mv, P/L, P/L %.",
    input_schema: {
      type: "object",
      properties: { symbol: { type: "string" } },
      required: ["symbol"],
    },
  },
  {
    name: "summarize_chart",
    description:
      "Return a compact numeric summary of a symbol's intraday price action: open/high/low/last and percent change.",
    input_schema: {
      type: "object",
      properties: { symbol: { type: "string" } },
      required: ["symbol"],
    },
  },
  {
    name: "list_positions",
    description: "List all open portfolio positions with mv and P/L.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "list_movers",
    description:
      "Return the top movers — gainers, losers, and most actives by |Δ%|.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "set_alert",
    description:
      "Create a price alert that fires once when a symbol crosses a level.",
    input_schema: {
      type: "object",
      properties: {
        symbol: { type: "string" },
        level: { type: "number" },
        condition: { type: "string", enum: [">=", "<="] },
      },
      required: ["symbol", "level", "condition"],
    },
  },
  {
    name: "go_to_screen",
    description:
      "Navigate to a screen by key: F1..F12 (primary) or MOST/ERN/CORR/GIP/MSG (secondary).",
    input_schema: {
      type: "object",
      properties: { key: { type: "string" } },
      required: ["key"],
    },
  },
  {
    name: "set_active_symbol",
    description:
      "Focus a security across the whole terminal — chart, depth, options, news rebind to it.",
    input_schema: {
      type: "object",
      properties: { symbol: { type: "string" } },
      required: ["symbol"],
    },
  },
];

// Cache the system prompt + tool list via cache_control on the last tool.
const CACHED_TOOLS: ToolDef[] = TOOLS.map((t, i, arr) =>
  i === arr.length - 1
    ? ({ ...t, cache_control: { type: "ephemeral" } } as ToolDef)
    : t,
);

/* ─────────────────────────────────────────────────────────────────────────────
   System prompt
   ──────────────────────────────────────────────────────────────────────────── */

const SYSTEM_PROMPT = `You are the AI co-pilot for "BBRG TERMINAL TX-02", a Bloomberg-style market data terminal.

PERSONA
- Voice: senior trading-desk operator. Terse, numeric, direct. No padding, no apologies, no "I can help with that".
- Format: ALL CAPS for tickers and screen labels. Cite numbers (price, %, level, qty) every time you reference market data. Prefer one or two short sentences per point.
- When you complete a local action, confirm it concisely: "ALERT NVDA >= 142.84." Do not imply order routing.

CAPABILITIES
You can READ data and ACT ON the local terminal workspace via tools. Use read tools aggressively.

Read tools (call freely, no confirmation needed):
- get_quote, get_news, get_position, summarize_chart, list_positions, list_movers

Local workspace tools (no order routing):
- set_alert(symbol, level, condition)
- go_to_screen(key)
- set_active_symbol(symbol)

RULES
- If the user asks to buy, sell, short, submit, route, or cancel an order, state that this build is read-only and can only provide market data, alerts, navigation, and local mark/risk views.
- "Why is X moving?" = call get_news(symbol) + summarize_chart(symbol), then synthesize the answer with citations to the headline times.
- When the user references "this" / "it" without a symbol, prefer the current active symbol from the live context.
- When asked to navigate ("show me the heatmap", "go to portfolio"), call go_to_screen.
- Never hallucinate prices — always call get_quote when you need a current number.
- "Set me an alert at X" = call set_alert; default to >= if direction is unclear and current px < X, else <=.

OUTPUT STYLE
- Lead with the answer, then evidence.
- Use short bullet lists for >=3 items.
- Highlight directional moves with ▲ / ▼ inline.`;

/* ─────────────────────────────────────────────────────────────────────────────
   Tool dispatcher — translates JSON tool calls into provider actions
   ──────────────────────────────────────────────────────────────────────────── */

type ToolCtx = {
  provider: DataProvider;
  activeSymbol: string;
  activeKey: string;
  setActiveSymbol: (s: string) => void;
  setActiveKey: (k: string) => void;
};

type ToolOutcome = { ok: true; result: string } | { ok: false; error: string };

function resolveSymbol(input: { symbol?: string } | undefined, ctx: ToolCtx) {
  const raw = (input?.symbol ?? "").toString().trim().toUpperCase();
  if (!raw) return ctx.activeSymbol;
  return raw;
}

async function executeTool(
  name: string,
  input: Record<string, unknown>,
  ctx: ToolCtx,
): Promise<ToolOutcome> {
  try {
    switch (name) {
      case "get_quote": {
        const sym = resolveSymbol(input as { symbol?: string }, ctx);
        const q = ctx.provider.getQuote(sym);
        if (!q) return { ok: false, error: `Unknown symbol: ${sym}` };
        return {
          ok: true,
          result: JSON.stringify({
            ticker: q.ticker,
            name: q.name,
            last: q.last,
            chg: q.chg,
            pct: q.pct,
            bid: q.bid,
            ask: q.ask,
            vol: q.vol,
          }),
        };
      }
      case "get_news": {
        const limit = Math.max(1, Math.min(20, Number(input.limit) || 8));
        const filter: { symbol?: string; category?: string } = {};
        if (input.symbol) filter.symbol = String(input.symbol).toUpperCase();
        if (input.category) filter.category = String(input.category).toUpperCase();
        const items = ctx.provider.getNews(filter).slice(0, limit);
        return {
          ok: true,
          result: JSON.stringify(
            items.map((n) => ({
              time: n.time,
              src: n.src,
              cat: n.cat ?? null,
              tone: n.tone,
              headline: n.headline,
            })),
          ),
        };
      }
      case "get_position": {
        const sym = resolveSymbol(input as { symbol?: string }, ctx);
        const p = ctx.provider
          .getPositions()
          .find((x) => x.ticker.toUpperCase() === sym.toUpperCase());
        if (!p) return { ok: true, result: JSON.stringify({ symbol: sym, position: "FLAT" }) };
        return {
          ok: true,
          result: JSON.stringify({
            symbol: p.ticker,
            qty: p.qty,
            avg: p.avg,
            mark: p.mark,
            mv: p.mv,
            pl: p.pl,
            plPct: p.plPct,
          }),
        };
      }
      case "summarize_chart": {
        const sym = resolveSymbol(input as { symbol?: string }, ctx);
        const data = ctx.provider.getChart(sym);
        if (data.length === 0) return { ok: false, error: `No chart data for ${sym}` };
        const open = data[0];
        const last = data[data.length - 1];
        const high = Math.max(...data);
        const low = Math.min(...data);
        const pct = ((last - open) / open) * 100;
        return {
          ok: true,
          result: JSON.stringify({
            symbol: sym,
            open: +open.toFixed(2),
            high: +high.toFixed(2),
            low: +low.toFixed(2),
            last: +last.toFixed(2),
            pct: +pct.toFixed(2),
          }),
        };
      }
      case "list_positions": {
        const ps = ctx.provider.getPositions();
        if (ps.length === 0) return { ok: true, result: "[]" };
        return {
          ok: true,
          result: JSON.stringify(
            ps.map((p) => ({
              ticker: p.ticker,
              qty: p.qty,
              avg: p.avg,
              mark: p.mark,
              pl: p.pl,
              plPct: p.plPct,
            })),
          ),
        };
      }
      case "list_movers": {
        const m = ctx.provider.getMovers();
        const fmt2 = (q: { ticker: string; pct: number; last: number }) =>
          `${q.ticker} ${q.last} (${q.pct >= 0 ? "+" : ""}${q.pct}%)`;
        return {
          ok: true,
          result: JSON.stringify({
            gainers: m.gainers.map(fmt2),
            losers: m.losers.map(fmt2),
            actives: m.actives.map(fmt2),
          }),
        };
      }
      case "set_alert": {
        const symbol = String(input.symbol).toUpperCase();
        const level = Number(input.level);
        const condition = String(input.condition) as AlertCondition;
        if (!symbol || !isFinite(level) || (condition !== ">=" && condition !== "<=")) {
          return { ok: false, error: "Invalid alert: need symbol, level, condition (>= or <=)" };
        }
        const a = ctx.provider.addAlert({ symbol, level, condition });
        return {
          ok: true,
          result: JSON.stringify({ id: a.id, symbol: a.symbol, level: a.level, condition: a.condition, status: a.status }),
        };
      }
      case "go_to_screen": {
        const key = String(input.key).toUpperCase();
        ctx.setActiveKey(key);
        return { ok: true, result: JSON.stringify({ activeKey: key }) };
      }
      case "set_active_symbol": {
        const symbol = String(input.symbol).toUpperCase();
        ctx.setActiveSymbol(symbol);
        return { ok: true, result: JSON.stringify({ activeSymbol: symbol }) };
      }
      default:
        return { ok: false, error: `Unknown tool: ${name}` };
    }
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Live context — short, refreshed every turn
   ──────────────────────────────────────────────────────────────────────────── */

function buildContext(
  provider: DataProvider,
  activeSymbol: string,
  activeKey: string,
): string {
  const q = provider.getQuote(activeSymbol);
  const pos = provider
    .getPositions()
    .find((p) => p.ticker === activeSymbol);
  const news = provider.getNews().slice(0, 3);
  const lines = [
    `Local time: ${new Date().toISOString()}`,
    `Active screen: ${activeKey}`,
    `Active symbol: ${activeSymbol}${q ? ` (LAST ${q.last}, ${q.chg >= 0 ? "▲" : "▼"}${q.pct}%)` : ""}`,
    pos
      ? `Position: ${pos.qty} @ avg ${pos.avg.toFixed(2)} · P/L ${pos.pl.toFixed(2)} (${pos.plPct.toFixed(2)}%)`
      : "Position: FLAT",
    `Top news:`,
    ...news.map((n) => `  ${n.time} ${n.src} [${n.cat ?? "-"}] ${n.headline}`),
  ];
  return lines.join("\n");
}

/* ─────────────────────────────────────────────────────────────────────────────
   Chat events + state
   ──────────────────────────────────────────────────────────────────────────── */

export type ChatEvent =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string; streaming: boolean }
  | {
      id: string;
      kind: "tool";
      name: string;
      input: Record<string, unknown>;
      result?: string;
      error?: string;
    }
  | { id: string; kind: "error"; text: string };

let _idCounter = 0;
function nextId() {
  _idCounter += 1;
  return `${Date.now().toString(36)}-${_idCounter}`;
}

type ChatCtx = {
  events: ChatEvent[];
  pending: boolean;
  send: (userMsg: string) => Promise<void>;
  reset: () => void;
  apiKey: string | null;
  setApiKey: (key: string) => void;
};

const ChatContext = createContext<ChatCtx | null>(null);

export function ChatProvider({
  children,
  setActiveKey,
  activeKey,
}: {
  children: React.ReactNode;
  setActiveKey: (k: string) => void;
  activeKey: string;
}) {
  const provider = useProvider();
  const [activeSymbol, setActiveSymbol] = useActiveSymbol();
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [pending, setPending] = useState(false);
  const [apiKey, setApiKeyState] = useState<string | null>(
    () => readEnvKey() ?? readStoredKey(),
  );

  // Keep refs that always point at the latest setters/values so tools dispatched
  // from a long-running async loop can see post-render state changes.
  const ctxRef = useRef<ToolCtx>({
    provider,
    activeSymbol,
    activeKey,
    setActiveSymbol,
    setActiveKey,
  });
  useEffect(() => {
    ctxRef.current = {
      provider,
      activeSymbol,
      activeKey,
      setActiveSymbol,
      setActiveKey,
    };
  }, [provider, activeSymbol, activeKey, setActiveSymbol, setActiveKey]);

  const apiHistoryRef = useRef<Anthropic.Messages.MessageParam[]>([]);

  const setApiKey = (key: string) => {
    try {
      localStorage.setItem(LS_KEY, key);
    } catch {}
    setApiKeyState(key);
  };

  const reset = () => {
    apiHistoryRef.current = [];
    setEvents([]);
  };

  const send = async (userMsgRaw: string) => {
    const userMsg = userMsgRaw.trim();
    if (!apiKey || !userMsg || pending) return;

    setEvents((e) => [...e, { id: nextId(), kind: "user", text: userMsg }]);
    apiHistoryRef.current.push({ role: "user", content: userMsg });
    setPending(true);

    try {
      const client = new Anthropic({ apiKey, dangerouslyAllowBrowser: true });

      // Agentic loop: stream → execute tools → loop until end_turn
      while (true) {
        // Map from API tool_use id → our event id (so we can update the right row)
        const toolEventByApiId = new Map<string, string>();
        let pendingTextEventId: string | null = null;

        const c = ctxRef.current;
        const context = buildContext(c.provider, c.activeSymbol, c.activeKey);

        const stream = client.messages.stream({
          model: MODEL,
          max_tokens: 2048,
          system: [
            {
              type: "text",
              text: SYSTEM_PROMPT,
              cache_control: { type: "ephemeral" },
            },
            { type: "text", text: `LIVE CONTEXT\n${context}` },
          ],
          tools: CACHED_TOOLS,
          messages: apiHistoryRef.current,
        });

        stream.on("contentBlock", (block) => {
          if (block.type === "text") {
            const id = nextId();
            pendingTextEventId = id;
            setEvents((e) => [
              ...e,
              { id, kind: "assistant", text: "", streaming: true },
            ]);
          } else if (block.type === "tool_use") {
            pendingTextEventId = null;
            const id = nextId();
            toolEventByApiId.set(block.id, id);
            setEvents((e) => [
              ...e,
              { id, kind: "tool", name: block.name, input: {} },
            ]);
          }
        });

        stream.on("text", (delta) => {
          if (!pendingTextEventId) return;
          const targetId = pendingTextEventId;
          setEvents((events) =>
            events.map((e) =>
              e.id === targetId && e.kind === "assistant"
                ? { ...e, text: e.text + delta }
                : e,
            ),
          );
        });

        const final = await stream.finalMessage();

        // Mark all assistant blocks as not streaming
        setEvents((events) =>
          events.map((e) =>
            e.kind === "assistant" && e.streaming ? { ...e, streaming: false } : e,
          ),
        );

        // Fill in tool inputs (we get the full input now)
        for (const block of final.content) {
          if (block.type === "tool_use") {
            const eventId = toolEventByApiId.get(block.id);
            if (eventId) {
              setEvents((events) =>
                events.map((e) =>
                  e.id === eventId && e.kind === "tool"
                    ? { ...e, input: block.input as Record<string, unknown> }
                    : e,
                ),
              );
            }
          }
        }

        apiHistoryRef.current.push({
          role: "assistant",
          content: final.content,
        });

        if (final.stop_reason !== "tool_use") break;

        const toolResults: Anthropic.Messages.ToolResultBlockParam[] = [];
        for (const block of final.content) {
          if (block.type !== "tool_use") continue;
          const outcome = await executeTool(
            block.name,
            block.input as Record<string, unknown>,
            ctxRef.current,
          );
          const eventId = toolEventByApiId.get(block.id);
          if (eventId) {
            setEvents((events) =>
              events.map((e) =>
                e.id === eventId && e.kind === "tool"
                  ? {
                      ...e,
                      result: outcome.ok ? outcome.result : undefined,
                      error: outcome.ok ? undefined : outcome.error,
                    }
                  : e,
              ),
            );
          }
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: outcome.ok ? outcome.result : outcome.error,
            is_error: !outcome.ok,
          });
        }
        apiHistoryRef.current.push({ role: "user", content: toolResults });
      }
    } catch (err) {
      setEvents((e) => [
        ...e,
        { id: nextId(), kind: "error", text: humanizeError(err) },
      ]);
    } finally {
      setPending(false);
    }
  };

  const value = useMemo(
    () => ({ events, pending, send, reset, apiKey, setApiKey }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [events, pending, apiKey],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

function humanizeError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return String(err);
}

export function useChat() {
  const c = useContext(ChatContext);
  if (!c) throw new Error("useChat must be inside <ChatProvider>");
  return c;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Chat screen UI — `MSG` panel
   ──────────────────────────────────────────────────────────────────────────── */

const PROMPT_SUGGESTIONS = [
  "Why is the active symbol moving today?",
  "Summarize the active symbol chart.",
  "Set an alert when it crosses 150.",
  "Show me the top movers.",
  "What's my P/L on this position?",
];

function ApiKeySetup() {
  const { apiKey, setApiKey } = useChat();
  const [draft, setDraft] = useState("");
  if (apiKey) return null;
  return (
    <div className="space-y-3 px-3 py-3 text-[12px]">
      <div className="text-term-yellow uppercase">
        ▸ Anthropic API key required
      </div>
      <div className="text-term-text">
        The MSG panel streams responses from{" "}
        <span className="text-term-accent">claude-sonnet-4-6</span>. Paste your
        Anthropic API key to enable it. It's stored locally in your browser
        (localStorage) and never leaves your machine except to call the
        Anthropic API directly.
      </div>
      <div className="text-term-dim">
        Or set{" "}
        <span className="text-term-accent">VITE_ANTHROPIC_API_KEY</span> in a{" "}
        <span className="text-term-accent">.env</span> file and restart{" "}
        <span className="text-term-accent">bun dev</span>.
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) setApiKey(draft.trim());
        }}
        className="flex items-center gap-2"
      >
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="sk-ant-..."
          className="min-w-0 flex-1 border border-term-border-hi bg-term-bg px-2 py-1 font-mono text-term-accent-hi outline-none focus:border-term-accent"
          spellCheck={false}
          autoFocus
        />
        <button
          type="submit"
          className="border border-term-accent bg-term-accent/15 px-3 py-1 text-[11px] uppercase text-term-accent-hi hover:bg-term-accent/25"
        >
          Save &lt;GO&gt;
        </button>
      </form>
    </div>
  );
}

function EventBubble({ ev }: { ev: ChatEvent }) {
  if (ev.kind === "user") {
    return (
      <div className="flex gap-3 border-b border-term-border/40 px-3 py-2">
        <span className="shrink-0 text-term-dim">OPERATOR ▸</span>
        <span className="whitespace-pre-wrap text-term-text">{ev.text}</span>
      </div>
    );
  }
  if (ev.kind === "assistant") {
    return (
      <div className="flex gap-3 border-b border-term-border/40 px-3 py-2">
        <span className="shrink-0 text-term-accent-hi">BBRG ▸</span>
        <span className="whitespace-pre-wrap text-term-text">
          {ev.text}
          {ev.streaming && <span className="blink text-term-accent-hi">▋</span>}
        </span>
      </div>
    );
  }
  if (ev.kind === "tool") {
    const inputStr = formatToolInput(ev.input);
    return (
      <div className="border-b border-term-border/40 px-3 py-1.5 text-[11px]">
        <div className="flex items-baseline gap-2 text-term-dim">
          <span className="text-term-yellow">▸ TOOL</span>
          <span className="text-term-accent">{ev.name}</span>
          <span className="text-term-text">{inputStr}</span>
        </div>
        {ev.result != null && (
          <div className="mt-1 pl-6 text-term-dim">
            <span className="text-term-green">→</span>{" "}
            <span className="break-all text-term-text">
              {truncateJson(ev.result)}
            </span>
          </div>
        )}
        {ev.error != null && (
          <div className="mt-1 pl-6 text-term-red">→ {ev.error}</div>
        )}
        {ev.result == null && ev.error == null && (
          <div className="mt-1 pl-6 text-term-dim">→ pending…</div>
        )}
      </div>
    );
  }
  if (ev.kind === "error") {
    return (
      <div className="border-b border-term-red/40 bg-term-red/10 px-3 py-2 text-[11px] text-term-red">
        ▸ ERROR {ev.text}
      </div>
    );
  }
  return null;
}

function formatToolInput(input: Record<string, unknown>): string {
  const entries = Object.entries(input);
  if (entries.length === 0) return "()";
  return (
    "{ " +
    entries
      .map(([k, v]) => `${k}: ${typeof v === "string" ? `"${v}"` : JSON.stringify(v)}`)
      .join(", ") +
    " }"
  );
}

function truncateJson(s: string, max = 240) {
  if (s.length <= max) return s;
  return s.slice(0, max) + "…";
}

function ContextPanel() {
  const [active] = useActiveSymbol();
  const { quote } = useQuote(active);
  const positions = usePositions();
  const { alerts } = useAlerts();
  const pos = positions.find((p) => p.ticker === active);
  const activeAlerts = alerts.filter((a) => a.status === "ACTIVE");

  const Row = ({ k, v, cls = "text-term-text" }: { k: string; v: string; cls?: string }) => (
    <div className="flex justify-between gap-3">
      <span className="text-term-dim">{k}</span>
      <span className={cls}>{v}</span>
    </div>
  );

  return (
    <div className="space-y-3 px-3 py-2 text-[11px] uppercase">
      <section>
        <div className="mb-1 text-term-accent-hi">Active</div>
        {quote ? (
          <div className="space-y-0.5">
            <Row k="Symbol" v={quote.ticker} cls="text-term-accent-hi" />
            <Row k="Name" v={quote.name} />
            <Row k="Last" v={fmt(quote.last, 2)} cls="text-term-accent-hi" />
            <Row
              k="Change"
              v={`${fmtSigned(quote.chg, 2)} (${fmtSigned(quote.pct, 2)}%)`}
              cls={quote.chg >= 0 ? "text-term-green" : "text-term-red"}
            />
            <Row k="Bid/Ask" v={`${fmt(quote.bid, 2)} / ${fmt(quote.ask, 2)}`} />
            <Row k="Volume" v={quote.vol} />
          </div>
        ) : (
          <div className="text-term-dim">No quote.</div>
        )}
      </section>

      <section>
        <div className="mb-1 text-term-accent-hi">Position</div>
        {pos ? (
          <div className="space-y-0.5">
            <Row k="Qty" v={pos.qty.toLocaleString()} cls={pos.qty >= 0 ? "text-term-text" : "text-term-red"} />
            <Row k="Avg Cost" v={fmt(pos.avg, 2)} />
            <Row k="Mark" v={fmt(pos.mark, 2)} cls="text-term-accent-hi" />
            <Row k="MV" v={fmt(pos.mv, 2)} />
            <Row
              k="P/L"
              v={fmtSigned(pos.pl, 2)}
              cls={pos.pl >= 0 ? "text-term-green" : "text-term-red"}
            />
            <Row
              k="P/L %"
              v={`${fmtSigned(pos.plPct, 2)}%`}
              cls={pos.plPct >= 0 ? "text-term-green" : "text-term-red"}
            />
          </div>
        ) : (
          <div className="text-term-dim">FLAT</div>
        )}
      </section>

      <section>
        <div className="mb-1 text-term-accent-hi">Activity</div>
        <Row k="Mode" v="READ ONLY" cls="text-term-accent-hi" />
        <Row
          k="Active Alerts"
          v={String(activeAlerts.length)}
          cls={activeAlerts.length > 0 ? "text-term-yellow" : "text-term-dim"}
        />
        <Row k="Positions" v={String(positions.length)} />
      </section>
    </div>
  );
}

export function ChatScreen() {
  const { events, pending, send, reset, apiKey } = useChat();
  const [draft, setDraft] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ block: "end" });
  }, [events]);

  useEffect(() => {
    taRef.current?.focus();
  }, []);

  const submit = async () => {
    const v = draft.trim();
    if (!v || pending) return;
    setDraft("");
    await send(v);
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      <div className="col-span-9 flex min-h-0">
        <Panel
          id={1}
          title="MSG — AI Co-Pilot"
          right={
            <span className="text-[10px]">
              {apiKey ? "READY · CLAUDE-SONNET-4-6" : "NEEDS KEY"}
            </span>
          }
        >
          <div className="flex h-full min-h-0 flex-col">
            <div className="min-h-0 flex-1 overflow-auto">
              {!apiKey && <ApiKeySetup />}
              {apiKey && events.length === 0 && (
                <div className="space-y-3 px-3 py-3 text-[12px]">
                  <div className="text-term-accent-hi uppercase">
                    ▸ Try one of these
                  </div>
                  <ul className="space-y-1">
                    {PROMPT_SUGGESTIONS.map((p) => (
                      <li key={p}>
                        <button
                          onClick={() => send(p)}
                          className="w-full border border-term-border-hi px-3 py-1.5 text-left text-term-text hover:border-term-accent hover:bg-term-accent/10"
                        >
                          <span className="text-term-dim">▸</span>{" "}
                          <span>{p}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="text-term-dim">
                    Or type any question. Claude can read live quotes,
                    positions, news, and the chart — and call{" "}
                    <span className="text-term-accent">set_alert</span>,{" "}
                    <span className="text-term-accent">go_to_screen</span>{" "}
                    on your behalf.
                  </div>
                </div>
              )}
              <div>
                {events.map((ev) => (
                  <EventBubble key={ev.id} ev={ev} />
                ))}
                <div ref={threadEndRef} />
              </div>
            </div>

            {apiKey && (
              <div className="shrink-0 border-t border-term-border bg-term-bg-elev p-2">
                <div className="flex items-end gap-2">
                  <span className="pb-2 text-term-accent">▸</span>
                  <textarea
                    ref={taRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={onKey}
                    placeholder={
                      pending
                        ? "Awaiting response…"
                        : "Ask anything about the data. ⏎ to send · ⇧⏎ for newline"
                    }
                    disabled={pending}
                    rows={2}
                    className="min-h-[44px] min-w-0 flex-1 resize-none bg-transparent text-[12px] text-term-text placeholder-term-muted outline-none disabled:text-term-dim"
                    spellCheck={false}
                  />
                  <button
                    onClick={submit}
                    disabled={pending || !draft.trim()}
                    className="border border-term-accent bg-term-accent/15 px-3 py-1 text-[11px] uppercase text-term-accent-hi hover:bg-term-accent/25 disabled:cursor-not-allowed disabled:border-term-border-hi disabled:bg-transparent disabled:text-term-dim"
                  >
                    Run &lt;GO&gt;
                  </button>
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] uppercase text-term-dim">
                  <span>
                    Tools active: get_quote · get_news · get_position ·
                    summarize_chart · list_positions · list_movers ·{" "}
                    <span className="text-term-yellow">set_alert</span> ·
                    go_to_screen · set_active_symbol
                  </span>
                  <button
                    onClick={reset}
                    className="border border-term-border-hi px-2 py-[1px] hover:bg-term-accent/10"
                  >
                    CLEAR
                  </button>
                </div>
              </div>
            )}
          </div>
        </Panel>
      </div>

      <div className="col-span-3 flex min-h-0">
        <Panel id={2} title="Live Context" right="STREAMED EACH TURN">
          <ContextPanel />
        </Panel>
      </div>
    </div>
  );
}
