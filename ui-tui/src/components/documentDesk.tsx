import { useStore } from '@nanostores/react'
import { Box, ScrollBox, type ScrollBoxHandle, Text, useStdout } from '@superforecasting/ink'
import { useEffect, useRef, useState } from 'react'

import { $globalModal, openHelpOverlay } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ObsidianNoteResponse, ObsidianStatusResponse } from '../gatewayTypes.js'
import { readDocumentDraft, saveDocumentDraft } from '../lib/documentDrafts.js'
import { createTexFile, docsDir, listTexFiles, readTexFile, writeTexFile } from '../lib/latexDocs.js'
import { openQuickMessage } from '../lib/messagingState.js'
import { asRpcResult } from '../lib/rpc.js'
import { useShareItem } from '../lib/useShareItem.js'
import { useViewInput } from '../lib/useViewInput.js'
import type { Theme } from '../theme.js'

import { docAge } from './docsShell.js'
import { DocumentConnections } from './documentConnections.js'
import { DocumentReader } from './documentReader.js'
import { FooterChips } from './footerChips.js'
import { ModalOverlay } from './modalOverlay.js'
import { ShortcutText } from './shortcutText.js'
import { TextInput } from './textInput.js'

interface Doc {
  id: string
  title: string
  folder: string
  modified?: string | number
}

