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

// A horizontal bar of `width` cells filling to `fraction` (0..1), using the
// eighth-block glyphs so a partial final cell renders sub-character precision.
// Pure + tested — used by the distribution bars in the Prediction Markets pane.
const HBLOCKS = '▏▎▍▌▋▊▉█'

export const hbar = (fraction: number, width: number): string => {
  if (!Number.isFinite(fraction) || width <= 0) {
    return ''
  }

  const clamped = Math.max(0, Math.min(1, fraction))
  const eighths = Math.round(clamped * width * 8)
  const full = Math.floor(eighths / 8)
  const rem = eighths % 8
  const body = '█'.repeat(Math.min(full, width))

  if (full >= width || rem === 0) {
    return body.slice(0, width)
  }

  return `${body}${HBLOCKS[rem - 1]}`
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
