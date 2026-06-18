import { describe, expect, it } from 'vitest'

import { parseGitStatus } from '../lib/docsCli.js'

describe('parseGitStatus', () => {
  it('reads branch, upstream tracking, ahead/behind, and dirty count', () => {
    const out = ['## main...origin/main [ahead 2, behind 1]', ' M paper.tex', '?? draft.tex'].join('\n')
    expect(parseGitStatus(out)).toEqual({ ahead: 2, behind: 1, branch: 'main', dirty: 2, tracked: true })
  })

  it('clean repo with upstream', () => {
    expect(parseGitStatus('## main...origin/main')).toEqual({ ahead: 0, behind: 0, branch: 'main', dirty: 0, tracked: true })
  })

  it('branch with no upstream', () => {
    const s = parseGitStatus('## feature/x\n M a.tex')
    expect(s.branch).toBe('feature/x')
    expect(s.tracked).toBe(false)
    expect(s.dirty).toBe(1)
  })

  it('fresh repo with no commits yet', () => {
    expect(parseGitStatus('## No commits yet on main').branch).toBe('main')
  })
})