export function DocumentDesk({ gw, t, onClose }: { gw: GatewayClient; t: Theme; onClose: () => void }) {
  const { stdout } = useStdout()

  const cols = stdout?.columns ?? 80,
    rows = stdout?.rows ?? 24

  const blocked = useStore($globalModal)
  const [kind, setKind] = useState<'markdown' | 'latex'>('markdown')
  const [docs, setDocs] = useState<Doc[]>([])
  const [vault, setVault] = useState('')
  const [folder, setFolder] = useState('All documents')
  const [selected, setSelected] = useState('')
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [content, setContent] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadedIdentity, setLoadedIdentity] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [editing, setEditing] = useState(false)
  const [truncated, setTruncated] = useState(false)
  const [page, setPage] = useState(0)
  const [creating, setCreating] = useState<string | null>(null)
  const [connections, setConnections] = useState(false)
  const [revision, setRevision] = useState(0)
  const [saving, setSaving] = useState(false)
  const [sourceReview, setSourceReview] = useState<string | null>(null)
  const saveLock = useRef(false)
  const generation = useRef(0)
  const editorRef = useRef<ScrollBoxHandle>(null)
  const scope = kind === 'markdown' ? vault : docsDir()

  const visible = docs.filter(
    d =>
      (folder === 'All documents' || d.folder === folder) &&
      `${d.title} ${d.id}`.toLowerCase().includes(query.toLowerCase())
  )

  const current = visible.find(d => d.id === selected) ?? visible[0]
  const currentId = current?.id

  const index = Math.max(
    0,
    visible.findIndex(d => d.id === current?.id)
  )

  const identity = `${kind}:${scope}:${current?.id || ''}`
  const ready = loadedIdentity === identity && !loading
  const canEdit = Boolean(current && ready && !truncated)
  const folders = ['All documents', ...new Set(docs.map(d => d.folder).filter(Boolean))]
  const height = Math.max(4, rows - 9)
  const libraryWidth = cols >= 110 ? 20 : 0
  const listWidth = Math.max(22, Math.floor((cols - libraryWidth) * 0.34))
  const readerWidth = Math.max(15, cols - libraryWidth - listWidth - 7)
  useShareItem(
    ready ? current?.title || '' : '',
    ready && current
      ? `${kind === 'markdown' ? 'Obsidian' : 'Overleaf'} · ${current.id}\n${content.slice(0, 2000)}${content.length > 2000 ? '\n[Excerpt]' : ''}`
      : ''
  )
  useEffect(() => {
    let active = true
    setDocs([])
    setError('')
    setLoading(true)

    const load = async () => {
      if (kind === 'latex') {
        return listTexFiles(docsDir()).map(f => ({
          id: f.rel,
          title: f.rel.split('/').pop()!,
          folder: f.rel.split('/').slice(0, -1).join('/') || 'Root',
          modified: f.mtime
        }))
      }

      const data = asRpcResult<ObsidianStatusResponse>(await gw.request('obsidian.status', { limit: 500 }))

      if (!data?.exists) {
        if (active) {
          setStatus('No vault connected. Press s to initialize Obsidian.')
        }

        return []
      }

      if (active) {
        setVault(data.vault || '')
      }

      return (data.notes || [])
        .filter(n => n.rel_path)
        .map(n => ({
          id: n.rel_path!,
          title: n.title || n.rel_path!,
          folder: n.folder || 'Root',
          modified: n.modified
        }))
    }

    void load()
      .then(next => {
        if (active) {
          setDocs(next)
          setLoading(false)
        }
      })
      .catch(e => {
        if (active) {
          setError(String(e))
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [gw, kind, revision])
  useEffect(() => {
    const token = ++generation.current
    setContent('')
    setOriginal('')
    setPage(0)
    setEditing(false)
    setTruncated(false)
    setSourceReview(null)
    setLoadedIdentity('')
    setError('')
    setStatus('')

    if (!currentId) {
      setLoading(false)

      return
    }

    setLoading(true)

    const load = async () =>
      kind === 'latex'
        ? { content: readTexFile(docsDir(), currentId) }
        : asRpcResult<ObsidianNoteResponse>(await gw.request('obsidian.note', { rel_path: currentId }))

    void load()
      .then(note => {
        if (token !== generation.current) {
          return
        }

        if (!note || typeof note.content !== 'string') {
          throw new Error('Document could not be read.')
        }

        setLoadedIdentity(identity)
        const draft = readDocumentDraft(identity)
        setOriginal(note.content)
        setTruncated(Boolean('truncated' in note && note.truncated))

        if (draft && draft.content !== draft.original) {
          setContent(draft.content)
          setOriginal(draft.original)
          setStatus('Recovered unsaved edit · e edit · Ctrl+Enter save')

          if (draft.original !== note.content) {
            setError('Source changed since this draft. Press R to reconcile before saving.')
          }
        } else {
          setContent(note.content)
        }

        setLoading(false)
      })
      .catch(e => {
        if (token === generation.current) {
          setError(String(e))
          setLoading(false)
        }
      })

    return () => {
      if (generation.current === token) {
        generation.current = token + 1
      }
    }
  }, [gw, kind, currentId, identity, revision])

  const edit = (value: string) => {
    setContent(value)

    try {
      saveDocumentDraft(identity, { content: value, original })
      setStatus('Draft saved locally')
    } catch {
      setError('Draft could not be saved. Keep this editor open and check profile permissions.')
    }
  }

  const save = async (value = content) => {
    if (!current || !canEdit || saveLock.current) {
      return
    }

    saveLock.current = true
    setSaving(true)
    setError('')

    const id = current.id,
      key = identity,
      base = original

    try {
      if (kind === 'markdown') {
        await gw.request('obsidian.write', { rel_path: id, content: value, expected_content: base })
      } else {
        const result = writeTexFile(docsDir(), id, value, base)

        if (result.error) {
          throw new Error(result.error)
        }
      }

      try {
        saveDocumentDraft(key, { content: value, original: value })
      } catch {
        setError('Document saved, but the local recovery snapshot could not be updated.')
      }

      setOriginal(value)
      setContent(value)
      setStatus('Saved')
      setEditing(false)
    } catch (e) {
      setError(String(e))
    } finally {
      saveLock.current = false
      setSaving(false)
    }
  }

  const reviewSource = async () => {
    const token = generation.current

    if (!current) {
      return
    }

    try {
      const note =
        kind === 'latex'
          ? { content: readTexFile(docsDir(), current.id) }
          : asRpcResult<ObsidianNoteResponse>(await gw.request('obsidian.note', { rel_path: current.id }))

      if (!note || typeof note.content !== 'string' || ('truncated' in note && note.truncated)) {
        throw new Error('Cannot reconcile a truncated or unavailable source')
      }

      if (token === generation.current) {
        setSourceReview(note.content)
      }
    } catch (e) {
      setError(String(e))
    }
  }

  const create = async (name = creating) => {
    if (!name?.trim() || saveLock.current) {
      return
    }

    try {
      if (kind === 'markdown') {
        await gw.request('obsidian.create', { rel_path: name.trim() })
      } else {
        const r = createTexFile(docsDir(), name.trim())

        if (r.error) {
          throw new Error(r.error)
        }
      }

      setSelected(name.trim())
      setCreating(null)
      setRevision(v => v + 1)
    } catch (e) {
      setError(String(e))
    }
  }

  const switchKind = (next: 'markdown' | 'latex') => {
    setKind(next)
    setFolder('All documents')
    setSelected('')
    setQuery('')
    setError('')
    setStatus('')
  }

  const handleFooterKey = useViewInput(
    (input, key) => {
      if (connections || blocked || saving) {
        return
      }

      if (sourceReview !== null) {
        if (key.escape) {
          setSourceReview(null)

          return
        }

        if (input === 'd' || input === 's') {
          const next = input === 's' ? sourceReview : content

          try {
            saveDocumentDraft(identity, { original: sourceReview, content: next })
            setContent(next)
            setOriginal(sourceReview)
            setSourceReview(null)
            setEditing(false)
            setError('')
            setStatus(
              input === 's'
                ? 'Source restored; draft discarded'
                : 'Draft retained against current source; review before saving'
            )
          } catch (e) {
            setError(String(e))
          }
        }

        return
      }

      if (creating !== null) {
        if (key.escape) {
          setCreating(null)
        }

        return
      }

      if (editing) {
        if (key.escape) {
          setEditing(false)
        }

        return
      }

      if (searching) {
        if (key.escape) {
          setSearching(false)
          setQuery('')
        }

        return
      }

      if (input === 'q' || key.escape) {
        return onClose()
      }

      if (input === '1') {
        return switchKind('markdown')
      }

      if (input === '2') {
        return switchKind('latex')
      }

      if (input === 'h' || input === '?') {
        return openHelpOverlay()
      }

      if (input === 'm') {
        return openQuickMessage()
      }

      if (input === '/') {
        return setSearching(true)
      }

      if (input === 'e' && canEdit) {
        return setEditing(true)
      }

      if (input === 'n') {
        return setCreating('')
      }

      if (input === 'c') {
        return setConnections(true)
      }

      if (input === 'R') {
        void reviewSource()

        return
      }

      if (input === 'r') {
        return setRevision(v => v + 1)
      }

      if (input === 's' && kind === 'markdown') {
        void gw
          .request('obsidian.setup', {})
          .then(() => setRevision(v => v + 1))
          .catch(e => setError(String(e)))

        return
      }

      if (key.pageUp) {
        return setPage(v => v - 1)
      }

      if (key.pageDown) {
        return setPage(v => v + 1)
      }

      if (key.upArrow || key.downArrow) {
        setSelected(visible[Math.max(0, Math.min(visible.length - 1, index + (key.upArrow ? -1 : 1)))]?.id || '')

        return
      }

      if (key.tab || key.leftArrow || key.rightArrow) {
        const delta = key.shift || key.leftArrow ? -1 : 1
        setFolder(folders[(folders.indexOf(folder) + delta + folders.length) % folders.length]!)
      }
    },
    { isActive: !blocked && !connections }
  )

  return (
    <Box flexDirection="column" flexGrow={1} minHeight={0} paddingX={1} paddingY={1}>
      <Box flexShrink={0} marginBottom={1}>
        <Box marginRight={2}>
          <Text bold color={t.color.primary}>
            DOCS
          </Text>
        </Box>
        <Text color={t.color.muted}> </Text>
        {(['markdown', 'latex'] as const).map((k, i) => (
          <Box
            key={k}
            marginRight={2}
            onClick={() => {
              if (!blocked && !editing && !connections && creating === null && sourceReview === null && !saving) {
                switchKind(k)
              }
            }}
          >
            <Text bold={kind === k} color={kind === k ? t.color.accent : t.color.muted}>
              {i + 1} {k === 'markdown' ? 'Obsidian' : 'Overleaf'}{' '}
            </Text>
          </Box>
        ))}
        <Text color={t.color.muted}>{saving ? 'Saving…' : loading ? 'Loading…' : `${visible.length} documents`}</Text>
      </Box>
      <Box flexShrink={0} height={2}>
        {searching ? (
          <TextInput
            columns={cols - 4}
            focus={!blocked}
            onChange={setQuery}
            onSubmit={() => setSearching(false)}
            placeholder="Search titles and paths…"
            value={query}
          />
        ) : (
          <Text color={t.color.muted} wrap="truncate-end">
            {folder} · {scope || 'No vault'}
            {query ? ` · ${query}` : ''}
          </Text>
        )}
      </Box>
      <Box flexDirection="row" flexShrink={0} height={height}>
        {libraryWidth > 0 && (
          <Box flexDirection="column" flexShrink={0} overflow="hidden" width={libraryWidth}>
            <Text bold color={t.color.label}>
              LIBRARY
            </Text>
            {folders.map(f => (
              <Box
                key={f}
                onClick={() => {
                  if (!blocked && !editing && !connections && creating === null && sourceReview === null && !saving) {
                    setFolder(f)
                  }
                }}
              >
                <Text color={folder === f ? t.color.accent : t.color.muted} wrap="truncate-end">
                  {folder === f ? '› ' : '  '}
                  {f}
                </Text>
              </Box>
            ))}
          </Box>
        )}
        <Box flexDirection="column" flexShrink={0} overflow="hidden" paddingRight={1} width={listWidth}>
          <Text bold color={t.color.label}>
            DOCUMENTS
          </Text>
          {visible
            .slice(
              Math.max(0, index - Math.floor((height - 2) / 2)),
              Math.max(0, index - Math.floor((height - 2) / 2)) + height - 2
            )
            .map(d => (
              <Box
                key={d.id}
                onClick={() => {
                  if (!blocked && !editing && !connections && creating === null && sourceReview === null && !saving) {
                    setSelected(d.id)
                  }
                }}
              >
                <Text
                  bold={d.id === current?.id}
                  color={d.id === current?.id ? t.color.accent : t.color.text}
                  wrap="truncate-end"
                >
                  {d.id === current?.id ? '› ' : '  '}
                  {d.title} <Text color={t.color.muted}>{docAge(d.modified)}</Text>
                </Text>
              </Box>
            ))}
          {!visible.length && (
            <ShortcutText color={t.color.muted} t={t}>No documents. Press n to create one, or c for connections.</ShortcutText>
          )}
        </Box>
        <Box
          borderBottom={false}
          borderColor={t.color.border}
          borderLeft
          borderRight={false}
          borderStyle="single"
          borderTop={false}
          flexDirection="column"
          flexGrow={1}
          minWidth={0}
          overflow="hidden"
          paddingLeft={1}
        >
          <Text bold color={t.color.label} wrap="truncate-end">
            {editing ? 'EDIT' : 'READER'} · {current?.title || 'Select a document'}
            {content !== original ? ' · unsaved' : ''}
          </Text>
          {editing ? (
            <ScrollBox decstbm={false} flexShrink={0} followContent={false} height={height - 2} ref={editorRef}>
              <TextInput
                columns={readerWidth}
                focus={!blocked && !saving && sourceReview === null}
                immediateChange
                key={identity}
                multiline
                onChange={edit}
                onCursorLine={line => editorRef.current?.scrollTo(Math.max(0, line - height + 4))}
                onSubmit={value => void save(value)}
                value={content}
              />
            </ScrollBox>
          ) : (
            <DocumentReader
              content={ready ? content : ''}
              height={height - 2}
              identity={identity}
              kind={kind}
              onWikiLink={target => {
                if (blocked || connections || creating !== null || sourceReview !== null || saving) {
                  return
                }

                const name = target.split('#')[0]?.toLowerCase()

                const matches = docs.filter(
                  d =>
                    d.id.toLowerCase() === name ||
                    d.id.toLowerCase() === `${name}.md` ||
                    d.title.toLowerCase() === name ||
                    d.id.split('/').pop()?.replace(/\.md$/, '').toLowerCase() === name
                )

                if (matches.length !== 1) {
                  setError(matches.length ? 'Ambiguous note link; search by path.' : 'Linked note not found.')

                  return
                }

                setFolder('All documents')
                setQuery('')
                setSelected(matches[0]!.id)
              }}
              page={page}
              t={t}
              width={readerWidth}
            />
          )}
        </Box>
      </Box>
      <Text color={error ? t.color.error : t.color.muted} wrap="truncate-end">
        {error || status || '↑↓ documents · Tab folders · PgUp/PgDn reader'}
        {truncated ? ' · Preview truncated; editing disabled' : ''}
      </Text>
      <FooterChips
        chips={
          editing
            ? [
                { k: '^Enter', label: 'Save', run: () => void save() },
                { k: 'Esc', label: 'Preview', run: () => setEditing(false) }
              ]
            : [
                { k: '/', label: 'Search', run: () => setSearching(true) },
                { k: 'e', label: 'Edit', run: () => canEdit && setEditing(true) },
                { k: 'n', label: 'New', run: () => setCreating('') },
                { k: 'c', label: 'Connections', run: () => setConnections(true) },
                { k: 'm', label: 'Forward', run: openQuickMessage },
                { k: 'h', label: 'Help', run: openHelpOverlay },
                { k: 'q', label: 'Close', run: onClose }
              ]
        }
        disabled={blocked || connections || creating !== null || sourceReview !== null || saving}
        onKey={handleFooterKey}
        t={t}
      />
      {sourceReview !== null && (
        <ModalOverlay
          cols={cols}
          footerHint="d keep draft as replacement · s discard draft · Esc cancel"
          maxHeight={24}
          rows={rows}
          t={t}
          title="RECONCILE DOCUMENT"
        >
          <Text color={t.color.warn}>
            The source and your draft remain separate. Nothing is written until you save.
          </Text>
          <Text bold color={t.color.label}>
            CURRENT SOURCE
          </Text>
          <Box height={4} overflow="hidden">
            <Text color={t.color.text}>{sourceReview}</Text>
          </Box>
          <Text bold color={t.color.label}>
            YOUR DRAFT
          </Text>
          <Box height={4} overflow="hidden">
            <Text color={t.color.text}>{content}</Text>
          </Box>
        </ModalOverlay>
      )}
      {connections && (
        <DocumentConnections
          cols={cols}
          gw={gw}
          onClose={() => {
            setConnections(false)
            setRevision(v => v + 1)
          }}
          rows={rows}
          t={t}
          vault={vault}
        />
      )}
      {creating !== null && (
        <ModalOverlay
          cols={cols}
          footerHint="Enter create · Esc cancel"
          maxHeight={10}
          rows={rows}
          t={t}
          title="NEW DOCUMENT"
        >
          <TextInput
            columns={Math.min(80, cols - 8)}
            focus={!blocked}
            onChange={setCreating}
            onSubmit={value => void create(value)}
            placeholder={kind === 'markdown' ? 'Folder/note.md' : 'latex/paper.tex'}
            value={creating}
          />
        </ModalOverlay>
      )}
    </Box>
  )
}
