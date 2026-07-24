import { Box, Text } from '@hermes/ink'
import { useEffect, useState } from 'react'

import { BERNARD_ANIMATION, type BernardAnimation } from '../content/bernardAnimation.js'

// Off-switch: any of the TUI alias triples set to a falsey string disables the
// animated desk header (some users want a still terminal). Read once at module
// load — it's decorative, not reactive.
const DISABLED = (() => {
  for (const key of [
    'SUPERFORECASTING_AGENT_TUI_DESK_ANIMATION',
    'FORECAST_TUI_DESK_ANIMATION',
    'HERMES_TUI_DESK_ANIMATION'
  ]) {
    const v = (process.env[key] ?? '').trim().toLowerCase()

    if (v === '0' || v === 'off' || v === 'false' || v === 'no') {
      return true
    }
  }

  return false
})()

interface AsciiAnimationProps {
  // Pause the timer when the rail it lives in isn't on screen, so a narrow
  // terminal (no rail) doesn't burn cycles re-rendering an unseen header.
  active?: boolean
  animation?: BernardAnimation
}

// A frame-cycling colored-ASCII header. Each frame is rows of run-length spans
// {t, c} where c indexes the palette (-1 = transparent → rendered as plain
// spaces). Re-renders only the small grid at the animation's own fps.
export function AsciiAnimation({ active = true, animation = BERNARD_ANIMATION }: AsciiAnimationProps) {
  const [frameIdx, setFrameIdx] = useState(0)
  const frameCount = animation.frames.length

  useEffect(() => {
    if (DISABLED || !active || frameCount <= 1) {
      return
    }

    const intervalMs = Math.max(40, Math.round(1000 / (animation.fps || 12)))

    const timer = setInterval(() => {
      setFrameIdx(i => (i + 1) % frameCount)
    }, intervalMs)

    return () => clearInterval(timer)
  }, [active, frameCount, animation.fps])

  if (DISABLED) {
    return null
  }

  const frame = animation.frames[Math.min(frameIdx, frameCount - 1)] ?? []

  return (
    <Box flexDirection="column">
      {frame.map((row, y) => (
        <Text key={y} wrap="truncate-end">
          {row.map((span, i) => {
            const color = span.c >= 0 ? animation.palette[span.c] : undefined

            // Half-block cells carry an optional background color (the lower
            // sub-pixel) so a `▀` paints two stacked colors in one cell — 2x
            // vertical resolution. Plain full-block cells omit `b`.
            const bg =
              span.b !== undefined && span.b >= 0 ? animation.palette[span.b] : undefined

            if (!color && !bg) {
              return <Text key={i}>{span.t}</Text>
            }

            return (
              <Text backgroundColor={bg} color={color} key={i}>
                {span.t}
              </Text>
            )
          })}
        </Text>
      ))}
    </Box>
  )
}
