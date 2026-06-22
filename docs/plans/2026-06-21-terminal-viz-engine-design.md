# Terminal Viz Engine — `@hermes/viz`

**The SVG/canvas of the terminal: a multi-backend chart engine that turns our string charts into Bloomberg/TradingView-grade visuals.**

Status: design locked (2026-06-21). Grounded in a 12-agent research+design pass (current viz stack, Ink substrate, external landscape; 5 layer designs; 3 adversarial reviews; synthesis). Implementation spec below.

---

## 1. Review of the team's proposal

The team's framing is correct: **the bottleneck is the graphics backend, not Ink.** Ink owns layout/focus/input; we need the terminal equivalent of a canvas with graceful degradation. Their 4-layer model (grammar → cell renderer → protocol renderer → Ink integration) and the notcurses-blitter insight are the right north star. Three corrections from grounding our actual substrate:

1. **We are further along than "build a serious terminal canvas from scratch."** Truecolor (24-bit) already works through `colorize.ts`/chalk with automatic 256→16 downgrade (tmux/Apple-Terminal aware). `stringWidth.ts` measures braille (U+2800–28FF) **and** block elements (U+2580–259F, sextants, octants) as **width-1** (`ambiguousAsWide:false`). And `subcellGlyphs.ts` already ships the mask→glyph blitter-table layer (`half/quad/sextant/octant`), proven on screen by `outriderHeader.tsx` (truecolor half-block span rows). **The cell-glyph tier needs ZERO changes to the vendored Ink fork** — it's just width-1 styled strings, which the renderer already handles. This is the 80/20: it is the entire visible fidelity jump, and it's low-risk.

2. **The protocol-renderer (Kitty/Sixel/iTerm2) is a genuine trap, not just "fragmented."** Our renderer uses a DECSTBM hardware-scroll fast-path + per-cell diff (`log-update.ts`/`screen.ts`) that has no concept of an image; image escapes anchor to absolute rows while text scrolls within a region → misalignment, and full-repaint won't clear them. Integrating it means invasive surgery on the fork (image-region tracking, scroll invalidation, atomic emit). **Defer it.** A truecolor half-block heatmap already produces the "you can do THAT in a terminal?!" reaction. Ship detection only.

3. **A full grammar-of-graphics compiler is over-built for v1.** Six named chart builders (`renderHeatmap`, `renderFan`, …) over shared scale/tick/downsample utilities beat a Vega-Lite-in-the-terminal. Keep the spec small, the API typed-per-chart.

Everything else in the proposal — offscreen buffer + cell-diff, "don't do per-pixel React reconciliation," the blitter ladder, dithering/quantization for color-limited cells — we adopt.

---

## 2. Architecture

```
AGENT → presentation.py (validate, tolerant) → wire blocks (JSON)            ── contract (additive only)
presentationView.renderBlock → <Chart kind=…>/<CellCanvas> (React, memoized) ── Layer R   BUILD
lib/viz/ pure engine: scale · buffer · blit · caps · color                   ── Layer E   BUILD
         charts/{heatmap, fan}  (Phase 2: distribution, candles, depth, sparkgrid)
subcellGlyphs.ts · colorize.ts · stringWidth.ts (Ink fork)                   ── substrate UNCHANGED

DEFER (flag-gated, post-MVP): grammar compiler · general RGBA canvas/AA/dither
                              · Tier-B image protocols · async capability probes · crosshair input
```

The **cell-glyph tier is the universal default and the whole product.** Tier B (pixel/image protocols) is deferred: detection ships (it informs blitter choice); no image code path is built in v1.

### Core interfaces (locked)

```ts
// lib/viz/types.ts
export interface StyledRun { text: string; color?: string; backgroundColor?: string; bold?: boolean; dim?: boolean }
export type StyledRow = StyledRun[]
export interface RenderResult { rows: StyledRow[]; axisBottom?: StyledRow; legend?: StyledRow[] }

export type Blitter = '1x1' | 'half' | 'quad' | 'sextant' | 'braille'   // 'octant' exists, never auto-selected
export type ColorMode = '16' | '256' | 'truecolor'
export interface TerminalCaps { colorMode: ColorMode; blitterMax: Blitter }   // sync-only in v1

export interface ChartTheme { fg: string; muted: string; grid: string; up: string; down: string; bands: string[]; heat: (t: number) => string }
export interface RenderCtx { width: number; height?: number; caps: TerminalCaps; theme: ChartTheme }
```

