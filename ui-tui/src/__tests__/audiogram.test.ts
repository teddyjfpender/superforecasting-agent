import { describe, expect, it } from 'vitest'

import { audiogramFrame, speakingLabel } from '../lib/audiogram.js'

describe('audiogram', () => {
  it('renders `width` block-bar characters', () => {
    const f = audiogramFrame(0, 7)
    expect([...f]).toHaveLength(7)
    expect([...f].every((c) => '▁▂▃▄▅▆▇█'.includes(c))).toBe(true)
  })

  it('is deterministic per frame but animates across frames', () => {
    expect(audiogramFrame(5, 9)).toBe(audiogramFrame(5, 9))
    const frames = [0, 1, 2, 3, 4, 5].map((n) => audiogramFrame(n, 7))
    expect(new Set(frames).size).toBeGreaterThan(1) // the bars actually move
  })

  it('speakingLabel prefixes the speaker glyph', () => {
    expect(speakingLabel(0)).toMatch(/^🔊 /)
    expect(speakingLabel(0)).toHaveLength('🔊 '.length + 7)
  })
})
