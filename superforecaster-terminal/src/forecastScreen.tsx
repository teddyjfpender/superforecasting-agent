// SF · SUPERFORECASTER DESK
//
// The web-terminal surface for the Superforecasting Agent. Structured like the
// NEWS screen's progressive disclosure: a narrow DOMAIN filter (1) → the
// scannable forecast BOOK (2) → a focused READ that leads with the headline
// trend (3) and discloses the analyst read + deeper sections on demand (4).
//
// Everything renders from the single /forecast/workspace payload (one round
// trip). Pure formatting + the color/tag system live in forecastFormat.ts; the
// trend chart is the dedicated SfTrendChart (fits its box + draws the 90% band).

import { useEffect, useMemo, useState } from "react";
import { Panel, useArrowNav } from "./components";
import { useModal } from "./modals";
import { useForecastWorkspace } from "./forecastProvider";
import { SfTrendChart } from "./sfTrendChart";
import {
  ANALYST_ANGLES,
  RELATIONSHIP_TAG,
  STANCE_LABEL,
  bandChart,
  chartScale,
  compactNumber,
  deltaLabel,
  distributionBars,
  domainTag,
  evidenceStanceClass,
  headlineCompact,
  headlineLabel,
  histogram,
  historyToBandPoints,
  matchesFilter,
  pct,
  shortDate,
  stanceTag,
  verdictTag,
} from "./forecastFormat";
import type {
  ForecastAnalystNote,
  ForecastRelatedView,
  ForecastWorkspaceEvidence,
  ForecastWorkspaceItem,
  TagStyle,
} from "./forecastFormat";

/* ── helpers ─────────────────────────────────────────────────────────────── */

function unitSuffixFor(item: ForecastWorkspaceItem): string {
  const u = (item.units ?? "").toLowerCase();
  return u.includes("percent") || u.includes("%") ? "%" : "";
}

const deltaClass = (d?: number | null): string =>
  d == null || Math.abs(d) < 1e-9 ? "text-term-dim" : d > 0 ? "text-term-green" : "text-term-red";

function impactStyle(impact: string): TagStyle {
  const i = impact.toLowerCase();
  if (i.includes("high") || i.includes("crit"))
    return { text: "text-term-red", chip: "border-term-red/50 bg-term-red/10" };
  if (i.includes("med")) return { text: "text-term-yellow", chip: "border-term-yellow/50 bg-term-yellow/10" };
  return { text: "text-term-dim", chip: "border-term-border-hi" };
}

/* ── presentational atoms ────────────────────────────────────────────────── */

function Tag({
  label,
  tone = "dim",
  style,
}: {
  label: string;
  tone?: "dim" | "accent" | "warn";
  style?: TagStyle;
}) {
  const cls = style
    ? `${style.text} ${style.chip}`
    : tone === "warn"
      ? "border-term-yellow/60 text-term-yellow"
      : tone === "accent"
        ? "border-term-accent/60 text-term-accent-hi"
        : "border-term-border-hi text-term-dim";
  return <span className={`inline-block border px-1 text-[10px] uppercase ${cls}`}>{label}</span>;
}

function KvCell({ k, v, cls = "text-term-accent-hi" }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-start justify-center border-l border-term-border px-3 py-1 first:border-l-0">
      <span className="text-[10px] uppercase text-term-dim">{k}</span>
      <span className={`truncate tabular-nums text-[12px] ${cls}`}>{v}</span>
    </div>
  );
}

function Collapsible({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-3 first:mt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 border-b border-term-border pb-[2px] text-left text-[10px] uppercase tracking-wider text-term-accent hover:text-term-accent-hi"
      >
        <span className="w-2 text-term-dim">{open ? "▾" : "▸"}</span>
        <span className="font-semibold">{title}</span>
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

function ExpandButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
      title="Expand to full-screen read"
    >
      EXPAND ↗
    </button>
  );
}

/* ── left: domain filter rows ────────────────────────────────────────────── */

