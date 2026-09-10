import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text } from '@superforecasting/ink'
import type { ReactNode, RefObject } from 'react'

import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

// The ONE shared modal-overlay primitive. Every view's modal paints THROUGH this
// so the interaction design is identical: the box IS the absolute element (not a
// full-width centering wrapper — that clears a cols-wide band of the body and
// reflows it; not inset:0 — that gets 0 size under an indefinite-height parent),
// with EXPLICIT width/height/left/top to centre it, a solid black opaque interior
// (a theme bg token like completionBg tints it), so the view body stays visible
// AROUND it. The view that mounts this MUST: render its body unconditionally +
// stack the overlay LAST, trap the keyboard (if (modalOpen) return in useInput),
// and gate the still-visible body's MOUSE handlers (onClick/onSelect) while open.

const clip = (value: string, max: number): string => (value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value)

export function ModalOverlay({
  children,
  cols,
  footerHint,
  maxHeight = 36,
  maxWidth = 100,
  rows,
  scrollRef,
  t,
  tick = 0,
  title,
}: {
  children: ReactNode
  cols: number
  /** one-line hint under the content (e.g. "↑↓ scroll · Esc close"); omit for none */
  footerHint?: string
  /** cap the box height; short forms pass a small value so the box hugs content */
  maxHeight?: number
  /** cap the box width (wide terminals) */
  maxWidth?: number
  rows: number
  /** pass a ref to wrap children in a scroll viewport (+ scrollbar); omit for forms */
  scrollRef?: RefObject<null | ScrollBoxHandle>
  t: Theme
  tick?: number
  title?: string
}) {
  const narrow = cols < 100
  const modalW = narrow ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, maxWidth))
  const modalH = Math.max(8, Math.min(rows - 6, maxHeight))
  // Computed offsets centre the box deterministically (alignItems on an absolute
  // box doesn't reliably centre, and a full-width centring wrapper reflows the body).
  const modalTop = Math.max(0, Math.floor((rows - modalH) / 2) - 1)
  const modalLeft = Math.max(0, Math.floor((cols - modalW) / 2))

  // The content region's height = box minus border(2) + padding(2) + title(1) +
  // footer(1). A ScrollBox needs an EXPLICIT height (flexGrow doesn't resolve under
  // absolute positioning); forms render directly and manage their own layout.
  const contentH = Math.max(3, modalH - 4 - (title ? 1 : 0) - (footerHint ? 1 : 0))

  const body = scrollRef ? (
    <Box flexDirection="row" flexShrink={0} height={contentH} minHeight={0}>
      <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
        {children}
      </ScrollBox>
      <NoSelect flexShrink={0} marginLeft={1}>
        <OverlayScrollbar scrollRef={scrollRef} t={t} tick={tick} />
      </NoSelect>
    </Box>
  ) : (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0}>
      {children}
    </Box>
  )

  return (
    <Box
      backgroundColor="black"
      borderColor={t.color.accent}
      borderStyle="round"
      flexDirection="column"
      height={modalH}
      left={modalLeft}
      paddingX={2}
      paddingY={1}
      position="absolute"
      top={modalTop}
      width={modalW}
    >
      {title ? (
        <Text bold color={t.color.primary} wrap="truncate-end">
          {clip(title, Math.max(10, modalW - 6))}
        </Text>
      ) : null}
      {title ? <Box flexGrow={1} flexShrink={1} marginTop={1} minHeight={0}>{body}</Box> : body}
      {footerHint ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {footerHint}
        </Text>
      ) : null}
    </Box>
  )
}
