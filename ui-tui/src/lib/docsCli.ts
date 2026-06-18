import { spawn, spawnSync } from 'node:child_process'

// Shell out to the doc-sync CLIs from the TUI's Node runtime (the standalone
// TUI runs locally alongside the doc directories):
//   - git / gh  → commit / push / pull a Markdown or LaTeX dir to a repo
//   - olcli     → Overleaf CLI (https://github.com/aloth/olcli); Overleaf
//                 projects are git-backed, so day-to-day sync is git pull/push,
//                 with olcli available for clone/auth flows.
// All spawns use an argv array (no shell), so paths/messages can't be
// reinterpreted as commands.

export const commandExists = (bin: string): boolean => {
  try {
    const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', [bin], { encoding: 'utf8', timeout: 4000 })

    return r.status === 0
  } catch {
    return false
  }
}

export interface RunResult {
  code: number
  error: null | string
  stderr: string
  stdout: string
}

export const runCli = (bin: string, args: string[], cwd: string, timeoutMs = 60_000): Promise<RunResult> =>
  new Promise(resolve => {
    let stdout = ''
    let stderr = ''
    let child

    try {
      child = spawn(bin, args, { cwd, env: process.env })
    } catch (e) {
      resolve({ code: -1, error: e instanceof Error ? e.message : String(e), stderr: '', stdout: '' })

      return
    }

    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs)
    child.stdout?.on('data', d => {
      stdout += d.toString()
    })
    child.stderr?.on('data', d => {
      stderr += d.toString()
    })
    child.on('error', e => {
      clearTimeout(timer)
      resolve({ code: -1, error: e.message, stderr, stdout })
    })
    child.on('close', code => {
      clearTimeout(timer)
      resolve({ code: code ?? -1, error: code === 0 ? null : stderr.trim() || `exit ${code ?? '?'}`, stderr, stdout })
    })
  })

// ── git ────────────────────────────────────────────────────────────────────

export interface GitStatus {
  ahead: number
  behind: number
  branch: string
  dirty: number // count of changed/untracked paths
  tracked: boolean // has an upstream
}

// Pure parser for `git status -b --porcelain`.
export const parseGitStatus = (out: string): GitStatus => {
  const lines = out.split('\n').filter(Boolean)
  const head = lines.find(l => l.startsWith('## ')) ?? ''
  const changes = lines.filter(l => !l.startsWith('## '))
  const branch = /^## (?:No commits yet on )?([^\s.]+)/.exec(head)?.[1] ?? '—'

  return {
    ahead: Number(/ahead (\d+)/.exec(head)?.[1] ?? 0),
    behind: Number(/behind (\d+)/.exec(head)?.[1] ?? 0),
    branch,
    dirty: changes.length,
    tracked: head.includes('...')
  }
}

export const isGitRepo = async (dir: string): Promise<boolean> => {
  const r = await runCli('git', ['-C', dir, 'rev-parse', '--is-inside-work-tree'], dir, 8000)

  return r.code === 0 && r.stdout.trim() === 'true'
}

export const gitStatus = async (dir: string): Promise<GitStatus | null> => {
  const r = await runCli('git', ['-C', dir, 'status', '-b', '--porcelain'], dir, 12_000)

  return r.code === 0 ? parseGitStatus(r.stdout) : null
}

export const gitPull = (dir: string): Promise<RunResult> =>
  runCli('git', ['-C', dir, 'pull', '--rebase', '--autostash'], dir, 90_000)

// Stage everything, commit (tolerating "nothing to commit"), then push.
export const gitCommitPush = async (dir: string, message: string): Promise<RunResult> => {
  const add = await runCli('git', ['-C', dir, 'add', '-A'], dir)

  if (add.code !== 0) {
    return add
  }

  await runCli('git', ['-C', dir, 'commit', '-m', message], dir) // ok if nothing to commit

  return runCli('git', ['-C', dir, 'push'], dir, 90_000)
}

// ── Overleaf (olcli) ─────────────────────────────────────────────────────────

export const overleaf = (dir: string, args: string[]): Promise<RunResult> => runCli('olcli', args, dir, 90_000)
