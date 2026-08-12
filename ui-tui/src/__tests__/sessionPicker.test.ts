import { describe, expect, it } from 'vitest'

import { moveSessionSelection } from '../components/sessionPicker.js'

describe('SessionPicker', () => {
  it('scrolls and page-jumps through recent sessions without leaving bounds', () => {
    expect(moveSessionSelection(0, 1, 40)).toBe(1)
    expect(moveSessionSelection(0, 15, 40)).toBe(15)
    expect(moveSessionSelection(39, 15, 40)).toBe(39)
    expect(moveSessionSelection(0, -15, 40)).toBe(0)
    expect(moveSessionSelection(0, 1, 0)).toBe(0)
  })
})
