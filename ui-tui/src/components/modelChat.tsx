import { Box, Text } from '@hermes/ink'

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
        <Box marginTop={1}>
          <Text color={sem.star}>{`${spinnerFrame(tick)} `}</Text>
          <Box width={Math.max(8, innerW - 2)}>
            <Text color={t.color.muted} wrap="truncate-end">
              {status?.trim() || 'working…'}
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
        {busy ? 'refining…' : '⏎ send · Esc close chat'}
      </Text>
    </Box>
  )
}
