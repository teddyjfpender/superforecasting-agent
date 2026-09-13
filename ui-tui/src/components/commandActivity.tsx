import { useStore } from '@nanostores/react'
import { Box, Text } from '@superforecasting/ink'

import { $commands } from '../app/commandStore.js'
import { $uiSessionId, $uiTheme } from '../app/uiStore.js'
import { stripAnsi } from '../lib/text.js'

export function CommandActivity() {
  const commands = useStore($commands)
  const sid = useStore($uiSessionId)
  const theme = useStore($uiTheme)
  const active = commands.filter(command => command.sessionId === sid)

  if (!active.length) {
    return null
  }

  const last = active.at(-1)!
  const preview = stripAnsi(last.output).replace(/\s+/g, ' ').trim().slice(-160)

  return (
    <Box flexDirection="column" flexShrink={0}>
      <Text color={theme.color.accent} wrap="truncate">
        {last.cancelling ? 'Cancelling' : 'Running'} /{last.name}
        {active.length > 1 ? ` · ${active.length} commands` : ''} · Ctrl+C to cancel
      </Text>
      {preview ? (
        <Text color={theme.color.muted} wrap="truncate">
          {preview}
        </Text>
      ) : null}
    </Box>
  )
}