function DomainRow({
  name,
  count,
  active,
  swatch,
  onSelect,
}: {
  name: string;
  count: number;
  active: boolean;
  swatch: string;
  onSelect: () => void;
}) {
  return (
    <li
      data-nav-key={name}
      onClick={onSelect}
      className={`flex cursor-pointer items-center justify-between border-b border-term-border/60 px-3 py-2 text-[12px] ${
        active ? "bg-term-accent/15 text-term-accent-hi" : "text-term-text hover:bg-term-accent/10"
      }`}
    >
      <span className="flex min-w-0 items-center gap-2 uppercase">
        <span className={`inline-block h-2 w-2 shrink-0 bg-current ${swatch}`} />
        <span className="truncate">{name}</span>
      </span>
      <span className="shrink-0 tabular-nums text-term-dim">{count}</span>
    </li>
  );
}

/* ── center: scannable book rows (NewsFeed model) ────────────────────────── */

function DeskRow({
  item,
  active,
  onSelect,
}: {
  item: ForecastWorkspaceItem;
  active: boolean;
  onSelect: () => void;
}) {
  const alerts = item.open_alert_count ?? 0;
  const dt = domainTag(item.domain);
  return (
    <li
      data-nav-key={item.id ?? item.title ?? ""}
      onClick={onSelect}
      className={`flex cursor-pointer items-center gap-2 border-b border-term-border/60 px-2 py-1.5 ${
        active ? "row-active" : "hover:bg-term-accent/10"
      }`}
    >
      <span
        className={`min-w-[3.5rem] shrink-0 tabular-nums text-[12px] ${
          active ? "text-term-accent-hi" : "text-term-accent"
        }`}
      >
        {headlineCompact(item)}
      </span>
      <span className={`w-14 shrink-0 truncate text-[10px] uppercase ${dt.text}`} title={item.domain ?? ""}>
        {item.domain ?? "—"}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-term-text">{item.title || item.id || "—"}</span>
      <span className={`shrink-0 tabular-nums text-[11px] ${deltaClass(item.delta)}`}>{deltaLabel(item)}</span>
      {alerts > 0 && (
        <span className="shrink-0 border border-term-yellow px-1 text-[10px] font-semibold text-term-yellow">
          ▲{alerts}
        </span>
      )}
      {item.closing_soon && <span className="shrink-0 text-[10px] font-semibold text-term-red">CLOSE</span>}
    </li>
  );
}

/* ── right (3): headline strip + trend chart ─────────────────────────────── */

function TrendBlock({ item }: { item: ForecastWorkspaceItem }) {
  const points = useMemo(() => historyToBandPoints(item), [item]);
  const series = points.map((p) => p.y).filter((v): v is number => v != null);
  const isDist = item.headline_kind === "distribution";
  const dates = (item.history ?? []).map((h) => h.as_of).filter(Boolean) as string[];
  const xLabels = dates.length
    ? [shortDate(dates[0]), shortDate(dates[Math.floor(dates.length / 2)]), shortDate(dates[dates.length - 1])]
    : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-term-border px-3 py-1.5 text-[12px]">
        <span className="text-term-accent-hi">{headlineLabel(item)}</span>
        <span className={`tabular-nums ${deltaClass(item.delta)}`}>{deltaLabel(item)}</span>
        <span className="text-[10px] uppercase text-term-dim">conf</span>
        <span className="tabular-nums text-term-text">{item.confidence != null ? pct(item.confidence) : "—"}</span>
        <span className="ml-auto text-[10px] uppercase text-term-dim">{item.freshness ?? shortDate(item.as_of)}</span>
      </div>
      <div className="min-h-0 flex-1">
        {series.length >= 2 ? (
          <SfTrendChart
            points={points}
            xLabels={xLabels}
            formatY={isDist ? (v) => `${compactNumber(v)}${unitSuffixFor(item)}` : (v) => pct(v)}
            yLabel={isDist ? (item.units ?? "μ") : "P"}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] uppercase text-term-dim">
            awaiting a second snapshot for a trend
          </div>
        )}
      </div>
    </div>
  );
}

/* ── right (4): the analyst read + disclosed sections ────────────────────── */

