import { describe, expect, it } from 'vitest'

import { abbrevTokens, activityAdjective, turnTokenCount, workTokens } from '../lib/liveStatus.js'

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

  it('the honest work number stays a sane scale, not the 4.8M billing total', () => {
    // A real session: usage.total 4,760,671 would render "4.8M" (the operator's
    // "feels off"); the honest work (280,612 fresh in + 32,315 out) is 15x smaller.
    expect(abbrevTokens(4_760_671)).toBe('4.8M')
    expect(abbrevTokens(workTokens({ input: 280_612, output: 32_315 }))).toBe('312.9k')
  })
})

describe('workTokens — honest work tally: fresh input + output, no cached re-sends', () => {
  it('sums fresh (cache-excluded) input and output', () => {
    // The real 4.8M-total session: 4.45M of the total was cache_read re-sends; the
    // genuine work is input 280,612 + output 32,315 = 312,927.
    expect(workTokens({ input: 280_612, output: 32_315 })).toBe(312_927)
  })

  it('treats a missing split as zero', () => {
    expect(workTokens({} as never)).toBe(0)
  })
})

describe('turnTokenCount — honest work delta (input+output), never usage.total', () => {
  it('reports the fresh input+output delta since turn start', () => {
    const t = turn({ reasoningTokens: 0, streaming: '', toolTokens: 0 }) as never
    // input 100k + output 20k = 120k now; baseline 100k → 20k of real work.
    expect(turnTokenCount(t, { input: 100_000, output: 20_000 }, 100_000)).toBe(20_000)
  })

  it('a long multi-call turn does NOT inflate — cached context re-sends excluded', () => {
    const t = turn({ reasoningTokens: 0, streaming: '', toolTokens: 0 }) as never
    // Baseline (input+output) at turn start = 300k. Over 50 tool calls the billing
    // meter (usage.total) would climb into the MILLIONS as the whole context is
    // re-sent each call, but fresh input only rose 40k and output 8k → honest 48k.
    expect(turnTokenCount(t, { input: 340_000, output: 8_000 }, 300_000)).toBe(48_000)
  })

  it('falls back to the live in-flight estimate before usage lands', () => {
    // No fresh delta yet (input+output == baseline) → reasoning+tool+prose estimate.
    const t = turn({ reasoningTokens: 120, streaming: 'abcd', toolTokens: 30 }) as never
    // estimateTokensRough('abcd') = (4 + 3) >> 2 = 1 → 120 + 30 + 1 = 151.
    expect(turnTokenCount(t, { input: 5000, output: 0 }, 5000)).toBe(151)
  })

  it('never regresses below the reported delta', () => {
    const t = turn({ reasoningTokens: 10, toolTokens: 10 }) as never
    // input 8000 + output 1000 = 9000; baseline 5000 → 4000 (beats the 20 estimate).
    expect(turnTokenCount(t, { input: 8000, output: 1000 }, 5000)).toBe(4000)
  })

  it('resets cleanly per turn: a fresh baseline zeroes the counter', () => {
    const t = turn({ reasoningTokens: 0, streaming: '', toolTokens: 0 }) as never
    // Baseline captured AT the current snapshot → 0 work for the brand-new turn,
    // even though the session cumulative is already large.
    expect(turnTokenCount(t, { input: 500_000, output: 90_000 }, 590_000)).toBe(0)
  })
})
