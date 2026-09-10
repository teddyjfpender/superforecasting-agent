import { Box, Text } from '@superforecasting/ink'
import { useRef } from 'react'

import { spinnerFrame } from '../lib/icons.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

export interface ChatMessage {
  content: string
  role: string
}

// Render-only conversation panel for an open model. The parent (marketsView)
// owns the input + send keybinding; this shows the thread + the composer line.
export function ModelChat({
  busy,
  focused = true,
  input,
  messages,
  status,
  t,
  tick,
  width
}: {
  busy: boolean
  focused?: boolean
  input: string
  messages: ChatMessage[]
  status?: string
  t: Theme
  tick: number
  width: number
}) {
  const sem = semantics(t)
  const recent = messages.slice(-8)
  const innerW = Math.max(20, width - 2)

  // Elapsed seconds since the refine started (tick advances every 600ms) — a
  // reassurance the long agentic run is alive.
  const startTick = useRef<null | number>(null)

  if (busy) {
    if (startTick.current === null) {
      startTick.current = tick
    }
  } else {
    startTick.current = null
  }

  const elapsed = busy && startTick.current !== null ? Math.max(0, Math.round((tick - startTick.current) * 0.6)) : 0
  // Live step from the agent's tool calls; the generic 'refining' phase reads as
  // "thinking…" so it doesn't echo the "Refining the model" header.
  const step = status && status.trim() && status.trim() !== 'refining' ? status.trim() : 'thinking…'

  return (
    <Box flexDirection="column" flexShrink={0} width={innerW}>
      <Text bold color={focused ? t.color.accent : t.color.muted} wrap="truncate-end">
        {focused ? '▸ CONVERSATION' : '  CONVERSATION'}
        {focused ? '' : '  · Tab to focus'}
      </Text>
      {recent.length === 0 ? (
        <Text color={t.color.muted}>Ask a follow-up to refine the model (add data, change the method, extend the horizon).</Text>
      ) : (
        recent.map((m, i) => (
          <Box flexDirection="column" key={i} marginTop={i ? 1 : 0}>
            <Text color={m.role === 'user' ? sem.cursor : t.color.label}>{m.role === 'user' ? 'you' : 'desk'}</Text>
            <Box width={innerW}>
              <Text color={t.color.text} wrap="wrap">
                {m.content}
              </Text>
            </Box>
          </Box>
        ))
      )}
      {busy ? (
        <Box flexDirection="column" marginTop={1}>
          <Box>
            <Text color={sem.star}>{`${spinnerFrame(tick)} `}</Text>
            <Text bold color={t.color.text}>
              Refining the model
            </Text>
            <Text color={t.color.muted}>{`  ${elapsed}s`}</Text>
          </Box>
          <Box marginLeft={2} width={Math.max(8, innerW - 2)}>
            <Text color={t.color.muted} wrap="truncate-end">
              {step}
            </Text>
          </Box>
        </Box>
      ) : (
        <Box marginTop={1}>
          <Text color={t.color.muted}>{'› '}</Text>
          <Text color={t.color.text}>{input}</Text>
          <Text color={t.color.text} inverse>
            {' '}
          </Text>
        </Box>
      )}
      <Text color={t.color.muted} wrap="truncate-end">
        {busy ? 'researching + recomputing — this can take a minute' : '⏎ send · Esc close chat'}
      </Text>
    </Box>
  )
}