function QuickRead({ note }: { note: ForecastAnalystNote }) {
  const retro = note.kind === "retrospective";
  return (
    <div className="space-y-2 text-[12px]">
      {note.headline && <div className="font-semibold leading-snug text-term-accent-hi">{note.headline}</div>}
      <div className="flex flex-wrap gap-1">
        {retro && <Tag label="retrospective" tone="warn" />}
        {note.stance && <Tag label={STANCE_LABEL[note.stance] ?? note.stance} style={stanceTag(note.stance)} />}
        {note.verdict && <Tag label={`verdict ${note.verdict}`} style={verdictTag(note.verdict)} />}
      </div>
      {ANALYST_ANGLES.map((angle) => {
        const text = note[angle.key];
        if (!text) return null;
        return (
          <div key={angle.key} className="leading-snug">
            <span
              className={`mr-2 text-[10px] uppercase ${angle.warn ? "text-term-yellow" : "text-term-accent/80"}`}
            >
              {angle.label}
            </span>
            <span className="text-term-text">{text}</span>
          </div>
        );
      })}
      {retro && note.body && <div className="leading-snug text-term-text">{note.body}</div>}
    </div>
  );
}

function IntervalReadout({ item }: { item: ForecastWorkspaceItem }) {
  const dist = item.distribution;
  if (!dist) return null;
  const suffix = unitSuffixFor(item);
  const span = (pair?: number[] | null): string =>
    Array.isArray(pair) && pair.length === 2
      ? `${compactNumber(pair[0])}${suffix} – ${compactNumber(pair[1])}${suffix}`
      : "—";
  return (
    <div className="flex flex-wrap items-stretch border border-term-border">
      <KvCell k="median" v={`${compactNumber(dist.median)}${suffix}`} />
      <KvCell k="mean" v={`${compactNumber(dist.mean)}${suffix}`} />
      <KvCell k="σ" v={compactNumber(dist.sd)} cls="text-term-text" />
      <KvCell k="50% CI" v={span(dist.ci50)} cls="text-term-text" />
      <KvCell k="90% CI" v={span(dist.ci90)} cls="text-term-text" />
    </div>
  );
}

function RelatedRow({ view, onJump }: { view: ForecastRelatedView; onJump: (id: string) => void }) {
  const tag = view.relationship ? RELATIONSHIP_TAG[view.relationship] : undefined;
  const jumpable = Boolean(view.id);
  return (
    <button
      onClick={() => view.id && onJump(view.id)}
      disabled={!jumpable}
      className={`flex w-full items-baseline gap-2 border-b border-term-border/60 px-2 py-[3px] text-left text-[11px] last:border-b-0 ${
        jumpable ? "cursor-pointer hover:bg-term-accent/10" : "cursor-default"
      }`}
    >
      <span className="w-14 shrink-0 text-[10px] uppercase text-term-cyan">
        {tag ? `${tag.glyph} ${tag.label}` : view.link_type ?? "rel"}
      </span>
      <span className="min-w-0 flex-1 truncate text-term-text">{view.title || view.id}</span>
      <span className="shrink-0 tabular-nums text-term-accent-hi">
        {view.probability_display ?? (view.headline_probability != null ? pct(view.headline_probability) : "—")}
      </span>
    </button>
  );
}

