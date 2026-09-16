import { Box, ScrollBox, type ScrollBoxHandle, Text } from '@superforecasting/ink'
import { useRef } from 'react'

import { inputVisualHeight } from '../lib/inputMetrics.js'
import type { Theme } from '../theme.js'

import { TextInput } from './textInput.js'

export const messageComposerRows = (text: string, columns: number, availableRows: number): number =>
  Math.max(1, Math.min(inputVisualHeight(text, columns), Math.max(1, Math.min(6, Math.floor(availableRows / 3) - 1))))

/** Bounded editor shared by chat-sized layouts; the caller owns durable drafts and sends. */
export function MessageComposer({
  text,
  columns,
  inputRows,
  active,
  busy,
  t,
  multiline = false,
  hasAttachment = false,
  onChange,
  onSend,
  onBack
}: {
  text: string
  columns: number
  inputRows: number
  active: boolean
  busy: boolean
  t: Theme
  multiline?: boolean
  hasAttachment?: boolean
  onChange: (text: string) => void
  onSend: (text: string) => void
  onBack: () => void
}) {
  const scroll = useRef<ScrollBoxHandle>(null)

  return (
    <Box
      borderColor={active ? t.color.accent : t.color.border}
      borderStyle="round"
      flexDirection="column"
      flexShrink={0}
      height={inputRows + 3}
      marginTop={1}
      paddingX={1}
    >
      <ScrollBox decstbm={false} flexShrink={0} followContent={false} height={inputRows} ref={scroll}>
        <TextInput
          columns={columns}
          focus={active}
          immediateChange
          multiline={multiline}
          onChange={onChange}
          onCursorLine={line => scroll.current?.scrollTo(Math.max(0, line - inputRows + 1))}
          onLeftBoundary={onBack}
          onSubmit={onSend}
          placeholder="Write a message…"
          value={text}
        />
      </ScrollBox>
      <Box flexShrink={0} justifyContent="space-between">
        <Text color={t.color.muted} wrap="truncate-end">
          {multiline ? 'Enter newline' : 'Shift+Enter newline'}
        </Text>
        <Box
          onClick={() => {
            if (active && !busy && (text.trim() || hasAttachment)) {
              onSend(text)
            }
          }}
        >
          <Text bold color={active && !busy && (text.trim() || hasAttachment) ? t.color.accent : t.color.muted}>
            {busy ? '◷' : multiline ? '[Ctrl+Enter send]' : '[Enter send]'}
          </Text>
        </Box>
      </Box>
    </Box>
  )
}