```ts
// lib/viz/buffer.ts — lazy color plane; monochrome charts never allocate RGBA
export class CellBuffer {
  constructor(cols: number, rows: number, opts?: { color?: boolean })
  set(col: number, row: number, glyph: string, run?: Partial<StyledRun>): void
  // Heatmap fast path: serialize a whole row to coalesced runs WITHOUT a <Text> per cell.
  setRow(row: number, cells: { t: string; fg?: string; bg?: string }[]): void
  compile(): StyledRow[]   // coalesce adjacent identical-style cells into one run
}
```

```tsx
// components/viz/Chart.tsx — renders ONCE per [data,width,caps,themeKey] (useMemo); returns <Text> rows, no per-pixel nodes
export function Chart(props: { kind: 'heatmap'|'fan'|'distribution'|'candles'|'depth'|'sparkgrid'; data: unknown; t: Theme; width?: number; height?: number }): JSX.Element
export function CellCanvas(props: { result: RenderResult }): JSX.Element   // dumb StyledRow→<Text> renderer
```

`pickBlitter`, `resolveCaps`, `renderHeatmap`, `renderFan` are the public engine API. No `d3-scale` dep; `scale.ts` is hand-rolled (~80 lines) with the D3 nice-tick step (`1/2/5·10^k`), `.nice()`, `.ticks(n)`, and LTTB downsampling.

---

## 3. Blitter ladder + auto-selection (locked)

| Rung | Geometry | Colors/cell | Source | Use |
|---|---|---|---|---|
| `1x1` | 1×1 | 1 | ascii / glyphs | universal floor; legacy adapters; 16-color intensity `░▒▓█` |
| `half` | 1×2 | **2 truecolor** | `subcellGlyphs.HALF` (`▀` fg/bg) | **heatmap flagship** |
| `quad` | 2×2 | ≤2 | `subcellGlyphs.QUAD` | **DEFAULT ceiling** — plots + heatmap fallback |
| `sextant` | 2×3 | 1 | `buildSextant()` | opt-in mid-tier |
| `braille` | 2×4 dots | 1 fg | new braille bitmap | **fan/distribution lines** (opt-in; near-universal) |
| `octant` | 2×4 | 1 | `buildOctant()` | defined, **NEVER auto-selected** (U16, tofu risk) |

`pickBlitter(kind, caps)`: heatmap→`half` (truecolor) / `quad` (256) / `1x1` intensity (16); fan & distribution→`braille` (capped at `blitterMax`); candles & depth→`quad` (need color+shape, not 1-color braille); sparkgrid→`half`.

`blitterMax` resolves **sync, no probe**: default `quad` (ubiquitous, verified width-1) → `HERMES_VIZ_BLITTER` env override (load-bearing; the only reliable font signal over a pty) → optional persisted first-run glyph calibration promotes to `braille`/`sextant` → terminal-identity heuristic may raise to `braille` only (`KITTY_WINDOW_ID`, `TERM` ~ kitty/ghostty/foot, `VTE_VERSION≥6800`), never to sextant/octant.

---

## 4. Agent→renderer contract migration (confirmed non-breaking)

`forecasting/presentation.py` — **additive only, zero validate-logic change** (`validate_presentation` already does `_REQUIRED_FIELDS.get(btype, ())` and only hard-fails on a *known* type missing a required field):

```python
BLOCK_TYPES |= {"heatmap", "distribution", "candles", "depth", "sparkgrid"}   # fan upgraded in place
_REQUIRED_FIELDS.update({
    "heatmap": ("matrix",), "distribution": ("support", "pdf"),
    "candles": ("candles",), "depth": ("bids", "asks"), "sparkgrid": ("cells",),
})  # required = only the single irreducible field the renderer can't invent
```

- `presentation.ts`: **zero interface changes** (`PresentationBlock` is already open `{[k]:unknown; type:string}`; `normalizePresentation` only checks `type` is a string). Add optional typed helpers (`HeatmapData`, `FanData`, …) for renderer ergonomics.
- **`fan` upgraded in place** (best back-compat): no `paths` → current `bandChart` verbatim; with `paths` → braille cone + median + spaghetti. Old payloads render identically. No `montecarlo` type.
- **Legacy consumers (`forecastsWorkspace`, `marketsView`, `calibrationView`, `agentsOverlay`) are NOT migrated in v1** — they keep calling `forecastCharts.ts`/`marketCharts.ts`/`sparkline.ts` unchanged. Zero regression. Only `presentationView` is wired to `<Chart>`.
- Tolerant `default` fallback in `renderBlock` preserved → a new block type from a newer gateway renders gracefully on an older TUI.
- `SCHEMA_VERSION` stays `market-presentation-v1`; `EMIT_MARKET_PRESENTATION_SCHEMA` description updated to list the new types (the de-facto agent API doc).

