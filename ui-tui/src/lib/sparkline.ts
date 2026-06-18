// Unicode block sparkline: map a numeric series onto ▁▂▃▄▅▆▇█. Pure + tested.

const TICKS = '▁▂▃▄▅▆▇█'

export const sparkline = (values: number[], maxPoints = 0): string => {
  const series = (maxPoints > 0 ? values.slice(-maxPoints) : values).filter(n => Number.isFinite(n))

  if (series.length < 2) {
    return ''
  }

  const min = Math.min(...series)
  const max = Math.max(...series)
  const range = max - min || 1

  return series
    .map(n => {
      const idx = Math.round(((n - min) / range) * (TICKS.length - 1))

      return TICKS[Math.min(TICKS.length - 1, Math.max(0, idx))]
    })
    .join('')
}

// A filled block area-chart, `height` rows tall × up to `width` columns, oldest
// → newest. Each column rises to its normalized value; partial top cells use
// the eighth-blocks. Returns lines top→bottom (use a fixed-width font).
const FILL = ' ▁▂▃▄▅▆▇█'

export const blockChart = (values: number[], width: number, height: number): string[] => {
  const clean = values.filter(n => Number.isFinite(n))
  const series = clean.length > width ? clean.slice(-width) : clean

  if (series.length < 2 || height < 1) {
    return []
  }

  const min = Math.min(...series)
  const max = Math.max(...series)
  const range = max - min || 1
  const norm = series.map(n => ((n - min) / range) * height) // 0..height

  const lines: string[] = []

  for (let row = height - 1; row >= 0; row--) {
    let line = ''

    for (const level of norm) {
      if (level >= row + 1) {
        line += '█'
      } else if (level <= row) {
        line += ' '
      } else {
        line += FILL[Math.max(0, Math.min(8, Math.round((level - row) * 8)))]
      }
    }

    lines.push(line)
  }

  return lines
}
