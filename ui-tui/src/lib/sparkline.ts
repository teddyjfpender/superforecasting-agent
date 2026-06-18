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
