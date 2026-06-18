import { useState } from 'react'

import type { GatewayClient } from '../gatewayClient.js'
import type { Theme } from '../theme.js'

import { LatexDocsView } from './latexDocsView.js'
import { ObsidianView } from './obsidianView.js'

// Docs — two kinds of documents under one view:
//   1. Markdown — the Obsidian vault (GitHub-backed via the gateway tools).
//   2. LaTeX    — local .tex files, rendered in the TUI, Overleaf/git-synced.
// Only the active kind's component is mounted (so only its key handler is
// live); each renders the "1 Markdown · 2 LaTeX" tabs and switches on 1/2.

export type DocKind = 'latex' | 'markdown'

interface DocsViewProps {
  gw: GatewayClient
  onClose: () => void
  onDraft?: (command: string) => void
  sid: null | string
  t: Theme
}

export function DocsView({ gw, onClose, onDraft, sid, t }: DocsViewProps) {
  const [kind, setKind] = useState<DocKind>('markdown')

  if (kind === 'latex') {
    return <LatexDocsView docKind="latex" onClose={onClose} onSelectKind={setKind} t={t} />
  }

  return (
    <ObsidianView
      docKind="markdown"
      gw={gw}
      onClose={onClose}
      onDraft={onDraft}
      onSelectKind={setKind}
      sid={sid}
      t={t}
    />
  )
}
