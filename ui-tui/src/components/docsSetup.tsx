import { useStore } from '@nanostores/react'
import { Box, Text, useInput, useStdout } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import { commandExists, gitInit } from '../lib/docsCli.js'
import { docsDir, ensureWorkspaceDirs, migrateLegacyVault, vaultDir } from '../lib/latexDocs.js'
import { seedLatexExamples } from '../lib/latexExamples.js'
import { saveProviderKey } from '../lib/marketKeys.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { FooterChips } from './footerChips.js'

// First-run setup for the Docs view. When ~/.superforecasting-agent/docs doesn't
// exist yet, offer to create the one git-backed workspace that holds BOTH the
// Markdown vault and the LaTeX directory, so everything syncs to a single
// remote / GitHub account.

interface DocsSetupProps {
  onClose: () => void
  onReady: () => void
  t: Theme
}

export function DocsSetup({ onClose, onReady, t }: DocsSetupProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const sem = semantics(t)
  const root = docsDir()
  const vault = vaultDir()
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState('')
  const hasGitRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    hasGitRef.current = commandExists('git')

    return () => {
      aliveRef.current = false
    }
  }, [])

  const create = () => {
    if (busy) {
      return
    }

    setBusy(true)
    setFlash('creating workspace…')

    // Create docs/ + vault/ + latex/, seed example LaTeX docs, and persist the
    // vault path so the gateway's Obsidian tools use the unified location.
    const { latex } = ensureWorkspaceDirs()
    seedLatexExamples(latex)
    migrateLegacyVault(vault) // bring existing notes into the unified vault
    saveProviderKey('OBSIDIAN_VAULT_PATH', vault)
    process.env.OBSIDIAN_VAULT_PATH = vault

    void (async () => {
      if (hasGitRef.current) {
        await gitInit(root)
      }

      if (!aliveRef.current) {
        return
      }

      setBusy(false)
      setFlash('workspace ready')
      onReady()
    })()
  }

  useInput((ch, key) => {
    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === 'c' && !busy) {
      return create()
    }
  }, { isActive: !globalModal })

  const width = Math.min(80, Math.max(40, cols - 8))

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      <Box flexShrink={0} marginBottom={1}>
        <Text bold color={t.color.primary}>
          DOCS
        </Text>
        <Text color={t.color.muted}>{'   set up your workspace'}</Text>
      </Box>

      <Box alignItems="center" flexGrow={1} justifyContent="center">
        <Box flexDirection="column" width={width}>
          <Text bold color={t.color.text}>
            One workspace for all your docs.
          </Text>
          <Box marginTop={1}>
            <Text color={t.color.muted} wrap="wrap">
              No docs workspace yet. Create one git repository at{' '}
              <Text color={t.color.accent}>{root}</Text> holding both your Markdown vault and LaTeX — so everything
              syncs to a single GitHub / Overleaf remote.
            </Text>
          </Box>
          <Box flexDirection="column" marginTop={1}>
            <Text color={t.color.text}>
              <Text color={sem.up}>{'  •  '}</Text>
              <Text color={t.color.label}>vault/</Text>
              <Text color={t.color.muted}> — Markdown notes (Obsidian)</Text>
            </Text>
            <Text color={t.color.text}>
              <Text color={sem.up}>{'  •  '}</Text>
              <Text color={t.color.label}>latex/</Text>
              <Text color={t.color.muted}> — LaTeX documents (.tex)</Text>
            </Text>
            <Text color={t.color.text}>
              <Text color={sem.up}>{'  •  '}</Text>
              <Text color={t.color.muted}>{hasGitRef.current ? 'git repo initialised here' : 'git not found — install it to sync'}</Text>
            </Text>
          </Box>
          <Box marginTop={1}>
            <Text bold color={t.color.accent}>
              Press c
            </Text>
            <Text color={t.color.text}> to create the workspace.</Text>
          </Box>
        </Box>
      </Box>

      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        <FooterChips
          chips={[
            { k: 'c', label: 'Create workspace', run: create },
            { k: 'q', label: 'Close', run: onClose }
          ]}
          disabled={globalModal}
          t={t}
        />
        <Text color={t.color.muted} wrap="truncate-end">
          {flash ? <Text color={t.color.accent}>{flash} · </Text> : null}
          c create workspace · Esc/q close
        </Text>
      </Box>
    </Box>
  )
}
