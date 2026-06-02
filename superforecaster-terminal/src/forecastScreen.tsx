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
import { abbreviateSource } from "./data";
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
  shortUnit,
  stanceTag,
  verdictTag,
} from "./forecastFormat";
import type {
  ForecastAnalystNote,
  ForecastRelatedView,
  ForecastThesis,
  ForecastThesisComponent,
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

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 mb-1 border-b border-term-border pb-[2px] text-[10px] uppercase tracking-wider text-term-accent first:mt-2">
      {children}
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
            yLabel={isDist ? shortUnit(item.units) || "μ" : "P"}
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
      <span className="mr-2 whitespace-nowrap text-[10px] uppercase text-term-dim">
        {abbreviateSource(e.source ?? e.source_type ?? "src")}
      </span>
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

/* ── thesis lens (left-column filter + the thesis read) ──────────────────── */

const directionStyle = (direction?: string): TagStyle =>
  direction === "inverted"
    ? { text: "text-term-red", chip: "border-term-red/50 bg-term-red/10" }
    : { text: "text-term-green", chip: "border-term-green/50 bg-term-green/10" };

const healthClass = (health?: number | null): string =>
  health == null
    ? "text-term-dim"
    : health >= 0.6
      ? "text-term-green"
      : health >= 0.45
        ? "text-term-yellow"
        : "text-term-red";

function ThesisRow({
  thesis,
  active,
  onSelect,
}: {
  thesis: ForecastThesis;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li
      data-nav-key={thesis.id ?? thesis.title ?? ""}
      onClick={onSelect}
      className={`flex cursor-pointer items-center gap-2 border-b border-term-border/60 px-2 py-1.5 ${
        active ? "row-active" : "hover:bg-term-accent/10"
      }`}
    >
      <span className={`min-w-[2.5rem] shrink-0 tabular-nums text-[12px] ${healthClass(thesis.health_probability)}`}>
        {thesis.health_display ?? "—"}
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-term-accent-hi">{thesis.title || thesis.id}</span>
      <span className="shrink-0 tabular-nums text-[10px] text-term-dim">
        {thesis.member_count ?? thesis.components?.length ?? 0}
      </span>
    </li>
  );
}

function ThesisTrendBlock({ thesis }: { thesis: ForecastThesis }) {
  const points = (thesis.history ?? []).map((h) => ({ y: h.headline_probability ?? null, lo: null, hi: null }));
  const series = points.filter((p) => p.y != null);
  const dates = (thesis.history ?? []).map((h) => h.as_of).filter(Boolean) as string[];
  const xLabels = dates.length
    ? [shortDate(dates[0]), shortDate(dates[Math.floor(dates.length / 2)]), shortDate(dates[dates.length - 1])]
    : undefined;
  const band = thesis.score_band;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-term-border px-3 py-1.5 text-[12px]">
        <span className={`tabular-nums ${healthClass(thesis.health_probability)}`}>health {thesis.health_display ?? "—"}</span>
        <span className={`tabular-nums ${deltaClass(thesis.delta)}`}>
          {thesis.delta != null ? `${thesis.delta >= 0 ? "▲" : "▼"} ${(thesis.delta * 100).toFixed(0)}pp` : "· flat"}
        </span>
        <span className="text-[10px] uppercase text-term-dim">score</span>
        <span className="tabular-nums text-term-text">
          {thesis.thesis_score != null ? thesis.thesis_score.toFixed(0) : "—"}
          {band && band.q05 != null && band.q95 != null ? ` (${band.q05.toFixed(0)}–${band.q95.toFixed(0)})` : ""}
        </span>
        <span className="ml-auto text-[10px] uppercase text-term-dim">{thesis.freshness ?? shortDate(thesis.as_of)}</span>
      </div>
      <div className="min-h-0 flex-1">
        {series.length >= 2 ? (
          <SfTrendChart points={points} xLabels={xLabels} formatY={(v) => pct(v)} yLabel="HEALTH" />
        ) : (
          <div className="flex h-full items-center justify-center text-[11px] uppercase text-term-dim">
            awaiting a second aggregation for a trend
          </div>
        )}
      </div>
    </div>
  );
}