function ReasonList({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div className="mb-2">
      <div className={`text-[10px] uppercase ${tone}`}>{label}</div>
      <ul className="ml-3 list-disc text-[11px] leading-snug text-term-text marker:text-term-dim">
        {items.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceRow({ e }: { e: ForecastWorkspaceEvidence }) {
  const stanceCls = evidenceStanceClass(e.stance);
  return (
    <div className="border-l-2 border-term-border pl-2 text-[11px] leading-snug">
      <span className="mr-2 text-[10px] uppercase text-term-dim">{e.source ?? e.source_type ?? "src"}</span>
      {e.stance && <span className={`mr-2 text-[10px] uppercase ${stanceCls ?? "text-term-dim"}`}>{e.stance}</span>}
      <span className="text-term-text">{e.summary ?? e.claim ?? "—"}</span>
    </div>
  );
}

function DeskReadBlock({ item, onJump }: { item: ForecastWorkspaceItem; onJump: (id: string) => void }) {
  const note = item.analyst_note ?? item.analyst_notes?.[item.analyst_notes.length - 1] ?? null;
  const isDist = item.headline_kind === "distribution";
  const points = useMemo(() => historyToBandPoints(item), [item]);
  const scale = useMemo(() => chartScale(points), [points]);
  const band = useMemo(
    () => bandChart(points, { yMin: scale.yMin, yMax: scale.yMax, width: 56, height: 7 }),
    [points, scale],
  );
  const hasSeries = points.filter((p) => p.y != null).length >= 2;
  const pmfBars =
    item.distribution?.pmf?.map((p) => ({ label: p.label, value: p.probability })) ??
    distributionBars(item.probability) ??
    [];
  const related = item.related?.forecasts ?? [];
  const sharedSources = item.related?.shared_sources ?? [];
  const evidence = (item.evidence ?? []).slice(-6).reverse();
  const scores = item.scores;
  const resolution = item.resolution;
  const hasReasoning = Boolean(
    item.reasons_up?.length || item.reasons_down?.length || item.change_my_mind?.length,
  );

  return (
    <div className="px-3 py-2 text-[12px]">
      {/* domain / impact / counts strip */}
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {item.domain && <Tag label={item.domain} style={domainTag(item.domain)} />}
        {item.impact && <Tag label={`impact ${item.impact}`} style={impactStyle(item.impact)} />}
        <span className="ml-auto text-[10px] uppercase text-term-dim">
          {item.evidence_count ?? evidence.length} evid · {item.snapshot_count ?? item.history?.length ?? 0} snaps
        </span>
      </div>

      {/* lead: the analyst quick read (always visible) */}
      {note ? (
        <QuickRead note={note} />
      ) : (
        <div className="text-[11px] uppercase text-term-dim">no analyst note yet</div>
      )}

      {/* topics */}
      {(item.topics?.length ?? 0) > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {item.topics!.slice(0, 10).map((t) => (
            <Tag key={t} label={t} />
          ))}
        </div>
      )}

      {isDist && (
        <div className="mt-3">
          <IntervalReadout item={item} />
        </div>
      )}

      {pmfBars.length > 0 && (
        <Collapsible title="Outcome Distribution" defaultOpen>
          <pre className="overflow-x-auto text-[11px] leading-tight text-term-text">
            {histogram(pmfBars, { width: 26, labelWidth: 18 }).join("\n")}
          </pre>
        </Collapsible>
      )}

      {related.length > 0 && (
        <Collapsible title={`Related · Cross-Pollination (${related.length})`} defaultOpen>
          <div className="border border-term-border">
            {related.map((v) => (
              <RelatedRow key={v.id ?? v.title} view={v} onJump={onJump} />
            ))}
          </div>
          {sharedSources.length > 0 && (
            <div className="mt-1 text-[10px] uppercase leading-snug text-term-yellow">
              ⚠ shared evidence (non-independent):{" "}
              {sharedSources
                .map((s) => s.source)
                .filter(Boolean)
                .join(" · ")}
            </div>
          )}
        </Collapsible>
      )}

      {hasReasoning && (
        <Collapsible title="Reasoning" defaultOpen>
          <ReasonList label="reasons up" items={item.reasons_up ?? []} tone="text-term-green" />
          <ReasonList label="reasons down" items={item.reasons_down ?? []} tone="text-term-red" />
          <ReasonList label="change my mind" items={item.change_my_mind ?? []} tone="text-term-cyan" />
        </Collapsible>
      )}

      {evidence.length > 0 && (
        <Collapsible title={`Recent Evidence (${evidence.length})`}>
          <div className="space-y-1">
            {evidence.map((e, i) => (
              <EvidenceRow key={e.id ?? i} e={e} />
            ))}
          </div>
        </Collapsible>
      )}

      {(scores || resolution) && (
        <Collapsible title="Calibration">
          <div className="flex flex-wrap items-stretch border border-term-border">
            <KvCell k="scored" v={String(scores?.count ?? 0)} cls="text-term-text" />
            <KvCell k="mean brier" v={scores?.mean_brier != null ? scores.mean_brier.toFixed(3) : "—"} />
            <KvCell
              k="last bucket"
              v={(scores?.last_bucket ?? "—").toUpperCase()}
              cls={verdictTag(scores?.last_bucket).text}
            />
            <KvCell
              k="resolution"
              v={(resolution?.resolution_status ?? "unresolved").toUpperCase()}
              cls="text-term-text"
            />
          </div>
        </Collapsible>
      )}

      {hasSeries && band.rows.length > 0 && (
        <Collapsible title="Confidence Band · ASCII">
          <pre className="overflow-x-auto text-[11px] leading-tight text-term-accent">{band.rows.join("\n")}</pre>
        </Collapsible>
      )}
    </div>
  );
}

/* ── full-screen read (EXPAND) ───────────────────────────────────────────── */

function ForecastDetailModal({ item, close }: { item: ForecastWorkspaceItem; close: () => void }) {
  return (
    <>
      <header className="flex shrink-0 items-center justify-between border-b border-term-border bg-term-accent px-3 py-1 text-[12px] font-semibold uppercase tracking-wider text-term-on-accent">
        <span>FORECAST ▸ {item.title || item.id}</span>
        <button
          onClick={close}
          className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
        >
          ESC
        </button>
      </header>
      <div
        className="grid min-h-0 flex-1 gap-px bg-term-border"
        style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}
      >
        <div className="flex min-h-0 flex-col border border-term-border bg-term-panel">
          <div className="min-h-0 flex-1">
            <TrendBlock item={item} />
          </div>
        </div>
        <div className="min-h-0 overflow-auto border border-term-border bg-term-panel">
          <DeskReadBlock item={item} onJump={() => {}} />
        </div>
      </div>
    </>
  );
}

/* ── empty state ─────────────────────────────────────────────────────────── */

function EmptyBook({ enabled, query }: { enabled: boolean; query: string }) {
  return (
    <div className="px-2 py-4 text-[11px] uppercase leading-relaxed text-term-dim">
      {!enabled ? (
        <>
          forecast bridge is not running. start it with:
          <br />
          <span className="text-term-accent">bun run dev:sf</span>
          <br />
          or <span className="text-term-accent">python3 -m forecasting.webbridge</span>
        </>
      ) : query ? (
        "no forecasts match this filter"
      ) : (
        "awaiting forecast feed…"
      )}
    </div>
  );
}

/* ── the screen ──────────────────────────────────────────────────────────── */

export function ForecastScreen() {
  const { payload, source, enabled } = useForecastWorkspace();
  const forecasts = payload.forecasts;
  const modal = useModal();
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("ALL");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const domains = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of forecasts) {
      const d = (f.domain ?? "other").toLowerCase();
      counts.set(d, (counts.get(d) ?? 0) + 1);
    }
    const list = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));
    return [{ name: "ALL", count: forecasts.length }, ...list];
  }, [forecasts]);

  const inDomain = (f: ForecastWorkspaceItem, d: string) =>
    d === "ALL" || (f.domain ?? "other").toLowerCase() === d;

  const filtered = useMemo(
    () => forecasts.filter((f) => matchesFilter(f, query) && inDomain(f, domain)),
    [forecasts, query, domain],
  );
  const selected = filtered.find((f) => f.id === selectedId) ?? filtered[0] ?? null;

  // keep the selection inside the active filter
  useEffect(() => {
    if (filtered.length && !filtered.some((f) => f.id === selectedId)) {
      setSelectedId(filtered[0].id ?? null);
    }
  }, [filtered, selectedId]);

  const ensureSelectionInDomain = (d: string) => {
    setDomain(d);
    const list = forecasts.filter((f) => matchesFilter(f, query) && inDomain(f, d));
    if (list.length && !list.some((f) => f.id === selectedId)) setSelectedId(list[0].id ?? null);
  };

  const domainNav = useArrowNav<string, HTMLUListElement>({
    items: domains.map((d) => d.name),
    getKey: (d) => d,
    current: domain,
    setCurrent: ensureSelectionInDomain,
  });
  const bookNav = useArrowNav<ForecastWorkspaceItem, HTMLUListElement>({
    items: filtered,
    getKey: (f) => f.id ?? f.title ?? "",
    current: selectedId,
    setCurrent: (id) => setSelectedId(id),
  });

  const sourceRight = !enabled
    ? "BRIDGE OFFLINE"
    : source.kind === "live"
      ? `LIVE · ${shortDate(source.generatedAt ?? payload.generated_at)}`
      : "CONNECTING";

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      {/* 1) domains */}
      <div className="col-span-2 flex min-h-0">
        <Panel id={1} title="Domains" right={`${forecasts.length} BOOK`}>
          <ul
            ref={domainNav.ref}
            tabIndex={domainNav.tabIndex}
            onClick={domainNav.onClick}
            onKeyDown={domainNav.onKeyDown}
            className="outline-none"
          >
            {domains.map((d) => (
              <DomainRow
                key={d.name}
                name={d.name}
                count={d.count}
                active={domain === d.name}
                swatch={d.name === "ALL" ? "text-term-accent" : domainTag(d.name).text}
                onSelect={() => ensureSelectionInDomain(d.name)}
              />
            ))}
          </ul>
        </Panel>
      </div>

      {/* 2) book */}
      <div className="col-span-5 flex min-h-0 flex-col gap-px bg-term-border">
        <div className="flex shrink-0 items-center gap-2 border border-term-border bg-term-panel px-2 py-1 text-[11px] uppercase">
          <span className="text-term-accent">FIND</span>
          <span className="text-term-dim">▸</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="TITLE / DOMAIN / TOPIC"
            className="min-w-0 flex-1 bg-transparent text-term-accent-hi placeholder-term-muted outline-none"
            spellCheck={false}
          />
          <span className="shrink-0 tabular-nums text-term-dim">
            {filtered.length}/{forecasts.length}
          </span>
        </div>
        <Panel id={2} title={`Forecast Book — ${domain}`} right={sourceRight}>
          {filtered.length === 0 ? (
            <EmptyBook enabled={enabled} query={query} />
          ) : (
            <ul
              ref={bookNav.ref}
              tabIndex={bookNav.tabIndex}
              onClick={bookNav.onClick}
              onKeyDown={bookNav.onKeyDown}
              className="outline-none"
            >
              {filtered.map((item) => (
                <DeskRow
                  key={item.id ?? item.title}
                  item={item}
                  active={selected?.id === item.id}
                  onSelect={() => item.id && setSelectedId(item.id)}
                />
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {/* 3) trend  +  4) read */}
      <div
        className="col-span-5 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.6fr) minmax(0, 1fr)" }}
      >
        {selected ? (
          <>
            <div className="flex min-h-0">
              <Panel
                id={3}
                title="Headline Trend"
                right={
                  selected.headline_kind === "distribution"
                    ? `MEAN · ${(selected.units ?? "UNITS").toUpperCase()}`
                    : "PROBABILITY"
                }
              >
                <TrendBlock item={selected} />
              </Panel>
            </div>
            <div className="flex min-h-0">
              <Panel
                id={4}
                title={selected.title || selected.id || "DESK READ"}
                right={<ExpandButton onClick={() => modal.open((c) => <ForecastDetailModal item={selected} close={c} />)} />}
              >
                <DeskReadBlock key={selected.id} item={selected} onJump={(id) => setSelectedId(id)} />
              </Panel>
            </div>
          </>
        ) : (
          <div className="row-span-2 flex min-h-0">
            <Panel id={3} title="Forecast Detail" right="SF">
              <div className="flex h-full items-center justify-center text-[11px] uppercase text-term-dim">
                {enabled ? "select a forecast" : "forecast bridge offline"}
              </div>
            </Panel>
          </div>
        )}
      </div>
    </div>
  );
}
