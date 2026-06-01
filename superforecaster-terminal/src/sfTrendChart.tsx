// Dedicated SF trend chart — a small self-contained SVG. It does NOT touch the
// shared <Chart> (which the finance screens use with a raw-extrema domain).
//
// Fixes the three issues the generic <Chart> had on the forecast desk:
//   - FIT: the y-domain is the PADDED `chartScale(points)` (15% pad + a minimum
//     span + [0,1] clamp for probabilities), so the line never touches the top
//     or bottom edge / merges with the panel header.
//   - BAND: the 90% confidence band (lo..hi per snapshot) is shaded behind the
//     line as a filled polygon — the generic <Chart> could not draw it.
//   - CONTRAST: axis + tick labels render in term-text (not term-dim), and the
//     three y ticks share one decimal count + magnitude suffix via axisLabels.

import { useEffect, useRef, useState } from "react";
import { axisLabels, chartScale } from "./forecastFormat";
import type { BandPoint } from "./forecastFormat";

const MONO = "var(--font-mono)";

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
  const last = ys.length ? ys[ys.length - 1] : null;
  const stroke =
    (last ?? 0) >= first ? "var(--color-term-green)" : "var(--color-term-red)";

  const padL = W < 480 ? 52 : 64;
  const padR = 14;
  const padT = 18;
  const padB = 24;
  const innerW = Math.max(0, W - padL - padR);
  const innerH = Math.max(0, H - padT - padB);
  const x = (i: number) => padL + (N <= 1 ? 0 : (i / (N - 1)) * innerW);
  const y = (v: number) => padT + (1 - (v - yMin) / span) * innerH;

  const idx = points.map((p, i) => ({ p, i })).filter(({ p }) => p.y != null);
  const linePts = idx.map(({ p, i }) => `${x(i).toFixed(1)},${y(p.y as number).toFixed(1)}`).join(" ");
  const hiEdge = idx.map(({ p, i }) => `${x(i).toFixed(1)},${y(p.hi ?? (p.y as number)).toFixed(1)}`);
  const loEdge = idx
    .map(({ p, i }) => `${x(i).toFixed(1)},${y(p.lo ?? (p.y as number)).toFixed(1)}`)
    .reverse();
  const bandPts = [...hiEdge, ...loEdge].join(" ");
  const hasBand = idx.some(({ p }) => p.lo != null && p.hi != null);
  const lastIdx = idx[idx.length - 1];

  const [tL, mL, bL] = axisLabels([yMax, (yMax + yMin) / 2, yMin]);
  const yTicks = [
    { v: yMax, t: tL },
    { v: (yMax + yMin) / 2, t: mL },
    { v: yMin, t: bL },
  ];

  return (
    <div ref={ref} className="relative h-full min-h-0 w-full overflow-hidden">
      {W > 80 && H > 50 && (
        <svg className="block h-full w-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {/* plot frame */}
          <rect
            x={padL + 0.5}
            y={padT + 0.5}
            width={innerW}
            height={innerH}
            fill="none"
            stroke="var(--color-term-border)"
            shapeRendering="crispEdges"
          />
          {/* y grid + ticks (high-contrast labels) */}
          {yTicks.map((t, k) => (
            <g key={`y${k}`}>
              <line
                x1={padL}
                x2={padL + innerW}
                y1={y(t.v)}
                y2={y(t.v)}
                stroke="var(--color-term-grid)"
                shapeRendering="crispEdges"
              />
              <text
                x={padL - 6}
                y={y(t.v) + 3}
                textAnchor="end"
                fontSize="10"
                fill="var(--color-term-text)"
                fontFamily={MONO}
              >
                {t.t}
              </text>
            </g>
          ))}
          {/* 90% confidence band */}
          {hasBand && (
            <polygon
              points={bandPts}
              fill="var(--color-term-accent)"
              fillOpacity="0.14"
              stroke="var(--color-term-accent)"
              strokeOpacity="0.30"
              strokeWidth="0.75"
            />
          )}
          {/* mean / probability line */}
          <polyline
            points={linePts}
            fill="none"
            stroke={stroke}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
          {/* current-value marker + readout */}
          {lastIdx && (
            <>
              <circle
                cx={x(lastIdx.i)}
                cy={y(lastIdx.p.y as number)}
                r="2.5"
                fill={stroke}
                stroke="var(--color-term-panel)"
                strokeWidth="1"
              />
              {last != null && (
                <text
                  x={padL + innerW}
                  y={padT + 11}
                  textAnchor="end"
                  fontSize="11"
                  fontWeight="600"
                  fill={stroke}
                  fontFamily={MONO}
                >
                  {formatY(last)}
                </text>
              )}
            </>
          )}
          {/* x date labels */}
          {xLabels?.map((lab, k) => {
            const frac = xLabels.length === 1 ? 0 : k / (xLabels.length - 1);
            const anchor = k === 0 ? "start" : k === xLabels.length - 1 ? "end" : "middle";
            return (
              <text
                key={`x${k}`}
                x={padL + frac * innerW}
                y={padT + innerH + 14}
                textAnchor={anchor}
                fontSize="10"
                fill="var(--color-term-text)"
                fontFamily={MONO}
              >
                {lab}
              </text>
            );
          })}
          {/* y-axis caption, parked in the top gutter so it never overlaps a tick */}
          {yLabel && (
            <text
              x={padL - 6}
              y={11}
              textAnchor="end"
              fontSize="9"
              fill="var(--color-term-dim)"
              fontFamily={MONO}
              className="uppercase"
            >
              {yLabel}
            </text>
          )}
        </svg>
      )}
    </div>
  );
}
