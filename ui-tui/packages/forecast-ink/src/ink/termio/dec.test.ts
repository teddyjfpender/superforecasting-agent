import { describe, expect, it } from 'vitest'

import { DEC, decreset, decset, DISABLE_MOUSE_TRACKING, ENABLE_MOUSE_TRACKING } from './dec.js'

// Mouse-tracking mode contract. The operator reported drag-select jitter while
// the chat streams; this test documents EXACTLY which DEC private modes the app
// requests and why, so any future change to the set is deliberate (a narrower
// set trades away a real feature — see the per-mode rationale below).
describe('mouse tracking mode composition', () => {
  it('requests only the modes with a live consumer, in a stable order', () => {
    // 1000 button press/release + wheel  → clicks, click-zones, wheel scroll
    // 1002 button-motion (drag)          → in-app text drag-select, scrollbar
    //                                       thumb drag, selection edge-autoscroll
    // 1003 any-motion (button-free hover) → scrollbar/hyperlink/button hover
    // 1006 SGR extended coordinates      → columns/rows past 223 (wide terminals
    //                                       like the operator's 202-col kitty)
    expect(ENABLE_MOUSE_TRACKING).toBe(
      decset(DEC.MOUSE_NORMAL) + decset(DEC.MOUSE_BUTTON) + decset(DEC.MOUSE_ANY) + decset(DEC.MOUSE_SGR)
    )

    // SGR must be present — without 1006 a 202-wide terminal's coordinates
    // overflow the legacy single-byte encoding and clicks land on the wrong cell.
    expect(ENABLE_MOUSE_TRACKING).toContain(decset(DEC.MOUSE_SGR))
  })

  it('disables every mode it enabled (reverse order), so no tracking leaks on teardown', () => {
    expect(DISABLE_MOUSE_TRACKING).toBe(
      decreset(DEC.MOUSE_SGR) + decreset(DEC.MOUSE_ANY) + decreset(DEC.MOUSE_BUTTON) + decreset(DEC.MOUSE_NORMAL)
    )

    // Every enabled mode has a matching reset.
    for (const mode of [DEC.MOUSE_NORMAL, DEC.MOUSE_BUTTON, DEC.MOUSE_ANY, DEC.MOUSE_SGR]) {
      expect(ENABLE_MOUSE_TRACKING).toContain(decset(mode))
      expect(DISABLE_MOUSE_TRACKING).toContain(decreset(mode))
    }
  })
})
