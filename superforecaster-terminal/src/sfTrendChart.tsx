// Dedicated SF trend chart — a self-contained SVG in the house Bloomberg style
// (full grid, smoothed line, dashed current-level, right-edge price tag), with a
// forecast-specific 90% confidence band drawn as an in-hue cone.
//
// It does NOT touch the shared <Chart> (the finance screens use that with a
// raw-extrema domain). Fixes for the forecast desk:
//   - FIT: the y-domain is the PADDED `chartScale(points)` so the mean line and
//     band sit inside the plot, never flush against the edges.
//   - BAND: the 90% band (lo..hi) is a faint fill + dashed edges in the LINE's
//     own colour (green/red), so it reads as a confidence cone, not a grey slab.
//   - STYLE: matches the finance chart — gridlines + ticks, a smoothed curve, a
//     dashed current level, and a filled last-value tag at the right edge.

import { useEffect, useRef, useState } from "react";
import { axisLabels, chartScale } from "./forecastFormat";
import type { BandPoint } from "./forecastFormat";

const MONO = "var(--font-mono)";
const snap = (n: number) => Math.round(n) + 0.5;

/** Catmull-Rom → cubic-bezier smoothing (same shape as the finance chart). */
function smoothPath(pts: ReadonlyArray<readonly [number, number]>): string {
  if (pts.length === 0) return "";
  const p = pts;
  if (p.length === 1) return `M${p[0]![0].toFixed(2)},${p[0]![1].toFixed(2)}`;
  let d = `M${p[0]![0].toFixed(2)},${p[0]![1].toFixed(2)}`;
  for (let i = 0; i < p.length - 1; i += 1) {
    const p0 = p[i === 0 ? 0 : i - 1]!;
    const p1 = p[i]!;
    const p2 = p[i + 1]!;
    const p3 = p[i + 2 < p.length ? i + 2 : p.length - 1]!;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setSize({ w: rect.width, h: rect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export function SfTrendChart({
  points,
  xLabels,
  formatY,
  yLabel,
}: {
  points: BandPoint[];
  xLabels?: string[];
  formatY: (v: number) => string;
  yLabel?: string;
}) {
  const [ref, { w: W, h: H }] = useSize<HTMLDivElement>();

  const N = points.length;
  const ys = points.map((p) => p.y).filter((v): v is number => v != null);
  const { yMin, yMax } = chartScale(points); // padded + clamped domain
  const span = yMax - yMin || 1;
  const first = ys[0] ?? 0;
  const last = ys.length ? (ys[ys.length - 1] as number) : null;
  const rising = (last ?? 0) >= first;
  const stroke = rising ? "var(--color-term-green)" : "var(--color-term-red)";

  const padL = W < 480 ? 46 : 58;
  const padR = W < 480 ? 50 : 62; // room for the right-edge value tag
  const padT = 16;
  const padB = 22;
  const innerW = Math.max(0, W - padL - padR);
  const innerH = Math.max(0, H - padT - padB);
  const x = (i: number) => padL + (N <= 1 ? 0 : (i / (N - 1)) * innerW);
  const y = (v: number) => padT + (1 - (v - yMin) / span) * innerH;

  const idx = points.map((p, i) => ({ p, i })).filter(({ p }) => p.y != null);
  const meanPts = idx.map(({ p, i }) => [x(i), y(p.y as number)] as const);
  const hiPts = idx.map(({ p, i }) => [x(i), y(p.hi ?? (p.y as number))] as const);
  const loPts = idx.map(({ p, i }) => [x(i), y(p.lo ?? (p.y as number))] as const);
  const hasBand = idx.some(({ p }) => p.lo != null && p.hi != null);

  const meanPath = smoothPath(meanPts);
  const hiPath = smoothPath(hiPts);
  const loPath = smoothPath(loPts);
  // Closed cone: forward along the high edge, down the right side, back along
  // the low edge (smoothed, reversed), close.
  const bandFill = hasBand ? `${hiPath} L${smoothPath([...loPts].reverse()).slice(1)} Z` : "";

  const lastY = last != null ? y(last) : 0;

  // Y gridlines + ticks (shared decimals via axisLabels).
  const tCount = Math.max(2, Math.min(5, Math.floor(innerH / 46)));
  const tickVals = Array.from({ length: tCount + 1 }, (_, i) => yMax - (i / tCount) * span);
  const tickLabels = axisLabels(tickVals);

  return (
    <div ref={ref} className="relative h-full min-h-0 w-full overflow-hidden">
      {yLabel && (
        <span className="pointer-events-none absolute left-1 top-1 z-10 text-[10px] uppercase text-term-dim">
          {yLabel}
        </span>
      )}
      {W > 90 && H > 56 && (
        <svg className="block h-full w-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {/* plot frame */}
          <rect
            x={snap(padL)}
            y={snap(padT)}
            width={innerW}
            height={innerH}
            fill="none"
            stroke="var(--color-term-border)"
            shapeRendering="crispEdges"
          />
          {/* y grid + ticks */}
          {tickVals.map((_v, i) => {
            const yy = padT + (i / tCount) * innerH;
            return (
              <g key={`y${i}`}>
                <line
                  x1={padL}
                  x2={padL + innerW}
                  y1={snap(yy)}
                  y2={snap(yy)}
                  stroke="var(--color-term-grid)"
                  shapeRendering="crispEdges"
                />
                <line
                  x1={padL - 4}
                  x2={padL}
                  y1={snap(yy)}
                  y2={snap(yy)}
                  stroke="var(--color-term-border-hi)"
                  shapeRendering="crispEdges"
                />
                <text
                  x={padL - 6}
                  y={Math.round(yy) + 3}
                  textAnchor="end"
                  fontSize="10"
                  fill="var(--color-term-dim)"
                  fontFamily={MONO}
                  textRendering="geometricPrecision"
                >
                  {tickLabels[i]}
                </text>
              </g>
            );
          })}
          {/* x grid + date ticks */}
          {xLabels?.map((lab, k) => {
            const frac = xLabels.length === 1 ? 0 : k / (xLabels.length - 1);
            const xx = padL + frac * innerW;
            const anchor = k === 0 ? "start" : k === xLabels.length - 1 ? "end" : "middle";
            return (
              <g key={`x${k}`}>
                <line
                  x1={snap(xx)}
                  x2={snap(xx)}
                  y1={padT}
                  y2={padT + innerH}
                  stroke="var(--color-term-grid)"
                  shapeRendering="crispEdges"
                />
                <line
                  x1={snap(xx)}
                  x2={snap(xx)}
                  y1={padT + innerH}
                  y2={padT + innerH + 4}
                  stroke="var(--color-term-border-hi)"
                  shapeRendering="crispEdges"
                />
                <text
                  x={Math.round(xx)}
                  y={padT + innerH + 14}
                  textAnchor={anchor}
                  fontSize="10"
                  fill="var(--color-term-dim)"
                  fontFamily={MONO}
                  textRendering="geometricPrecision"
                >
                  {lab}
                </text>
              </g>
            );
          })}
          {/* 90% band — in-hue cone (fill + dashed edges in the line colour) */}
          {hasBand && (
            <>
              <path d={bandFill} fill={stroke} fillOpacity="0.10" stroke="none" />
              <path
                d={hiPath}
                fill="none"
                stroke={stroke}
                strokeOpacity="0.35"
                strokeWidth="1"
                strokeDasharray="2 3"
                vectorEffect="non-scaling-stroke"
              />
              <path
                d={loPath}
                fill="none"
                stroke={stroke}
                strokeOpacity="0.35"
                strokeWidth="1"
                strokeDasharray="2 3"
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
          {/* mean / probability line */}
          <path
            d={meanPath}
            fill="none"
            stroke={stroke}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            shapeRendering="geometricPrecision"
            vectorEffect="non-scaling-stroke"
          />
          {/* current level + right-edge value tag */}
          {last != null && (
            <>
              <line
                x1={padL}
                x2={padL + innerW}
                y1={snap(lastY)}
                y2={snap(lastY)}
                stroke={stroke}
                strokeDasharray="2 3"
                strokeOpacity="0.6"
                shapeRendering="crispEdges"
              />
              <rect
                x={Math.round(padL + innerW) + 1}
                y={Math.round(lastY) - 8}
                width={padR - 4}
                height={16}
                fill={stroke}
                shapeRendering="crispEdges"
              />
              <text
                x={Math.round(padL + innerW + (padR - 4) / 2 + 1)}
                y={Math.round(lastY) + 4}
                textAnchor="middle"
                fontSize="10.5"
                fill="#000"
                fontFamily={MONO}
                fontWeight="700"
                textRendering="geometricPrecision"
              >
                {formatY(last)}
              </text>
            </>
          )}
        </svg>
      )}
    </div>
  );
}
