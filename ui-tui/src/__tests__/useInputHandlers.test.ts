import { describe, expect, it, vi } from 'vitest'

import {
  applyVoiceRecordResponse,
  pageScrollStep,
  shouldFallThroughForScroll,
  shouldOpenHomeHelp,
  shouldSoftFocusToday
} from '../app/useInputHandlers.js'

const baseKey = {
  downArrow: false,
  pageDown: false,
  pageUp: false,
  shift: false,
  upArrow: false,
  wheelDown: false,
  wheelUp: false
}

describe('shouldFallThroughForScroll — keep transcript scrolling alive during prompt overlays', () => {
  it('falls through for wheel scrolls', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, wheelUp: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, wheelDown: true })).toBe(true)
  })

  it('falls through for PageUp / PageDown', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, pageUp: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, pageDown: true })).toBe(true)
  })

  it('falls through for Shift+ArrowUp / Shift+ArrowDown', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true, upArrow: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true, downArrow: true })).toBe(true)
  })

  it('does NOT fall through for plain arrows — those drive in-prompt selection', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, upArrow: true })).toBe(false)
    expect(shouldFallThroughForScroll({ ...baseKey, downArrow: true })).toBe(false)
  })

  it('does NOT fall through for plain Shift — without an arrow it is a no-op', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true })).toBe(false)
  })

  it('does NOT fall through for unrelated state (no scroll keys held)', () => {
    expect(shouldFallThroughForScroll(baseKey)).toBe(false)
  })
})

describe('pageScrollStep — PgUp/PgDn move a viewport-minus-one (one pager continuity line)', () => {
  it('steps by viewport - 1 so exactly one line of continuity carries over', () => {
    expect(pageScrollStep(24)).toBe(23)
    expect(pageScrollStep(10)).toBe(9)
  })

  it('never returns less than 1 for degenerate viewports', () => {
    expect(pageScrollStep(1)).toBe(1)
    expect(pageScrollStep(0)).toBe(1)
  })

  it('stays under the DECSTBM fast-path threshold (step < viewport)', () => {
    for (const vp of [5, 12, 40]) {
      expect(pageScrollStep(vp)).toBeLessThan(vp)
    }
  })
})

describe('shouldSoftFocusToday — the landing Today panel borrows ↑↓/⏎ only where history recall would otherwise fire', () => {
  it('is active on the empty conversation composer with Today rows present', () => {
    expect(shouldSoftFocusToday(true, 'conversation', 3)).toBe(true)
  })

  it('is INACTIVE once typing starts (chromeArmable false) — history recall stays live', () => {
    expect(shouldSoftFocusToday(false, 'conversation', 3)).toBe(false)
  })

  it('is INACTIVE when Today has no rows — history recall stays live', () => {
    expect(shouldSoftFocusToday(true, 'conversation', 0)).toBe(false)
  })

  it('is INACTIVE when the full Ctrl+T Today pane owns the keyboard', () => {
    expect(shouldSoftFocusToday(true, 'today', 3)).toBe(false)
  })
})

describe('shouldOpenHomeHelp — `h` opens Help on Home ONLY off the composer (soft-focus rules)', () => {
  it('does NOT open while the composer is focused — so a message starting with `h` types normally', () => {
    expect(shouldOpenHomeHelp(true, true, 'conversation')).toBe(false)
  })

  it('opens when focus sits on the Today pane (composer deactivated)', () => {
    expect(shouldOpenHomeHelp(true, true, 'today')).toBe(true)
  })

  it('does NOT open when off the Home route — a fullscreen view raises Help itself', () => {
    expect(shouldOpenHomeHelp(false, true, 'today')).toBe(false)
  })

  it('does NOT open while a blocking prompt/picker owns the keyboard (canOpenOverlay false)', () => {
    expect(shouldOpenHomeHelp(true, false, 'today')).toBe(false)
  })
})

describe('applyVoiceRecordResponse', () => {
  it('reverts optimistic REC state when the gateway reports voice busy', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()
    const sys = vi.fn()

    applyVoiceRecordResponse({ status: 'busy' }, true, { setProcessing, setRecording }, sys)

    expect(setRecording).toHaveBeenCalledWith(false)
    expect(setProcessing).toHaveBeenCalledWith(true)
    expect(sys).toHaveBeenCalledWith('voice: still transcribing; try again shortly')
  })

  it('keeps optimistic REC state for successful recording starts', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()

    applyVoiceRecordResponse({ status: 'recording' }, true, { setProcessing, setRecording }, vi.fn())

    expect(setRecording).not.toHaveBeenCalled()
    expect(setProcessing).not.toHaveBeenCalled()
  })

  it('reverts optimistic REC state when the gateway returns null', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()

    applyVoiceRecordResponse(null, true, { setProcessing, setRecording }, vi.fn())

    expect(setRecording).toHaveBeenCalledWith(false)
    expect(setProcessing).toHaveBeenCalledWith(false)
  })
})
