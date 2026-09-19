import { useStore } from '@nanostores/react'
import { Box, type ScrollBoxHandle, Text, useInput } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import {
  commandExists,
  docsSyncPull,
  gitCommitPush,
  gitInit,
  gitSetRemote,
  gitStatus,
  type GitStatus,
  overleaf,
  type RunResult
} from '../lib/docsCli.js'
import { docsDir } from '../lib/latexDocs.js'
import type { Theme } from '../theme.js'

import { ModalOverlay } from './modalOverlay.js'
import { ShortcutText } from './shortcutText.js'
import { TextInput } from './textInput.js'

export function DocumentConnections({
  gw,
  vault,
  onClose,
  t,
  cols,
  rows
}: {
  gw: GatewayClient
  vault: string
  onClose: () => void
  t: Theme
  cols: number
  rows: number
}) {
  const blocked = useStore($globalModal)
  const [git, setGit] = useState<GitStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [hasOlcli] = useState(() => commandExists('olcli'))
  const [message, setMessage] = useState('')
  const [remote, setRemote] = useState<string | null>(null)
  const [confirmPush, setConfirmPush] = useState(false)
  const scroll = useRef<ScrollBoxHandle>(null)
  const dir = docsDir()
  useEffect(() => {
    scroll.current?.scrollToBottom()
  }, [remote, confirmPush, message])
  useEffect(() => {
    let live = true
    void gitStatus(dir).then(result => {
      if (live) {
        setGit(result)
      }
    })

    return () => {
      live = false
    }
  }, [dir])

  const run = async (action: () => Promise<RunResult>) => {
    if (busy) {
      return
    }

    setBusy(true)
    setMessage('Working…')

    try {
      const result = await action()
      setMessage(
        result.code === 0
          ? 'Complete. Refresh Docs to see changes.'
          : result.error || result.stderr || 'Operation failed'
      )
      setGit(await gitStatus(dir))
    } catch (e) {
      setMessage(String(e))
    } finally {
      setBusy(false)
    }
  }

  const connect = (value = remote) => {
    if (!value) {
      return
    }

    try {
      const url = new URL(value)

      if (url.protocol !== 'https:' || url.username || url.password) {
        throw new Error('Use an HTTPS remote URL without embedded credentials. Authenticate Git separately.')
      }
    } catch (e) {
      setMessage(String(e))

      return
    }

    const url = value
    setRemote(null)
    void run(async () => {
      if (!git) {
        const initialized = await gitInit(dir)

        if (initialized.code !== 0) {
          return initialized
        }
      }

      return gitSetRemote(dir, url)
    })
  }

  useInput((input, key) => {
    if (busy || blocked) {
      return
    }

    if (key.pageUp || key.pageDown) {
      scroll.current?.scrollBy(key.pageUp ? -5 : 5)

      return
    }

    if (remote !== null) {
      if (key.escape) {
        setRemote(null)
      }

      return
    }

    if (confirmPush) {
      if (input === 'y') {
        setConfirmPush(false)
        void run(() => gitCommitPush(dir, 'Docs update from Superforecasting Agent'))
      } else if (key.escape || input === 'n') {
        setConfirmPush(false)
      }

      return
    }

    if (key.escape || input === 'q') {
      return onClose()
    }

    if (input === 'c') {
      return setRemote('')
    }

    if (input === 'p') {
      return void run(() => docsSyncPull(dir))
    }

    if (input === 'P') {
      return setConfirmPush(true)
    }

    if (input === 'u') {
      return void run(() => overleaf(dir, ['pull']))
    }

    if (input === 's') {
      setBusy(true)
      void gw
        .request('obsidian.setup', {})
        .then(() => setMessage('Obsidian vault ready.'))
        .catch(e => setMessage(String(e)))
        .finally(() => setBusy(false))
    }
  })

  return (
    <ModalOverlay
      cols={cols}
      footerHint="c connect remote · p pull · P publish · u olcli pull · s vault setup · Esc back"
      maxHeight={25}
      maxWidth={92}
      rows={rows}
      scrollRef={scroll}
      t={t}
      title="DOCUMENT CONNECTIONS"
    >
      <Box flexDirection="column" flexShrink={0}>
        <Text bold color={t.color.accent}>
          Obsidian
        </Text>
        <ShortcutText color={t.color.text} t={t}>{vault || 'Managed vault · press s to initialize'}</ShortcutText>
        <Text color={t.color.muted}>
          Reads and writes use the gateway vault. Existing vaults use OBSIDIAN_VAULT_PATH.
        </Text>
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={t.color.accent}>
            Overleaf / Git
          </Text>
          <Text color={t.color.text}>{dir}</Text>
          <Text color={t.color.muted}>
            {git
              ? `${git.branch} · ${git.dirty} changed · ${git.ahead} ahead · ${git.behind} behind`
              : 'No Git repository connected'}{' '}
            · olcli {hasOlcli ? 'available' : 'not installed'}
          </Text>
          <Text color={t.color.muted}>
            Connect the project’s Git URL and authenticate Git separately. Pull requires a clean workspace; publishing
            includes all changes under the path above.
          </Text>
        </Box>
        {remote !== null && (
          <TextInput
            columns={Math.min(80, cols - 8)}
            focus={!busy && !blocked}
            onChange={setRemote}
            onSubmit={connect}
            placeholder="https://git.overleaf.com/project-id"
            value={remote}
          />
        )}
        {confirmPush && <Text color={t.color.warn}>Publish all changes in this workspace? y send · n cancel</Text>}
        {message && <Text color={t.color.text}>{busy ? 'Working…' : message}</Text>}
      </Box>
    </ModalOverlay>
  )
}
