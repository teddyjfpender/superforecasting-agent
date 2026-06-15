import type { Theme } from '../theme.js'

// One styled run of the source line. The editor renders these so writing
// markdown gets IDE-like visual heuristics: structural markers are dimmed,
// content is styled (bold/italic/links/code), and you can see at a glance
// whether your markup is well-formed.
export interface MdEditSegment {
  bold?: boolean
  color?: string
  dim?: boolean
  italic?: boolean
  text: string
  underline?: boolean
}

// Inline tokens recognised while editing. Kept deliberately simpler than the
// renderer's INLINE_RE — this is a fast, forgiving source highlighter, not a
// parser; unmatched/half-typed markup just falls through as plain text.
const EDIT_INLINE_RE =
  /(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(`[^`\n]+`)|(\[\[[^\]\n]+\]\])|(\[[^\]\n]+\]\([^)\n]+\))|(\$[^$\n]+\$)/g

const inlineSegments = (text: string, t: Theme, base?: Partial<MdEditSegment>): MdEditSegment[] => {
  const out: MdEditSegment[] = []
  let last = 0

  const plain = (s: string) => {
    if (s) {
      out.push({ text: s, ...base })
    }
  }

  // Brackets / asterisks / backticks are pushed as their own dim runs so the
  // markup punctuation reads as "syntax" while the content reads as content.
  const wrap = (open: string, inner: string, style: Partial<MdEditSegment>, close = open) => {
    out.push({ color: t.color.muted, dim: true, text: open })
    out.push({ text: inner, ...style })
    out.push({ color: t.color.muted, dim: true, text: close })
  }

  for (const m of text.matchAll(EDIT_INLINE_RE)) {
    const i = m.index ?? 0

    if (i > last) {
      plain(text.slice(last, i))
    }

    if (m[1]) {
      wrap('**', m[1].slice(2, -2), { bold: true })
    } else if (m[2]) {
      wrap('__', m[2].slice(2, -2), { bold: true })
    } else if (m[3]) {
      wrap('*', m[3].slice(1, -1), { italic: true })
    } else if (m[4]) {
      wrap('`', m[4].slice(1, -1), { color: t.color.accent })
    } else if (m[5]) {
      // [[wikilink]] — brackets dim, target in the link colour + underline.
      wrap('[[', m[5].slice(2, -2), { color: t.color.primary, underline: true }, ']]')
    } else if (m[6]) {
      out.push({ color: t.color.primary, text: m[6], underline: true })
    } else if (m[7]) {
      out.push({ color: t.color.accent, italic: true, text: m[7] })
    }

    last = i + m[0].length
  }

  if (last < text.length) {
    plain(text.slice(last))
  }

  return out.length ? out : [{ text: text || '', ...base }]
}

// Highlight a single source line of markdown for the editor.
export const highlightMarkdownLine = (line: string, t: Theme): MdEditSegment[] => {
  if (!line) {
    return [{ text: '' }]
  }

  const heading = /^(\s{0,3}#{1,6}\s+)(.*)$/.exec(line)

  if (heading) {
    return [
      { color: t.color.muted, text: heading[1]! },
      { bold: true, color: t.color.accent, text: heading[2]! }
    ]
  }

  if (/^\s*(```|~~~)/.test(line)) {
    return [{ color: t.color.muted, dim: true, text: line }]
  }

  const quote = /^(\s*>\s?)(.*)$/.exec(line)

  if (quote) {
    return [{ color: t.color.muted, text: quote[1]! }, ...inlineSegments(quote[2]!, t, { color: t.color.muted })]
  }

  const list = /^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$/.exec(line)

  if (list) {
    return [{ color: t.color.accent, text: list[1]! }, ...inlineSegments(list[2]!, t)]
  }

  return inlineSegments(line, t)
}
