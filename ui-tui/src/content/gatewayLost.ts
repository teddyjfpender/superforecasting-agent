import type { PanelSection } from '../types.js'

export const GATEWAY_LOST_TITLE = 'Gateway Lost'

const MAX_TAIL_LINES = 12

/**
 * Trim the captured stderr to the last few lines. The tail is the whole reason
 * `getLogTail` exists: "bad config" vs "corrupt ledger" vs "wrong python" are
 * one glance apart in stderr and indistinguishable from an exit code.
 */
export const gatewayFailureTail = (raw: string, limit = MAX_TAIL_LINES): string[] => {
  const lines = (raw || '')
    .split('\n')
    .map(line => line.trimEnd())
    .filter(Boolean)

  return lines.slice(-Math.max(1, limit))
}

/**
 * The terminal panel: what died, how many times we tried, what it printed, and
 * exactly what to do. Rendered into the transcript (the same affordance
 * `Setup Required` / `Auth Expired` use), so the `/`-prefixed rows are clickable
 * as well as typeable.
 */
export const buildGatewayLostSections = (info: {
  attempts: number
  reason: string
  stderrTail: string
}): PanelSection[] => {
  const tail = gatewayFailureTail(info.stderrTail)

  const tried =
    info.attempts > 0
      ? `Gave up after ${info.attempts} reconnect ${info.attempts === 1 ? 'attempt' : 'attempts'}.`
      : 'The gateway could not be restarted.'

  const sections: PanelSection[] = [
    {
      text: `The forecast gateway is not running, so every command will fail until it is back. ${tried}`
    },
    { rows: [['cause', info.reason || 'gateway exited']], title: 'Last failure' }
  ]

  if (tail.length) {
    // `items` (not `rows`): a log tail is one column of free text, and Panel
    // wraps items as full-width paragraphs instead of squeezing them into the
    // 20-wide key column a row would impose.
    sections.push({ items: tail, title: 'Gateway stderr' })
  }

  sections.push({
    rows: [
      ['/reconnect', 'restart the gateway now'],
      ['/logs', 'inspect the full gateway log'],
      ['/quit', 'exit the desk and relaunch']
    ],
    title: 'Actions'
  })

  return sections
}

/** The one-line status shown in the ready-state slot while a respawn is pending. */
export const reconnectingStatus = (attempt: number, max: number, delayMs: number): string => {
  const secs = Math.max(1, Math.round(delayMs / 1000))

  return `gateway lost · reconnecting ${attempt}/${max} in ${secs}s`
}
