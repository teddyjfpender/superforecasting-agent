import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { delimiter, join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
import { checkHealth, type SignalConfig } from './signalClient.js'
import { saveSignalConfig } from './signalStore.js'

// Manages a local signal-cli daemon for the personal Signal client — entirely
// in-TUI, no hardcoded port. The TUI picks the next free port, spawns the
// daemon detached (so it survives the TUI and serves the agent bridge too),
// records pid+port, and reuses a healthy running daemon on reopen instead of
// double-spawning.

export interface DaemonInfo {
  account: string
  httpUrl: string
  pid: number
  port: number
  startedAt: number
}

export interface BinaryStatus {
  found: boolean
  home?: string // JAVA_HOME for java (the keg/JDK root), so callers can export it
  path: string
  version: string
}

const daemonFile = (dir = forecastHomeDir()) => join(dir, 'signal_daemon.json')

// signal-cli lands on PATH (brew/manual) or in the app-managed home dir.
const provisionedSignalCli = (): string => join(forecastHomeDir(), 'signal-cli', 'bin', 'signal-cli')

const which = (bin: string): string => {
  const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', [bin], { encoding: 'utf8' })

  return r.status === 0 ? (r.stdout || '').split('\n')[0].trim() : ''
}

const versionOf = (path: string, args: string[]): string => {
  try {
    const r = spawnSync(path, args, { encoding: 'utf8', timeout: 5000 })

    return ((r.stdout || '') + (r.stderr || '')).trim().split('\n')[0].trim()
  } catch {
    return ''
  }
}

export const findSignalCli = (): BinaryStatus => {
  const path = which('signal-cli') || (existsSync(provisionedSignalCli()) ? provisionedSignalCli() : '')

  return { found: Boolean(path), path, version: path ? versionOf(path, ['--version']) : '' }
}

// Java is the fiddly one: Homebrew's openjdk is KEG-ONLY (not symlinked onto
// PATH), and macOS ships a /usr/bin/java stub that errors when no JDK is
// registered. So we probe known JDK locations directly and validate each by
// actually running `java -version`, preferring a 17+ runtime.
const javaCandidates = (): string[] => {
  const out: string[] = []
  const add = (p: string) => p && out.push(p)

  if (process.env.JAVA_HOME) {
    add(join(process.env.JAVA_HOME, 'bin', 'java'))
  }

  add(which('java')) // may be the macOS stub; validated below

  // Homebrew keg-only openjdk (current + commonly-pinned majors), both arches.
  for (const prefix of ['/opt/homebrew/opt', '/usr/local/opt']) {
    for (const formula of ['openjdk', 'openjdk@21', 'openjdk@17']) {
      add(join(prefix, formula, 'bin', 'java'))
    }
  }

  try {
    const r = spawnSync('brew', ['--prefix', 'openjdk'], { encoding: 'utf8', timeout: 4000 })
    const prefix = (r.stdout || '').trim()

    if (prefix) {
      add(join(prefix, 'bin', 'java'))
    }
  } catch {
    /* brew not present */
  }

  // Installed JDK bundles — macOS (.../Contents/Home) and Linux (/usr/lib/jvm).
  for (const dir of ['/Library/Java/JavaVirtualMachines', '/usr/lib/jvm']) {
    try {
      for (const entry of readdirSync(dir)) {
        add(join(dir, entry, 'Contents', 'Home', 'bin', 'java'))
        add(join(dir, entry, 'bin', 'java'))
      }
    } catch {
      /* dir absent */
    }
  }

  return [...new Set(out)]
}

export const findJava = (): BinaryStatus => {
  let fallback: BinaryStatus | null = null

  for (const candidate of javaCandidates()) {
    if (!existsSync(candidate)) {
      continue
    }

    const version = versionOf(candidate, ['-version'])
    const major = parseMajorVersion(version)

    if (major <= 0) {
      continue // the macOS stub / unparseable → not a real JDK
    }

    const status: BinaryStatus = { found: true, home: candidate.replace(/[/\\]bin[/\\]java$/, ''), path: candidate, version }

    if (major >= 17) {
      return status
    }

    fallback ??= status // remember an older JDK so we can report its version
  }

  return fallback ?? { found: false, home: '', path: '', version: '' }
}

// Environment for spawning signal-cli: export JAVA_HOME + prepend its bin so the
// daemon finds Java even when Homebrew's openjdk is keg-only / off PATH.
export const daemonEnv = (): NodeJS.ProcessEnv => {
  const java = findJava()

  if (!java.home) {
    return { ...process.env }
  }

  return {
    ...process.env,
    JAVA_HOME: java.home,
    PATH: `${join(java.home, 'bin')}${delimiter}${process.env.PATH ?? ''}`
  }
}

// Parse a major version out of a `java -version` / `signal-cli --version` line.
export const parseMajorVersion = (version: string): number => {
  // java: 'openjdk version "21.0.1"' or '"1.8.0_392"'; signal-cli: 'signal-cli 0.13.x'
  const m = /(?:"|\s)(\d+)(?:\.(\d+))?/.exec(version)

  if (!m) {
    return 0
  }

  const major = Number(m[1])

  // Legacy Java "1.8" → 8.
  return major === 1 && m[2] ? Number(m[2]) : major
}

// Find a free TCP port: try the preferred one first, otherwise let the OS
// assign an ephemeral free port. Never throws — falls back to the preferred.
export const findFreePort = (preferred = 8080): Promise<number> =>
  new Promise(resolve => {
    const tryListen = (port: number, onFail: () => void) => {
      const srv = createServer()
      srv.once('error', () => {
        srv.close()
        onFail()
      })
      srv.listen(port, '127.0.0.1', () => {
        const addr = srv.address()
        const chosen = addr && typeof addr === 'object' ? addr.port : port
        srv.close(() => resolve(chosen))
      })
    }

    // Preferred port → else OS-assigned (listen on 0) → else just the preferred.
    tryListen(preferred, () => tryListen(0, () => resolve(preferred)))
  })

export const daemonArgs = (account: string, port: number): string[] => [
  '-a',
  account,
  'daemon',
  '--http',
  `127.0.0.1:${port}`
]

export const readDaemonInfo = (file = daemonFile()): DaemonInfo | null => {
  try {
    const d = JSON.parse(readFileSync(file, 'utf8')) as DaemonInfo

    return typeof d.pid === 'number' && typeof d.httpUrl === 'string' ? d : null
  } catch {
    return null
  }
}

const writeDaemonInfo = (info: DaemonInfo, file = daemonFile()): void => {
  try {
    const dir = forecastHomeDir()

    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }

    writeFileSync(file, `${JSON.stringify(info, null, 2)}\n`, { mode: 0o600 })
  } catch {
    /* best effort */
  }
}

const pidAlive = (pid: number): boolean => {
  try {
    process.kill(pid, 0)

    return true
  } catch {
    return false
  }
}

// Reuse an already-running, healthy daemon if one is recorded — so reopening
// the TUI (or a second surface) doesn't spawn a duplicate.
export const reuseRunningDaemon = async (account: string): Promise<DaemonInfo | null> => {
  const info = readDaemonInfo()

  if (!info || info.account !== account || !pidAlive(info.pid)) {
    return null
  }

  const ok = await checkHealth({ account, httpUrl: info.httpUrl })

  return ok ? info : null
}

export interface StartResult {
  error: null | string
  info: DaemonInfo | null
}

// Start (or reuse) the daemon for an account. Picks a free port, spawns
// detached, writes config + daemon info, and polls health until it answers.
export const startDaemon = async (account: string, timeoutMs = 25000): Promise<StartResult> => {
  const existing = await reuseRunningDaemon(account)

  if (existing) {
    saveSignalConfig({ account, httpUrl: existing.httpUrl })

    return { error: null, info: existing }
  }

  const cli = findSignalCli()

  if (!cli.found) {
    return { error: 'signal-cli not found', info: null }
  }

  const port = await findFreePort(8080)
  const httpUrl = `http://127.0.0.1:${port}`
  const cfg: SignalConfig = { account, httpUrl }

  let child

  try {
    child = spawn(cli.path, daemonArgs(account, port), { detached: true, env: daemonEnv(), stdio: 'ignore' })
    child.unref()
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), info: null }
  }

  const info: DaemonInfo = { account, httpUrl, pid: child.pid ?? 0, port, startedAt: Date.now() }
  writeDaemonInfo(info)
  saveSignalConfig(cfg)

  // Poll health until the daemon answers (it loads state + connects first).
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    if (await checkHealth(cfg, 3000)) {
      return { error: null, info }
    }

    if (child.exitCode !== null) {
      return { error: `signal-cli exited (code ${child.exitCode}) — is ${account} registered/linked?`, info: null }
    }

    await new Promise(r => setTimeout(r, 1000))
  }

  return { error: 'daemon did not become healthy in time', info }
}

export const stopDaemon = (file = daemonFile()): boolean => {
  const info = readDaemonInfo(file)

  if (!info || !pidAlive(info.pid)) {
    return false
  }

  try {
    process.kill(info.pid)

    return true
  } catch {
    return false
  }
}

// Force a FRESH daemon even if the current one still answers /api/v1/check:
// signal-cli's upstream receive websocket can stall while the local HTTP API
// stays responsive, so reuse-if-healthy (startDaemon) cannot recover it. Kill
// the recorded daemon, wait for the pid to exit so startDaemon won't reuse it,
// then start clean. Returns the new StartResult.
export const restartDaemon = async (account: string, timeoutMs = 25000): Promise<StartResult> => {
  const info = readDaemonInfo()
  stopDaemon()

  // Wait (briefly) for the old process to actually exit so reuseRunningDaemon
  // sees a dead pid and spawns fresh instead of reattaching to the stalled one.
  for (let i = 0; i < 30; i += 1) {
    if (!info || !pidAlive(info.pid)) {
      break
    }

    await new Promise(resolve => setTimeout(resolve, 150))
  }

  return startDaemon(account, timeoutMs)
}