---

## 5. Killer primitives — v1 vs later

**v1 (2 flagships):**
1. **`heatmap` — FLAGSHIP.** Truecolor half-block (`▀`, fg=top pixel, bg=bottom pixel = 2 truecolor pixels/cell), diverging colormap (blue↔white↔red for correlation), legend. Reuses the proven `outriderHeader` span-row technique but **row-coalesced** (one `<Text>` per row — see Risk 2). Degrades truecolor → 256 (hand-picked `ansi256` palette) → 16-color glyph-intensity. Correlation / liquidity / volume matrices.
2. **`fan` upgrade — Monte-Carlo cone.** Braille median + faint braille spaghetti (LTTB-downsampled, ≤20 paths) + half-block confidence band. No-paths fallback = current `bandChart`.

**The flagship demo:** one Market Models response rendering a **truecolor correlation heatmap beside a braille Monte-Carlo fan**, live over SSH, degrading cleanly on Apple Terminal (256) and tmux. That screenshot is the pitch.

**Phase 2 (direct typed builders, still cell-glyph):** `distribution` (PDF+CDF braille + 50/80/95% interval bands + tails), `candles` (half-block OHLC + volume sub-panel + MA), `depth` (mirrored cumulative bid/ask step-area + spread/mid), `sparkgrid` (dashboard grid reusing `sparkline`/`deltaGlyph`).

**Never:** `chart` escape-hatch wire type (unbounded validation/DoS surface); grammar compiler; image protocols (v1); octant auto-select; Xiaolin-Wu AA; Floyd-Steinberg dither / k-means (over-built for 1-bit cells).

---

## 6. Phased roadmap

**Phase 1 — MVP / the demo (the 80/20, no Ink-fork changes):**
- `ui-tui/src/lib/viz/{types,scale,buffer,blit,caps,color}.ts` + `charts/{heatmap,fan}.ts`.
- `ui-tui/src/components/viz/{Chart,Canvas,chartTheme,useViewportCaps}.tsx`.
- `presentation.py`: add `heatmap`+`distribution` types (stabilize schema now); wire `heatmap` + `fan`-upgrade in `presentationView.renderBlock`.
- Tests (`src/__tests__/viz/`): golden `StyledRow[]` snapshots at truecolor/256/16; **`width.test.ts`** (every chart × fixtures × widths 24–120 → `stringWidth(row)===expected` — the highest-value invariant); a heatmap-in-`ScrollBox` bleed test; **perf gate = 120×40 truecolor heatmap reconcile+diff**.

**Phase 2 — catalog:** `distribution/candles/depth/sparkgrid` builders + block types; pure-render annotations (last-value labels, threshold lines, legend); first-run glyph calibration → promote `blitterMax`.

**Phase 3 — deferred/riskiest (flag-gated, build on demand):** thin-adapter migration of the 4 legacy consumers (only if shared code demands it; gated by a byte-diff golden harness, old impls retained one release); async capability probes (Kitty APC / DA1 sixel) to refine the rung; **Tier-B image protocols** (Kitty Unicode-placeholder first, `HERMES_PIXEL_IMAGES=1`, separate `screen.ts` width-registration spike with its own invariant test before touching `ScrollBox`); crosshair/cursor readout (needs `parse-keypress` input wiring).

---

## 7. Top risks + concrete guards

