import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { waitForText, waitUntil } from '../testing/settle.js'

const roots: string[] = []
afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  roots.splice(0).forEach(p => rmSync(p, { recursive: true, force: true }))
})

async function mount(view: React.ReactNode, cols = 100, rows = 32) {
  const { render, Box, Text } = await import('@superforecasting/ink')
  const { stripAnsi } = await import('../lib/text.js')
  const stdout = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => {}, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const app = await render(
    React.createElement(
      Box,
      { width: cols, height: rows, flexDirection: 'column' },
      React.createElement(Text, {}, 'Desk'),
      view
    ),
    {
      stdout: stdout as never,
      stdin: stdin as never,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false
    }
  )

  return {
    read: () => stripAnsi(output),
    input: async (text: string) => {
      stdin.write(text)
      await new Promise(r => setTimeout(r, 60))
    },
    close: () => {
      app.unmount()
      app.cleanup()
      stdout.destroy()
      stdin.destroy()
    }
  }
}

function profile() {
  const dir = mkdtempSync(join(tmpdir(), 'desk-ui-'))
  roots.push(dir)
  vi.stubEnv('SUPERFORECASTING_AGENT_HOME', dir)
  vi.stubEnv('FORECAST_TUI_INLINE', '1')

  return dir
}

it('Docs selects the requested document and rejects stale async note replies', async () => {
  profile()
  const { DocumentDesk } = await import('../components/documentDesk.js')
  const { DARK_THEME } = await import('../theme.js')
  let finishFirst!: (v: unknown) => void

  const request = vi.fn((method: string, params: { rel_path?: string }) => {
    if (method === 'obsidian.status') {
      return Promise.resolve({
        exists: true,
        vault: '/fake/vault',
        notes: [
          { rel_path: 'a.md', title: 'Alpha' },
          { rel_path: 'b.md', title: 'Beta' }
        ]
      })
    }

    if (params.rel_path === 'a.md') {
      return new Promise(resolve => {
        finishFirst = resolve
      })
    }

    return Promise.resolve({ content: '# Beta\n\nSelected document body', rel_path: 'b.md' })
  })

  const app = await mount(<DocumentDesk gw={{ request } as never} onClose={() => {}} t={DARK_THEME} />)

  try {
    await waitForText(app.read, 'Alpha')
    await waitUntil(() => typeof finishFirst === 'function', { label: 'initial note request started' })
    await app.input('\x1b[B')
    await waitForText(app.read, 'Selected document body')
    finishFirst({ content: 'STALE ALPHA BODY' })
    await new Promise(r => setTimeout(r, 80))
    expect(app.read()).not.toContain('STALE ALPHA BODY')
    await app.input('e')
    await app.input('!')
    await app.input('\x1b')
    const { readDocumentDraft } = await import('../lib/documentDrafts.js')
    expect(readDocumentDraft('markdown:/fake/vault:b.md')?.content).toContain('!')
  } finally {
    app.close()
  }
}, 15000)

it('quick compose preserves edited text on dismiss without sending', async () => {
  profile()
  const { QuickMessage } = await import('../components/quickMessage.js')
  const { $quickMessage, openQuickMessage, loadMessagingState } = await import('../lib/messagingState.js')
  const { DARK_THEME } = await import('../theme.js')
  openQuickMessage()
  const app = await mount(<QuickMessage cols={100} rows={32} t={DARK_THEME} />)

  try {
    await waitForText(app.read, 'MESSAGE', { timeout: 1200, label: 'quick modal visible' })
    await app.input('+15550001111')
    await app.input('\r')
    await waitForText(app.read, 'Write a message', { timeout: 1200, label: 'recipient selected' })
    await app.input('A retained draft')
    await app.input('\x1b')
    expect($quickMessage.get()).toBeNull()
    expect(loadMessagingState()['+15550001111']?.draft).toBe('A retained draft')
  } finally {
    app.close()
  }
})
