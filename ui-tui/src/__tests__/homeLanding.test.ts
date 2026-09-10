import { describe, expect, it } from 'vitest'

import { HOME_TIPS, pickTip, reviewCountFromDeskStatus } from '../components/homeLanding.js'

// ── Rotating tip picker ────────────────────────────────────────────────────────

describe('pickTip', () => {
  it('always returns a known tip, wrapping the index', () => {
    for (let seed = -5; seed <= 12; seed++) {
      expect(HOME_TIPS).toContain(pickTip(seed))
    }
  })

  it('rotates through every tip across consecutive seeds', () => {
    const seen = new Set<string>()

    for (let seed = 0; seed < HOME_TIPS.length; seed++) {
      seen.add(pickTip(seed))
    }

    expect(seen.size).toBe(HOME_TIPS.length)
  })
})

// ── Actionable review count for the slim status bar ────────────────────────────

describe('reviewCountFromDeskStatus', () => {
  it('parses the "N to review" segment from the desk-status label', () => {
    expect(reviewCountFromDeskStatus('2 forecasts · 103 to review · 1322 alerts')).toBe(103)
  })

  it('handles a thousands-separated count', () => {
    expect(reviewCountFromDeskStatus('471 forecasts · 1,250 to review')).toBe(1250)
  })

  it('is 0 when the label carries no review segment', () => {
    expect(reviewCountFromDeskStatus('471 forecasts · 13 entities')).toBe(0)
    expect(reviewCountFromDeskStatus('')).toBe(0)
  })
})

describe('session vitals on the conversation bar', () => {
  it('renders context% / voice / bg conditionally; the landing (no vitals) stays bare', async () => {
    const { render } = await import('@superforecasting/ink')
    const React = (await import('react')).default
    const { HomeStatusBar } = await import('../components/homeLanding.js')
    const { DARK_THEME } = await import('../theme.js')
    const { PassThrough } = await import('stream')

    const frame = (vitals?: object): Promise<string> => {
      const stream = new PassThrough() as never as PassThrough & { columns: number; isTTY: boolean; rows: number }
      stream.columns = 120
      stream.rows = 6
      stream.isTTY = false
      let out = ''
      stream.on('data', (c: Buffer) => (out += c.toString()))

      const inst = render(
        React.createElement(HomeStatusBar, {
          agents: null, cols: 120, cwdLabel: '~/x', deskStatus: null,
          model: 'gpt-5.5', onOpenAgents: () => undefined,
          status: 'ready', statusColor: '#0f0', t: DARK_THEME,
          ...(vitals ? { vitals } : {})
        } as never),
        { exitOnCtrlC: false, patchConsole: false, stdout: stream as never }
      )

      return new Promise(res => setTimeout(() => { inst.unmount?.(); res(out) }, 80))
    }

    const bare = await frame()
    expect(bare).not.toContain('%')
    expect(bare).not.toContain(' bg')

    const full = await frame({ bgCount: 2, contextPct: 84, voiceLabel: '◉ rec' })
    expect(full).toContain('84%')
    expect(full).toContain('◉ rec')
    expect(full).toContain('2 bg')

    const quiet = await frame({ bgCount: 0, contextPct: null, voiceLabel: null })
    expect(quiet).not.toContain('%')
    expect(quiet).not.toContain(' bg')
  })
})
