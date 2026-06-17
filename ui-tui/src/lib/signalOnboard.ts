import { spawn, spawnSync } from 'node:child_process'

import { findSignalCli } from './signalDaemon.js'

export const commandExists = (bin: string): boolean =>
  spawnSync(process.platform === 'win32' ? 'where' : 'which', [bin], { encoding: 'utf8' }).status === 0

// signal-cli listAccounts prints lines like "Number: +1555…"; pull the numbers.
export const parseAccounts = (output: string): string[] => [
  ...new Set([...output.matchAll(/\+\d{7,15}/g)].map(m => m[0]))
]

// Drives signal-cli for in-TUI onboarding — linking this device to an existing
// Signal account (the common case) or registering a new number. These spawn the
// signal-cli binary directly (not the daemon); the modal renders the device-link
// QR and collects the register captcha/code. Pure parsers are unit-tested.

// Signal's captcha helper — the user solves it and copies the resulting
// `signalcaptcha://…` token back into the modal.
export const CAPTCHA_URL = 'https://signalcaptcha.host/registration/generate.html'

// signal-cli prints a device-link URI (sgnl://linkdevice?… on current builds,
// tsdevice:/?… on older ones) that the phone's Signal app scans.
export const parseLinkUri = (output: string): string => {
  const m = /(sgnl:\/\/linkdevice\?[^\s'"]+|tsdevice:\/?\??[^\s'"]+)/.exec(output)

  return m ? m[1] : ''
}

// A register attempt needs a captcha when signal-cli says so.
export const needsCaptcha = (output: string): boolean =>
  /captcha/i.test(output) && /(required|needed|provide|invalid|rejected)/i.test(output)

export interface LinkHandle {
  cancel: () => void
}

// Run `signal-cli link -n <name>`: surfaces the link URI as soon as it appears,
// then resolves via onDone when the phone completes (exit 0) or it fails.
export const runLink = (
  name: string,
  cb: { onDone: (ok: boolean, error: string) => void; onLog?: (line: string) => void; onUri: (uri: string) => void }
): LinkHandle => {
  const cli = findSignalCli()

  if (!cli.found) {
    cb.onDone(false, 'signal-cli not found')

    return { cancel: () => {} }
  }

  const child = spawn(cli.path, ['link', '-n', name || 'Outrider'], { stdio: ['ignore', 'pipe', 'pipe'] })
  let buffer = ''
  let uriSent = false

  const scan = (chunk: string) => {
    buffer += chunk
    cb.onLog?.(chunk.trim())

    if (!uriSent) {
      const uri = parseLinkUri(buffer)

      if (uri) {
        uriSent = true
        cb.onUri(uri)
      }
    }
  }

  child.stdout?.on('data', d => scan(String(d)))
  child.stderr?.on('data', d => scan(String(d)))
  child.on('error', e => cb.onDone(false, e instanceof Error ? e.message : String(e)))
  child.on('exit', code => cb.onDone(code === 0, code === 0 ? '' : `signal-cli link exited (code ${code ?? '?'})`))

  return {
    cancel: () => {
      try {
        child.kill()
      } catch {
        /* already gone */
      }
    }
  }
}

const runOnce = (args: string[], timeoutMs = 60000): Promise<{ error: string; ok: boolean; output: string }> =>
  new Promise(resolve => {
    const cli = findSignalCli()

    if (!cli.found) {
      resolve({ error: 'signal-cli not found', ok: false, output: '' })

      return
    }

    const child = spawn(cli.path, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''

    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {
        /* ignore */
      }
    }, timeoutMs)

    child.stdout?.on('data', d => (out += String(d)))
    child.stderr?.on('data', d => (out += String(d)))
    child.on('error', e => {
      clearTimeout(timer)
      resolve({ error: e instanceof Error ? e.message : String(e), ok: false, output: out })
    })
    child.on('exit', code => {
      clearTimeout(timer)
      resolve({ error: code === 0 ? '' : out.trim().split('\n').slice(-1)[0] || `exit ${code}`, ok: code === 0, output: out })
    })
  })

// Register a new number. Returns needsCaptcha=true when signal-cli wants a
// captcha token (the modal then sends the user to CAPTCHA_URL).
export const registerNumber = async (
  account: string,
  opts: { captcha?: string; voice?: boolean } = {}
): Promise<{ error: string; needsCaptcha: boolean; ok: boolean }> => {
  const args = ['-a', account, 'register']

  if (opts.captcha) {
    args.push('--captcha', opts.captcha)
  }

  if (opts.voice) {
    args.push('--voice')
  }

  const r = await runOnce(args)

  return { error: r.error, needsCaptcha: !r.ok && needsCaptcha(r.output), ok: r.ok }
}

export const verifyNumber = async (account: string, code: string): Promise<{ error: string; ok: boolean }> => {
  const r = await runOnce(['-a', account, 'verify', code.trim()])

  return { error: r.error, ok: r.ok }
}

// Discover which number(s) signal-cli has registered/linked (used after a
// device link, since linking doesn't tell us our own number up front).
export const listAccounts = async (): Promise<string[]> => {
  const r = await runOnce(['listAccounts'], 10000)

  return parseAccounts(r.output)
}

export interface InstallHandle {
  cancel: () => void
}

// Install signal-cli via Homebrew (macOS / linuxbrew), streaming output into the
// modal so the user never leaves the TUI. Returns null when brew isn't present
// (the modal then shows manual steps for that platform).
export const brewInstall = (
  pkg: string,
  cb: { onDone: (ok: boolean) => void; onLog: (line: string) => void }
): InstallHandle | null => {
  if (!commandExists('brew')) {
    return null
  }

  const child = spawn('brew', ['install', pkg], { stdio: ['ignore', 'pipe', 'pipe'] })
  child.stdout?.on('data', d => cb.onLog(String(d).trimEnd()))
  child.stderr?.on('data', d => cb.onLog(String(d).trimEnd()))
  child.on('error', () => cb.onDone(false))
  child.on('exit', code => cb.onDone(code === 0))

  return {
    cancel: () => {
      try {
        child.kill()
      } catch {
        /* ignore */
      }
    }
  }
}
