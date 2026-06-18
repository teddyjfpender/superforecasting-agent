import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir, platform } from 'node:os'
import { join } from 'node:path'

// Open a received Signal attachment in the OS's default app.
//
// signal-cli auto-downloads attachments on receive into its data dir's
// `attachments/` folder, named by the attachment id. We start the daemon with
// no --config, so it uses the default location: $XDG_DATA_HOME/signal-cli or
// ~/.local/share/signal-cli (override with SIGNALCLI_ATTACHMENTS if yours
// differs). This is the file/local-app analogue of openExternalUrl — kept
// separate so that http-link opener stays strictly http(s)-only.
//
// Safety: the id must be a flat filename (no path separators / "..") so a
// crafted message can't traverse out of the attachments dir; we verify the
// file exists, then launch it with the OS opener via spawn (no shell), so the
// path can't be reinterpreted as a command.

export const attachmentsDir = (env: NodeJS.ProcessEnv = process.env, home = homedir()): string => {
  const override = env.SIGNALCLI_ATTACHMENTS?.trim()

  if (override) {
    return override
  }

  const dataHome = env.XDG_DATA_HOME?.trim() || join(home, '.local', 'share')

  return join(dataHome, 'signal-cli', 'attachments')
}

export const attachmentPath = (id: string, env: NodeJS.ProcessEnv = process.env, home = homedir()): string =>
  join(attachmentsDir(env, home), id)

const openerFor = (platformId: string): null | { args: readonly string[]; command: string } => {
  if (platformId === 'darwin') {
    return { args: [], command: 'open' }
  }

  if (platformId === 'win32') {
    return { args: [], command: 'explorer.exe' }
  }

  if (new Set(['dragonfly', 'freebsd', 'linux', 'netbsd', 'openbsd']).has(platformId)) {
    return { args: [], command: 'xdg-open' }
  }

  return null
}

export interface OpenAttachmentDeps {
  env?: NodeJS.ProcessEnv
  existsSync?: (p: string) => boolean
  home?: string
  platform?: () => string
  spawn?: typeof spawn
}

export const openAttachment = (id: string, deps: OpenAttachmentDeps = {}): { error: null | string } => {
  const env = deps.env ?? process.env
  const home = deps.home ?? homedir()
  const exists = deps.existsSync ?? existsSync
  const spawnFn = deps.spawn ?? spawn
  const platformId = deps.platform?.() ?? platform()

  if (!id || /[/\\]/.test(id) || id.includes('..')) {
    return { error: 'invalid attachment id' } // no path traversal
  }

  const path = attachmentPath(id, env, home)

  if (!exists(path)) {
    return { error: 'attachment not found on disk' }
  }

  const opener = openerFor(platformId)

  if (!opener) {
    return { error: 'no file opener for this platform' }
  }

  try {
    const child = spawnFn(opener.command, [...opener.args, path], { detached: true, stdio: 'ignore' })
    child.once('error', () => {
      /* no-op: keep the TUI alive if the opener binary is missing */
    })
    child.unref()

    return { error: null }
  } catch {
    return { error: 'failed to launch opener' }
  }
}
