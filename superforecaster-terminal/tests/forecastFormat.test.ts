import { expect, test } from "bun:test";
import {
  chartScale,
  compactNumber,
  deltaLabel,
  headlineCompact,
  headlineLabel,
  historyToBandPoints,
  matchesFilter,
  pct,
  shortUnit,
} from "../src/forecastFormat";
import type { ForecastWorkspaceItem } from "../src/forecastFormat";

// A distribution forecast whose `headline_probability` (the mean, 3.1) would
// misrender as "310%" if the formatter treated it as a probability. This is the
// load-bearing rule the SF screen depends on.
const distItem: ForecastWorkspaceItem = {
  id: "cpi",
  title: "CPI MoM",
  headline_kind: "distribution",
  headline_probability: 3.1,
  units: "percent",
  delta: 0.2,
  distribution: { mean: 3.1, sd: 0.1, median: 3.0, ci50: [2.9, 3.2], ci90: [2.7, 3.5], pmf: null },
};

const probItem: ForecastWorkspaceItem = {
  id: "rain",
  title: "Rain tomorrow",
  headline_kind: "probability",
  headline_probability: 0.62,
  delta: 0.03,
};

test("a distribution mean renders as μ, never as a percent of the prob field", () => {
  expect(headlineCompact(distItem)).toBe("μ3.1%");
  expect(headlineLabel(distItem)).toContain("μ 3.1%");
  expect(headlineLabel(distItem)).toContain("σ 0.1");
  expect(headlineCompact(distItem)).not.toContain("310");
});

test("a probability headline renders as a percent", () => {
  expect(headlineCompact(probItem)).toBe("62%");
  expect(headlineLabel(probItem)).toBe("62%");
});

test("deltaLabel uses Δμ (outcome units) for distributions and pt for probabilities", () => {
  expect(deltaLabel(distItem)).toContain("Δμ");
  expect(deltaLabel(probItem)).toContain("pt");
});

test("matchesFilter spans title / domain / id / topics", () => {
  const item: ForecastWorkspaceItem = {
    id: "x",
    title: "Hurricane count",
    domain: "climate",
    topics: ["atlantic"],
  };
  expect(matchesFilter(item, "")).toBe(true);
  expect(matchesFilter(item, "hurricane")).toBe(true);
  expect(matchesFilter(item, "climate")).toBe(true);
  expect(matchesFilter(item, "atlantic")).toBe(true);
  expect(matchesFilter(item, "zzz")).toBe(false);
});

test("historyToBandPoints uses the explicit 90% band for distributions", () => {
  const item: ForecastWorkspaceItem = {
    headline_kind: "distribution",
    history: [
      { headline_probability: 3.0, band_low: 2.5, band_high: 3.6 },
      { headline_probability: 3.1, band_low: 2.7, band_high: 3.5 },
    ],
  };
  const pts = historyToBandPoints(item);
  expect(pts.length).toBe(2);
  expect(pts[0]).toEqual({ y: 3.0, lo: 2.5, hi: 3.6 });
});

test("historyToBandPoints derives a confidence band for probabilities", () => {
  const item: ForecastWorkspaceItem = {
    headline_kind: "probability",
    confidence: 0.5,
    history: [{ headline_probability: 0.5, confidence: 0.5 }],
  };
  const pts = historyToBandPoints(item);
  expect(pts[0]?.y).toBe(0.5);
  expect(pts[0]?.lo).not.toBeNull();
  expect(pts[0]?.hi).not.toBeNull();
});

test("chartScale auto-zooms but clamps probability series to [0,1]", () => {
  const s = chartScale([{ y: 0.5, lo: 0.49, hi: 0.58 }]);
  expect(s.yMin).toBeGreaterThanOrEqual(0);
  expect(s.yMax).toBeLessThanOrEqual(1);
  expect(s.yMax).toBeGreaterThan(s.yMin);
});

test("compactNumber + pct primitives", () => {
  expect(compactNumber(73000)).toBe("73k");
  expect(pct(0.523)).toBe("52%");
  expect(pct(null)).toBe("—");
});

test("shortUnit abbreviates long unit strings for the axis caption", () => {
  expect(shortUnit("percent-year-over-year")).toBe("%");
  expect(shortUnit("degrees fahrenheit")).toBe("°F");
  expect(shortUnit("USD")).toBe("USD");
  expect(shortUnit("storm count")).toBe("#");
  expect(shortUnit("")).toBe("");
  expect(shortUnit("widgets").length).toBeLessThanOrEqual(5);
});
