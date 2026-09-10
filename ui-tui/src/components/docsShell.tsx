import { Box, NoSelect, Text } from '@superforecasting/ink'

import type { Theme } from '../theme.js'

import type { DocKind } from './docsView.js'

// ── Shared Docs chrome ────────────────────────────────────────────────────
// Both Docs branches (Markdown vault + LaTeX workspace) wear the same shell so
// they read as ONE view: a header line (title + status segments + path), a
// lens/tab strip for the doc KINDS right beneath it (house pattern — Markets /
// Desk put their tabs up top, not in the footer), and shared list-row meta
// helpers (relative age + a size chip) so rows in either branch look alike.

// Relative age for a note/file timestamp. Accepts epoch ms, epoch seconds, an
// ISO string, or a numeric string; returns a compact token (now/5m/2h/3d/4mo).
export const docAge = (value: number | string | undefined): string => {
  if (value === undefined || value === null || value === '') {
    return ''
  }

  let ms: number

  if (typeof value === 'number') {
    ms = value
  } else if (/^\d+(\.\d+)?$/.test(value.trim())) {
    ms = Number(value)
  } else {
    ms = Date.parse(value)
  }

  if (!Number.isFinite(ms) || ms <= 0) {
    return ''
  }

  // Heuristic: values below ~1e12 are epoch SECONDS, not milliseconds.
  if (ms < 1e12) {
    ms *= 1000
  }

  const secs = Math.max(0, Math.floor((Date.now() - ms) / 1000))

  if (secs < 45) {
    return 'now'
  }

  const mins = Math.floor(secs / 60)

  if (mins < 60) {
    return `${mins}m`
  }

  const hours = Math.floor(mins / 60)

  if (hours < 24) {
    return `${hours}h`
  }

  const days = Math.floor(hours / 24)

  if (days < 30) {
    return `${days}d`
  }

  const months = Math.floor(days / 30)

  if (months < 12) {
    return `${months}mo`
  }

  return `${Math.floor(months / 12)}y`
}

// Title-priority truncation for a slash path (the deskView QCOMFORT pattern):
// the leaf name (the "title") is protected; the parent directory is what gets
// shrunk first, ellipsised from the LEFT so the meaningful tail survives. Only
// when the leaf itself can't fit is it truncated from the right.
export const titlePath = (path: string, width: number): { base: string; dir: string } => {
  const base = path.split('/').pop() ?? path
  const rawDir = path.slice(0, path.length - base.length)

  if (base.length >= width) {
    return { base: width > 1 ? `${base.slice(0, width - 1)}…` : base.slice(0, width), dir: '' }
  }

  const room = width - base.length

  if (rawDir.length <= room) {
    return { base, dir: rawDir }
  }

  return { base, dir: room > 1 ? `…${rawDir.slice(rawDir.length - (room - 1))}` : '' }
}

// Compact byte-size chip: 820 B · 1.2K · 3.4M.
export const sizeChip = (bytes: number | undefined): string => {
  if (!bytes || bytes < 0) {
    return ''
  }

  if (bytes < 1024) {
    return `${bytes} B`
  }

  if (bytes < 1024 * 1024) {
    const k = bytes / 1024

    return `${k < 10 ? k.toFixed(1) : Math.round(k)}K`
  }

  const m = bytes / (1024 * 1024)

  return `${m < 10 ? m.toFixed(1) : Math.round(m)}M`
}

// The doc-kind lens strip — the ONE canonical place to switch collections, kept
// at the top under the header (not buried in the footer). Mirrors the Markets
// tab strip: bold-accent active, `·` separators, clickable for mouse parity.
// The `1`/`2` prefixes advertise the number keys that also switch kinds.
export function DocsKindTabs({
  disabled = false,
  kind,
  onSelect,
  t
}: {
  disabled?: boolean
  kind: DocKind
  onSelect: (kind: DocKind) => void
  t: Theme
}) {
  const tab = (k: DocKind, key: string, label: string) => {
    const on = kind === k

    return (
      <Box onClick={() => { if (!disabled) {onSelect(k)} }}>
        <Text bold={on} color={on ? t.color.accent : t.color.muted}>
          {`${on ? '▸ ' : '  '}${key} ${label}`}
        </Text>
      </Box>
    )
  }

  return (
    <NoSelect flexShrink={0} marginBottom={1}>
      <Box>
        <Text color={t.color.label}>{'DOCS  '}</Text>
        {tab('markdown', '1', 'Markdown')}
        <Text color={t.color.border}>{'   ·   '}</Text>
        {tab('latex', '2', 'LaTeX')}
      </Box>
    </NoSelect>
  )
}

// The shared header frame. Each branch composes its own status `segments`
// (git state / vault counts), but the FRAME — bold title, an optional path on
// the right, and the `/`-filter search form — is identical across both, so the
// two branches feel like one view. When a filter is live, the header flips to
// the `⌕ query` form (the same affordance Markets uses).
export function DocsHeader({
  cols,
  filter,
  path,
  segments,
  t,
  title
}: {
  cols: number
  filter?: null | { live: boolean; query: string }
  path?: string
  segments?: React.ReactNode
  t: Theme
  title: string
}) {
  const filtering = filter && (filter.live || filter.query.length > 0)

  return (
    <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      {filtering ? (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            {title}
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          <Text color={t.color.primary}>{'⌕ '}</Text>
          <Text color={t.color.text}>{filter!.query}</Text>
          {filter!.live ? (
            <Text color={t.color.primary} inverse>
              {' '}
            </Text>
          ) : null}
          <Text color={t.color.muted}>
            {`   ${filter!.live ? '⏎ done · Esc clear' : '/ refine · Esc clear'}`}
          </Text>
        </Text>
      ) : (
        <Text wrap="truncate-end">
          <Text bold color={t.color.primary}>
            {title}
          </Text>
          <Text color={t.color.muted}>{'   '}</Text>
          {segments}
        </Text>
      )}
      {path && !filtering ? (
        <Text color={t.color.muted} wrap="truncate-end">
          {path.length > cols - 2 ? `…${path.slice(-(cols - 3))}` : path}
        </Text>
      ) : null}
    </Box>
  )
}
