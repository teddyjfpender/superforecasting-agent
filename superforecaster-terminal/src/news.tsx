import { useEffect, useMemo, useState } from "react";
import { DatasetRight, NewsFeed, fmt, fmtSigned, useArrowNav } from "./components";
import { useModal } from "./modals";
import { useActiveSymbol, useNews, useProvider, useRssFeeds } from "./providers";
import type { NewsItem } from "./data";
import type { TermdRssFeed } from "./termdApi";

const CATS = ["TOP", "ECON", "FX", "EQ", "FI", "CMDTY", "CRED"] as const;
type Cat = (typeof CATS)[number];


/* ─────────────────────────────────────────────────────────────────────────────
   Story reader — used inside the in-panel pane AND inside the expand modal.
   ──────────────────────────────────────────────────────────────────────────── */

export function StoryReader({
  item,
  compact = false,
}: {
  item: NewsItem;
  compact?: boolean;
}) {
  const provider = useProvider();
  const [, setActive] = useActiveSymbol();

  return (
    <article className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-term-border px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[10px] uppercase">
          <span className="text-term-accent">{item.src}</span>
          <span className="text-term-dim">▸</span>
          <span className="tabular-nums text-term-dim">{item.time} ET</span>
          {item.cat && (
            <>
              <span className="text-term-dim">▸</span>
              <span className="text-term-accent">{item.cat}</span>
            </>
          )}
          {item.tone === "alert" && (
            <>
              <span className="text-term-dim">▸</span>
              <span className="text-term-yellow">
                <span className="mr-1 inline-block border border-term-yellow px-1 font-semibold text-term-yellow">
                  !
                </span>
                ALERT
              </span>
            </>
          )}
          {item.dateline && (
            <>
              <span className="text-term-dim">▸</span>
              <span className="text-term-dim">{item.dateline}</span>
            </>
          )}
        </div>
        <h2
          className={`mt-2 font-semibold uppercase leading-snug text-term-accent-hi ${
            compact ? "text-[13px]" : "text-[15px]"
          }`}
        >
          {item.headline}
        </h2>
        {item.byline && (
          <div className="mt-2 text-[10px] uppercase text-term-dim">
            BY {item.byline}
          </div>
        )}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 block truncate text-[10px] uppercase text-term-dim hover:text-term-accent-hi"
          >
            SOURCE ▸ {storyHost(item.url)}
          </a>
        )}
        {item.symbols && item.symbols.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <span className="text-[10px] uppercase text-term-dim">TICKERS ▸</span>
            {item.symbols.map((sym) => {
              const q = provider.getQuote(sym);
              const pos = (q?.chg ?? 0) >= 0;
              return (
                <button
                  key={sym}
                  onClick={() => setActive(sym)}
                  className="inline-flex items-baseline gap-1 border border-term-border-hi px-1.5 py-[1px] text-[11px] hover:border-term-accent hover:bg-term-accent/10"
                  title={`Focus ${sym}`}
                >
                  <span className="text-term-accent-hi">{sym}</span>
                  {q && (
                    <>
                      <span className="tabular-nums text-term-text">
                        {fmt(q.last, 2)}
                      </span>
                      <span
                        className={`tabular-nums ${pos ? "text-term-green" : "text-term-red"}`}
                      >
                        {pos ? "▲" : "▼"} {fmtSigned(q.pct, 2)}%
                      </span>
                    </>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        <div className={`space-y-3 ${compact ? "text-[12px]" : "text-[13px]"} leading-relaxed text-term-text`}>
          {item.body.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          <div className="mt-6 border-t border-term-border pt-3 text-[10px] uppercase text-term-dim">
            — END OF STORY — © {item.src} — IRR LICENSE — ID {item.id}
          </div>
        </div>
      </div>
    </article>
  );
}

function storyHost(url: string): string {
  try {
    return new URL(url).hostname.toUpperCase();
  } catch {
    return url.toUpperCase();
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Story modal — full-screen reader
   ──────────────────────────────────────────────────────────────────────────── */

export function StoryReaderModal({
  item,
  close,
}: {
  item: NewsItem;
  close: () => void;
}) {
  return (
    <>
      <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-3 py-1 text-[12px] font-semibold uppercase tracking-wider text-term-on-accent">
        <span>
          STORY ▸ {item.src} ▸ {item.time}
        </span>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-term-on-accent/70">ID {item.id}</span>
          <button
            onClick={close}
            className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
          >
            ESC
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        <StoryReader item={item} compact={false} />
      </div>
    </>
  );
}

function RssSourcePanel({ feeds }: { feeds: readonly TermdRssFeed[] }) {
  const visible = feeds.slice(0, 12);
  return (
    <section className="shrink-0 border-t border-term-border">
      <div className="flex items-center justify-between border-b border-term-border/70 px-2 py-[2px] text-[10px] font-semibold uppercase text-term-dim">
        <span>RSS Sources</span>
        <span className={feeds.length > 0 ? "tabular-nums text-term-accent-hi" : "text-term-dim"}>
          {feeds.length > 0 ? `${feeds.length} FEEDS` : "N/A"}
        </span>
      </div>
      <div className="max-h-44 overflow-auto text-[10px] uppercase">
        {visible.length > 0 ? (
          visible.map((feed) => {
            const symbols =
              feed.manualSymbols.length > 0
                ? feed.manualSymbols.slice(0, 4).join(" ")
                : feed.categories.slice(0, 3).join(" ") || "GLOBAL";
            return (
              <div
                key={feed.id}
                className="grid grid-cols-[minmax(0,1fr)_3.5rem] gap-2 border-b border-term-border/50 px-2 py-1.5"
                title={feed.url}
              >
                <div className="min-w-0">
                  <div className="truncate text-term-accent-hi">{feed.name}</div>
                  <div className="truncate text-term-dim">
                    {rssHost(feed.url)} · {feed.categories.slice(0, 2).join(" ")}
                  </div>
                </div>
                <div className="text-right tabular-nums">
                  <div className="text-term-text">{rssPollLabel(feed.pollSecs)}</div>
                  <div className="truncate text-term-dim">{feed.symbolTagging.toUpperCase()}</div>
                </div>
                <div className="col-span-2 truncate text-term-dim">{symbols}</div>
              </div>
            );
          })
        ) : (
          <div className="px-2 py-2 text-term-dim">AUTH RSS READ MODEL N/A</div>
        )}
      </div>
    </section>
  );
}

function rssPollLabel(seconds: number): string {
  if (seconds >= 3600) return `${Math.round(seconds / 3600)}H`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}M`;
  return `${seconds}S`;
}

function rssHost(url: string): string {
  try {
    return new URL(url).hostname.toUpperCase();
  } catch {
    return url.toUpperCase();
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   News screen
   ──────────────────────────────────────────────────────────────────────────── */

export function NewsScreen() {
  const newsItems = useNews();
  const rssFeeds = useRssFeeds();
  const [cat, setCat] = useState<Cat>("TOP");
  const filtered = useMemo(
    () => (cat === "TOP" ? newsItems : newsItems.filter((n) => n.cat === cat)),
    [cat, newsItems],
  );
  const [selectedId, setSelectedId] = useState<string>(
    () => newsItems[0]?.id ?? "",
  );

  // Selected item — guard against the active category not containing it.
  const selected =
    newsItems.find((n) => n.id === selectedId) ?? filtered[0] ?? newsItems[0];

  useEffect(() => {
    if (filtered.length > 0 && !filtered.some((n) => n.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  // When category changes, snap selection to the first item of that filter
  // if the current selection isn't in the new filter.
  const ensureSelectionInCat = (c: Cat) => {
    const list = c === "TOP" ? newsItems : newsItems.filter((n) => n.cat === c);
    setCat(c);
    if (list.length === 0) return;
    if (!list.some((n) => n.id === selectedId)) setSelectedId(list[0].id);
  };

  const catNav = useArrowNav<Cat, HTMLUListElement>({
    items: CATS,
    getKey: (c) => c,
    current: cat,
    setCurrent: (c) => ensureSelectionInCat(c as Cat),
  });

  const modal = useModal();
  const expand = () =>
    selected && modal.open((c) => <StoryReaderModal item={selected} close={c} />);

  const related = useMemo(() => {
    if (!selected) return [];
    // Stories that share at least one symbol or are in the same category,
    // excluding the selected one. Capped at 8.
    const sharesSymbol = (n: NewsItem) =>
      !!n.symbols &&
      !!selected.symbols &&
      n.symbols.some((s) => selected.symbols!.includes(s));
    const scored = newsItems.filter((n) => n.id !== selected.id).map((n) => ({
      n,
      score:
        (sharesSymbol(n) ? 3 : 0) + (n.cat === selected.cat ? 1 : 0),
    }));
    scored.sort((a, b) => b.score - a.score);
    return scored.filter((s) => s.score > 0).map((s) => s.n).slice(0, 8);
  }, [newsItems, selected]);

  if (!selected) {
    return (
      <div className="col-span-12 flex min-h-0 items-center justify-center border border-term-border bg-term-panel text-[11px] uppercase text-term-dim">
        No news available.
      </div>
    );
  }

  return (
    <>
      <div className="col-span-2 flex min-h-0">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
          <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-2 py-[2px] text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
            <span><span className="mr-2">1)</span>Categories</span>
            <span className="text-[10px]">
              <DatasetRight datasetKey="news" fallback={`${newsItems.length} TOTAL`} />
            </span>
          </header>
          <ul
            ref={catNav.ref}
            tabIndex={catNav.tabIndex}
            onClick={catNav.onClick}
            onKeyDown={catNav.onKeyDown}
            className="min-h-0 flex-1 overflow-auto text-[12px] outline-none"
          >
            {CATS.map((c, i) => (
              <li key={c} data-nav-key={c}>
                <button
                  onClick={() => ensureSelectionInCat(c)}
                  className={`flex w-full items-center justify-between border-b border-term-border/60 px-3 py-2 text-left hover:bg-term-accent/10 ${
                    c === cat
                      ? "bg-term-accent/15 text-term-accent-hi"
                      : "text-term-text"
                  }`}
                >
                  <span className="uppercase">
                    <span className="mr-2 text-term-dim">{i + 1})</span>
                    {c}
                  </span>
                  <span className="tabular-nums text-term-dim">
                    {newsItems.filter((n) => c === "TOP" || n.cat === c).length}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <RssSourcePanel feeds={rssFeeds} />
        </div>
      </div>

      <div className="col-span-5 flex min-h-0">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
          <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-2 py-[2px] text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
            <span><span className="mr-2">2)</span>News Wire — {cat}</span>
            <span className="text-[10px]">
              <DatasetRight datasetKey="news" fallback={`${filtered.length} STORIES`} />
            </span>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">
            <NewsFeed
              items={filtered}
              selectedId={selected.id}
              onSelect={(n) => setSelectedId(n.id)}
            />
          </div>
        </div>
      </div>

      <div
        className="col-span-5 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.6fr) minmax(0, 1fr)" }}
      >
        <div className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
          <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-2 py-[2px] text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
            <span>
              <span className="mr-2">3)</span>Selected Story
            </span>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-term-on-accent/70">
                <DatasetRight datasetKey="news" fallback={`${selected.src} · ${selected.time} ET`} />
              </span>
              <button
                onClick={expand}
                className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
                title="Expand to full-screen reader"
              >
                EXPAND ↗
              </button>
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-hidden">
            <StoryReader item={selected} compact />
          </div>
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col border border-term-border bg-term-panel">
          <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-2 py-[2px] text-[11px] font-semibold uppercase tracking-wider text-term-on-accent">
            <span>
              <span className="mr-2">4)</span>Related Stories
            </span>
            <span className="text-[10px]">
              <DatasetRight datasetKey="news" fallback={`SAME CAT/SYMBOL · ${related.length}`} />
            </span>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">
            {related.length > 0 ? (
              <NewsFeed
                items={related}
                selectedId={selected.id}
                onSelect={(n) => setSelectedId(n.id)}
                dense
              />
            ) : (
              <div className="p-3 text-[11px] uppercase text-term-dim">
                No related stories for this item.
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
