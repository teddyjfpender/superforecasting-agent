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
