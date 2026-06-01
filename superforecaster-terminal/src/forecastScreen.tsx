// SF · SUPERFORECASTER DESK
//
// The web-terminal surface for the Superforecasting Agent: a forecast book
// (left) + a focused read (right) that mirrors the `forecast` TUI's `/desk`
// workspace — headline + distribution intervals, the analyst QUICK READ, a
// time-series trend with a confidence band, the outcome distribution, related
// (cross-pollinated) forecasts, reasoning, and recent evidence.
//
// Everything renders from the single `/forecast/workspace` payload (one round
// trip, no per-row refetch). All pure formatting lives in `forecastFormat.ts`
// (ported verbatim from the TUI) so the load-bearing rules — e.g. a
// distribution mean never rendering as "310%" — are shared, not re-derived.

import { useMemo, useState } from "react";
import { Chart, Panel } from "./components";
import { useForecastWorkspace } from "./forecastProvider";
import {
  ANALYST_ANGLES,
  RELATIONSHIP_TAG,
  STANCE_LABEL,
  bandChart,
  chartScale,
  compactNumber,
  deltaLabel,
  distributionBars,
  headlineCompact,
  headlineLabel,
  histogram,
  historyToBandPoints,
  matchesFilter,
  pct,
  shortDate,
} from "./forecastFormat";
import type {
  ForecastAnalystNote,
  ForecastRelatedView,
  ForecastWorkspaceItem,
} from "./forecastFormat";

/* ── small presentational atoms ──────────────────────────────────────────── */

function Tag({ label, tone = "dim" }: { label: string; tone?: "dim" | "accent" | "warn" }) {
  const cls =
    tone === "warn"
      ? "border-term-yellow/60 text-term-yellow"
      : tone === "accent"
        ? "border-term-accent/60 text-term-accent-hi"
        : "border-term-border-hi text-term-dim";
  return (
    <span className={`inline-block border px-1 text-[10px] uppercase ${cls}`}>{label}</span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 mb-1 border-b border-term-border pb-[2px] text-[10px] uppercase tracking-wider text-term-accent first:mt-0">
      {children}
    </div>
  );
}

function KvRow({ k, v, cls = "text-term-accent-hi" }: { k: string; v: React.ReactNode; cls?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-start justify-center border-l border-term-border px-3 py-1 first:border-l-0">
      <span className="text-[10px] uppercase text-term-dim">{k}</span>
      <span className={`truncate tabular-nums text-[12px] ${cls}`}>{v}</span>
    </div>
  );
}

function unitSuffixFor(item: ForecastWorkspaceItem): string {
  const u = (item.units ?? "").toLowerCase();
  return u.includes("percent") || u.includes("%") ? "%" : "";
}

/* ── left: the forecast book ─────────────────────────────────────────────── */

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
  const closing = item.closing_soon;
  return (
    <button
      onClick={onSelect}
      aria-pressed={active}
      className={`flex w-full flex-col gap-[1px] border-b border-term-border px-2 py-[5px] text-left transition-colors ${
        active ? "bg-term-accent/20" : "hover:bg-term-accent/10"
      }`}
    >
      <div className="flex items-baseline gap-2">
        <span
          className={`min-w-[3.5rem] shrink-0 tabular-nums text-[12px] ${active ? "text-term-accent-hi" : "text-term-accent"}`}
        >
          {headlineCompact(item)}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-term-text">
          {item.title || item.id || "—"}
        </span>
        {alerts > 0 && <span className="shrink-0 text-[10px] text-term-yellow">▲{alerts}</span>}
        {closing && <span className="shrink-0 text-[10px] text-term-red">CLOSE</span>}
      </div>
      <div className="flex items-baseline gap-2 text-[10px] uppercase text-term-dim">
        <span className="truncate">{item.domain ?? item.outcome_type ?? "—"}</span>
        <span className="ml-auto shrink-0 tabular-nums text-term-muted">{deltaLabel(item)}</span>
      </div>
    </button>
  );
}

/* ── right: focused read sub-sections ────────────────────────────────────── */

