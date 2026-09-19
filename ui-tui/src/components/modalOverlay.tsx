import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text } from '@superforecasting/ink'
import type { ReactNode, RefObject } from 'react'

import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'
import { ShortcutText } from './shortcutText.js'

// The ONE shared modal-overlay primitive. Every view's modal paints THROUGH this
// so the interaction design is identical: the box IS the absolute element (not a
// full-width centering wrapper — that clears a cols-wide band of the body and
// reflows it; not inset:0 — that gets 0 size under an indefinite-height parent),
// with EXPLICIT width/height/left/top to centre it, a solid black opaque interior
// (a theme bg token like completionBg tints it), so the view body stays visible
// AROUND it. The view that mounts this MUST: render its body unconditionally +
// stack the overlay LAST, trap the keyboard (if (modalOpen) return in useInput),
// and gate the still-visible body's MOUSE handlers (onClick/onSelect) while open.

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
  verticalMargin = 6
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
  /** Total rows reserved outside the modal; compact scan dialogs may use 2. */
  verticalMargin?: number
}) {
  const narrow = cols < 100
  const modalW = Math.max(1, Math.min(cols, maxWidth, cols - (narrow ? 2 : 6)))
  const modalH = Math.max(1, Math.min(rows, maxHeight, Math.max(8, rows - verticalMargin)))
  const bordered = modalH >= 4 && modalW >= 8
  const paddingX = bordered ? (modalW < 48 ? 1 : 2) : 0
  const paddingY = modalH < 12 ? 0 : 1
  const showTitle = Boolean(title) && modalH >= 6
  const contentH = Math.max(0, modalH - (bordered ? 2 : 0) - 2 * paddingY - (showTitle ? 2 : 0) - (footerHint ? 1 : 0))
  // Computed offsets centre the box deterministically (alignItems on an absolute
  // box doesn't reliably centre, and a full-width centring wrapper reflows the body).
  const modalTop = Math.max(0, Math.floor((rows - modalH) / 2) - 1)
  const modalLeft = Math.max(0, Math.floor((cols - modalW) / 2))

  // Compact windows surrender decorative padding/title before the exit hint.
  const body = scrollRef ? (
    <Box flexDirection="row" flexShrink={0} height={contentH} minHeight={0} overflow="hidden">
      <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} height={contentH} ref={scrollRef}>
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
      borderStyle={bordered ? 'round' : undefined}
      flexDirection="column"
      height={modalH}
      left={modalLeft}
      overflow="hidden"
      paddingX={paddingX}
      paddingY={paddingY}
      position="absolute"
      top={modalTop}
      width={modalW}
    >
      {showTitle ? (
        <Text bold color={t.color.primary} flexShrink={0} wrap="truncate-end">
          {title}
        </Text>
      ) : null}
      {showTitle ? (
        <Box flexGrow={1} flexShrink={1} marginTop={1} minHeight={0}>
          {body}
        </Box>
      ) : (
        body
      )}
      {footerHint ? (
        <ShortcutText color={t.color.muted} flexShrink={0} t={t} wrap="truncate-end">
          {footerHint}
        </ShortcutText>
      ) : null}
    </Box>
  )
}
