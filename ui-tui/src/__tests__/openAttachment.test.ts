import { describe, expect, it, vi } from 'vitest'

import { attachmentPath, attachmentsDir, openAttachment } from '../lib/openAttachment.js'

describe('attachmentsDir', () => {
  it('honours SIGNALCLI_ATTACHMENTS, then XDG_DATA_HOME, then ~/.local/share', () => {
    expect(attachmentsDir({ SIGNALCLI_ATTACHMENTS: '/custom/dir' }, '/home/u')).toBe('/custom/dir')
    expect(attachmentsDir({ XDG_DATA_HOME: '/x' }, '/home/u')).toBe('/x/signal-cli/attachments')
    expect(attachmentsDir({}, '/home/u')).toBe('/home/u/.local/share/signal-cli/attachments')
  })
})

describe('openAttachment', () => {
  const base = { env: { SIGNALCLI_ATTACHMENTS: '/att' }, home: '/home/u', platform: () => 'darwin' }

  it('rejects path traversal in the id without touching the FS', () => {
    const spawn = vi.fn()

    for (const bad of ['../secret', 'a/b', 'a\\b', '', '..']) {
      const { error } = openAttachment(bad, { ...base, existsSync: () => true, spawn: spawn as never })
      expect(error).toBe('invalid attachment id')
    }

    expect(spawn).not.toHaveBeenCalled()
  })

  it('errors when the file is missing', () => {
    const { error } = openAttachment('abc123', { ...base, existsSync: () => false, spawn: vi.fn() as never })
    expect(error).toBe('attachment not found on disk')
  })

  it('launches the OS opener with the resolved path (no shell)', () => {
    const spawn = vi.fn(() => ({ once: vi.fn(), unref: vi.fn() }))
    const { error } = openAttachment('abc123', { ...base, existsSync: () => true, spawn: spawn as never })
    expect(error).toBeNull()
    expect(spawn).toHaveBeenCalledWith('open', [attachmentPath('abc123', base.env, base.home)], expect.objectContaining({ detached: true }))
    expect(attachmentPath('abc123', base.env, base.home)).toBe('/att/abc123')
  })

  it('reports when no opener exists for the platform', () => {
    const { error } = openAttachment('abc123', { ...base, existsSync: () => true, platform: () => 'aix', spawn: vi.fn() as never })
    expect(error).toBe('no file opener for this platform')
  })
})
