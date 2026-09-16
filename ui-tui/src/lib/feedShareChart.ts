import type { FeedShare, SharedObservation } from '../protocol/generated.js'

/** Zero-based bars; missing observations leave gaps. Bounded independent of payload size. */
export function feedChartLines(
  points: SharedObservation[],
  type: FeedShare['presentation'],
  width: number,
  height = 5
): string[] {
  width = Math.max(1, Math.min(120, Math.floor(width)))
  height = Math.max(2, Math.min(8, Math.floor(height)))
  const values = points.map(p => p.value).filter((n): n is number => n !== null)

  if (!values.length) {
    return ['No numeric observations']
  }

  if (points.length < 2) {
    return ['Only one dated observation; trend unavailable']
  }

  const low = Math.min(0, ...values),
    high = Math.max(0, ...values)

  // Normalize before subtracting to avoid overflow on hostile finite numbers.
  const magnitude = Math.max(Math.abs(low), Math.abs(high), 1)

  const min = low / magnitude,
    max = high / magnitude

  const y = (value: number) => Math.round(((max - value / magnitude) / (max - min || 1)) * (height - 1))
  const zero = y(0)
  const grid = Array.from({ length: height }, (_, row) => Array<string>(width).fill(row === zero ? '─' : ' '))
  const firstDate = Date.parse(points[0]!.end)
  const span = Date.parse(points.at(-1)!.end) - firstDate || 1
  let previous: { x: number; y: number } | null = null
  points.forEach(point => {
    const x = Math.round(((Date.parse(point.end) - firstDate) / span) * (width - 1))

    if (point.value === null) {
      previous = null

      return
    }

    const row = y(point.value)

    if (type === 'bar-chart') {
      for (let r = Math.min(row, zero); r <= Math.max(row, zero); r++) {
        grid[r]![x] = r === zero ? '┼' : '█'
      }
    } else {
      if (previous) {
        for (let col = previous.x + 1; col < x; col++) {
          const r = Math.round(previous.y + ((row - previous.y) * (col - previous.x)) / (x - previous.x))
          grid[r]![col] = '·'
        }
      }

      grid[row]![x] = '●'
      previous = { x, y: row }
    }
  })

  const label = (value: number) =>
    Math.abs(value) >= 1e9 || (value !== 0 && Math.abs(value) < 1e-4)
      ? value.toExponential(3)
      : value.toLocaleString(undefined, { maximumFractionDigits: 6 })

  return [`${label(high)} max`, ...grid.map(row => row.join('')), `${label(low)} min · zero baseline`]
}