function ThesisComponentRow({
  comp,
  onJump,
}: {
  comp: ForecastThesisComponent;
  onJump: (id: string) => void;
}) {
  const s = comp.s_i;
  const signalClass = s == null ? "text-term-dim" : s >= 0.5 ? "text-term-green" : "text-term-red";
  const stale = comp.status && comp.status !== "ok";
  return (
    <button
      onClick={() => comp.id && onJump(comp.id)}
      disabled={!comp.id}
      className={`flex w-full items-baseline gap-2 border-b border-term-border/60 px-2 py-[3px] text-left text-[11px] last:border-b-0 ${
        comp.id ? "cursor-pointer hover:bg-term-accent/10" : "cursor-default"
      }`}
    >
      <span className={`w-12 shrink-0 text-[10px] uppercase ${directionStyle(comp.direction).text}`}>
        {comp.direction === "inverted" ? "↓risk" : "↑supp"}
      </span>
      <span className="min-w-0 flex-1 truncate text-term-text">{comp.title || comp.id}</span>
      <span className="w-10 shrink-0 text-right tabular-nums text-term-dim">{comp.latest_belief_display ?? "—"}</span>
      <span className={`w-10 shrink-0 text-right tabular-nums ${signalClass}`}>
        {s != null ? `${(s * 100).toFixed(0)}%` : "—"}
      </span>
      <span className="w-12 shrink-0 text-right tabular-nums text-term-accent-hi">
        {comp.contribution_pts != null ? `${comp.contribution_pts >= 0 ? "+" : ""}${comp.contribution_pts.toFixed(1)}` : "—"}
      </span>
      {stale && <span className="shrink-0 text-[9px] uppercase text-term-yellow">{comp.status}</span>}
    </button>
  );
}

function ThesisDeskRead({ thesis, onJump }: { thesis: ForecastThesis; onJump: (id: string) => void }) {
  const note = thesis.analyst_note ?? null;
  const comps = [...(thesis.components ?? [])].sort(
    (a, b) => (b.contribution_pts ?? 0) - (a.contribution_pts ?? 0),
  );
  const pctOf = (v?: number | null) => (v != null ? `${(v * 100).toFixed(0)}%` : "—");
  return (
    <div className="px-3 py-2 text-[12px]">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {thesis.domain && <Tag label={thesis.domain} style={domainTag(thesis.domain)} />}
        {(thesis.topics ?? []).slice(0, 6).map((t) => (
          <Tag key={t} label={t} />
        ))}
        <span className="ml-auto text-[10px] uppercase text-term-dim">{thesis.member_count ?? comps.length} members</span>
      </div>

      {note ? (
        <QuickRead note={note} />
      ) : (
        <div className="text-[11px] uppercase text-term-dim">no thesis note yet</div>
      )}

      <SectionLabel>Aggregate</SectionLabel>
      <div className="flex flex-wrap items-stretch border border-term-border">
        <KvCell k="health" v={thesis.health_display ?? "—"} />
        <KvCell k="score" v={thesis.thesis_score != null ? thesis.thesis_score.toFixed(0) : "—"} cls="text-term-text" />
        <KvCell
          k="90% band"
          v={
            thesis.score_band && thesis.score_band.q05 != null && thesis.score_band.q95 != null
              ? `${thesis.score_band.q05.toFixed(0)} – ${thesis.score_band.q95.toFixed(0)}`
              : "—"
          }
          cls="text-term-text"
        />
        <KvCell k="coverage" v={pctOf(thesis.coverage)} cls="text-term-text" />
        <KvCell k="n_eff" v={thesis.n_eff != null ? thesis.n_eff.toFixed(1) : "—"} cls="text-term-text" />
        <KvCell k="ρ" v={thesis.rho != null ? thesis.rho.toFixed(2) : "—"} cls="text-term-text" />
      </div>

      <SectionLabel>Member Contributions</SectionLabel>
      <div className="mb-1 flex items-baseline gap-2 px-2 text-[9px] uppercase text-term-dim">
        <span className="w-12 shrink-0">dir</span>
        <span className="min-w-0 flex-1">member</span>
        <span className="w-10 shrink-0 text-right">belief</span>
        <span className="w-10 shrink-0 text-right">signal</span>
        <span className="w-12 shrink-0 text-right">contrib</span>
      </div>
      <div className="border border-term-border">
        {comps.length ? (
          comps.map((c) => <ThesisComponentRow key={c.id ?? c.title} comp={c} onJump={onJump} />)
        ) : (
          <div className="px-2 py-2 text-[11px] uppercase text-term-dim">no members tagged yet</div>
        )}
      </div>

      <SectionLabel>Caveats</SectionLabel>
      <div className="text-[11px] leading-snug text-term-yellow">
        Aggregated after the members&apos; latest runs; members co-move (ρ {thesis.rho?.toFixed(2) ?? "—"}, n_eff ~
        {thesis.n_eff?.toFixed(1) ?? "—"} of {thesis.components?.length ?? 0}). Coverage {pctOf(thesis.coverage)}.
      </div>
    </div>
  );
}

function BackToThesisButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="border border-term-on-accent/40 px-1.5 py-[1px] text-[10px] hover:bg-term-on-accent/15"
      title="Back to the thesis read"
    >
      ◂ THESIS
    </button>
  );
}

/* ── the screen ──────────────────────────────────────────────────────────── */

type Lens = { kind: "domain" | "thesis"; value: string };

