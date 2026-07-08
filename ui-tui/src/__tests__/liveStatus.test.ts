import { describe, expect, it } from 'vitest'

import { abbrevTokens, activityAdjective, turnTokenCount } from '../lib/liveStatus.js'

// A minimal turn shape — only the fields activityAdjective/turnTokenCount read.
const turn = (over: Partial<Parameters<typeof activityAdjective>[0]> = {}) => ({
  reasoningActive: false,
  reasoningStreaming: false,
  streaming: '',
  subagents: [],
  tools: [],
  ...over
})

describe('activityAdjective — honest gerund from live turn state', () => {
  it('a running tool wins, mapped to a tool-appropriate verb', () => {
    expect(activityAdjective(turn({ tools: [{ id: '1', name: 'web_search' }] }) as never)).toBe('Searching')
    expect(activityAdjective(turn({ tools: [{ id: '1', name: 'read_file' }] }) as never)).toBe('Reading')
    expect(activityAdjective(turn({ tools: [{ id: '1', name: 'apply_patch' }] }) as never)).toBe('Writing')
    expect(activityAdjective(turn({ tools: [{ id: '1', name: 'bash' }] }) as never)).toBe('Running')
  })

  it('streamed prose reads as Writing', () => {
    expect(activityAdjective(turn({ streaming: 'the answer so far' }) as never)).toBe('Writing')
  })

  it('reasoning (thinking) reads as Reasoning', () => {
    expect(activityAdjective(turn({ reasoningActive: true }) as never)).toBe('Reasoning')
    expect(activityAdjective(turn({ reasoningStreaming: true }) as never)).toBe('Reasoning')
  })

  it('a fanned-out panel of agents reads as Deliberating', () => {
    expect(activityAdjective(turn({ subagents: [{ status: 'running' }] }) as never)).toBe('Deliberating')
  })

  it('falls back to Working when nothing concrete is happening', () => {
    expect(activityAdjective(turn() as never)).toBe('Working')
    // A finished subagent is NOT an active panel — honest fallback.
    expect(activityAdjective(turn({ subagents: [{ status: 'completed' }] }) as never)).toBe('Working')
  })

  it('precedence: a live tool outranks streaming/reasoning', () => {
    expect(
      activityAdjective(
        turn({ reasoningActive: true, streaming: 'x', tools: [{ id: '1', name: 'web_search' }] }) as never
      )
    ).toBe('Searching')
  })
})

describe('abbrevTokens — k/M to one decimal, boundary-exact', () => {
  it('holds the operator-named boundaries', () => {
    expect(abbrevTokens(999)).toBe('999')
    expect(abbrevTokens(1000)).toBe('1.0k')
    expect(abbrevTokens(999949)).toBe('999.9k')
    expect(abbrevTokens(1_000_000)).toBe('1.0M')
  })

  it('handles small / mid / large / degenerate inputs', () => {
    expect(abbrevTokens(0)).toBe('0')
    expect(abbrevTokens(45_200)).toBe('45.2k')
    expect(abbrevTokens(2_500_000)).toBe('2.5M')
    expect(abbrevTokens(-5)).toBe('0')
    expect(abbrevTokens(999.9)).toBe('999')
  })
})

describe('turnTokenCount — max(reported delta, live estimate)', () => {
  it('uses the authoritative usage.total delta since turn start', () => {
    const t = turn({ reasoningTokens: 0, streaming: '', toolTokens: 0 }) as never
    // usage.total 8000, baseline 5000 → 3000 reported tokens this turn.
    expect(turnTokenCount(t, { total: 8000 }, 5000)).toBe(3000)
  })

  it('falls back to the live in-flight estimate before usage lands', () => {
    // Nothing reported yet (delta 0) → reasoning + tool + streamed prose estimate.
    const t = turn({ reasoningTokens: 120, streaming: 'abcd', toolTokens: 30 }) as never
    // estimateTokensRough('abcd') = (4 + 3) >> 2 = 1 → 120 + 30 + 1 = 151.
    expect(turnTokenCount(t, { total: 5000 }, 5000)).toBe(151)
  })

  it('never regresses below the reported delta', () => {
    const t = turn({ reasoningTokens: 10, toolTokens: 10 }) as never
    expect(turnTokenCount(t, { total: 9000 }, 5000)).toBe(4000)
  })
})
