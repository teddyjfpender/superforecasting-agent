import { useState } from "react";
import { fmt, fmtSigned, pad, useArrowNav } from "./components";
import { dataSourceDisplayLabel, type Quote } from "./data";
import {
  AddSymbolModal,
  NewWatchlistModal,
  useModal,
} from "./modals";
import {
  symbolPassesFilter,
  useActiveFilter,
  useActiveSymbol,
  useQuoteList,
  useTickFlash,
  useWatchlists,
} from "./providers";

const sourceClass = (source: Quote["source"]) => {
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
   Watchlist selector — pills with click-to-switch, double-click to rename,
   + NEW, and a DELETE button on the active one (refuses to remove the last).
   ──────────────────────────────────────────────────────────────────────────── */

export function WatchlistBar() {
  const { watchlists, activeId, readOnly, setActive, rename, remove } = useWatchlists();
  const modal = useModal();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const commit = () => {
    if (editingId && draft.trim()) rename(editingId, draft.trim());
    setEditingId(null);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 items-center gap-1 overflow-x-auto px-2 py-1 text-[11px] uppercase">
      <span className="shrink-0 text-term-dim">WATCHLIST ▸</span>
      {watchlists.map((w) => {
        const isActive = w.id === activeId;
        const isEditing = editingId === w.id;
        if (isEditing) {
          return (
            <input
              key={w.id}
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit();
                if (e.key === "Escape") {
                  setEditingId(null);
                  setDraft("");
                }
              }}
              maxLength={40}
              className="w-40 border border-term-accent bg-term-bg px-2 py-[2px] text-term-accent-hi outline-none"
              spellCheck={false}
            />
          );
        }
        return (
          <button
            key={w.id}
            onClick={() => setActive(w.id)}
            onDoubleClick={() => {
              if (readOnly) return;
              setEditingId(w.id);
              setDraft(w.name);
            }}
            className={`shrink-0 border px-2 py-[2px] uppercase ${
              isActive
                ? "border-term-accent bg-term-accent text-term-on-accent"
                : "border-term-border-hi text-term-text hover:border-term-accent hover:bg-term-accent/10"
            }`}
            title={readOnly ? "Backend read-only watchlist" : "Double-click to rename"}
          >
            {w.name}
          </button>
        );
      })}
      {!readOnly && (
        <button
          onClick={() => modal.open((c) => <NewWatchlistModal close={c} />)}
          className="shrink-0 border border-term-border-hi px-2 py-[2px] text-term-accent hover:border-term-accent hover:bg-term-accent/10"
        >
          + NEW
        </button>
      )}
      {watchlists.length > 1 && !readOnly && (
        <button
          onClick={() => {
            const active = watchlists.find((w) => w.id === activeId);
            if (!active) return;
            // eslint-disable-next-line no-alert
            const ok = window.confirm(
              `Delete watchlist "${active.name}"? Cannot be undone.`,
            );
            if (ok) remove(active.id);
          }}
          className="shrink-0 border border-term-border-hi px-2 py-[2px] text-term-red hover:border-term-red hover:bg-term-red/10"
          title="Delete active watchlist"
        >
          DELETE
        </button>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Editable watchlist table — same columns as the read-only Watchlist used
   elsewhere, plus a trailing ✕ column and an inline "+ ADD SYMBOL" footer.
   ──────────────────────────────────────────────────────────────────────────── */

export function EditableWatchlist() {
  const allRows = useQuoteList("watchlist");
  const [filter] = useActiveFilter();
  const rows = allRows.filter((r) => symbolPassesFilter(r.ticker, filter));
  const filteredOut = allRows.length - rows.length;
  const { watchlists, activeId, readOnly, removeSymbol } = useWatchlists();
  const [activeSym, setActiveSym] = useActiveSymbol();
  const nav = useArrowNav<Quote, HTMLTableElement>({
    items: rows,
    getKey: (q) => q.ticker,
    current: activeSym,
    setCurrent: setActiveSym,
  });
  const modal = useModal();
  const active = watchlists.find((w) => w.id === activeId);
  if (!active) return null;
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
          <th className="px-2 py-[3px] text-left font-normal uppercase">#</th>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Ticker</th>
          <th className="px-2 py-[3px] text-left font-normal uppercase">Security</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Bid</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Ask</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Last</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Chg</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">%Chg</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">Vol</th>
          <th className="px-2 py-[3px] text-right font-normal uppercase">
            {readOnly ? "Src" : " "}
          </th>
        </tr>
        <tr><th colSpan={10} className="border-b border-term-border p-0" /></tr>
      </thead>
      <tbody>
        {rows.map((q, i) => (
          <WatchlistRowEditable
            key={q.ticker}
            q={q}
            idx={i}
            readOnly={readOnly}
            onRemove={() => removeSymbol(active.id, q.ticker)}
          />
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={10} className="px-3 py-6 text-center text-[12px] uppercase text-term-dim">
              {filteredOut > 0
                ? `Filter hides every symbol in ${active.name} (${filteredOut} hidden). Clear the lens to see them.`
                : readOnly
                  ? <>No backend symbols in {active.name}.</>
                  : <>No symbols in {active.name}. Click{" "}<span className="text-term-accent">+ ADD SYMBOL</span> below.</>
              }
            </td>
          </tr>
        )}
        {rows.length > 0 && filteredOut > 0 && (
          <tr>
            <td colSpan={10} className="border-b border-term-border/60 bg-term-accent/5 px-2 py-1 text-[10px] uppercase text-term-dim">
              ▸ Lens hides <span className="text-term-cyan">{filteredOut}</span> row{filteredOut === 1 ? "" : "s"} not matching the active filter.
            </td>
          </tr>
        )}
        {!readOnly && (
          <tr>
            <td colSpan={10} className="px-2 py-2">
              <button
                onClick={() =>
                  modal.open((c) => (
                    <AddSymbolModal
                      watchlistId={active.id}
                      watchlistName={active.name}
                      close={c}
                    />
                  ))
                }
                className="border border-term-accent bg-term-accent/10 px-3 py-1 text-[11px] uppercase text-term-accent-hi hover:bg-term-accent/20"
              >
                + ADD SYMBOL
              </button>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function WatchlistRowEditable({
  q,
  idx,
  readOnly,
  onRemove,
}: {
  q: Quote;
  idx: number;
  readOnly: boolean;
  onRemove: () => void;
}) {
  const [active, setActive] = useActiveSymbol();
  const isActive = active === q.ticker;
  const unavailable = q.source?.kind === "unavailable";
  const flash = useTickFlash(q.last);
  const pos = q.chg >= 0;
  const flashClass =
    flash === "up" ? "cell-flash-up" : flash === "down" ? "cell-flash-down" : "";
  return (
    <tr
      data-nav-key={q.ticker}
      className={`cursor-pointer border-b border-term-border/60 hover:bg-term-accent/10 ${
        isActive ? "row-active" : ""
      }`}
    >
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-term-dim">
        {pad(idx + 1, 2, true)}
      </td>
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-term-accent-hi">
        {q.ticker}
      </td>
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-term-text">
        {q.name}
      </td>
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-right text-term-text">
        {unavailable ? "N/A" : fmt(q.bid, 2)}
      </td>
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-right text-term-text">
        {unavailable ? "N/A" : fmt(q.ask, 2)}
      </td>
      <td
        onClick={() => setActive(q.ticker)}
        className={`px-2 py-[3px] text-right text-term-accent-hi ${flashClass}`}
      >
        {unavailable ? "N/A" : fmt(q.last, 2)}
      </td>
      <td
        onClick={() => setActive(q.ticker)}
        className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}
      >
        {unavailable ? "-" : fmtSigned(q.chg, 2)}
      </td>
      <td
        onClick={() => setActive(q.ticker)}
        className={`px-2 py-[3px] text-right ${unavailable ? "text-term-dim" : pos ? "text-term-green" : "text-term-red"}`}
      >
        {unavailable ? "-" : `${pos ? "▲" : "▼"} ${fmtSigned(q.pct, 2)}%`}
      </td>
      <td onClick={() => setActive(q.ticker)} className="px-2 py-[3px] text-right text-term-text">
        {unavailable ? "N/A" : q.vol}
      </td>
      <td className="px-2 py-[3px] text-right">
        {readOnly ? (
          <span className={sourceClass(q.source)}>{dataSourceDisplayLabel(q.source)}</span>
        ) : (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="border border-term-border-hi px-1.5 py-[1px] text-[10px] text-term-dim hover:border-term-red hover:bg-term-red/10 hover:text-term-red"
            title="Remove symbol"
          >
            ✕
          </button>
        )}
      </td>
    </tr>
  );
}