export function ForecastScreen() {
  const { payload, source, enabled } = useForecastWorkspace();
  const forecasts = payload.forecasts;
  const theses = payload.theses ?? [];
  const modal = useModal();
  const [query, setQuery] = useState("");
  const [lens, setLens] = useState<Lens>({ kind: "domain", value: "ALL" });
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

  const activeThesis = lens.kind === "thesis" ? theses.find((t) => t.id === lens.value) ?? null : null;

  const inDomain = (f: ForecastWorkspaceItem, d: string) =>
    d === "ALL" || (f.domain ?? "other").toLowerCase() === d;

  const filtered = useMemo(() => {
    if (lens.kind === "thesis" && activeThesis) {
      const ids = new Set(
        (activeThesis.components ?? []).map((c) => c.id).filter((x): x is string => Boolean(x)),
      );
      return forecasts.filter((f) => f.id != null && ids.has(f.id) && matchesFilter(f, query));
    }
    const d = lens.kind === "domain" ? lens.value : "ALL";
    return forecasts.filter((f) => matchesFilter(f, query) && inDomain(f, d));
  }, [forecasts, query, lens, activeThesis]);

  const memberSelected = selectedId ? filtered.find((f) => f.id === selectedId) ?? null : null;
  // A thesis lens leads with the thesis read; a domain lens leads with the first forecast.
  const selected = activeThesis ? memberSelected : memberSelected ?? filtered[0] ?? null;

  useEffect(() => {
    if (!activeThesis && filtered.length && !filtered.some((f) => f.id === selectedId)) {
      setSelectedId(filtered[0].id ?? null);
    }
  }, [filtered, selectedId, activeThesis]);

  const selectDomain = (d: string) => {
    setLens({ kind: "domain", value: d });
    const list = forecasts.filter((f) => matchesFilter(f, query) && inDomain(f, d));
    if (list.length && !list.some((f) => f.id === selectedId)) setSelectedId(list[0].id ?? null);
  };
  const selectThesis = (id: string) => {
    setLens({ kind: "thesis", value: id });
    setSelectedId(null); // lead with the thesis read, not a member
  };

  const domainNav = useArrowNav<string, HTMLUListElement>({
    items: domains.map((d) => d.name),
    getKey: (d) => d,
    current: lens.kind === "domain" ? lens.value : "",
    setCurrent: selectDomain,
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
  const bookTitle = activeThesis
    ? `Members — ${activeThesis.title ?? activeThesis.id}`
    : `Forecast Book — ${lens.value}`;

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      {/* 1) lens: theses at the top, then domains */}
      <div className="col-span-2 flex min-h-0">
        <Panel id={1} title="Lens" right={`${theses.length}T · ${forecasts.length}Q`}>
          {theses.length > 0 && (
            <>
              <div className="border-b border-term-border bg-term-bg-elev px-2 py-[2px] text-[9px] uppercase tracking-wider text-term-accent">
                Theses
              </div>
              <ul className="outline-none">
                {theses.map((t) => (
                  <ThesisRow
                    key={t.id ?? t.title}
                    thesis={t}
                    active={lens.kind === "thesis" && lens.value === t.id}
                    onSelect={() => t.id && selectThesis(t.id)}
                  />
                ))}
              </ul>
            </>
          )}
          <div className="border-b border-term-border bg-term-bg-elev px-2 py-[2px] text-[9px] uppercase tracking-wider text-term-accent">
            Domains
          </div>
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
                active={lens.kind === "domain" && lens.value === d.name}
                swatch={d.name === "ALL" ? "text-term-accent" : domainTag(d.name).text}
                onSelect={() => selectDomain(d.name)}
              />
            ))}
          </ul>
        </Panel>
      </div>

      {/* 2) book (the thesis's members when a thesis lens is active) */}
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
        <Panel id={2} title={bookTitle} right={sourceRight}>
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

      {/* 3) trend  +  4) read — thesis read, or member detail */}
      <div
        className="col-span-5 grid min-h-0 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, 1.6fr) minmax(0, 1fr)" }}
      >
        {activeThesis && !selected ? (
          <>
            <div className="flex min-h-0">
              <Panel
                id={3}
                title="Thesis Health"
                right={`SCORE ${activeThesis.thesis_score != null ? activeThesis.thesis_score.toFixed(0) : "—"}`}
              >
                <ThesisTrendBlock thesis={activeThesis} />
              </Panel>
            </div>
            <div className="flex min-h-0">
              <Panel
                id={4}
                title={activeThesis.title || "THESIS"}
                right={`${activeThesis.member_count ?? 0} MEMBERS`}
              >
                <ThesisDeskRead thesis={activeThesis} onJump={(id) => setSelectedId(id)} />
              </Panel>
            </div>
          </>
        ) : selected ? (
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
                right={
                  <span className="flex items-center gap-1.5">
                    {activeThesis && <BackToThesisButton onClick={() => setSelectedId(null)} />}
                    <ExpandButton onClick={() => modal.open((c) => <ForecastDetailModal item={selected} close={c} />)} />
                  </span>
                }
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