function QuickRead({ note }: { note: ForecastAnalystNote }) {
  const retro = note.kind === "retrospective";
  return (
    <div className="space-y-2 text-[12px]">
      {note.headline && <div className="text-term-accent-hi">{note.headline}</div>}
      <div className="flex flex-wrap gap-1">
        {retro && <Tag label="retrospective" tone="warn" />}
        {note.stance && <Tag label={`stance · ${STANCE_LABEL[note.stance] ?? note.stance}`} tone="accent" />}
        {note.verdict && <Tag label={`verdict · ${note.verdict}`} tone={retro ? "accent" : "dim"} />}
      </div>
      {ANALYST_ANGLES.map((angle) => {
        const text = note[angle.key];
        if (!text) return null;
        return (
          <div key={angle.key} className="leading-snug">
            <span
              className={`mr-2 text-[10px] uppercase ${angle.warn ? "text-term-yellow" : "text-term-dim"}`}
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
  const span = (pair: number[] | null | undefined): string =>
    Array.isArray(pair) && pair.length === 2
      ? `${compactNumber(pair[0])}${suffix} – ${compactNumber(pair[1])}${suffix}`
      : "—";
  return (
    <div className="flex flex-wrap items-stretch border border-term-border">
      <KvRow k="median" v={`${compactNumber(dist.median)}${suffix}`} />
      <KvRow k="mean" v={`${compactNumber(dist.mean)}${suffix}`} />
      <KvRow k="σ" v={compactNumber(dist.sd)} cls="text-term-text" />
      <KvRow k="50% CI" v={span(dist.ci50)} cls="text-term-text" />
      <KvRow k="90% CI" v={span(dist.ci90)} cls="text-term-text" />
    </div>
  );
}

function RelatedRow({
  view,
  onJump,
}: {
  view: ForecastRelatedView;
  onJump: (id: string) => void;
}) {
  const tag = view.relationship ? RELATIONSHIP_TAG[view.relationship] : undefined;
  const jumpable = Boolean(view.id);
  return (
    <button
      onClick={() => view.id && onJump(view.id)}
      disabled={!jumpable}
      className={`flex w-full items-baseline gap-2 border-b border-term-border px-1 py-[3px] text-left text-[11px] ${
        jumpable ? "hover:bg-term-accent/10" : "cursor-default"
      }`}
    >
      <span className="w-12 shrink-0 text-[10px] uppercase text-term-cyan">
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

/* ── the detail pane ─────────────────────────────────────────────────────── */

function ForecastDetail({
  item,
  onJump,
}: {
  item: ForecastWorkspaceItem;
  onJump: (id: string) => void;
}) {
  const isDist = item.headline_kind === "distribution";
  const note = item.analyst_note ?? item.analyst_notes?.[item.analyst_notes.length - 1] ?? null;

  // Trend: band points → auto-zoomed line + ASCII confidence band.
  const points = useMemo(() => historyToBandPoints(item), [item]);
  const scale = useMemo(() => chartScale(points), [points]);
  const series = points.map((p) => p.y).filter((v): v is number => v != null);
  const history = item.history ?? [];
  const dates = history.map((h) => h.as_of).filter(Boolean) as string[];
  const xLabels = dates.length
    ? [shortDate(dates[0]), shortDate(dates[Math.floor(dates.length / 2)]), shortDate(dates[dates.length - 1])]
    : undefined;
  const band = useMemo(
    () => bandChart(points, { yMin: scale.yMin, yMax: scale.yMax, width: 60, height: 7 }),
    [points, scale],
  );

  // Outcome distribution: prefer the canonical PMF, fall back to raw buckets.
  const pmfBars =
    item.distribution?.pmf?.map((p) => ({ label: p.label, value: p.probability })) ??
    distributionBars(item.probability) ??
    [];

  const related = item.related?.forecasts ?? [];
  const sharedSources = item.related?.shared_sources ?? [];
  const evidence = (item.evidence ?? []).slice(-6).reverse();
  const scores = item.scores;
  const resolution = item.resolution;

  return (
    <div className="flex h-full min-h-0 flex-col gap-px bg-term-border">
      {/* header + chart: a sized grid so the Chart gets a real height */}
      <div
        className="grid min-h-0 flex-1 gap-px bg-term-border"
        style={{ gridTemplateRows: "minmax(0, auto) minmax(0, 1fr)" }}
      >
        <Panel
          id={2}
          title={item.title || item.id || "FORECAST"}
          right={`${(item.status ?? "open").toUpperCase()} · ${item.freshness ?? shortDate(item.as_of)}`}
        >
          <div className="flex flex-col gap-2 px-2 py-2">
            <div className="flex flex-wrap items-stretch border border-term-border">
              <KvRow k="headline" v={headlineLabel(item)} />
              <KvRow k="Δ" v={deltaLabel(item)} cls="text-term-text" />
              <KvRow k="confidence" v={item.confidence != null ? pct(item.confidence) : "—"} cls="text-term-text" />
              <KvRow k="domain" v={(item.domain ?? "—").toUpperCase()} cls="text-term-text" />
              <KvRow k="impact" v={(item.impact ?? "—").toUpperCase()} cls="text-term-text" />
              <KvRow k="evidence" v={String(item.evidence_count ?? evidence.length)} cls="text-term-text" />
            </div>
            {isDist && <IntervalReadout item={item} />}
            <div className="flex flex-wrap gap-1">
              {(item.topics ?? []).slice(0, 8).map((t) => (
                <Tag key={t} label={t} />
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          id={3}
          title="Headline Trend"
          right={isDist ? `MEAN · ${(item.units ?? "UNITS").toUpperCase()}` : "PROBABILITY"}
        >
          {series.length >= 2 ? (
            <Chart
              title={item.id ? item.id.toUpperCase() : "TREND"}
              subtitle={isDist ? "MEAN OVER TIME · 90% BAND" : "PROBABILITY OVER TIME"}
              data={series}
              xLabels={xLabels}
              formatY={isDist ? (v) => `${compactNumber(v)}${unitSuffixFor(item)}` : (v) => pct(v)}
              yLabel={isDist ? (item.units ?? "μ") : "P"}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[11px] uppercase text-term-dim">
              awaiting a second snapshot for a trend
            </div>
          )}
        </Panel>
      </div>

      {/* scrolling desk read */}
      <div className="flex min-h-0 flex-[1.15]">
        <Panel id={4} title="Desk Read" right="QUICK READ · CONF BAND · RELATED · EVIDENCE">
          <div className="px-2 py-2">
            {note ? (
              <>
                <SectionLabel>Analyst Quick Read</SectionLabel>
                <QuickRead note={note} />
              </>
            ) : (
              <div className="text-[11px] uppercase text-term-dim">no analyst note yet</div>
            )}

            {band.rows.length > 0 && series.length >= 2 && (
              <>
                <SectionLabel>Confidence Band</SectionLabel>
                <pre className="overflow-x-auto text-[11px] leading-tight text-term-accent">
                  {band.rows.join("\n")}
                </pre>
              </>
            )}

            {pmfBars.length > 0 && (
              <>
                <SectionLabel>Outcome Distribution</SectionLabel>
                <pre className="overflow-x-auto text-[11px] leading-tight text-term-text">
                  {histogram(pmfBars, { width: 26, labelWidth: 18 }).join("\n")}
                </pre>
              </>
            )}

            {related.length > 0 && (
              <>
                <SectionLabel>Related Forecasts · Cross-Pollination</SectionLabel>
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
              </>
            )}

            {(item.reasons_up?.length || item.reasons_down?.length || item.change_my_mind?.length) ? (
              <>
                <SectionLabel>Reasoning</SectionLabel>
                <ReasonList label="reasons up" items={item.reasons_up ?? []} tone="text-term-green" />
                <ReasonList label="reasons down" items={item.reasons_down ?? []} tone="text-term-red" />
                <ReasonList label="change my mind" items={item.change_my_mind ?? []} tone="text-term-cyan" />
              </>
            ) : null}

            {evidence.length > 0 && (
              <>
                <SectionLabel>Recent Evidence</SectionLabel>
                <div className="space-y-1">
                  {evidence.map((e, i) => (
                    <div key={e.id ?? i} className="border-l-2 border-term-border pl-2 text-[11px] leading-snug">
                      <span className="mr-2 text-[10px] uppercase text-term-dim">{e.source ?? e.source_type ?? "src"}</span>
                      {e.stance && (
                        <span
                          className={`mr-2 text-[10px] uppercase ${
                            e.stance.toLowerCase().includes("support") || e.stance.toLowerCase().includes("up")
                              ? "text-term-green"
                              : e.stance.toLowerCase().includes("against") || e.stance.toLowerCase().includes("down")
                                ? "text-term-red"
                                : "text-term-dim"
                          }`}
                        >
                          {e.stance}
                        </span>
                      )}
                      <span className="text-term-text">{e.summary ?? e.claim ?? "—"}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {(scores || resolution) && (
              <>
                <SectionLabel>Calibration</SectionLabel>
                <div className="flex flex-wrap items-stretch border border-term-border">
                  <KvRow k="scored" v={String(scores?.count ?? 0)} cls="text-term-text" />
                  <KvRow
                    k="mean brier"
                    v={scores?.mean_brier != null ? scores.mean_brier.toFixed(3) : "—"}
                  />
                  <KvRow k="last bucket" v={(scores?.last_bucket ?? "—").toUpperCase()} cls="text-term-text" />
                  <KvRow
                    k="resolution"
                    v={(resolution?.resolution_status ?? "unresolved").toUpperCase()}
                    cls="text-term-text"
                  />
                </div>
              </>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* ── the screen ──────────────────────────────────────────────────────────── */

export function ForecastScreen() {
  const { payload, source, enabled } = useForecastWorkspace();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const forecasts = payload.forecasts;
  const filtered = useMemo(
    () => forecasts.filter((f) => matchesFilter(f, query)),
    [forecasts, query],
  );
  const selected =
    filtered.find((f) => f.id === selectedId) ?? filtered[0] ?? null;

  const sourceRight = !enabled
    ? "BRIDGE OFFLINE"
    : source.kind === "live"
      ? `SF · ${shortDate(source.generatedAt ?? payload.generated_at)} · ${forecasts.length} BOOK`
      : "SF · CONNECTING";

  return (
    <div className="col-span-12 grid min-h-0 grid-cols-12 gap-px bg-term-border">
      {/* left — the book */}
      <div className="col-span-4 flex min-h-0 flex-col gap-px bg-term-border">
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
        <Panel id={1} title="Forecast Book" right={sourceRight}>
          {filtered.length === 0 ? (
            <div className="px-2 py-4 text-[11px] uppercase leading-relaxed text-term-dim">
              {!enabled ? (
                <>
                  forecast bridge is not running.
                  <br />
                  start it with:
                  <br />
                  <span className="text-term-accent">python3 -m forecasting.webbridge</span>
                  <br />
                  then set <span className="text-term-accent">VITE_FORECAST_API_ENABLED=1</span> in .env.local
                </>
              ) : query ? (
                "no forecasts match this filter"
              ) : (
                "awaiting forecast feed…"
              )}
            </div>
          ) : (
            filtered.map((item) => (
              <DeskRow
                key={item.id ?? item.title}
                item={item}
                active={selected?.id === item.id}
                onSelect={() => item.id && setSelectedId(item.id)}
              />
            ))
          )}
        </Panel>
      </div>

      {/* right — the read */}
      <div className="col-span-8 flex min-h-0">
        {selected ? (
          <ForecastDetail item={selected} onJump={(id) => setSelectedId(id)} />
        ) : (
          <Panel id={2} title="Forecast Detail" right="SF">
            <div className="flex h-full items-center justify-center text-[11px] uppercase text-term-dim">
              {enabled ? "select a forecast" : "forecast bridge offline"}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
