import { Text } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import unicodeSpinners from 'unicode-animations'

import { $liveBaseTokens, $liveStartedAt, $liveTick } from '../app/liveTickStore.js'
import { getTurnState } from '../app/turnStore.js'
import { getUiState } from '../app/uiStore.js'
import { fmtDuration } from '../domain/messages.js'
import { sweepColor, sweepStops } from '../lib/accentSweep.js'
import { abbrevTokens, activityAdjective, turnTokenCount } from '../lib/liveStatus.js'
import type { Theme } from '../theme.js'

const SPINNER = unicodeSpinners.braille

// The leading segment of the status bar — the ONE thing that animates while a
// turn runs. It subscribes to the $liveTick heartbeat and to NOTHING else: the
// turn/usage state it renders is SAMPLED imperatively at tick rate, so a burst
// of streaming deltas can never re-render the bar faster than the heartbeat, and
// the whole line stays a one-row-per-tick diff. Idle keeps $liveTick pinned at 0,
// so this subscription is inert and the component only re-renders when its parent
// (a rare status change) does — the render-isolation wins hold.
export function LiveStatus({
  busy,
  status,
  statusColor,
  t
}: {
  busy: boolean
  status: string
  statusColor: string
  t: Theme
}) {
  const tick = useStore($liveTick)

  if (!busy) {
    // Byte-identical to the pre-heartbeat bar: the border prefix + plain status.
    return (
      <>
        <Text color={t.color.border}>{'─ '}</Text>
        <Text color={statusColor}>{status}</Text>
      </>
    )
  }

  const turn = getTurnState()
  const startedAt = $liveStartedAt.get()

  const glyph = SPINNER.frames[tick % SPINNER.frames.length] ?? '⠋'
  // The glyph sweeps the brand accent family while busy (the "alive" cue); the
  // verb keeps the status colour so an error/warn tint still reads.
  const glyphColor = sweepColor(sweepStops(t), tick)
  const adjective = activityAdjective(turn)
  const elapsed = startedAt ? fmtDuration(Date.now() - startedAt) : '0s'
  const tokens = abbrevTokens(turnTokenCount(turn, getUiState().usage, $liveBaseTokens.get()))

  return (
    <>
      <Text color={glyphColor}>{glyph}</Text>
      <Text color={statusColor}>{` ${adjective}… `}</Text>
      <Text color={t.color.muted}>{elapsed}</Text>
      <Text color={t.color.muted}>{' · '}</Text>
      <Text color={t.color.info}>{tokens}</Text>
      <Text color={t.color.muted}>{' tokens'}</Text>
    </>
  )
}