| # | Risk | Guard |
|---|---|---|
| 1 | **Font tofu / misalignment** (sextant U13, octant U16 absent in most fonts; width-1 ≠ renders cleanly) | Default ceiling `quad` (verified-ubiquitous Block Elements). `octant` never auto-selected. `HERMES_VIZ_BLITTER` override is load-bearing. Promote to braille/sextant only via persisted first-run calibration; `TERM` heuristic promotes to braille at most. |
| 2 | **Heatmap run-count blows the diff hot loop** — a real correlation matrix is adjacent-distinct colors → per-cell `<Text>` ≈ 3,840 interned styles/frame at 120×40, thrashing the style pool | `CellBuffer.setRow` pre-serializes each heatmap **row to one `<Text>`** (96→1 node/row). Do NOT generalize `outriderHeader`'s per-span pattern full-screen. Mandatory matrix downsample above a size threshold. Gating perf benchmark = 120×40 truecolor heatmap. |
| 3 | **256/tmux colormap degradation** — chalk RGB→cube nearest-match merges adjacent correlation buckets; Apple Terminal HSL-snaps the near-zero midband to gray (kills sign distinction at the key boundary) | At `chalk.level===2`, emit hand-picked `ansi256(n)` directly (colorize passes these through) from a 9-step perceptually-separated diverging palette. **Dual-encode** sign/magnitude with a glyph-intensity channel (`░▒▓█`) at ≤256 colors. Enforced glyph-intensity fallback at 16. Quantization-legibility test: adjacent buckets → distinct tokens. |
| 4 | **Image-protocol substrate break** (DECSTBM scroll fast-path can't track image escapes) | Deferred entirely from v1 (detection only). Flag-gated, Kitty-placeholder-first, separate spike with width-invariant test before it may touch `ScrollBox`. |
| 5 | **Migration drift** (trailing-space + rounding ≠ byte-identical → breaks existing snapshots across 4 consumers) | Don't migrate legacy consumers in v1. Phase 3: byte-diff golden harness (old vs adapter, random widths × all kinds) asserts string equality before deleting old code; old impls behind a flag one release; no big-bang PR. |
| 6 | **Async-probe race / mid-session reflow flicker** | No async probe in v1 (sync `chalk.level` only). When probes land: memoize blitter choice per chart instance at first paint; drop `caps` from the memo key after first resolve (upgrade-only for next mount); bound the APC arm against unterminated sequences. |

---

## 8. Package + public API

`ui-tui/src/lib/viz/` (pure engine, zero React, zero new deps) + `ui-tui/src/components/viz/` (React). Internal name **`@hermes/viz`** (workspace-local).

```ts
// lib/viz/index.ts
export function renderHeatmap(data: HeatmapData, ctx: RenderCtx): RenderResult
export function renderFan(data: FanData, ctx: RenderCtx): RenderResult
// Phase 2: renderDistribution, renderCandles, renderDepth, renderSparkgrid
export { CellBuffer } from './buffer.js'
export { pickBlitter, resolveCaps } from './caps.js'
export type { StyledRun, StyledRow, RenderResult, TerminalCaps, Blitter, ChartTheme, RenderCtx }
// components/viz/index.ts
export function Chart(props: ChartProps): JSX.Element
export function CellCanvas(props: { result: RenderResult }): JSX.Element
```

**DX rules (load-bearing):** named `renderHeatmap`/`renderFan` are the contract — no `renderChart(spec)` discriminated-union as the *primary* API (worse types/errors/test-names; a dispatcher is fine internally). Additive-only, **frozen field names** (`matrix`, `support`/`pdf`, `candles`, `bids`/`asks`, `cells`) — renaming = agent-retraining cost. Each `charts/*.ts` independently importable (tree-shakeable). Tolerant `default` fallback non-negotiable.

---

## Critical files

- `forecasting/presentation.py` — additive `BLOCK_TYPES` + `_REQUIRED_FIELDS` (`heatmap/distribution/candles/depth/sparkgrid`; `fan` unchanged; validate logic untouched).
- `ui-tui/src/components/presentationView.tsx` — the one upgraded consumer (add `heatmap` case + `fan`-upgrade + `<Chart>` wiring; preserve tolerant default).
- `ui-tui/src/components/outriderHeader.tsx` — proven truecolor half-block span-row pattern to copy for the heatmap (but row-coalesce per Risk 2).
- `ui-tui/src/lib/subcellGlyphs.ts` — existing `half/quad/sextant/octant` tables the blitter wraps (cap MVP at `quad`).
- `ui-tui/packages/hermes-ink/src/ink/colorize.ts` — truecolor→256→16 downgrade; at level 2 emit `ansi256(n)` directly to bypass chalk's cube nearest-match (Risk 3).
- New: `ui-tui/src/lib/viz/{types,scale,buffer,blit,caps,color}.ts`, `charts/{heatmap,fan}.ts`, `ui-tui/src/components/viz/{Chart,Canvas,chartTheme,useViewportCaps}.tsx`.
