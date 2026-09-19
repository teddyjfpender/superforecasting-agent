import { Text } from '@superforecasting/ink'
import { Children, type ComponentProps } from 'react'

import type { Theme } from '../theme.js'

// Only use for application-authored help, never article/message/document bodies.
// Backticks explicitly mark short keys in prose. Familiar named keys and chords
// are recognized too, as are single keys after "press" and in bracketed hints.
const keyPattern =
  /`([^`\n]{1,24})`|\b(?:Ctrl|Alt|Shift|Cmd|Meta)(?:[+-](?:Enter|Return|Tab|Esc|Space|[A-Za-z0-9/?]))+(?!\w)|\b(?:PgUp\/(?:PgDn|Dn)|PageUp|PageDown|PgUp|PgDn|Enter|Return|Escape|Esc|Tab|Space|Backspace|Delete)\b|\^[A-Z]|[↑↓←→⏎]+|(?<=^)[a-z0-9/?](?= )|(?<=· )[a-z0-9/?](?= )|(?<=\b[Pp]ress )[A-Za-z0-9/?](?!\w)|(?<=\[)[A-Za-z0-9/?](?=\s)|(?<=\bor )[A-Za-z0-9/?](?= (?:to|for)\b)/g

export function shortcutParts(text: string): { text: string; key: boolean }[] {
  const parts: { text: string; key: boolean }[] = []
  let end = 0

  for (const match of text.matchAll(keyPattern)) {
    if (match.index > end) {
      parts.push({ text: text.slice(end, match.index), key: false })
    }

    parts.push({ text: match[1] ?? match[0], key: true })
    end = match.index + match[0].length
  }

  if (end < text.length) {
    parts.push({ text: text.slice(end), key: false })
  }

  return parts
}

/** Theme-aware keyboard affordances without changing copy or input handling. */
export function ShortcutText({ t, children, ...props }: ComponentProps<typeof Text> & { t: Theme }) {
  return (
    <Text {...props}>
      {Children.map(children, child =>
        typeof child === 'string'
          ? shortcutParts(child).map((part, index) =>
              part.key ? (
                <Text bold color={t.color.accent} key={index}>
                  {part.text}
                </Text>
              ) : (
                part.text
              )
            )
          : child
      )}
    </Text>
  )
}
