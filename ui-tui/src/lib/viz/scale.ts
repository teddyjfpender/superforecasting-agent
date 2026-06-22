// Scales, nice ticks, and downsampling — hand-rolled (no d3-scale dependency).
// Just the math the charts need: a linear domain→range map, the D3 1/2/5·10^k
// nice-tick algorithm, domain nicing, and LTTB downsampling for dense series.

export interface Scale {
  (v: number): number // domain value → range coord
  domain: [number, number]
  invert: (px: number) => number
}

export const linear = (domain: [number, number], range: [number, number]): Scale => {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1
  const fn = ((v: number) => r0 + ((v - d0) / span) * (r1 - r0)) as Scale
  fn.domain = domain
  fn.invert = (px: number) => d0 + ((px - r0) / (r1 - r0 || 1)) * span

  return fn
}

// Choose a "nice" step (1·10^k, 2·10^k, or 5·10^k) bracketing the raw step.
export const tickIncrement = (lo: number, hi: number, count: number): number => {
  const raw = (hi - lo) / Math.max(1, count)

  if (!(raw > 0)) {
    return 1
  }

  const pow = Math.floor(Math.log10(raw))
  const base = Math.pow(10, pow)
  const err = raw / base // in [1,10)
  const f = err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1

  return f * base
}

export const niceTicks = (lo: number, hi: number, count = 5): number[] => {
  if (lo === hi) {
    return [lo]
  }

  const step = tickIncrement(lo, hi, count)
  const start = Math.ceil(lo / step) * step
  const stop = Math.floor(hi / step) * step
  const n = Math.max(0, Math.round((stop - start) / step))

  // Multiply (not accumulate) to avoid floating-point drift.
  return Array.from({ length: n + 1 }, (_, i) => start + i * step)
}

// Snap a domain outward to the nice-step grid (D3 .nice()).
export const niceDomain = (lo: number, hi: number, count = 5): [number, number] => {
  if (lo === hi) {
    return lo === 0 ? [0, 1] : [Math.min(0, lo), Math.max(0, hi)]
  }

  const step = tickIncrement(lo, hi, count)

  return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step]
}

// Largest-Triangle-Three-Buckets downsampling: reduce `data` ([x,y]) to
// `threshold` points while preserving visual peaks/valleys. O(n).
export const lttb = (data: ReadonlyArray<[number, number]>, threshold: number): [number, number][] => {
  const n = data.length

  if (threshold >= n || threshold < 3) {
    return data.map(p => [p[0], p[1]])
  }

  const sampled: [number, number][] = [[data[0]![0], data[0]![1]]]
  const bucketSize = (n - 2) / (threshold - 2)
  let a = 0

  for (let i = 0; i < threshold - 2; i++) {
    // Average point of the next bucket (the triangle's third vertex).
    const rangeStart = Math.floor((i + 1) * bucketSize) + 1
    const rangeEnd = Math.min(Math.floor((i + 2) * bucketSize) + 1, n)
    let avgX = 0
    let avgY = 0
    const len = Math.max(1, rangeEnd - rangeStart)

    for (let j = rangeStart; j < rangeEnd; j++) {
      avgX += data[j]![0]
      avgY += data[j]![1]
    }

    avgX /= len
    avgY /= len

    // Pick the point in this bucket that maximizes triangle area with `a`.
    const curStart = Math.floor(i * bucketSize) + 1
    const curEnd = Math.floor((i + 1) * bucketSize) + 1
    const [ax, ay] = data[a]!
    let maxArea = -1
    let next = curStart

    for (let j = curStart; j < curEnd; j++) {
      const area = Math.abs((ax - avgX) * (data[j]![1] - ay) - (ax - data[j]![0]) * (avgY - ay))

      if (area > maxArea) {
        maxArea = area
        next = j
      }
    }

    sampled.push([data[next]![0], data[next]![1]])
    a = next
  }

  sampled.push([data[n - 1]![0], data[n - 1]![1]])

  return sampled
}
